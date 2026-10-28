import hashlib
import json
import re

from backend.app.collection.intent import ParsedCollectionIntent, parse_collection_intent
from backend.app.collection.models import CollectionTask
from backend.app.collection.service import CollectionService
from backend.app.connector.contracts import (
    ConnectorCreateTaskRequest,
    ConnectorHealth,
    ConnectorResultItem,
    ConnectorSearchRequest,
    ConnectorSearchResponse,
    ConnectorTaskResults,
    ConnectorTaskSummary,
)
from backend.app.domain.models import LeadRecord

_SOFT_FURNISHING_QUERY_EXPANSIONS = (
    '软装设计公司',
    '住宅软装',
    '室内软装',
    '私宅软装',
    '豪宅软装公司',
    '全案设计公司',
    '室内设计公司',
)

_SOFT_FURNISHING_CACHE_TERMS = (
    '软装',
    '室内设计',
    '室内软装',
    '装饰',
    '家居',
    '全案设计',
)


class ConnectorFacade:
    def __init__(self, service: CollectionService | None) -> None:
        self._service = service

    def health(self) -> ConnectorHealth:
        return ConnectorHealth(
            status='ready' if self._service is not None else 'degraded',
            capabilities=[
                'lead_search',
                'lead_task_read',
                'lead_task_control',
                'lead_result_read',
            ],
        )

    def list_tasks(self, *, account_scope: str | None = None) -> list[ConnectorTaskSummary]:
        assert self._service is not None
        return [
            self._summary(task)
            for task in self._service.list_tasks(account_scope=account_scope)
        ]

    def get_task(self, task_id: str, *, account_scope: str | None = None) -> ConnectorTaskSummary:
        assert self._service is not None
        return self._summary(self._service.get_task(task_id, account_scope=account_scope))

    def create_task(
        self,
        payload: ConnectorCreateTaskRequest,
        *,
        account_scope: str | None = None,
    ) -> ConnectorTaskSummary:
        assert self._service is not None
        task = self._service.create_from_text(
            payload.request_text,
            configured_models=set(payload.models) if payload.models else None,
            verified_auto_deliver=False,
            account_scope=account_scope,
        )
        if (
            task.intent.target_valid_contacts
            and len(task.intent.keywords) == 1
            and '软装' in task.intent.keywords[0]
        ):
            self._service.extend_keywords(task.id, list(_SOFT_FURNISHING_QUERY_EXPANSIONS))
        return self._summary(self._service.resume_async(task.id))

    def get_results(
        self,
        task_id: str,
        *,
        account_scope: str | None = None,
    ) -> ConnectorTaskResults:
        assert self._service is not None
        task = self._service.get_task(task_id, account_scope=account_scope)
        items = self._result_items(task)
        return ConnectorTaskResults(task_id=task.id, status=task.status, items=items)

    def search(
        self,
        payload: ConnectorSearchRequest,
        *,
        account_scope: str | None = None,
    ) -> ConnectorSearchResponse:
        assert self._service is not None
        request_intent = parse_collection_intent(
            payload.request_text,
            configured_models=self._service.configured_models,
        )
        limit = max(request_intent.target_valid_contacts or 1, 1)
        seen: set[str] = set()
        items: list[ConnectorResultItem] = []
        for task in self._service.list_tasks():
            if task.status not in {'completed', 'completed_with_errors'}:
                continue
            if not _task_matches_cached_search(
                task,
                request_intent,
                payload.request_text,
            ):
                continue
            for item in self._result_items(
                task,
                request_intent=request_intent,
                request_text=payload.request_text,
            ):
                if len(items) >= limit:
                    break
                if not _item_matches_requested_city(item, request_intent):
                    continue
                fingerprint = _result_fingerprint(item)
                if fingerprint in seen:
                    continue
                if not self._claim_result(fingerprint, task.id):
                    continue
                seen.add(fingerprint)
                items.append(item)
            if len(items) >= limit:
                break
        if items:
            return ConnectorSearchResponse(
                mode='cached',
                status='completed',
                items=items,
            )

        task = self._service.create_from_text(
            payload.request_text,
            configured_models=set(payload.models) if payload.models else None,
            verified_auto_deliver=False,
            account_scope=account_scope,
        )
        if (
            task.intent.target_valid_contacts
            and len(task.intent.keywords) == 1
            and '软装' in task.intent.keywords[0]
        ):
            self._service.extend_keywords(task.id, list(_SOFT_FURNISHING_QUERY_EXPANSIONS))
        task = self._service.resume_async(task.id)
        return ConnectorSearchResponse(
            mode='task',
            task_id=task.id,
            status=task.status,
        )

    def control_task(
        self,
        task_id: str,
        action: str,
        *,
        account_scope: str | None = None,
    ) -> ConnectorTaskSummary:
        assert self._service is not None
        task = self._service.get_task(task_id, account_scope=account_scope)
        if action == 'pause':
            task = self._service.pause(task.id)
        elif action == 'resume':
            task = self._service.resume_async(task.id)
        elif action == 'cancel':
            task = self._service.cancel(task.id)
        else:
            raise ValueError(f'unsupported connector task action: {action}')
        return self._summary(task)

    @staticmethod
    def _summary(task: CollectionTask) -> ConnectorTaskSummary:
        return ConnectorTaskSummary(
            task_id=task.id,
            status=task.status,
            total_work_units=task.summary.total_work_units,
            completed_work_units=task.summary.completed_work_units,
            verified_lead_count=task.summary.verified_count,
            delivery_enabled=task.auto_deliver or task.verified_auto_deliver,
        )

    def _claim_result(self, fingerprint: str, source_task_id: str) -> bool:
        repository = self._service.repository if self._service is not None else None
        if repository is not None and hasattr(repository, 'claim_result_consumption'):
            return repository.claim_result_consumption(
                result_fingerprint=fingerprint,
                source_task_id=source_task_id,
            )
        consumed = getattr(self._service, '_connector_globally_consumed_results', None)
        if consumed is None:
            consumed = set()
            self._service._connector_globally_consumed_results = consumed
        if fingerprint in consumed:
            return False
        consumed.add(fingerprint)
        return True

    @staticmethod
    def _result_items(
        task: CollectionTask,
        *,
        request_intent: ParsedCollectionIntent | None = None,
        request_text: str = '',
    ) -> list[ConnectorResultItem]:
        items: list[ConnectorResultItem] = []
        for lead in task.results:
            if not _is_completed_amap_contact(lead):
                continue
            if request_intent and not _lead_matches_requested_industry(
                lead,
                request_intent,
                request_text,
            ):
                continue
            contact = lead.telephone or lead.mobile or lead.email
            if not contact:
                continue
            evidence_urls = lead.source_urls or lead.contact_evidence_urls
            items.append(ConnectorResultItem(
                company_name=lead.company_name,
                city=lead.city,
                address=lead.address,
                contact=contact,
                evidence_url=evidence_urls[0] if evidence_urls else lead.source_url,
                verification_status='amap_collected',
            ))
        return items


