from datetime import UTC, datetime
from typing import Literal

from backend.app.collection.intent import ParsedCollectionIntent
from backend.app.domain.models import LeadRecord, MapPoiCandidate
from pydantic import BaseModel, Field

CollectionTaskStatus = Literal[
    'planned',
    'queued',
    'running',
    'paused',
    'needs_attention',
    'completed',
    'completed_with_errors',
    'cancelled',
]
WorkUnitStatus = Literal[
    'planned',
    'queued',
    'running',
    'succeeded',
    'no_result',
    'skipped_limit',
    'retry_wait',
    'needs_attention',
    'failed',
    'paused',
    'cancelled',
]
RelevanceStatus = Literal['relevant', 'not_relevant', 'review']
CollectionCompletionReason = Literal[
    'target_reached',
    'source_exhausted',
    'completed_with_errors',
]


def utc_now() -> datetime:
    return datetime.now(UTC)


class CompanyNameCandidate(BaseModel):
    """A real company name found in public web results before map lookup."""

    company_name: str
    city: str
    matched_keyword: str
    source_urls: list[str] = Field(default_factory=list)
    evidence_quotes: list[str] = Field(default_factory=list)
    discovery_channel: Literal['public_web', 'amap_keyword'] = 'public_web'
    discovered_at: datetime = Field(default_factory=utc_now)


class RelevanceDecision(BaseModel):
    candidate_id: str
    model_id: str
    keyword: str | None = None
    status: RelevanceStatus
    reason: str
    confidence: float | None = None
    created_at: datetime = Field(default_factory=utc_now)


class CollectionWorkUnit(BaseModel):
    id: str
    city: str
    keyword: str
    provider_id: str = 'amap_web'
    models: list[str] = Field(default_factory=list)
    required_contacts: list[str] = Field(default_factory=list)
    contact_match: Literal['any', 'all'] = 'any'
    limit_per_city: int | None = None
    status: WorkUnitStatus = 'planned'
    candidate_count: int = 0
    company_name_candidate_count: int = 0
    map_match_count: int = 0
    relevant_count: int = 0
    contact_count: int = 0
    retry_count: int = 0
    retry_after: datetime | None = None
    last_error: str | None = None
    updated_at: datetime = Field(default_factory=utc_now)


class CollectionCheckpoint(BaseModel):
    current_stage: str = 'planned'
    current_work_unit_id: str | None = None
    completed_work_unit_ids: list[str] = Field(default_factory=list)
    failed_work_unit_ids: list[str] = Field(default_factory=list)
    browser_state: str = 'stopped'
    retry_after: datetime | None = None
    contact_refresh_active: bool = False
    contact_refresh_index: int = 0
    contact_refresh_total: int = 0


class CollectionSummary(BaseModel):
    total_work_units: int = 0
    completed_work_units: int = 0
    candidate_count: int = 0
    relevant_count: int = 0
    review_count: int = 0
    contact_count: int = 0
    verified_count: int = 0
    erp_success_count: int = 0
    erp_failure_count: int = 0
    target_valid_contacts: int | None = None
    valid_contact_count: int = 0
    no_phone_count: int = 0
    rejected_count: int = 0
    source_exhausted: bool = False


class CollectionTask(BaseModel):
    id: str
    name: str
    request_text: str
    # Populated by the trusted desktop connector boundary.  Direct/internal
    # callers may leave it empty for backwards compatibility.
    account_scope: str | None = None
    intent: ParsedCollectionIntent
    created_at: datetime = Field(default_factory=utc_now)
    status: CollectionTaskStatus = 'planned'
    continuous_mode: bool = True
    auto_deliver: bool = False
    verified_auto_deliver: bool = False
    work_units: list[CollectionWorkUnit] = Field(default_factory=list)
    company_name_candidates: list[CompanyNameCandidate] = Field(default_factory=list)
    candidates: list[MapPoiCandidate] = Field(default_factory=list)
    results: list[LeadRecord] = Field(default_factory=list)
    relevance_decisions: dict[str, list[RelevanceDecision]] = Field(default_factory=dict)
    summary: CollectionSummary = Field(default_factory=CollectionSummary)
    checkpoint: CollectionCheckpoint = Field(default_factory=CollectionCheckpoint)
    errors: list[str] = Field(default_factory=list)
    completion_reason: CollectionCompletionReason | None = None
