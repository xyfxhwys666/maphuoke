from backend.app.config import RuntimeSettings
from backend.app.domain.merge import merge_candidate_with_enrichment
from backend.app.domain.models import DoubaoEnrichment
from backend.app.providers.amap_api import AmapApiProvider
from backend.app.providers.fake import FakeDoubaoGateway, FakeErpAdapter, FakeEvidenceVerifier, FakeMapDiscoveryProvider
from backend.app.providers.registry import build_map_provider
from backend.app.runtime import build_runtime_components
from backend.app.services.search_task import CompanySearchService


def test_api_provider_output_uses_same_downstream_candidate_contract() -> None:
    provider = AmapApiProvider(api_key='key', client=None, request_interval_seconds=0)
    candidate = provider.candidate_from_poi(
        {
            'id': 'B0001',
            'name': '深圳示例科技有限公司',
            'address': '南山区示例路 1 号',
            'location': '113.93,22.53',
            'tel': '',
        },
        city='深圳市',
    )
    lead = merge_candidate_with_enrichment(
        candidate,
        DoubaoEnrichment(),
        task_id='task-1',
    )

    assert lead.company_name == candidate.company_name
    assert lead.address == candidate.address
    assert lead.discovery_channel == 'amap_api'


def test_provider_registry_exposes_web_and_api_without_using_dom_in_service() -> None:
    providers = build_map_provider(
        'amap_api',
        api_key='key',
        browser=None,
    )

    assert providers.id == 'amap_api'
    assert providers.configured is True


def test_service_selects_task_discovery_provider_without_changing_downstream_contract() -> None:
    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                'status': '1',
                'count': '1',
                'pois': [{'id': 'B0001', 'name': 'API 示例科技有限公司', 'address': 'API 路 1 号'}],
            }

    class FakeClient:
        def get(self, *_args, **_kwargs):
            return FakeResponse()

    api_provider = AmapApiProvider(api_key='key', client=FakeClient(), request_interval_seconds=0)
    service = CompanySearchService(
        map_provider=FakeMapDiscoveryProvider(),
        map_providers={'amap_api': api_provider},
        doubao_gateway=FakeDoubaoGateway(),
        evidence_verifier=FakeEvidenceVerifier(),
        erp_adapter=FakeErpAdapter(),
    )
    task = service.create_task(
        company_name='API 示例科技有限公司',
        city='深圳市',
        discovery_provider='amap_api',
    )

    discovered = service.discover(task.id)

    assert discovered.candidates[0].discovery_channel == 'amap_api'
    assert discovered.candidates[0].address == 'API 路 1 号'


def test_runtime_registers_real_and_fake_providers_without_starting_browsers() -> None:
    components = build_runtime_components(
        RuntimeSettings(
            amap_api_key='key',
            browser_profile_dir='C:/tmp/mapsearch-test-profiles',
            amap_cdp_port=49981,
            doubao_cdp_port=49982,
        )
    )
    try:
        assert set(components.service.map_providers) == {'fake_map', 'amap_web', 'amap_api'}
        assert set(components.service.doubao_gateways) == {'fake_doubao', 'doubao_web'}
        assert components.service.map_providers['amap_web'].browser.state.value == 'stopped'
        assert components.service.doubao_gateways['doubao_web'].browser.state.value == 'stopped'
    finally:
        components.close()
