from __future__ import annotations

from backend.app.domain.models import DoubaoEnrichment, MapPoiCandidate
from backend.app.services.enrichment import DoubaoEnrichmentService


def test_enrichment_service_passes_map_context_without_mutating_candidate() -> None:
    candidate = MapPoiCandidate(
        candidate_id='poi-1',
        company_name='深圳示例科技有限公司',
        city='深圳市',
        address='广东省深圳市南山区示例路 1 号',
        telephone='0755-12345678',
        category='软件服务',
        poi_id='poi-1',
        source_url='https://uri.amap.com/marker?pid=poi-1',
    )

    class FakeGateway:
        id = 'doubao_web'

        def __init__(self) -> None:
            self.received: dict[str, object] = {}

        def enrich_company(self, **kwargs):
            self.received = kwargs
            return DoubaoEnrichment(mobile='13800138000')

    gateway = FakeGateway()
    result = DoubaoEnrichmentService(gateway).enrich(
        candidate,
        requested_contacts=['mobile', 'email'],
    )

    assert result.mobile == '13800138000'
    assert gateway.received['known_fields'] == {
        'address': '广东省深圳市南山区示例路 1 号',
        'telephone': '0755-12345678',
        'source_url': 'https://uri.amap.com/marker?pid=poi-1',
        'category': '软件服务',
        'poi_id': 'poi-1',
    }
    assert candidate.address == '广东省深圳市南山区示例路 1 号'
