from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from backend.app.domain.evidence import evaluate_delivery_gate
from backend.app.domain.merge import merge_candidate_with_enrichment
from backend.app.domain.models import DeliveryLedgerEntry, DeliveryPolicy, DeliveryResult, LeadRecord
from backend.app.domain.task_state import CompanyProgress, SearchTask, transition_task_status
from backend.app.providers.protocols import (
    DoubaoEnrichmentGateway,
    ErpAdapter,
    MapDiscoveryProvider,
    MapEvidenceVerifier,
    ProviderPaused,
    PublicEvidenceProvider,
)


class TaskStore(Protocol):
    def save(self, task: SearchTask) -> None: ...

    def get(self, task_id: str) -> SearchTask | None: ...

    def get_delivery(self, fingerprint: str) -> DeliveryLedgerEntry | None: ...

    def record_delivery(
        self,
        *,
        task_id: str,
        lead_id: str,
        fingerprint: str,
        payload: dict[str, object],
        result: DeliveryResult,
    ) -> DeliveryLedgerEntry: ...


class CompanySearchService:
    def __init__(
        self,
        *,
        map_provider: MapDiscoveryProvider,
        doubao_gateway: DoubaoEnrichmentGateway,
        evidence_verifier: MapEvidenceVerifier,
        erp_adapter: ErpAdapter,
        repository: TaskStore | None = None,
        map_providers: dict[str, MapDiscoveryProvider] | None = None,
        doubao_gateways: dict[str, DoubaoEnrichmentGateway] | None = None,
        public_evidence_verifier: PublicEvidenceProvider | None = None,
    ) -> None:
        self.map_provider = map_provider
        self.doubao_gateway = doubao_gateway
        self.evidence_verifier = evidence_verifier
        self.erp_adapter = erp_adapter
        self.repository = repository
        self.map_providers = dict(map_providers or {})
        self.map_providers.setdefault(map_provider.id, map_provider)
        self.doubao_gateways = dict(doubao_gateways or {})
        self.doubao_gateways.setdefault(doubao_gateway.id, doubao_gateway)
        self.public_evidence_verifier = public_evidence_verifier
        self._tasks: dict[str, SearchTask] = {}

    def create_task(
        self,
        *,
        company_name: str,
        city: str,
        required_contacts: list[str] | None = None,
        auto_deliver: bool = False,
        allow_map_only_verification: bool = False,
        discovery_provider: str = 'amap_web',
        enrichment_provider: str = 'doubao_web',
    ) -> SearchTask:
        task = SearchTask(
            id=uuid4().hex,
            company_name=company_name.strip(),
            city=city.strip(),
            discovery_provider=discovery_provider,
            enrichment_provider=enrichment_provider,
            required_contacts=required_contacts or ['mobile', 'email', 'wechat'],
            auto_deliver=auto_deliver,
            allow_map_only_verification=allow_map_only_verification,
        )
        self._tasks[task.id] = task
        self._persist(task)
        return task

    def get_task(self, task_id: str) -> SearchTask:
        try:
            return self._tasks[task_id]
        except KeyError:
            task = self.repository.get(task_id) if self.repository else None
            if task:
                self._tasks[task.id] = task
                return task
            raise KeyError(f'task not found: {task_id}') from None

    def start(self, task_id: str) -> SearchTask:
        task = self.get_task(task_id)
        if task.status in {'paused', 'waiting_for_login', 'waiting_for_challenge'}:
            self.resume(task_id)
            task = self.get_task(task_id)
        if task.status == 'created' or (task.status == 'completed_with_errors' and not task.candidates):
            return self.discover(task_id)
        if task.status == 'discovering_map':
            return self.discover(task_id)
        if task.status == 'enriching_doubao' and task.checkpoint.current_company_id:
            return self.enrich(task_id, candidate_id=task.checkpoint.current_company_id)
        if task.status == 'verifying' and task.checkpoint.current_company_id:
            return self.verify(task_id, candidate_id=task.checkpoint.current_company_id)
        if task.status == 'delivering' and task.checkpoint.current_company_id:
            self.deliver(task_id, candidate_id=task.checkpoint.current_company_id)
            return self.get_task(task_id)
        return task

    def discover(self, task_id: str) -> SearchTask:
        task = self.get_task(task_id)
        map_provider = self.map_providers.get(task.discovery_provider, self.map_provider)
        if task.status != 'discovering_map':
            task.status = transition_task_status(task.status, 'discovering_map')
        task.checkpoint.current_stage = 'discovering_map'
        task.checkpoint.current_company_index = 0
        task.checkpoint.current_company_id = None
        task.checkpoint.retry_after = None
        self._persist(task)
        try:
            task.candidates = map_provider.search_company(
                company_name=task.company_name,
                city=task.city,
            )
        except ProviderPaused as exc:
            return self._pause_for_provider(task, exc)
        except Exception as exc:  # noqa: BLE001 - isolate one provider failure in the task
            task.errors.append(str(exc))
            task.status = 'completed_with_errors'
            task.checkpoint.retry_after = _utc_now()
            self._persist(task)
            return task

        task.checkpoint.browser_state = _provider_browser_state(map_provider)
        now = _utc_now()
        task.progress = {
            candidate.candidate_id: CompanyProgress(
                candidate_id=candidate.candidate_id,
                last_updated_at=now,
            )
            for candidate in task.candidates
        }
        task.checkpoint.current_stage = 'candidates_ready'
        task.checkpoint.current_company_id = task.candidates[0].candidate_id if task.candidates else None
        task.checkpoint.completed_company_ids = [candidate.candidate_id for candidate in task.candidates]
        task.checkpoint.last_successful_query_at = now
        task.checkpoint.retry_after = None
        task.status = transition_task_status(task.status, 'candidates_ready')
        self._persist(task)
        return task

    def enrich(self, task_id: str, *, candidate_id: str) -> SearchTask:
        task = self.get_task(task_id)
        doubao_gateway = self.doubao_gateways.get(task.enrichment_provider, self.doubao_gateway)
        if task.status != 'enriching_doubao':
            task.status = transition_task_status(task.status, 'enriching_doubao')
        candidate = self._candidate(task, candidate_id)
        self._set_current_company(task, candidate_id, stage='enriching_doubao')
        self._persist(task)
        try:
            enrichment = doubao_gateway.enrich_company(
                company_name=candidate.company_name,
                city=candidate.city,
                requested_contacts=task.required_contacts,
                known_fields={
                    'address': candidate.address,
                    'telephone': candidate.telephone,
                    'source_url': candidate.source_url,
                    'category': candidate.category,
                    'poi_id': candidate.poi_id,
                },
            )
            lead = merge_candidate_with_enrichment(candidate, enrichment, task_id=task.id)
        except ProviderPaused as exc:
            return self._pause_for_provider(task, exc)
        except Exception as exc:  # noqa: BLE001 - isolate one company enrichment failure
            self._record_company_error(task, candidate_id, str(exc))
            return task

        task.leads = [existing for existing in task.leads if existing.id != lead.id]
        task.leads.append(lead)
        task.progress[candidate_id].enrichment_state = 'completed'
        self._touch_progress(task, candidate_id)
        self._clear_company_error(task, candidate_id)
        task.checkpoint.current_stage = 'enriching_doubao'
        task.checkpoint.current_company_id = candidate_id
        self._persist(task)
        return task

    def verify(self, task_id: str, *, candidate_id: str | None = None) -> SearchTask:
        task = self.get_task(task_id)
        candidate_id = candidate_id or task.checkpoint.current_company_id
        if not candidate_id:
            raise ValueError('candidate_id is required when the task has no current company')
        if task.status != 'verifying':
            task.status = transition_task_status(task.status, 'verifying')
        candidate = self._candidate(task, candidate_id)
        lead = self._lead(task, candidate_id)
        self._set_current_company(task, candidate_id, stage='verifying')
        self._persist(task)
        try:
            evidence = self.evidence_verifier.verify(
                candidate,
                expected_company_name=lead.company_name,
                expected_contact=lead.mobile or lead.email,
            )
            public_evidence = self._verify_public_contact(candidate, lead)
            if public_evidence is not None and public_evidence.contact_verification_status == 'verified_public_web':
                evidence.company_name_verification_status = (
                    public_evidence.company_name_verification_status
                    or evidence.company_name_verification_status
                )
                evidence.contact_verification_status = public_evidence.contact_verification_status
                evidence.source_urls = [*evidence.source_urls, *public_evidence.source_urls]
                evidence.quotes = [*evidence.quotes, *public_evidence.quotes]
                evidence.field_evidence = {
                    **evidence.field_evidence,
                    **public_evidence.field_evidence,
                }
                evidence.grade = public_evidence.grade or evidence.grade
                evidence.score = public_evidence.score if public_evidence.score is not None else evidence.score
        except Exception as exc:  # noqa: BLE001 - isolate one company verification failure
            self._record_company_error(task, candidate_id, str(exc))
            return task

        if evidence.company_name_verification_status:
            lead.company_name_verification_status = evidence.company_name_verification_status
        lead.contact_verification_status = evidence.contact_verification_status
        lead.contact_evidence_urls = list(dict.fromkeys([*lead.contact_evidence_urls, *evidence.source_urls]))
        lead.contact_evidence_quotes = list(dict.fromkeys([*lead.contact_evidence_quotes, *evidence.quotes]))
        lead.source_urls = list(dict.fromkeys([*lead.source_urls, *evidence.source_urls]))
        lead.evidence_quotes = list(dict.fromkeys([*lead.evidence_quotes, *evidence.quotes]))
        lead.contact_evidence_grade = evidence.grade or lead.contact_evidence_grade
        lead.contact_evidence_score = evidence.score if evidence.score is not None else lead.contact_evidence_score
        for field, field_evidence in evidence.field_evidence.items():
            existing = lead.field_evidence.get(field)
            if existing is None:
                lead.field_evidence[field] = field_evidence
                continue
            lead.field_evidence[field] = existing.model_copy(
                update={
                    'status': field_evidence.status,
                    'source_urls': list(dict.fromkeys([*existing.source_urls, *field_evidence.source_urls])),
                    'quotes': list(dict.fromkeys([*existing.quotes, *field_evidence.quotes])),
                }
            )
        task.progress[candidate_id].verification_state = 'completed'
        self._touch_progress(task, candidate_id)
        self._clear_company_error(task, candidate_id)
        task.checkpoint.current_stage = 'verifying'
        task.checkpoint.current_company_id = candidate_id
        task.status = transition_task_status(task.status, 'ready')
        self._persist(task)
        if task.auto_deliver:
            self.deliver(task.id, candidate_id=candidate_id)
        return task

    def deliver(self, task_id: str, *, candidate_id: str) -> DeliveryResult:
        task = self.get_task(task_id)
        lead = self._lead(task, candidate_id)
        policy = DeliveryPolicy(
            required_contacts=list(task.required_contacts),
            allow_map_only_verification=task.allow_map_only_verification,
        )
        decision = evaluate_delivery_gate(policy, lead)
        if decision.status == 'display_only':
            lead.delivery_status = 'display_only'
            task.progress[candidate_id].delivery_status = 'display_only'
            self._persist(task)
            return DeliveryResult(status='display_only', reasons=decision.reasons)

        payload = self.erp_adapter.build_payload(task, lead)
        fingerprint = self.erp_adapter.fingerprint(payload)
        ledger_entry = self._get_delivery(fingerprint)
        if fingerprint in task.checkpoint.delivery_fingerprints:
            self._persist(task)
            return DeliveryResult(
                status='duplicate',
                reasons=['duplicate_payload'],
                operation_id=(
                    task.checkpoint.delivery_operation_ids.get(fingerprint)
                    or (ledger_entry.operation_id if ledger_entry else None)
                ),
                payload=payload,
            )

        if ledger_entry is not None and ledger_entry.status == 'delivered':
            lead.delivery_status = 'duplicate'
            lead.delivery_fingerprint = fingerprint
            task.progress[candidate_id].delivery_status = 'duplicate'
            self._touch_progress(task, candidate_id)
            self._persist(task)
            return DeliveryResult(
                status='duplicate',
                reasons=['duplicate_payload'],
                operation_id=ledger_entry.operation_id,
                payload=payload,
            )

        if task.status != 'delivering':
            task.status = transition_task_status(task.status, 'delivering')
        result = self.erp_adapter.deliver(payload)
        self._record_delivery(
            task_id=task.id,
            lead_id=lead.id,
            fingerprint=fingerprint,
            payload=payload,
            result=result,
        )
        lead.delivery_status = result.status
        task.progress[candidate_id].delivery_status = result.status
        self._touch_progress(task, candidate_id)
        if result.status == 'delivered':
            self._clear_company_error(task, candidate_id)
            lead.delivery_fingerprint = fingerprint
            task.checkpoint.delivery_fingerprints.append(fingerprint)
            if result.operation_id:
                task.checkpoint.delivery_operation_ids[fingerprint] = result.operation_id
                task.checkpoint.operation_ids.append(result.operation_id)
            task.status = transition_task_status(task.status, 'completed')
        else:
            progress = task.progress[candidate_id]
            progress.last_error = result.error or result.status
            if candidate_id not in task.checkpoint.failed_company_ids:
                task.checkpoint.failed_company_ids.append(candidate_id)
            task.status = transition_task_status(task.status, 'completed_with_errors')
        self._persist(task)
        return result

    def retry_errors(self, task_id: str, *, candidate_id: str | None = None) -> SearchTask:
        task = self.get_task(task_id)
        candidate_ids = (
            [candidate_id]
            if candidate_id
            else list(dict.fromkeys(task.checkpoint.failed_company_ids))
        )
        if not candidate_ids:
            return self.discover(task.id) if not task.candidates else task

        for current_id in candidate_ids:
            progress = task.progress.get(current_id)
            if progress is None:
                continue
            if progress.enrichment_state != 'completed':
                self.enrich(task.id, candidate_id=current_id)
            if task.status in {'waiting_for_login', 'waiting_for_challenge'}:
                return task
            progress = task.progress[current_id]
            if progress.verification_state != 'completed' and any(
                lead.id == f'lead-{current_id}' for lead in task.leads
            ):
                self.verify(task.id, candidate_id=current_id)
            if task.status in {'waiting_for_login', 'waiting_for_challenge'}:
                return task
            progress = task.progress[current_id]
            if progress.verification_state == 'completed' and progress.delivery_status == 'failed':
                self.deliver(task.id, candidate_id=current_id)

        return task

    def pause(self, task_id: str) -> SearchTask:
        task = self.get_task(task_id)
        if task.status != 'paused':
            task.checkpoint.resume_stage = (
                task.checkpoint.resume_stage
                or (task.status if task.status != 'created' else 'discovering_map')
            )
            task.status = transition_task_status(task.status, 'paused')
        self._persist(task)
        return task

    def resume(self, task_id: str) -> SearchTask:
        task = self.get_task(task_id)
        target = task.checkpoint.resume_stage or 'discovering_map'
        task.status = transition_task_status(task.status, target)
        task.checkpoint.resume_stage = None
        self._persist(task)
        return task

    def deliver_lead(self, lead_id: str) -> DeliveryResult:
        for task in self._tasks.values():
            for lead in task.leads:
                if lead.id == lead_id:
                    return self.deliver(task.id, candidate_id=lead_id.removeprefix('lead-'))
        raise KeyError(f'lead not found: {lead_id}')

    def _candidate(self, task: SearchTask, candidate_id: str):
        for candidate in task.candidates:
            if candidate.candidate_id == candidate_id:
                return candidate
        raise KeyError(f'candidate not found: {candidate_id}')

    def _lead(self, task: SearchTask, candidate_id: str) -> LeadRecord:
        lead_id = f'lead-{candidate_id}'
        for lead in task.leads:
            if lead.id == lead_id:
                return lead
        raise KeyError(f'lead not found: {lead_id}')

    @staticmethod
    def _record_company_error(task: SearchTask, candidate_id: str, error: str) -> None:
        now = _utc_now()
        progress = task.progress[candidate_id]
        progress.last_error = error
        progress.retry_count += 1
        progress.retry_after = now
        progress.last_updated_at = now
        if candidate_id not in task.checkpoint.failed_company_ids:
            task.checkpoint.failed_company_ids.append(candidate_id)
        task.checkpoint.retry_after = now
        task.errors.append(error)
        task.status = 'completed_with_errors'

    @staticmethod
    def _clear_company_error(task: SearchTask, candidate_id: str) -> None:
        progress = task.progress[candidate_id]
        progress.last_error = None
        progress.retry_after = None
        task.checkpoint.failed_company_ids = [
            failed_id
            for failed_id in task.checkpoint.failed_company_ids
            if failed_id != candidate_id
        ]
        if not task.checkpoint.failed_company_ids:
            task.checkpoint.retry_after = None

    def _pause_for_provider(self, task: SearchTask, error: ProviderPaused) -> SearchTask:
        task.checkpoint.resume_stage = task.status
        task.checkpoint.browser_state = error.browser_state
        task.errors.append(str(error))
        task.status = transition_task_status(task.status, error.task_status)
        self._persist(task)
        return task

    def _set_current_company(self, task: SearchTask, candidate_id: str, *, stage: str) -> None:
        task.checkpoint.current_stage = stage
        task.checkpoint.current_company_id = candidate_id
        task.checkpoint.current_company_index = next(
            (index for index, candidate in enumerate(task.candidates) if candidate.candidate_id == candidate_id),
            0,
        )

    @staticmethod
    def _touch_progress(task: SearchTask, candidate_id: str) -> None:
        task.progress[candidate_id].last_updated_at = _utc_now()

    def _get_delivery(self, fingerprint: str) -> DeliveryLedgerEntry | None:
        getter = getattr(self.repository, 'get_delivery', None) if self.repository else None
        return getter(fingerprint) if callable(getter) else None

    def _record_delivery(
        self,
        *,
        task_id: str,
        lead_id: str,
        fingerprint: str,
        payload: dict[str, object],
        result: DeliveryResult,
    ) -> None:
        recorder = getattr(self.repository, 'record_delivery', None) if self.repository else None
        if callable(recorder):
            recorder(
                task_id=task_id,
                lead_id=lead_id,
                fingerprint=fingerprint,
                payload=payload,
                result=result,
            )

    def _verify_public_contact(self, candidate, lead):
        if self.public_evidence_verifier is None or not (lead.mobile or lead.email):
            return None
        urls = [
            url
            for url in [*lead.contact_evidence_urls, *lead.source_urls]
            if url and url != candidate.source_url and 'amap.com' not in url
        ]
        if not urls:
            return None
        return self.public_evidence_verifier.verify_contact(
            company_name=lead.company_name,
            mobile=lead.mobile,
            email=lead.email,
            source_urls=list(dict.fromkeys(urls)),
        )

    def _persist(self, task: SearchTask) -> None:
        if self.repository:
            self.repository.save(task)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _provider_browser_state(provider: object) -> str:
    state = getattr(provider, 'last_state', None)
    if state is None:
        browser = getattr(provider, 'browser', None)
        state = getattr(browser, 'state', None)
    value = getattr(state, 'value', state)
    return value if isinstance(value, str) and value else 'ready'