def _task_matches_cached_search(
    task: CollectionTask,
    request_intent: ParsedCollectionIntent,
    request_text: str,
) -> bool:
    if request_intent.cities and not any(
        _city_matches_requested(lead.city, request_intent)
        for lead in task.results
    ):
        return False
    return bool(
        _cache_industry_terms([*task.intent.keywords, task.request_text])
        & _cache_industry_terms([*request_intent.keywords, request_text])
    )


def _item_matches_requested_city(
    item: ConnectorResultItem,
    request_intent: ParsedCollectionIntent,
) -> bool:
    return not request_intent.cities or _city_matches_requested(item.city, request_intent)


def _lead_matches_requested_industry(
    lead: LeadRecord,
    request_intent: ParsedCollectionIntent,
    request_text: str,
) -> bool:
    matched_keywords = lead.source_metadata.get('matched_keywords')
    if not isinstance(matched_keywords, list):
        return True
    lead_terms = _cache_industry_terms([
        value for value in matched_keywords if isinstance(value, str)
    ])
    if not lead_terms:
        return True
    request_terms = _cache_industry_terms([
        *request_intent.keywords,
        request_text,
    ])
    return bool(lead_terms & request_terms)


def _city_matches_requested(city: str, request_intent: ParsedCollectionIntent) -> bool:
    normalized_city = city.removesuffix('市')
    return normalized_city in {
        requested_city.removesuffix('市')
        for requested_city in request_intent.cities
    }


def _cache_industry_terms(keywords: list[str]) -> set[str]:
    terms: set[str] = set()
    for keyword in keywords:
        normalized = re.sub(r'\s+', '', keyword).casefold()
        if not normalized:
            continue
        if any(term in normalized for term in _SOFT_FURNISHING_CACHE_TERMS):
            terms.add('soft_furnishing')
        else:
            terms.add(normalized)
    return terms


def _is_completed_amap_contact(lead: LeadRecord) -> bool:
    if lead.contact_verification_status in {
        'verified',
        'verified_map',
        'verified_public_web',
        'verified_cross_source',
    }:
        return bool(lead.company_name.strip() and (lead.telephone or lead.mobile or lead.email))
    return bool(
        lead.company_name.strip()
        and (lead.telephone or lead.mobile or lead.email)
        and (lead.source_urls or lead.source_url)
        and lead.source_metadata.get('provider') in {'amap_web', 'amap_api'}
        and lead.source_metadata.get('detail_verified') is True
    )


def _result_fingerprint(item: ConnectorResultItem) -> str:
    payload = {
        'city': item.city,
        'company_name': item.company_name,
        'contact': item.contact,
        'evidence_url': item.evidence_url,
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode('utf-8')
    ).hexdigest()
