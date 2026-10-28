from typing import Protocol

from backend.app.collection.models import CompanyNameCandidate, RelevanceDecision
from backend.app.domain.models import MapPoiCandidate


class KeywordDiscoveryProvider(Protocol):
    id: str
    label: str
    configured: bool

    def search_keyword(
        self,
        *,
        city: str,
        keyword: str,
        max_results: int = 20,
    ) -> list[MapPoiCandidate]: ...


class CompanyCandidateDiscoveryProvider(Protocol):
    id: str
    label: str
    configured: bool

    def discover_company_names(
        self,
        *,
        city: str,
        keyword: str,
        request_text: str,
        max_results: int,
    ) -> list[CompanyNameCandidate]: ...


class RelevanceJudge(Protocol):
    id: str
    configured: bool

    def judge(
        self,
        *,
        request_text: str,
        city: str,
        keyword: str,
        candidate: MapPoiCandidate,
    ) -> RelevanceDecision: ...
