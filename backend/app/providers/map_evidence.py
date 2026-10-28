from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from backend.app.domain.models import EvidenceResult, EvidenceValue, MapPoiCandidate
from backend.app.domain.normalization import normalize_company_name, normalize_email, normalize_mobile


@dataclass(frozen=True, slots=True)
class MapEvidenceSnapshot:
    snapshot_id: str
    provider: str
    poi_id: str | None
    source_url: str | None
    captured_at: datetime
    visible_text: str
    metadata: dict[str, Any]


def capture_map_snapshot(candidate: MapPoiCandidate) -> MapEvidenceSnapshot:
    visible_text = candidate.raw_text or ''
    source_url = candidate.source_url
    identity = '|'.join((candidate.discovery_channel, candidate.poi_id or '', source_url or '', visible_text))
    snapshot_id = f'map-snapshot-{hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]}'
    return MapEvidenceSnapshot(
        snapshot_id=snapshot_id,
        provider=candidate.discovery_channel,
        poi_id=candidate.poi_id,
        source_url=source_url,
        captured_at=candidate.captured_at,
        visible_text=visible_text,
        metadata=dict(candidate.source_metadata),
    )


def attach_map_snapshot(candidate: MapPoiCandidate) -> MapPoiCandidate:
    snapshot = capture_map_snapshot(candidate)
    metadata = {
        **candidate.source_metadata,
        'evidence_snapshot_id': snapshot.snapshot_id,
    }
    return candidate.model_copy(
        update={
            'evidence_snapshot_id': snapshot.snapshot_id,
            'source_metadata': metadata,
        }
    )


class MapEvidenceVerifier:
    def verify(
        self,
        candidate: MapPoiCandidate,
        *,
        expected_company_name: str,
        expected_contact: str | None,
    ) -> EvidenceResult:
        visible_text = candidate.raw_text or ''
        compact_text = ''.join(visible_text.split()).casefold()
        expected_name = ''.join((normalize_company_name(expected_company_name) or '').split()).casefold()
        company_match = bool(expected_name and expected_name in compact_text)
        source_urls = list(dict.fromkeys([candidate.source_url, *candidate.source_urls]))
        source_urls = [value for value in source_urls if value]
        quotes = [line.strip() for line in visible_text.splitlines() if line.strip()]
        if not company_match:
            return EvidenceResult(
                company_name_verification_status='rejected',
                contact_verification_status='rejected_mismatch',
                source_urls=source_urls,
                quotes=quotes[:3],
                grade='F',
                score=0,
            )

        contact_match = self._contact_in_text(visible_text, expected_contact)
        field_evidence = {}
        if contact_match and expected_contact:
            field = 'mobile' if normalize_mobile(expected_contact) else 'email' if normalize_email(expected_contact) else None
            if field:
                field_evidence[field] = EvidenceValue(
                    value=expected_contact,
                    status='verified',
                    source_urls=source_urls,
                    quotes=quotes[:3],
                )
        return EvidenceResult(
            company_name_verification_status='verified_map',
            contact_verification_status='verified_map' if contact_match else 'captured',
            source_urls=source_urls,
            quotes=quotes[:3],
            field_evidence=field_evidence,
            grade='B' if contact_match else 'C',
            score=75 if contact_match else 55,
        )

    @staticmethod
    def _contact_in_text(text: str, expected_contact: str | None) -> bool:
        if not expected_contact:
            return False
        normalized_mobile = normalize_mobile(expected_contact)
        if normalized_mobile:
            return normalized_mobile in ''.join(char for char in text if char.isdigit())
        normalized_email = normalize_email(expected_contact)
        if normalized_email:
            return normalized_email in text.casefold()
        expected_digits = ''.join(char for char in str(expected_contact) if char.isdigit())
        return bool(expected_digits) and expected_digits in ''.join(char for char in text if char.isdigit())
