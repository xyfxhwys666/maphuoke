from backend.app.main import create_app
from backend.app.providers.fake import FakeDoubaoGateway, FakeErpAdapter, FakeEvidenceVerifier, FakeMapDiscoveryProvider
from backend.app.services.batch_jobs import BatchJobManager
from backend.app.services.search_task import CompanySearchService
from fastapi.testclient import TestClient


def make_client() -> TestClient:
    service = CompanySearchService(
        map_provider=FakeMapDiscoveryProvider(),
        doubao_gateway=FakeDoubaoGateway(),
        evidence_verifier=FakeEvidenceVerifier(),
        erp_adapter=FakeErpAdapter(),
    )
    manager = BatchJobManager(service, request_interval_seconds=0, background=False)
    return TestClient(create_app(service=service, batch_manager=manager))


def test_batch_routes_accept_csv_create_and_run_a_job() -> None:
    client = make_client()
    csv_data = '公司名称,城市\n深圳示例科技有限公司,深圳市\n广州另一家公司,广州市\n'

    created = client.post(
        '/api/v1/batches?filename=companies.csv',
        content=csv_data.encode('utf-8'),
        headers={'content-type': 'text/csv'},
    )
    assert created.status_code == 201
    job = created.json()
    assert job['status'] == 'created'
    assert job['total'] == 2

    started = client.post(f"/api/v1/batches/{job['id']}/start")
    fetched = client.get(f"/api/v1/batches/{job['id']}")

    assert started.status_code == 200
    assert fetched.status_code == 200
    body = fetched.json()
    assert body['status'] == 'completed'
    assert [item['status'] for item in body['items']] == ['completed', 'completed']
    assert all(item['task_id'] for item in body['items'])


def test_batch_routes_report_import_errors() -> None:
    client = make_client()

    response = client.post(
        '/api/v1/batches?filename=companies.csv',
        content='company_name\n示例公司\n'.encode(),
        headers={'content-type': 'text/csv'},
    )

    assert response.status_code == 422
    assert '公司名称' in response.json()['detail']
