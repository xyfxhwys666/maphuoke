from backend.app.main import create_app
from backend.app.providers.erp import ErpHttpAdapter
from backend.app.providers.fake import FakeDoubaoGateway, FakeEvidenceVerifier, FakeMapDiscoveryProvider
from backend.app.services.search_task import CompanySearchService
from fastapi.testclient import TestClient


def make_client() -> TestClient:
    return TestClient(create_app(database_url='sqlite+pysqlite:///:memory:'))


def create_task(client: TestClient) -> dict:
    response = client.post(
        '/api/v1/company-search-tasks',
        json={
            'company_name': '深圳示例科技有限公司',
            'city': '深圳市',
            'discovery_provider': 'fake_map',
            'enrichment_provider': 'fake_doubao',
            'required_contacts': ['mobile', 'email', 'wechat'],
            'auto_deliver': False,
            'allow_map_only_verification': False,
        },
    )
    assert response.status_code == 201
    return response.json()


def test_provider_listing_and_task_creation_return_explicit_state() -> None:
    client = make_client()

    providers = client.get('/api/v1/providers')
    task = create_task(client)

    assert providers.status_code == 200
    assert any(item['id'] == 'fake_map' for item in providers.json()['map_discovery'])
    assert task['status'] == 'created'
    assert task['candidates'] == []
    assert task['leads'] == []


def test_erp_config_reports_runtime_adapter_configuration() -> None:
    client = TestClient(
        create_app(
            service=CompanySearchService(
                map_provider=FakeMapDiscoveryProvider(),
                doubao_gateway=FakeDoubaoGateway(),
                evidence_verifier=FakeEvidenceVerifier(),
                erp_adapter=ErpHttpAdapter(target_url='https://erp.example.test/leads'),
            )
        )
    )

    response = client.get('/api/v1/erp-config')

    assert response.status_code == 200
    assert response.json() == {'configured': True, 'auto_deliver_default': False}


def test_start_and_get_task_expose_map_fields_separately() -> None:
    client = make_client()
    task = create_task(client)

    started = client.post(f"/api/v1/company-search-tasks/{task['id']}/start")
    fetched = client.get(f"/api/v1/company-search-tasks/{task['id']}")

    assert started.status_code == 200
    assert fetched.status_code == 200
    body = fetched.json()
    assert body['status'] == 'candidates_ready'
    assert body['candidates'][0]['address'] == '广东省深圳市南山区示例路 1 号'
    assert body['candidates'][0]['source_metadata']['provider'] == 'fake_map'
    assert body['leads'] == []


def test_pause_and_resume_preserve_checkpoint() -> None:
    client = make_client()
    task = create_task(client)

    paused = client.post(f"/api/v1/company-search-tasks/{task['id']}/pause")
    resumed = client.post(f"/api/v1/company-search-tasks/{task['id']}/resume")

    assert paused.status_code == 200
    assert paused.json()['status'] == 'paused'
    assert resumed.status_code == 200
    assert resumed.json()['status'] == 'discovering_map'


def test_enrich_verify_and_deliver_return_gate_reason() -> None:
    client = make_client()
    task = create_task(client)
    client.post(f"/api/v1/company-search-tasks/{task['id']}/start")
    candidate_id = client.get(f"/api/v1/company-search-tasks/{task['id']}").json()['candidates'][0]['candidate_id']

    enriched = client.post(
        f"/api/v1/company-search-tasks/{task['id']}/enrich",
        json={'candidate_id': candidate_id},
    )
    verified = client.post(
        f"/api/v1/company-search-tasks/{task['id']}/verify",
        json={'candidate_id': candidate_id},
    )
    delivered = client.post(
        f"/api/v1/company-search-tasks/{task['id']}/deliver",
        json={'candidate_id': candidate_id},
    )

    assert enriched.status_code == 200
    assert enriched.json()['leads'][0]['address'] == '广东省深圳市南山区示例路 1 号'
    assert verified.status_code == 200
    assert delivered.status_code == 200
    assert delivered.json()['delivery']['status'] == 'display_only'
    assert 'contact_unverified' in delivered.json()['delivery']['reasons']


def test_retry_errors_restarts_discovery_when_task_has_no_candidates() -> None:
    client = make_client()
    task = create_task(client)

    retried = client.post(f"/api/v1/company-search-tasks/{task['id']}/retry-errors")

    assert retried.status_code == 200
    assert retried.json()['status'] == 'candidates_ready'
    assert retried.json()['candidates']
