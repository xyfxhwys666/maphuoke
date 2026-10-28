from uuid import NAMESPACE_URL, uuid5

from backend.app.collection.models import RelevanceDecision
from backend.app.domain.dedup import company_identity, payload_fingerprint
from backend.app.domain.models import (
    DeliveryResult,
    DoubaoEnrichment,
    EvidenceResult,
    LeadRecord,
    MapPoiCandidate,
)
from backend.app.domain.task_state import SearchTask


class FakeMapDiscoveryProvider:
    id = 'fake_map'
    label = 'Fake map provider'
    configured = True

    def search_company(self, *, company_name: str, city: str, max_results: int = 5) -> list[MapPoiCandidate]:
        if not company_name.strip():
            return []
        return [
            MapPoiCandidate(
                candidate_id='fake-poi-1',
                company_name=company_name.strip(),
                city=city.strip(),
                address=f'广东省{city.strip()}南山区示例路 1 号',
                source_url='https://map.example.test/poi/fake-poi-1',
                discovery_channel=self.id,
                source_metadata={'provider': self.id, 'poi_id': 'fake-poi-1'},
            )
        ][:max_results]


class FakeRelevanceJudge:
    id = 'fake'
    configured = True

    def __init__(self, decisions: dict[str, RelevanceDecision] | None = None) -> None:
        self.decisions = decisions or {}

    def judge(
        self,
        *,
        request_text: str,
        city: str,
        keyword: str,
        candidate: MapPoiCandidate,
    ) -> RelevanceDecision:
        configured = self.decisions.get(candidate.candidate_id)
        if configured is not None:
            return configured.model_copy(deep=True)
        name = candidate.company_name.lower()
        token = keyword.strip().lower().removesuffix('公司')
        status = 'relevant' if token and token in name else 'review'
        return RelevanceDecision(
            candidate_id=candidate.candidate_id,
            model_id=self.id,
            status=status,
            reason=(
                f'Fake judge matched keyword {keyword}'
                if status == 'relevant'
                else 'Fake judge needs review'
            ),
            confidence=1.0 if status == 'relevant' else 0.5,
        )


class FakeDoubaoGateway:
    id = 'fake_doubao'

    def __init__(self, enrichment: DoubaoEnrichment | None = None) -> None:
        self.enrichment = enrichment or DoubaoEnrichment(mobile='13800138000')
        self.last_known_fields: dict[str, object] = {}

    def enrich_company(
        self,
        *,
        company_name: str,
        city: str,
        requested_contacts: list[str],
        known_fields: dict[str, object],
    ) -> DoubaoEnrichment:
        self.last_known_fields = dict(known_fields)
        return self.enrichment.model_copy(deep=True)


class FakeEvidenceVerifier:
    def __init__(self, result: EvidenceResult | None = None) -> None:
        self.result = result or EvidenceResult()

    def verify(
        self,
        candidate: MapPoiCandidate,
        *,
        expected_company_name: str,
        expected_contact: str | None,
    ) -> EvidenceResult:
        return self.result.model_copy(deep=True)


class FakeErpAdapter:
    def __init__(self) -> None:
        self.payloads: list[dict[str, object]] = []

    def build_payload(self, task: SearchTask, lead: LeadRecord) -> dict[str, object]:
        return {
            'customerAccountGuid': str(uuid5(NAMESPACE_URL, company_identity(lead.city, lead.company_name))),
            'customerAccountName': lead.company_name,
            'customerIpRegion': lead.city,
            'contactInfo': {
                'mobilePhone': lead.mobile,
                'email': lead.email,
                'wechat': lead.wechat,
            },
            'otherContact': {
                'telephone': lead.telephone,
                'address': lead.address,
                'sourceUrls': lead.source_urls,
            },
        }

    def deliver(self, payload: dict[str, object]) -> DeliveryResult:
        self.payloads.append(payload)
        return DeliveryResult(
            status='delivered',
            operation_id=f'fake-operation-{len(self.payloads)}',
            payload=payload,
        )

    def fingerprint(self, payload: dict[str, object]) -> str:
        return payload_fingerprint(payload)
