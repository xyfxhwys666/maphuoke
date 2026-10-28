from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from backend.app.collection.models import CollectionTask
from backend.app.domain.models import EvidenceResult, LeadRecord

_VERIFIED_CONTACT_STATUSES = {
    'verified',
    'verified_map',
    'verified_public_web',
    'verified_cross_source',
}


class _PublicEvidenceVerifier(Protocol):
    def verify_contact(
        self,
        *,
        company_name: str,
        mobile: str | None = None,
        email: str | None = None,
        source_urls: list[str] | None = None,
    ) -> EvidenceResult: ...


class _CollectionService(Protocol):
    public_evidence_verifier: _PublicEvidenceVerifier | None

    def _persist(self, task: CollectionTask) -> None: ...


@dataclass(frozen=True)
class PublicEvidenceBackfillSummary:
    checked_count: int
    verified_count: int
    error_count: int


def refresh_task_public_evidence(
    service: _CollectionService,
    task: CollectionTask,
    *,
    max_leads: int | None = None,
) -> PublicEvidenceBackfillSummary:
    """Re-verify stored contacts without collecting, delivering, or creating work."""
    verifier = service.public_evidence_verifier
    if verifier is None:
        return PublicEvidenceBackfillSummary(0, 0, 0)

    checked_count = 0
    verified_count = 0
    error_count = 0
    for lead in task.results:
        if max_leads is not None and checked_count >= max(max_leads, 0):
            break
        if not _needs_public_evidence(lead):
            continue
        checked_count += 1
        try:
            evidence = verifier.verify_contact(
                company_name=lead.company_name,
                mobile=lead.mobile,
                email=lead.email,
                source_urls=list(lead.source_urls),
            )
        except Exception as exc:  # noqa: BLE001 - evidence sources are best-effort
            task.errors.append(f'公开证据回填失败：{lead.company_name}：{exc}')
            error_count += 1
            continue
        _apply_evidence(lead, evidence)
        if lead.contact_verification_status in _VERIFIED_CONTACT_STATUSES:
            verified_count += 1

    if checked_count or error_count:
        service._persist(task)
    return PublicEvidenceBackfillSummary(checked_count, verified_count, error_count)


def _needs_public_evidence(lead: LeadRecord) -> bool:
    return bool(
        (lead.mobile or lead.email)
        and lead.contact_verification_status not in _VERIFIED_CONTACT_STATUSES
    )


def _apply_evidence(lead: LeadRecord, evidence: EvidenceResult) -> None:
    if evidence.company_name_verification_status:
        lead.company_name_verification_status = evidence.company_name_verification_status
    lead.contact_verification_status = evidence.contact_verification_status
    lead.contact_evidence_urls = list(dict.fromkeys(evidence.source_urls))
    lead.contact_evidence_quotes = list(dict.fromkeys(evidence.quotes))
    lead.contact_evidence_grade = evidence.grade
    lead.contact_evidence_score = evidence.score
    lead.field_evidence = dict(evidence.field_evidence)
