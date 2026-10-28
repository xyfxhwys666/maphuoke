from datetime import datetime
from typing import Literal

from backend.app.domain.models import LeadRecord, MapPoiCandidate
from pydantic import BaseModel, Field

TaskStatus = Literal[
    'created',
    'discovering_map',
    'candidates_ready',
    'enriching_doubao',
    'verifying',
    'ready',
    'delivering',
    'completed',
    'paused',
    'waiting_for_login',
    'waiting_for_challenge',
    'completed_with_errors',
]


_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    'created': {'discovering_map', 'paused'},
    'discovering_map': {'candidates_ready', 'completed_with_errors', 'paused', 'waiting_for_login', 'waiting_for_challenge'},
    'candidates_ready': {'enriching_doubao', 'paused', 'completed_with_errors'},
    'enriching_doubao': {'verifying', 'completed_with_errors', 'paused', 'waiting_for_login', 'waiting_for_challenge'},
    'verifying': {'ready', 'completed_with_errors', 'paused'},
    'ready': {'delivering', 'completed', 'paused', 'completed_with_errors'},
    'delivering': {'completed', 'completed_with_errors', 'paused'},
    'completed': set(),
    'paused': {'discovering_map', 'enriching_doubao', 'verifying', 'ready', 'delivering', 'completed_with_errors'},
    'waiting_for_login': {'discovering_map', 'enriching_doubao', 'paused', 'completed_with_errors'},
    'waiting_for_challenge': {'discovering_map', 'enriching_doubao', 'paused', 'completed_with_errors'},
    'completed_with_errors': {'discovering_map', 'enriching_doubao', 'verifying', 'delivering', 'completed'},
}


def transition_task_status(current: str, target: str) -> str:
    if target not in _ALLOWED_TRANSITIONS.get(current, set()):
        raise ValueError(f'invalid task transition: {current} -> {target}')
    return target


class CompanyProgress(BaseModel):
    candidate_id: str
    discovery_state: str = 'completed'
    enrichment_state: str = 'pending'
    verification_state: str = 'pending'
    delivery_status: str = 'display_only'
    retry_count: int = 0
    retry_after: datetime | None = None
    last_error: str | None = None
    last_updated_at: datetime | None = None


class TaskCheckpoint(BaseModel):
    current_stage: str = 'created'
    current_company_index: int = 0
    current_company_id: str | None = None
    completed_company_ids: list[str] = Field(default_factory=list)
    browser_state: str = 'stopped'
    last_successful_query_at: datetime | None = None
    failed_company_ids: list[str] = Field(default_factory=list)
    retry_after: datetime | None = None
    delivery_fingerprints: list[str] = Field(default_factory=list)
    delivery_operation_ids: dict[str, str] = Field(default_factory=dict)
    operation_ids: list[str] = Field(default_factory=list)
    resume_stage: str | None = None


class SearchTask(BaseModel):
    id: str
    company_name: str
    city: str
    discovery_provider: str = 'amap_web'
    enrichment_provider: str = 'doubao_web'
    required_contacts: list[str] = Field(default_factory=lambda: ['mobile', 'email', 'wechat'])
    auto_deliver: bool = False
    allow_map_only_verification: bool = False
    status: TaskStatus = 'created'
    candidates: list[MapPoiCandidate] = Field(default_factory=list)
    leads: list[LeadRecord] = Field(default_factory=list)
    progress: dict[str, CompanyProgress] = Field(default_factory=dict)
    checkpoint: TaskCheckpoint = Field(default_factory=TaskCheckpoint)
    errors: list[str] = Field(default_factory=list)
