from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from threading import Event, RLock, Thread
from typing import Protocol
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from backend.app.collection.contracts import (
    CompanyCandidateDiscoveryProvider,
    KeywordDiscoveryProvider,
    RelevanceJudge,
)
from backend.app.collection.intent import ParsedCollectionIntent, parse_collection_intent
from backend.app.collection.models import (
    CollectionSummary,
    CollectionTask,
    CollectionWorkUnit,
    CompanyNameCandidate,
    RelevanceDecision,
)
from backend.app.collection.planner import build_work_units, contact_requirement_satisfied
from backend.app.domain.dedup import company_identity, payload_fingerprint
from backend.app.domain.merge import merge_candidate_with_enrichment, merge_map_candidate
from backend.app.domain.models import DeliveryResult, DoubaoEnrichment, LeadRecord, MapPoiCandidate
from backend.app.domain.normalization import (
    normalize_company_name,
    normalize_mobile,
)
from backend.app.providers.protocols import (
    DoubaoEnrichmentGateway,
    ErpAdapter,
    MapEvidenceVerifier,
    ProviderPaused,
    PublicEvidenceProvider,
)

_RESIDENTIAL_REQUEST_PATTERN = re.compile(
    r'软装|整装|家装|室内设计|装修|别墅|大宅|私宅|住宅'
)
_HARD_IRRELEVANT_COMPANY_PATTERN = re.compile(
    r'婚礼|婚庆|活动策划|广告|传媒|工业设计|产品设计|平面设计|品牌设计|'
    r'包装设计|景观设计|园林设计|教育|培训|招聘|建材供应|钢板|钢筋|'
    r'模板|物流|货运|汽车|医疗|口腔|餐饮'
)
_TARGET_RESIDENTIAL_BUSINESS_PATTERN = re.compile(
    r'软装|室内(?:设计|装修)|装饰|装修|整装|全案|空间设计|陈设|家装'
)
_LOCATION_POI_PATTERN = re.compile(
    r'(?:出口|入口|[Tt]\d+座|村|大道|路|街|地铁站|车站|园区|广场|中心|大厦|写字楼)$'
)


class CollectionStore(Protocol):
    def save(self, task: CollectionTask) -> None: ...

    def get(self, task_id: str) -> CollectionTask | None: ...

    def list(self, *, account_scope: str | None = None) -> list[CollectionTask]: ...

    def get_delivery(self, fingerprint: str): ...

    def record_delivery(self, **kwargs): ...


class _CollectionPauseRequested(RuntimeError):
    pass


class _CollectionCancelledRequested(RuntimeError):
    pass


