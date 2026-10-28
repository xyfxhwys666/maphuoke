from __future__ import annotations

from typing import Any

from backend.app.domain.models import DoubaoEnrichment, MapPoiCandidate
from backend.app.providers.protocols import DoubaoEnrichmentGateway


class DoubaoEnrichmentService:
    def __init__(self, gateway: DoubaoEnrichmentGateway) -> None:
        self.gateway = gateway

    def enrich(self, candidate: MapPoiCandidate, *, requested_contacts: list[str]) -> DoubaoEnrichment:
        known_fields: dict[str, Any] = {
            'address': candidate.address,
            'telephone': candidate.telephone,
            'source_url': candidate.source_url,
            'category': candidate.category,
            'poi_id': candidate.poi_id,
        }
        return self.gateway.enrich_company(
            company_name=candidate.company_name,
            city=candidate.city,
            requested_contacts=requested_contacts,
            known_fields=known_fields,
        )
