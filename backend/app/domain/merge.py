from collections.abc import Iterable

from backend.app.domain.models import (
    DoubaoEnrichment,
    EvidenceValue,
    LeadRecord,
    MapPoiCandidate,
)
from backend.app.domain.normalization import (
    normalize_email,
    normalize_mobile,
    normalize_telephone,
    normalize_wechat,
)


def _first_text(*values: str | None) -> str | None:
    for value in values:
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _unique(values: Iterable[str | None]) -> list[str]:
    result: list[str] = []
    for value in values:
        normalized = str(value or '').strip()
        if normalized and normalized not in result:
            result.append(normalized)
    return result


def merge_map_candidate(current: MapPoiCandidate, incoming: MapPoiCandidate) -> MapPoiCandidate:
    """Merge another discovery hit into the canonical company candidate."""
    for field in (
        'address',
        'telephone',
        'mobile',
        'category',
        'longitude',
        'latitude',
        'poi_id',
        'raw_text',
        'evidence_snapshot_id',
    ):
        if getattr(current, field) in (None, '') and getattr(incoming, field) not in (None, ''):
            setattr(current, field, getattr(incoming, field))

    current.source_urls = _unique([
        current.source_url,
        *current.source_urls,
        incoming.source_url,
        *incoming.source_urls,
    ])
    if current.source_url is None and current.source_urls:
        current.source_url = current.source_urls[0]
    for key, value in incoming.source_metadata.items():
        existing = current.source_metadata.get(key)
        if isinstance(existing, list) or isinstance(value, list):
            current.source_metadata[key] = _unique([
                *(existing if isinstance(existing, list) else [existing]),
                *(value if isinstance(value, list) else [value]),
            ])
        elif existing in (None, ''):
            current.source_metadata[key] = value
    return current


def merge_candidate_with_enrichment(
    candidate: MapPoiCandidate,
    enrichment: DoubaoEnrichment,
    *,
    task_id: str,
) -> LeadRecord:
    source_urls = _unique([
        candidate.source_url,
        *candidate.source_urls,
        *enrichment.source_urls,
    ])
    contact_evidence_urls = _unique(enrichment.source_urls)
    contact_evidence_quotes = _unique(enrichment.evidence_quotes)
    contact_status = 'source_backed' if contact_evidence_urls or contact_evidence_quotes else 'captured'
    candidate_address = _first_text(candidate.address)
    candidate_telephone = normalize_telephone(candidate.telephone)
    enrichment_address = _first_text(enrichment.address)
    enrichment_telephone = normalize_telephone(enrichment.telephone)
    address = candidate_address or enrichment_address
    mobile = (
        normalize_mobile(enrichment.mobile)
        or normalize_mobile(candidate.mobile)
        or normalize_mobile(candidate.telephone)
        or normalize_mobile(enrichment.telephone)
    )
    telephone = None if mobile else candidate_telephone or enrichment_telephone
    email = normalize_email(enrichment.email)
    wechat = normalize_wechat(enrichment.wechat)
    service_intro = _first_text(enrichment.service_intro, candidate.category)

    field_evidence = {
        'address': EvidenceValue(
            value=address,
            status='source_backed' if candidate_address and candidate.source_url else 'captured',
            source_urls=_unique([candidate.source_url]),
        ),
        'telephone': EvidenceValue(
            value=telephone,
            status='source_backed' if candidate_telephone and candidate.source_url else 'captured',
            source_urls=_unique([candidate.source_url]),
        ),
        'mobile': EvidenceValue(
            value=mobile,
            status=contact_status,
            source_urls=contact_evidence_urls,
            quotes=contact_evidence_quotes,
        ),
    }
    for field, value in {
        'email': email,
        'wechat': wechat,
        'contact_person_name': _first_text(enrichment.contact_person_name),
        'contact_person_role': _first_text(enrichment.contact_person_role),
    }.items():
        if value:
            field_evidence[field] = EvidenceValue(
                value=value,
                status=contact_status,
                source_urls=contact_evidence_urls,
                quotes=contact_evidence_quotes,
            )

    return LeadRecord(
        id=f'lead-{candidate.candidate_id}',
        task_id=task_id,
        city=candidate.city,
        company_name=candidate.company_name,
        mobile=mobile,
        telephone=telephone,
        contact_person_name=_first_text(enrichment.contact_person_name),
        contact_person_role=_first_text(enrichment.contact_person_role),
        email=email,
        wechat=wechat,
        address=address,
        service_intro=service_intro,
        discovery_channel=candidate.discovery_channel,
        enrichment_model='doubao_web' if enrichment != DoubaoEnrichment() else None,
        source_url=source_urls[0] if source_urls else None,
        source_urls=source_urls,
        evidence_quotes=contact_evidence_quotes,
        source_metadata=dict(candidate.source_metadata),
        field_evidence=field_evidence,
        company_name_verification_status='verified_map' if candidate.source_url else 'pending',
        contact_verification_status=contact_status,
        contact_evidence_urls=contact_evidence_urls,
        contact_evidence_quotes=contact_evidence_quotes,
        contact_evidence_grade=enrichment.contact_evidence_grade,
        contact_evidence_score=enrichment.contact_evidence_score,
        enrichment_state='completed',
    )
