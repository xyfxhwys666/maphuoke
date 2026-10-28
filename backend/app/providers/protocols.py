from typing import Any, Protocol

from backend.app.collection.contracts import KeywordDiscoveryProvider, RelevanceJudge
from backend.app.domain.models import (
    DeliveryResult,
    DoubaoEnrichment,
    EvidenceResult,
    LeadRecord,
    MapPoiCandidate,
)

__all__ = [
    'DoubaoEnrichmentGateway',
    'ErpAdapter',
    'KeywordDiscoveryProvider',
    'MapDiscoveryProvider',
    'MapEvidenceVerifier',
    'ProviderPaused',
    'PublicEvidenceProvider',
    'RelevanceJudge',
]


class ProviderPaused(RuntimeError):
    def __init__(self, message: str, *, task_status: str, browser_state: str) -> None:
        super().__init__(message)
        self.task_status = task_status
        self.browser_state = browser_state


class MapDiscoveryProvider(Protocol):
    id: str
    label: str
    configured: bool

    def search_company(
        self,
        *,
        company_name: str,
        city: str,
        max_results: int = 5,
    ) -> list[MapPoiCandidate]: ...


class DoubaoEnrichmentGateway(Protocol):
    id: str

    def enrich_company(
        self,
        *,
        company_name: str,
        city: str,
        requested_contacts: list[str],
        known_fields: dict[str, Any],
    ) -> DoubaoEnrichment: ...


class MapEvidenceVerifier(Protocol):
    def verify(
        self,
        candidate: MapPoiCandidate,
        *,
        expected_company_name: str,
        expected_contact: str | None,
    ) -> EvidenceResult: ...


class PublicEvidenceProvider(Protocol):
    def verify_contact(
        self,
        *,
        company_name: str,
        mobile: str | None = None,
        email: str | None = None,
        source_urls: list[str] | None = None,
    ) -> EvidenceResult: ...


class ErpAdapter(Protocol):
    def build_payload(self, task: Any, lead: LeadRecord) -> dict[str, Any]: ...

    def deliver(self, payload: dict[str, Any]) -> DeliveryResult: ...

    def fingerprint(self, payload: dict[str, Any]) -> str: ...
