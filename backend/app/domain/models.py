from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

EvidenceStatus = Literal['captured', 'source_backed', 'verified']
DeliveryDecisionStatus = Literal['ready', 'display_only']


class EvidenceValue(BaseModel):
    value: str | None = None
    status: EvidenceStatus = 'captured'
    source_urls: list[str] = Field(default_factory=list)
    quotes: list[str] = Field(default_factory=list)


class EvidenceResult(BaseModel):
    company_name_verification_status: str | None = None
    contact_verification_status: str = 'captured'
    source_urls: list[str] = Field(default_factory=list)
    quotes: list[str] = Field(default_factory=list)
    field_evidence: dict[str, EvidenceValue] = Field(default_factory=dict)
    grade: str | None = None
    score: int | None = None


class DeliveryResult(BaseModel):
    status: Literal['delivered', 'display_only', 'failed', 'duplicate']
    reasons: list[str] = Field(default_factory=list)
    operation_id: str | None = None
    error: str | None = None
    payload: dict[str, Any] | None = None


class DeliveryLedgerEntry(BaseModel):
    fingerprint: str
    task_id: str
    lead_id: str
    status: Literal['delivered', 'failed']
    operation_id: str | None = None
    error: str | None = None
    attempts: int = 0


class MapPoiCandidate(BaseModel):
    candidate_id: str
    company_name: str
    city: str
    address: str | None = None
    telephone: str | None = None
    mobile: str | None = None
    category: str | None = None
    longitude: float | None = None
    latitude: float | None = None
    poi_id: str | None = None
    source_url: str | None = None
    source_urls: list[str] = Field(default_factory=list)
    discovery_channel: str = 'amap_web'
    raw_text: str | None = None
    source_metadata: dict[str, Any] = Field(default_factory=dict)
    captured_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    evidence_snapshot_id: str | None = None


class DoubaoEnrichment(BaseModel):
    company_name: str | None = None
    mobile: str | None = None
    telephone: str | None = None
    contact_person_name: str | None = None
    contact_person_role: str | None = None
    email: str | None = None
    wechat: str | None = None
    address: str | None = None
    service_intro: str | None = None
    source_urls: list[str] = Field(default_factory=list)
    evidence_quotes: list[str] = Field(default_factory=list)
    contact_evidence_grade: str | None = None
    contact_evidence_score: int | None = None


class LeadRecord(BaseModel):
    id: str
    task_id: str
    city: str
    company_name: str
    mobile: str | None = None
    telephone: str | None = None
    contact_person_name: str | None = None
    contact_person_role: str | None = None
    email: str | None = None
    wechat: str | None = None
    address: str | None = None
    service_intro: str | None = None
    discovery_channel: str = 'amap_web'
    enrichment_model: str | None = None
    source_url: str | None = None
    source_urls: list[str] = Field(default_factory=list)
    evidence_quotes: list[str] = Field(default_factory=list)
    source_metadata: dict[str, Any] = Field(default_factory=dict)
    field_evidence: dict[str, EvidenceValue] = Field(default_factory=dict)
    company_name_verification_status: str = 'pending'
    contact_verification_status: str = 'pending'
    contact_evidence_urls: list[str] = Field(default_factory=list)
    contact_evidence_quotes: list[str] = Field(default_factory=list)
    contact_evidence_grade: str | None = None
    contact_evidence_score: int | None = None
    enrichment_state: str = 'pending'
    delivery_status: str = 'display_only'
    delivery_fingerprint: str | None = None
    delivery_at: datetime | None = None


class DeliveryPolicy(BaseModel):
    required_contacts: list[str] = Field(default_factory=lambda: ['mobile', 'email'])
    require_all_contacts: bool = False
    allow_map_only_verification: bool = False


class DeliveryDecision(BaseModel):
    status: DeliveryDecisionStatus
    reasons: list[str] = Field(default_factory=list)