class CollectionService:
    def __init__(
        self,
        *,
        map_provider: KeywordDiscoveryProvider,
        candidate_discovery_provider: CompanyCandidateDiscoveryProvider | None = None,
        relevance_judges: dict[str, RelevanceJudge],
        enrichment_gateway: DoubaoEnrichmentGateway | None,
        evidence_verifier: MapEvidenceVerifier,
        public_evidence_verifier: PublicEvidenceProvider | None = None,
        erp_adapter: ErpAdapter | None = None,
        manual_delivery_adapter_factory: Callable[[str, str | None], ErpAdapter] | None = None,
        configured_models: set[str] | None = None,
        repository: CollectionStore | None = None,
        max_results_per_work_unit: int = 20,
    ) -> None:
        self.map_provider = map_provider
        self.candidate_discovery_provider = candidate_discovery_provider
        self.relevance_judges = dict(relevance_judges)
        self.enrichment_gateway = enrichment_gateway
        self.evidence_verifier = evidence_verifier
        self.public_evidence_verifier = public_evidence_verifier
        self.erp_adapter = erp_adapter
        self.manual_delivery_adapter_factory = manual_delivery_adapter_factory
        self.configured_models = set(configured_models or self.relevance_judges)
        self.repository = repository
        self.max_results_per_work_unit = max(max_results_per_work_unit, 1)
        self._tasks: dict[str, CollectionTask] = {}
        self._workers: dict[str, Thread] = {}
        self._done_events: dict[str, Event] = {}
        self._pause_events: dict[str, Event] = {}
        self._cancel_events: dict[str, Event] = {}
        self._state_lock = RLock()

    def create_from_text(
        self,
        request_text: str,
        *,
        name: str | None = None,
        model_keywords: list[str] | None = None,
        explicit_keywords: list[str] | None = None,
        configured_models: set[str] | None = None,
        continuous_mode: bool = True,
        auto_deliver: bool = False,
        verified_auto_deliver: bool = False,
        account_scope: str | None = None,
    ) -> CollectionTask:
        if auto_deliver and verified_auto_deliver:
            raise ValueError('automatic delivery modes are mutually exclusive')
        intent = parse_collection_intent(
            request_text,
            configured_models=(
                self.configured_models if configured_models is None else configured_models
            ),
            model_keywords=model_keywords,
        )
        if explicit_keywords is not None:
            keywords = list(
                dict.fromkeys(
                    str(keyword).strip()
                    for keyword in explicit_keywords
                    if str(keyword).strip()
                )
            )
            if not keywords:
                raise ValueError('explicit_keywords cannot be empty')
            intent = replace(intent, keywords=keywords)
        return self.create_from_intent(
            intent,
            name=name,
            continuous_mode=continuous_mode,
            auto_deliver=auto_deliver,
            verified_auto_deliver=verified_auto_deliver,
            account_scope=account_scope,
        )

    def create_from_intent(
        self,
        intent: ParsedCollectionIntent,
        *,
        name: str | None = None,
        task_id: str | None = None,
        continuous_mode: bool = True,
        auto_deliver: bool = False,
        verified_auto_deliver: bool = False,
        account_scope: str | None = None,
    ) -> CollectionTask:
        if auto_deliver and verified_auto_deliver:
            raise ValueError('automatic delivery modes are mutually exclusive')
        identifier = task_id or f'collection-{uuid4().hex}'
        work_units = build_work_units(
            intent,
            provider_id=self.map_provider.id,
            task_seed=identifier,
        )
        task = CollectionTask(
            id=identifier,
            name=name or intent.request_text[:40],
            request_text=intent.request_text,
            account_scope=account_scope,
            intent=intent,
            continuous_mode=continuous_mode,
            auto_deliver=auto_deliver,
            verified_auto_deliver=verified_auto_deliver,
            work_units=work_units,
            summary=CollectionSummary(total_work_units=len(work_units)),
        )
        self._tasks[task.id] = task
        self._persist(task)
        return task

    def get_task(
        self,
        task_id: str,
        *,
        account_scope: str | None = None,
    ) -> CollectionTask:
        task = self._tasks.get(task_id)
        if task is not None and self._is_visible(task, account_scope):
            return task
        stored = self.repository.get(task_id) if self.repository else None
        if stored is not None and self._is_visible(stored, account_scope):
            return self._restore_persisted_task(stored)
        raise KeyError(f'collection task not found: {task_id}')

    def list_tasks(self, *, account_scope: str | None = None) -> list[CollectionTask]:
        if self.repository is not None and hasattr(self.repository, 'list'):
            stored = self.repository.list(account_scope=account_scope)
            tasks = [
                self._tasks.get(task.id) or self._restore_persisted_task(task)
                for task in stored
            ]
            return [task for task in tasks if self._is_visible(task, account_scope)]
        return [
            task
            for task in reversed(list(self._tasks.values()))
            if self._is_visible(task, account_scope)
        ]

    @staticmethod
    def _is_visible(task: CollectionTask, account_scope: str | None) -> bool:
        return account_scope is None or task.account_scope == account_scope

    def extend_keywords(
        self,
        task_id: str,
        keywords: list[str],
    ) -> CollectionTask:
        task = self.get_task(task_id)
        self._prune_hard_irrelevant_residential_results(task)
        existing = {
            (unit.city, unit.keyword)
            for unit in task.work_units
        }
        cities = task.intent.cities or list(dict.fromkeys(
            unit.city for unit in task.work_units
        ))
        cleaned = list(dict.fromkeys(
            keyword.strip()
            for keyword in keywords
            if keyword.strip()
        ))
        new_keywords = [
            keyword
            for keyword in cleaned
            if any((city, keyword) not in existing for city in cities)
        ]
        if not new_keywords:
            return task

        extended_intent = replace(
            task.intent,
            keywords=list(dict.fromkeys([
                *task.intent.keywords,
                *new_keywords,
            ])),
        )
        added_units = build_work_units(
            replace(extended_intent, keywords=new_keywords),
            provider_id=self.map_provider.id,
            task_seed=task.id,
        )
        task.intent = extended_intent
        task.work_units.extend(
            unit for unit in added_units
            if (unit.city, unit.keyword) not in existing
        )
        task.status = 'planned'
        task.checkpoint.current_stage = 'planned'
        task.summary.total_work_units = len(task.work_units)
        task.summary.source_exhausted = False
        self._persist(task)
        return task

    def _restore_persisted_task(self, stored: CollectionTask) -> CollectionTask:
        task = stored.model_copy(deep=True)
        persisted_summary = task.summary.model_dump()
        changed = self._canonicalize_mobile_fields(task)
        changed = self._prune_hard_irrelevant_residential_results(task) or changed
        worker = self._workers.get(task.id)
        if not (worker and worker.is_alive()):
            for unit in task.work_units:
                if unit.status == 'running':
                    unit.status = 'paused'
                    unit.updated_at = _utc_now()
                    changed = True
        if task.status in {'queued', 'running'} and not (worker and worker.is_alive()):
            task.status = 'paused'
            task.checkpoint.current_stage = 'paused'
            task.checkpoint.browser_state = self._map_browser_state()
            changed = True
        if task.status == 'completed_with_errors' and self._target_reached(task):
            task.status = 'completed'
            task.completion_reason = 'target_reached'
            task.checkpoint.current_stage = 'completed'
            changed = True
        self._refresh_summary(task)
        if task.summary.model_dump() != persisted_summary:
            changed = True
        if changed:
            self._persist(task)
        self._tasks[task.id] = task
        return task

    @staticmethod
    def _prune_hard_irrelevant_residential_results(
        task: CollectionTask,
    ) -> bool:
        if not _RESIDENTIAL_REQUEST_PATTERN.search(task.request_text):
            return False

        invalid_candidate_ids = {
            candidate.candidate_id
            for candidate in task.candidates
            if _HARD_IRRELEVANT_COMPANY_PATTERN.search(candidate.company_name)
        }
        before = (
            len(task.company_name_candidates),
            len(task.candidates),
            len(task.results),
            len(task.relevance_decisions),
        )
        task.company_name_candidates = [
            candidate
            for candidate in task.company_name_candidates
            if not _HARD_IRRELEVANT_COMPANY_PATTERN.search(
                candidate.company_name
            )
        ]
        task.candidates = [
            candidate
            for candidate in task.candidates
            if candidate.candidate_id not in invalid_candidate_ids
        ]
        task.results = [
            lead
            for lead in task.results
            if not _HARD_IRRELEVANT_COMPANY_PATTERN.search(lead.company_name)
        ]
        task.relevance_decisions = {
            candidate_id: decisions
            for candidate_id, decisions in task.relevance_decisions.items()
            if candidate_id not in invalid_candidate_ids
        }
        after = (
            len(task.company_name_candidates),
            len(task.candidates),
            len(task.results),
            len(task.relevance_decisions),
        )
        return before != after

    def start(self, task_id: str) -> CollectionTask:
        """Run a task synchronously for compatibility with service callers and tests."""
        self._pause_event(task_id).clear()
        return self._execute(task_id)

    def start_async(self, task_id: str) -> CollectionTask:
        task = self.get_task(task_id)
        if task.status in {'completed', 'cancelled'}:
            return task
        return self._launch(task_id)

    def wait(self, task_id: str, timeout: float | None = None) -> CollectionTask:
        event = self._done_events.get(task_id)
        if event is not None:
            event.wait(timeout)
        return self.get_task(task_id)

    def _execute(self, task_id: str) -> CollectionTask:
        task = self.get_task(task_id)
        if task.status in {'completed', 'cancelled'}:
            return task
        if task.status == 'needs_attention':
            current = self._current_unit(task)
            if current is not None:
                current.status = 'queued'
        task.status = 'running'
        task.checkpoint.current_stage = 'running'
        self._persist(task)

        for unit_index, unit in enumerate(task.work_units):
            if self._cancel_event(task.id).is_set():
                self._cancel_task(task, unit)
                return task
            if self._pause_event(task.id).is_set():
                self._pause_for_user(task, unit)
                return task
            if unit.status in {'succeeded', 'no_result', 'skipped_limit'}:
                continue
            if unit.status in {'needs_attention', 'paused'}:
                unit.status = 'queued'
            if self._city_limit_reached(task, unit):
                unit.status = 'skipped_limit'
                unit.last_error = 'city_limit_reached'
                unit.updated_at = _utc_now()
                if unit.id not in task.checkpoint.completed_work_unit_ids:
                    task.checkpoint.completed_work_unit_ids.append(unit.id)
                continue
            task.checkpoint.current_work_unit_id = unit.id
            try:
                self._run_work_unit(task, unit)
            except _CollectionCancelledRequested:
                self._cancel_task(task, unit)
                return task
            except _CollectionPauseRequested:
                self._pause_for_user(task, unit)
                return task
            except ProviderPaused as exc:
                self._pause_for_provider(task, unit, exc)
                return task
            except Exception as exc:  # noqa: BLE001 - isolate one work unit failure
                self._fail_work_unit(task, unit, str(exc))

            remaining_units = task.work_units[unit_index + 1:]
            self._refresh_summary(task)
            if self._target_reached(task):
                for remaining in remaining_units:
                    if remaining.status in {'succeeded', 'no_result', 'skipped_limit'}:
                        continue
                    remaining.status = 'skipped_limit'
                    remaining.last_error = 'target_valid_contacts_reached'
                    remaining.updated_at = _utc_now()
                    if remaining.id not in task.checkpoint.completed_work_unit_ids:
                        task.checkpoint.completed_work_unit_ids.append(remaining.id)
                break
            if not task.continuous_mode and any(
                remaining.status not in {'succeeded', 'no_result', 'skipped_limit'}
                for remaining in remaining_units
            ):
                task.checkpoint.current_work_unit_id = remaining_units[0].id
                self._refresh_summary(task)
                self._pause_for_user(task, None)
                return task

        if self._cancel_event(task.id).is_set():
            self._cancel_task(task, self._current_unit(task))
            return task
        if self._pause_event(task.id).is_set():
            self._pause_for_user(task, self._current_unit(task))
            return task
        task.checkpoint.current_work_unit_id = None
        has_errors = any(unit.status == 'failed' for unit in task.work_units)
        target_reached = self._target_reached(task)
        task.status = (
            'completed_with_errors'
            if has_errors and not target_reached
            else 'completed'
        )
        if target_reached:
            task.completion_reason = 'target_reached'
        elif has_errors:
            task.completion_reason = 'completed_with_errors'
        elif task.intent.target_valid_contacts is not None:
            task.completion_reason = 'source_exhausted'
        task.checkpoint.current_stage = task.status
        task.checkpoint.browser_state = self._map_browser_state()
        self._refresh_summary(task)
        self._persist(task)
        return task

    def _launch(self, task_id: str) -> CollectionTask:
        task = self.get_task(task_id)
        pause_event = self._pause_event(task_id)
        pause_event.clear()
        task.status = 'queued'
        task.checkpoint.current_stage = 'queued'
        self._persist(task)
        snapshot = task.model_copy(deep=True)
        worker = self._workers.get(task_id)
        if worker is None or not worker.is_alive():
            done = Event()
            self._done_events[task_id] = done

            def run() -> None:
                try:
                    self._execute(task_id)
                finally:
                    done.set()

            worker = Thread(target=run, name=f'collection-task-{task_id}', daemon=True)
            self._workers[task_id] = worker
            worker.start()
        return snapshot

    def pause(self, task_id: str) -> CollectionTask:
        task = self.get_task(task_id)
        if task.status not in {'completed', 'cancelled'}:
            self._pause_event(task_id).set()
            task.status = 'paused'
            task.checkpoint.current_stage = 'paused'
            self._persist(task)
        return task

    def cancel(self, task_id: str) -> CollectionTask:
        task = self.get_task(task_id)
        if task.status in {'completed', 'completed_with_errors', 'cancelled'}:
            return task
        self._cancel_event(task_id).set()
        self._pause_event(task_id).clear()
        self._cancel_task(task, self._current_unit(task))
        return task

    def resume(self, task_id: str) -> CollectionTask:
        task = self.get_task(task_id)
        if task.status in {'paused', 'needs_attention'}:
            self._pause_event(task_id).clear()
            task.status = 'queued'
            self._persist(task)
        if task.status == 'cancelled':
            return task
        return self.start(task_id)

    def resume_async(self, task_id: str) -> CollectionTask:
        task = self.get_task(task_id)
        if task.status == 'cancelled':
            return task
        if task.status in {'paused', 'needs_attention'}:
            self._pause_event(task_id).clear()
        return self._launch(task_id)

    def retry_errors(self, task_id: str) -> CollectionTask:
        task = self.get_task(task_id)
        self._pause_event(task_id).clear()
        self._reset_retryable_units(task)
        task.status = 'queued'
        self._persist(task)
        return self.start(task_id)

    def retry_errors_async(self, task_id: str) -> CollectionTask:
        task = self.get_task(task_id)
        self._reset_retryable_units(task)
        return self._launch(task_id)

    def _reset_retryable_units(self, task: CollectionTask) -> None:
        for unit in task.work_units:
            retry_failure = unit.status in {'failed', 'needs_attention', 'retry_wait'}
            retry_city_limit = (
                unit.status == 'skipped_limit'
                and unit.last_error == 'city_limit_reached'
                and not self._city_limit_reached(task, unit)
            )
            if not (retry_failure or retry_city_limit):
                continue
            unit.status = 'queued'
            unit.last_error = None
            if unit.id in task.checkpoint.failed_work_unit_ids:
                task.checkpoint.failed_work_unit_ids.remove(unit.id)
            if unit.id in task.checkpoint.completed_work_unit_ids:
                task.checkpoint.completed_work_unit_ids.remove(unit.id)

    def summary(self, task_id: str) -> CollectionSummary:
        task = self.get_task(task_id)
        self._refresh_summary(task)
        self._persist(task)
        return task.summary

    def deliver_results(
        self,
        task_id: str,
        *,
        target_url: str,
        bearer_token: str | None = None,
        lead_id: str | None = None,
    ) -> list[tuple[LeadRecord, DeliveryResult]]:
        task = self.get_task(task_id)
        adapter = self._manual_delivery_adapter(target_url, bearer_token)
        selected = (
            [lead for lead in task.results if self._valid_mobile(lead)]
            if lead_id is None
            else [self._find_lead(task, lead_id)]
        )
        delivered: list[tuple[LeadRecord, DeliveryResult]] = []
        for lead in selected:
            if lead is None:
                raise KeyError(f'collection lead not found: {lead_id}')
            mobile = self._valid_mobile(lead)
            if not mobile:
                raise ValueError('lead has no valid Amap mobile')
            lead.mobile = mobile
            delivered.append((lead, self._deliver_with_adapter(
                task,
                lead,
                adapter,
                manual=True,
                destination_scope=target_url,
            )))
        self._refresh_summary(task)
        self._persist(task)
        return delivered

    def refresh_amap_contacts_and_deliver(
        self,
        task_id: str,
        *,
        target_url: str,
        bearer_token: str | None = None,
    ) -> CollectionTask:
        """Re-open each stored company in Amap and deliver only captured mobiles."""
        task = self.get_task(task_id)
        if not target_url.strip():
            raise ValueError('ERP target URL is required')
        adapter = self._manual_delivery_adapter(target_url, bearer_token)
        task.status = 'running'
        task.checkpoint.current_stage = 'refreshing_amap_contacts'
        task.checkpoint.contact_refresh_active = True
        task.checkpoint.contact_refresh_total = len(task.candidates)
        self._persist(task)

        for index, original in enumerate(list(task.candidates)):
            task.checkpoint.contact_refresh_index = index
            self._persist(task)
            self._raise_if_contact_refresh_interrupted(task)
            try:
                lookup = getattr(self.map_provider, 'search_company', None)
                if not callable(lookup):
                    raise TypeError('map provider does not support exact company lookup')
                matches = lookup(
                    company_name=original.company_name,
                    city=original.city,
                    max_results=5,
                )
            except ProviderPaused as exc:
                self._pause_contact_refresh_for_provider(task, exc)
                return task
            except (_CollectionPauseRequested, _CollectionCancelledRequested):
                self._finish_contact_refresh_interrupted(task)
                return task
            except TimeoutError as exc:
                task.errors.append(f'高德详情复核超时：{original.company_name}：{exc}')
                continue

            exact = next(
                (
                    match for match in matches
                    if company_identity(match.city, match.company_name)
                    == company_identity(original.city, original.company_name)
                    and match.source_metadata.get('detail_verified') is True
                ),
                None,
            )
            if exact is None:
                continue
            identity = company_identity(original.city, original.company_name)
            previous_lead = next(
                (
                    lead for lead in task.results
                    if company_identity(lead.city, lead.company_name) == identity
                ),
                None,
            )
            task.results = [
                lead for lead in task.results
                if company_identity(lead.city, lead.company_name) != identity
            ]
            candidate = self._upsert_candidate(
                task,
                exact,
                keyword='高德详情复核',
            )
            self._enrich_and_verify(task, candidate)
            lead = next(
                (
                    item for item in task.results
                    if company_identity(item.city, item.company_name)
                    == company_identity(candidate.city, candidate.company_name)
                ),
                None,
            )
            if lead is None:
                continue
            if previous_lead is not None:
                lead.delivery_status = previous_lead.delivery_status
                lead.delivery_fingerprint = previous_lead.delivery_fingerprint
                lead.delivery_at = previous_lead.delivery_at
            mobile = self._valid_mobile(lead)
            if not mobile:
                continue
            lead.mobile = mobile
            self._deliver_with_adapter(
                task,
                lead,
                adapter,
                manual=True,
                destination_scope=target_url,
            )
            self._refresh_summary(task)
            self._persist(task)

        task.checkpoint.contact_refresh_index = len(task.candidates)
        task.checkpoint.contact_refresh_active = False
        task.checkpoint.current_stage = 'completed'
        task.checkpoint.browser_state = self._map_browser_state()
        task.status = 'completed'
        self._refresh_summary(task)
        self._persist(task)
        return task

    def refresh_amap_contacts_and_deliver_async(
        self,
        task_id: str,
        *,
        target_url: str,
        bearer_token: str | None = None,
    ) -> CollectionTask:
        task = self.get_task(task_id)
        if task.status == 'cancelled':
            return task
        snapshot = task.model_copy(deep=True)
        done = Event()
        self._done_events[task_id] = done

        def run() -> None:
            try:
                self.refresh_amap_contacts_and_deliver(
                    task_id,
                    target_url=target_url,
                    bearer_token=bearer_token,
                )
            finally:
                done.set()

        worker = Thread(target=run, name=f'amap-contact-refresh-{task_id}', daemon=True)
        self._workers[task_id] = worker
        worker.start()
        return snapshot

    def _raise_if_contact_refresh_interrupted(self, task: CollectionTask) -> None:
        if self._cancel_event(task.id).is_set():
            raise _CollectionCancelledRequested()
        if self._pause_event(task.id).is_set():
            raise _CollectionPauseRequested()

    def _finish_contact_refresh_interrupted(self, task: CollectionTask) -> None:
        task.checkpoint.contact_refresh_active = False
        task.status = 'cancelled' if self._cancel_event(task.id).is_set() else 'paused'
        task.checkpoint.current_stage = task.status
        self._persist(task)

    def _pause_contact_refresh_for_provider(
        self,
        task: CollectionTask,
        error: ProviderPaused,
    ) -> None:
        task.checkpoint.contact_refresh_active = False
        task.status = 'needs_attention'
        task.checkpoint.current_stage = 'needs_attention'
        task.checkpoint.browser_state = error.browser_state
        if str(error) not in task.errors:
            task.errors.append(str(error))
        self._persist(task)

    def _run_work_unit(self, task: CollectionTask, unit: CollectionWorkUnit) -> None:
        unit.status = 'running'
        unit.retry_after = None
        unit.updated_at = _utc_now()
        self._persist(task)
        if self.candidate_discovery_provider is not None or callable(
            getattr(self.map_provider, 'search_company', None)
        ):
            self._run_name_discovery_work_unit(task, unit)
            return
        candidates = self.map_provider.search_keyword(
            city=unit.city,
            keyword=unit.keyword,
            max_results=self.max_results_per_work_unit,
        )
        unit.candidate_count = 0
        for discovered in candidates:
            self._raise_if_paused(task, unit)
            if self._is_competitor(task, discovered.company_name):
                continue
            candidate = self._upsert_candidate(task, discovered, keyword=unit.keyword)
            unit.candidate_count += 1
            if not unit.models:
                unit.relevant_count += 1
                self._enrich_and_verify(task, candidate)
                continue
            existing_decisions = task.relevance_decisions.get(candidate.candidate_id, [])
            decisions = self._judge_candidate(
                task,
                unit,
                candidate,
                existing_decisions=existing_decisions,
            )
            merged_decisions = self._merge_decisions(existing_decisions, decisions)
            task.relevance_decisions[candidate.candidate_id] = merged_decisions
            if _combined_status(merged_decisions) != 'relevant':
                continue
            self._raise_if_paused(task, unit)
            unit.relevant_count += 1
            self._enrich_and_verify(task, candidate)
        unit.status = 'succeeded' if candidates else 'no_result'
        unit.updated_at = _utc_now()
        if unit.id not in task.checkpoint.completed_work_unit_ids:
            task.checkpoint.completed_work_unit_ids.append(unit.id)
        self._refresh_summary(task)
        self._persist(task)

    def _run_name_discovery_work_unit(self, task: CollectionTask, unit: CollectionWorkUnit) -> None:
        provider = self.candidate_discovery_provider
        name_candidates = (
            provider.discover_company_names(
                city=unit.city,
                keyword=unit.keyword,
                request_text=task.request_text,
                max_results=self.max_results_per_work_unit,
            )
            if provider is not None
            else []
        )
        broad_candidates = self.map_provider.search_keyword(
            city=unit.city,
            keyword=unit.keyword,
            max_results=self.max_results_per_work_unit,
        )
        name_candidates.extend(
            CompanyNameCandidate(
                company_name=candidate.company_name,
                city=unit.city,
                matched_keyword=unit.keyword,
                source_urls=[candidate.source_url] if candidate.source_url else [],
                evidence_quotes=[candidate.raw_text] if candidate.raw_text else [],
                discovery_channel='amap_keyword',
            )
            for candidate in broad_candidates
            if candidate.company_name.strip()
        )
        unique_name_candidates: list[CompanyNameCandidate] = []
        seen_names: set[str] = set()
        for name_candidate in name_candidates:
            normalized_name = normalize_company_name(name_candidate.company_name)
            if not normalized_name or normalized_name.casefold() in seen_names:
                continue
            if not self._is_target_business_candidate(task, name_candidate):
                continue
            if (
                _RESIDENTIAL_REQUEST_PATTERN.search(task.request_text)
                and _HARD_IRRELEVANT_COMPANY_PATTERN.search(normalized_name)
            ):
                continue
            seen_names.add(normalized_name.casefold())
            unique_name_candidates.append(name_candidate)
        name_candidates = unique_name_candidates
        unit.company_name_candidate_count = 0
        unit.map_match_count = 0
        unit.candidate_count = 0
        unit.relevant_count = 0
        lookup_errors: list[str] = []
        for name_candidate in name_candidates:
            name_candidate = name_candidate.model_copy(update={'city': unit.city})
            self._raise_if_paused(task, unit)
            if self._target_reached(task):
                break
            if self._is_competitor(task, name_candidate.company_name):
                continue
            if self._company_name_seen_in_other_task(task.id, name_candidate.company_name):
                continue
            if self._company_name_searched_in_earlier_work_unit(task, unit, name_candidate.company_name):
                continue
            unit.company_name_candidate_count += 1
            self._upsert_company_name_candidate(task, name_candidate)
            lookup = getattr(self.map_provider, 'search_company', None)
            if not callable(lookup):
                raise TypeError('map provider does not support exact company lookup')
            try:
                matches = lookup(
                    company_name=name_candidate.company_name,
                    city=unit.city,
                    max_results=5,
                )
            except ProviderPaused:
                raise
            except TimeoutError as exc:
                lookup_errors.append(f'{name_candidate.company_name}：{exc}')
                continue
            for match in matches:
                if company_identity(match.city, match.company_name) != company_identity(
                    unit.city,
                    name_candidate.company_name,
                ):
                    continue
                discovered = self._attach_name_evidence(match, name_candidate)
                candidate = self._upsert_candidate(task, discovered, keyword=unit.keyword)
                unit.candidate_count += 1
                unit.map_match_count += 1
                unit.relevant_count += 1
                self._enrich_and_verify(task, candidate)
                if self._target_reached(task):
                    break
        if lookup_errors:
            self._fail_work_unit(task, unit, f"高德精确查询超时：{'；'.join(lookup_errors)}")
        else:
            unit.status = 'succeeded' if name_candidates else 'no_result'
        unit.updated_at = _utc_now()
        if not lookup_errors and unit.id not in task.checkpoint.completed_work_unit_ids:
            task.checkpoint.completed_work_unit_ids.append(unit.id)
        self._refresh_summary(task)
        self._persist(task)

    @staticmethod
    def _upsert_company_name_candidate(
        task: CollectionTask,
        incoming: CompanyNameCandidate,
    ) -> None:
        normalized = incoming.company_name.replace(' ', '').casefold()
        existing = next(
            (
                item for item in task.company_name_candidates
                if item.city == incoming.city
                and item.company_name.replace(' ', '').casefold() == normalized
            ),
            None,
        )
        if existing is None:
            task.company_name_candidates.append(incoming.model_copy(deep=True))
            return
        existing.source_urls = list(dict.fromkeys([*existing.source_urls, *incoming.source_urls]))
        existing.evidence_quotes = list(dict.fromkeys([*existing.evidence_quotes, *incoming.evidence_quotes]))

    @staticmethod
    def _attach_name_evidence(
        candidate: MapPoiCandidate,
        name_candidate: CompanyNameCandidate,
    ) -> MapPoiCandidate:
        enriched = candidate.model_copy(deep=True)
        metadata = dict(enriched.source_metadata)
        metadata['discovery_channel'] = name_candidate.discovery_channel
        metadata['company_name_evidence_urls'] = list(name_candidate.source_urls)
        metadata['company_name_evidence_quotes'] = list(name_candidate.evidence_quotes)
        metadata['amap_category'] = candidate.category
        metadata['amap_coordinates'] = {
            'longitude': candidate.longitude,
            'latitude': candidate.latitude,
        }
        metadata['amap_poi_id'] = candidate.poi_id
        enriched.source_metadata = metadata
        return enriched

    def _judge_candidate(
        self,
        task: CollectionTask,
        unit: CollectionWorkUnit,
        candidate: MapPoiCandidate,
        *,
        existing_decisions: list[RelevanceDecision] | None = None,
    ) -> list[RelevanceDecision]:
        decisions: list[RelevanceDecision] = []
        existing = existing_decisions or []
        for model_id in unit.models:
            if any(
                decision.model_id == model_id and decision.keyword == unit.keyword
                for decision in existing
            ):
                continue
            judge = self.relevance_judges.get(model_id)
            if judge is None:
                decisions.append(
                    RelevanceDecision(
                        candidate_id=candidate.candidate_id,
                        model_id=model_id,
                        keyword=unit.keyword,
                        status='review',
                        reason='模型未配置，等待人工复核',
                    )
                )
                continue
            judge_method = getattr(judge, 'judge', None) or getattr(judge, 'judge_relevance', None)
            if not callable(judge_method):
                decisions.append(
                    RelevanceDecision(
                        candidate_id=candidate.candidate_id,
                        model_id=model_id,
                        keyword=unit.keyword,
                        status='review',
                        reason='模型没有提供相关性判断接口，等待人工复核',
                    )
                )
                continue
            decision = judge_method(
                request_text=task.request_text,
                city=unit.city,
                keyword=unit.keyword,
                candidate=candidate,
            )
            decisions.append(
                decision.model_copy(
                    update={
                        'candidate_id': candidate.candidate_id,
                        'keyword': unit.keyword,
                    }
                )
            )
        return decisions

    def _upsert_candidate(
        self,
        task: CollectionTask,
        discovered: MapPoiCandidate,
        *,
        keyword: str,
    ) -> MapPoiCandidate:
        incoming = discovered.model_copy(deep=True)
        metadata = dict(incoming.source_metadata)
        metadata['matched_keywords'] = [keyword]
        incoming.source_metadata = metadata
        existing = self._find_candidate(task, incoming)
        if existing is None:
            if not incoming.source_urls and incoming.source_url:
                incoming.source_urls = [incoming.source_url]
            task.candidates.append(incoming)
            return incoming
        merge_map_candidate(existing, incoming)
        return existing

    @staticmethod
    def _merge_decisions(
        existing: list[RelevanceDecision],
        incoming: list[RelevanceDecision],
    ) -> list[RelevanceDecision]:
        merged = list(existing)
        seen = {(decision.model_id, decision.keyword) for decision in merged}
        for decision in incoming:
            key = (decision.model_id, decision.keyword)
            if key not in seen:
                merged.append(decision)
                seen.add(key)
        return merged

    def _raise_if_paused(self, task: CollectionTask, unit: CollectionWorkUnit) -> None:
        if self._cancel_event(task.id).is_set():
            raise _CollectionCancelledRequested(unit.id)
        if self._pause_event(task.id).is_set():
            raise _CollectionPauseRequested(unit.id)

    def _enrich_and_verify(self, task: CollectionTask, candidate: MapPoiCandidate) -> None:
        enrichment = (
            self.enrichment_gateway.enrich_company(
                company_name=candidate.company_name,
                city=candidate.city,
                requested_contacts=list(task.intent.required_contacts),
                known_fields={
                    'address': candidate.address,
                    'telephone': candidate.telephone,
                    'source_url': candidate.source_url,
                    'category': candidate.category,
                    'poi_id': candidate.poi_id,
                },
            )
            if self.enrichment_gateway is not None
            else DoubaoEnrichment()
        )
        amap_safe_enrichment = enrichment.model_copy(
            update={'mobile': None, 'telephone': None, 'address': None}
        )
        if (
            candidate.source_metadata.get('detail_verified') is False
            or (
                candidate.source_metadata.get('provider') == 'amap_web'
                and candidate.source_metadata.get('detail_verified') is not True
            )
        ):
            candidate = candidate.model_copy(update={'mobile': None})
        lead = merge_candidate_with_enrichment(
            candidate,
            amap_safe_enrichment,
            task_id=task.id,
        )
        evidence = self.evidence_verifier.verify(
            candidate,
            expected_company_name=lead.company_name,
            expected_contact=lead.mobile or lead.email,
        )
        self._apply_evidence(lead, evidence)
        if self.public_evidence_verifier is not None and (lead.mobile or lead.email):
            try:
                public_evidence = self.public_evidence_verifier.verify_contact(
                    company_name=lead.company_name,
                    mobile=lead.mobile,
                    email=lead.email,
                    source_urls=list(lead.source_urls),
                )
            except Exception as exc:  # noqa: BLE001 - public evidence is an independent best-effort source
                task.errors.append(f'公开证据核验失败：{lead.company_name}：{exc}')
            else:
                self._apply_evidence(lead, public_evidence)
        self._auto_deliver(task, lead)
        task.results = [existing for existing in task.results if existing.id != lead.id]
        task.results.append(lead)

    @staticmethod
    def _apply_evidence(lead: LeadRecord, evidence) -> None:
        if evidence.company_name_verification_status:
            lead.company_name_verification_status = evidence.company_name_verification_status
        lead.contact_verification_status = evidence.contact_verification_status
        lead.contact_evidence_urls = list(dict.fromkeys([*lead.contact_evidence_urls, *evidence.source_urls]))
        lead.contact_evidence_quotes = list(dict.fromkeys([*lead.contact_evidence_quotes, *evidence.quotes]))
        lead.source_urls = list(dict.fromkeys([*lead.source_urls, *evidence.source_urls]))
        lead.evidence_quotes = list(dict.fromkeys([*lead.evidence_quotes, *evidence.quotes]))
        for field, field_evidence in evidence.field_evidence.items():
            existing = lead.field_evidence.get(field)
            if existing is None:
                lead.field_evidence[field] = field_evidence
            else:
                lead.field_evidence[field] = existing.model_copy(
                    update={
                        'status': field_evidence.status,
                        'source_urls': list(dict.fromkeys([*existing.source_urls, *field_evidence.source_urls])),
                        'quotes': list(dict.fromkeys([*existing.quotes, *field_evidence.quotes])),
                    }
                )

    def _auto_deliver(self, task: CollectionTask, lead: LeadRecord) -> DeliveryResult | None:
        if not (task.auto_deliver or task.verified_auto_deliver):
            return None
        if not self._valid_mobile(lead):
            return None
        if self.erp_adapter is None or not contact_requirement_satisfied(lead, task.intent):
            return None
        if not self._contact_evidence_satisfied(lead, task):
            lead.delivery_status = 'display_only'
            return None
        if lead.contact_verification_status not in {
            'verified',
            'verified_public_web',
            'verified_cross_source',
        } and lead.source_metadata.get('detail_verified') is not True:
            return None

        return self._deliver_with_adapter(task, lead, self.erp_adapter, manual=False)

    def _deliver_with_adapter(
        self,
        task: CollectionTask,
        lead: LeadRecord,
        adapter: ErpAdapter,
        *,
        manual: bool,
        destination_scope: str | None = None,
    ) -> DeliveryResult:
        fingerprint: str | None = None
        try:
            payload = adapter.build_payload(task, lead)
            fingerprint = self._delivery_fingerprint(
                adapter,
                payload,
                destination_scope=destination_scope,
            )
            if lead.delivery_status == 'delivered' and lead.delivery_fingerprint == fingerprint:
                lead.delivery_status = 'duplicate'
                return DeliveryResult(
                    status='duplicate',
                    reasons=['duplicate_payload'],
                    operation_id=None,
                    payload=payload,
                )
            normalized_mobile = normalize_mobile(lead.mobile)
            legacy_mobile_duplicate = next(
                (
                    existing
                    for existing in task.results
                    if not manual
                    and existing.id != lead.id
                    and existing.delivery_status == 'delivered'
                    and normalized_mobile
                    and normalize_mobile(existing.mobile) == normalized_mobile
                ),
                None,
            )
            if legacy_mobile_duplicate is not None:
                lead.delivery_status = 'duplicate'
                lead.delivery_fingerprint = fingerprint
                return DeliveryResult(
                    status='duplicate',
                    reasons=['duplicate_mobile'],
                    operation_id=None,
                    payload=payload,
                )
            task_duplicate = next(
                (
                    existing
                    for existing in task.results
                    if existing.id != lead.id
                    and existing.delivery_status == 'delivered'
                    and existing.delivery_fingerprint == fingerprint
                ),
                None,
            )
            if task_duplicate is not None:
                lead.delivery_status = 'duplicate'
                lead.delivery_fingerprint = fingerprint
                return DeliveryResult(
                    status='duplicate',
                    reasons=['duplicate_mobile'],
                    operation_id=None,
                    payload=payload,
                )
            previous = self._get_delivery(fingerprint)
            if previous is not None and previous.status == 'delivered':
                lead.delivery_status = 'duplicate'
                lead.delivery_fingerprint = fingerprint
                return DeliveryResult(
                    status='duplicate',
                    reasons=['duplicate_payload'],
                    operation_id=previous.operation_id,
                    payload=payload,
                )
            result = adapter.deliver(payload)
        except Exception as exc:  # noqa: BLE001 - preserve the lead when ERP is unavailable
            result = DeliveryResult(status='failed', error=str(exc))
            action = '人工推送' if manual else '自动投递'
            task.errors.append(f'ERP {action}失败：{lead.company_name}：{exc}')

        lead.delivery_status = result.status
        if result.status == 'delivered':
            lead.delivery_at = datetime.now(UTC)
        if result.status in {'delivered', 'duplicate'} and fingerprint is not None:
            lead.delivery_fingerprint = fingerprint
        if fingerprint is not None:
            self._record_delivery(
                task=task,
                lead=lead,
                fingerprint=fingerprint,
                payload=payload,
                result=result,
            )
        return result

    @staticmethod
    def _delivery_fingerprint(
        adapter: ErpAdapter,
        payload: dict[str, object],
        *,
        destination_scope: str | None,
    ) -> str:
        contact_info = payload.get('contactInfo')
        mobile = None
        if isinstance(contact_info, dict):
            mobile = normalize_mobile(contact_info.get('mobilePhone'))
        base_fingerprint = (
            payload_fingerprint({'mobile': mobile})
            if mobile
            else adapter.fingerprint(payload)
        )
        scope = destination_scope or getattr(adapter, 'target_url', None)
        if not scope:
            return base_fingerprint
        parsed = urlsplit(str(scope).strip())
        normalized_path = parsed.path.rstrip('/') or '/'
        normalized_scope = urlunsplit((
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            normalized_path,
            parsed.query,
            '',
        ))
        return payload_fingerprint({
            'destination': normalized_scope,
            'payload_fingerprint': base_fingerprint,
        })

    def _manual_delivery_adapter(self, target_url: str, bearer_token: str | None) -> ErpAdapter:
        if self.manual_delivery_adapter_factory is not None:
            return self.manual_delivery_adapter_factory(target_url, bearer_token)
        from backend.app.providers.erp import ErpHttpAdapter

        return ErpHttpAdapter(target_url=target_url, bearer_token=bearer_token)

    def _map_browser_state(self) -> str:
        state = getattr(self.map_provider, 'last_state', None)
        if state is None:
            browser = getattr(self.map_provider, 'browser', None)
            state = getattr(browser, 'state', None)
        return str(getattr(state, 'value', state) or 'stopped')

    @staticmethod
    def _find_lead(task: CollectionTask, lead_id: str) -> LeadRecord | None:
        return next((lead for lead in task.results if lead.id == lead_id), None)

    @staticmethod
    def _contact_evidence_satisfied(task_lead: LeadRecord, task: CollectionTask) -> bool:
        fields = list(task.intent.required_contacts)
        matches = [
            bool(getattr(task_lead, field, None))
            and task_lead.field_evidence.get(field) is not None
            and task_lead.field_evidence[field].status == 'verified'
            for field in fields
        ]
        return all(matches) if task.intent.contact_match == 'all' else any(matches)

    def _get_delivery(self, fingerprint: str):
        if self.repository is None or not hasattr(self.repository, 'get_delivery'):
            return None
        return self.repository.get_delivery(fingerprint)

    def _record_delivery(
        self,
        *,
        task: CollectionTask,
        lead: LeadRecord,
        fingerprint: str,
        payload: dict[str, object],
        result: DeliveryResult,
    ) -> None:
        if self.repository is None or not hasattr(self.repository, 'record_delivery'):
            return
        self.repository.record_delivery(
            task_id=task.id,
            lead_id=lead.id,
            fingerprint=fingerprint,
            payload=payload,
            result=result,
        )

    @staticmethod
    def _find_candidate(task: CollectionTask, candidate: MapPoiCandidate) -> MapPoiCandidate | None:
        identity = company_identity(candidate.city, candidate.company_name)
        return next(
            (
                existing
                for existing in task.candidates
                if company_identity(existing.city, existing.company_name) == identity
            ),
            None,
        )

    @staticmethod
    def _company_name_key(value: object) -> str:
        return (normalize_company_name(value) or '').casefold()

    def _company_name_seen_in_other_task(self, task_id: str, company_name: str) -> bool:
        key = self._company_name_key(company_name)
        if not key:
            return False
        tasks: list[CollectionTask] = list(self._tasks.values())
        if self.repository is not None and hasattr(self.repository, 'list'):
            known_ids = {task.id for task in tasks}
            tasks.extend(item for item in self.repository.list() if item.id not in known_ids)
        for other in tasks:
            if other.id == task_id:
                continue
            names = [
                *(item.company_name for item in other.company_name_candidates),
                *(item.company_name for item in other.candidates),
                *(item.company_name for item in other.results),
            ]
            if any(self._company_name_key(name) == key for name in names):
                return True
        return False

    def _company_name_searched_in_earlier_work_unit(
        self,
        task: CollectionTask,
        unit: CollectionWorkUnit,
        company_name: str,
    ) -> bool:
        identity = company_identity(unit.city, company_name)
        if any(
            company_identity(item.city, item.company_name) == identity
            for item in [*task.candidates, *task.results]
        ):
            return True
        return any(
            company_identity(item.city, item.company_name) == identity
            and item.matched_keyword != unit.keyword
            for item in task.company_name_candidates
        )

    @staticmethod
    def _is_competitor(task: CollectionTask, company_name: str) -> bool:
        refreshed_terms = parse_collection_intent(
            task.request_text,
            configured_models=set(),
        ).competitor_terms
        terms = list(dict.fromkeys([
            *task.intent.competitor_terms,
            *refreshed_terms,
        ]))
        return bool(terms and any(term in company_name for term in terms))

    @staticmethod
    def _is_target_business_candidate(
        task: CollectionTask,
        candidate: CompanyNameCandidate,
    ) -> bool:
        """Keep broad Amap POIs out unless name or source evidence proves target business."""
        name = normalize_company_name(candidate.company_name)
        if not name or _LOCATION_POI_PATTERN.search(name):
            return False
        evidence = '\n'.join([name, *candidate.evidence_quotes])
        if _HARD_IRRELEVANT_COMPANY_PATTERN.search(evidence):
            return False
        if not _RESIDENTIAL_REQUEST_PATTERN.search(task.request_text):
            return True
        return bool(_TARGET_RESIDENTIAL_BUSINESS_PATTERN.search(evidence))

    @staticmethod
    def _current_unit(task: CollectionTask) -> CollectionWorkUnit | None:
        current_id = task.checkpoint.current_work_unit_id
        return next((unit for unit in task.work_units if unit.id == current_id), None)

    def _city_limit_reached(self, task: CollectionTask, unit: CollectionWorkUnit) -> bool:
        if unit.limit_per_city is None:
            return False
        return len(self._unique_phone_valid_leads(task, city=unit.city)) >= unit.limit_per_city

    def _pause_for_provider(
        self,
        task: CollectionTask,
        unit: CollectionWorkUnit,
        error: ProviderPaused,
    ) -> None:
        unit.status = 'needs_attention'
        unit.last_error = str(error)
        unit.retry_count += 1
        unit.updated_at = _utc_now()
        task.status = 'needs_attention'
        task.checkpoint.current_stage = 'needs_attention'
        task.checkpoint.browser_state = error.browser_state
        task.checkpoint.retry_after = None
        if str(error) not in task.errors:
            task.errors.append(str(error))
        self._persist(task)

    def _pause_for_user(
        self,
        task: CollectionTask,
        unit: CollectionWorkUnit | None,
    ) -> None:
        if unit is not None and unit.status == 'running':
            unit.status = 'paused'
            unit.updated_at = _utc_now()
        task.status = 'paused'
        task.checkpoint.current_stage = 'paused'
        self._persist(task)

    def _cancel_task(
        self,
        task: CollectionTask,
        unit: CollectionWorkUnit | None,
    ) -> None:
        if unit is not None and unit.status == 'running':
            unit.status = 'cancelled'
            unit.updated_at = _utc_now()
        task.status = 'cancelled'
        task.checkpoint.current_stage = 'cancelled'
        task.checkpoint.current_work_unit_id = None
        self._persist(task)

    @staticmethod
    def _fail_work_unit(task: CollectionTask, unit: CollectionWorkUnit, error: str) -> None:
        unit.status = 'failed'
        unit.last_error = error
        unit.retry_count += 1
        unit.retry_after = _utc_now()
        unit.updated_at = _utc_now()
        if unit.id not in task.checkpoint.failed_work_unit_ids:
            task.checkpoint.failed_work_unit_ids.append(unit.id)
        task.errors.append(error)

    def _refresh_summary(self, task: CollectionTask) -> None:
        relevant = {
            candidate_id
            for candidate_id, decisions in task.relevance_decisions.items()
            if _combined_status(decisions) == 'relevant'
        }
        review = {
            candidate_id
            for candidate_id, decisions in task.relevance_decisions.items()
            if _combined_status(decisions) == 'review'
        }
        map_matched_without_model = {
            candidate.candidate_id
            for candidate in task.candidates
            if candidate.candidate_id not in task.relevance_decisions
        }
        contact_count = sum(
            contact_requirement_satisfied(lead, task.intent)
            for lead in task.results
        )
        valid_leads = self._unique_phone_valid_leads(task)
        task.summary = CollectionSummary(
            total_work_units=len(task.work_units),
            completed_work_units=sum(
                unit.status in {'succeeded', 'no_result', 'skipped_limit'}
                for unit in task.work_units
            ),
            candidate_count=len(task.candidates),
            relevant_count=len(relevant | map_matched_without_model),
            review_count=len(review),
            contact_count=contact_count,
            verified_count=sum(
                lead.contact_verification_status in {
                    'verified',
                    'verified_map',
                    'verified_public_web',
                    'verified_cross_source',
                }
                for lead in task.results
            ),
            erp_success_count=sum(lead.delivery_status == 'delivered' for lead in task.results),
            erp_failure_count=sum(lead.delivery_status == 'failed' for lead in task.results),
            target_valid_contacts=task.intent.target_valid_contacts,
            valid_contact_count=len(valid_leads),
            no_phone_count=sum(
                not (
                    normalize_mobile(candidate.mobile)
                    or normalize_mobile(candidate.telephone)
                )
                for candidate in task.candidates
            ),
            rejected_count=max(0, len(task.company_name_candidates) - len(task.candidates)),
            source_exhausted=task.completion_reason == 'source_exhausted',
        )

    def _unique_phone_valid_leads(
        self,
        task: CollectionTask,
        *,
        city: str | None = None,
    ) -> list[LeadRecord]:
        unique: list[LeadRecord] = []
        phones: set[str] = set()
        for lead in task.results:
            if city is not None and lead.city != city:
                continue
            phone = self._valid_mobile(lead)
            if not phone or phone in phones:
                continue
            phones.add(phone)
            unique.append(lead)
        return unique

    @staticmethod
    def _valid_mobile(lead: LeadRecord) -> str | None:
        if lead.source_metadata.get('detail_verified') is False:
            return None
        if (
            lead.source_metadata.get('provider') == 'amap_web'
            and lead.source_metadata.get('detail_verified') is not True
        ):
            return None
        mobile = normalize_mobile(lead.mobile)
        if not mobile:
            return None
        if lead.source_metadata.get('detail_verified') is True:
            raw_text = str(lead.source_metadata.get('detail_raw_text') or '')
            digits = re.sub(r'\D', '', raw_text)
            if mobile not in digits:
                return None
        return mobile

    @staticmethod
    def _canonicalize_mobile_fields(task: CollectionTask) -> bool:
        changed = False
        for record in [*task.candidates, *task.results]:
            normalized_mobile = normalize_mobile(record.mobile)
            mobile = normalized_mobile or normalize_mobile(record.telephone)
            if record.source_metadata.get('detail_verified') is False or (
                record.source_metadata.get('provider') == 'amap_web'
                and record.source_metadata.get('detail_verified') is not True
            ):
                mobile = None
            if record.mobile is not None and normalized_mobile is None:
                record.mobile = None
                changed = True
            if not mobile:
                continue
            if record.mobile != mobile or record.telephone is not None:
                record.mobile = mobile
                record.telephone = None
                changed = True
        return changed

    def _target_reached(self, task: CollectionTask) -> bool:
        target = task.intent.target_valid_contacts
        return target is not None and len(self._unique_phone_valid_leads(task)) >= target

    def _pause_event(self, task_id: str) -> Event:
        with self._state_lock:
            return self._pause_events.setdefault(task_id, Event())

    def _cancel_event(self, task_id: str) -> Event:
        with self._state_lock:
            return self._cancel_events.setdefault(task_id, Event())

    def _persist(self, task: CollectionTask) -> None:
        if self.repository:
            self.repository.save(task)


def _combined_status(decisions: list[RelevanceDecision]) -> str:
    statuses = {decision.status for decision in decisions}
    if statuses == {'relevant'}:
        return 'relevant'
    if statuses == {'not_relevant'}:
        return 'not_relevant'
    return 'review'


def _utc_now() -> datetime:
    return datetime.now(UTC)
