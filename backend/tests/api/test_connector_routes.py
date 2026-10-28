import pytest
from backend.app.collection.service import CollectionService
from backend.app.domain.models import LeadRecord
from backend.app.main import create_app
from backend.app.providers.fake import (
    FakeDoubaoGateway,
    FakeErpAdapter,
    FakeEvidenceVerifier,
    FakeMapDiscoveryProvider,
    FakeRelevanceJudge,
)
from backend.app.services.search_task import CompanySearchService
from fastapi.testclient import TestClient


def _legacy_service() -> CompanySearchService:
    return CompanySearchService(
        map_provider=FakeMapDiscoveryProvider(),
        doubao_gateway=FakeDoubaoGateway(),
        evidence_verifier=FakeEvidenceVerifier(),
        erp_adapter=FakeErpAdapter(),
    )


@pytest.fixture
def client() -> TestClient:
    collection_service = CollectionService(
        map_provider=FakeMapDiscoveryProvider(),
        relevance_judges={'doubao': FakeRelevanceJudge()},
        enrichment_gateway=FakeDoubaoGateway(),
        evidence_verifier=FakeEvidenceVerifier(),
        erp_adapter=FakeErpAdapter(),
        configured_models={'doubao'},
    )
    return TestClient(create_app(service=_legacy_service(), collection_service=collection_service))


@pytest.fixture
def unavailable_collection_client() -> TestClient:
    return TestClient(create_app(service=_legacy_service()))


@pytest.fixture
def collection_task(client: TestClient):
    task = client.app.state.collection_service.create_from_text(
        'SENSITIVE_TASK_REQUEST',
        configured_models={'doubao'},
        auto_deliver=True,
    )
    task.results = [
        LeadRecord(
            id='connector-test-lead',
            task_id=task.id,
            city='深圳市',
            company_name='深圳示例设计有限公司',
            mobile='CONTACT_VALUE',
        )
    ]
    return task


def test_connector_health_advertises_stable_capabilities(client: TestClient) -> None:
    response = client.get('/connector/v1/health')

    assert response.status_code == 200
    assert response.json() == {
        'connector_code': 'mapsearch',
        'version': '1',
        'status': 'ready',
        'capabilities': [
            'lead_search', 'lead_task_read', 'lead_task_control',
            'lead_result_read',
        ],
    }


def test_connector_health_is_degraded_without_collection_service(
    unavailable_collection_client: TestClient,
) -> None:
    response = unavailable_collection_client.get('/connector/v1/health')

    assert response.status_code == 200
    assert response.json()['status'] == 'degraded'


def test_connector_task_detail_does_not_return_raw_task_text_or_contact_data(
    client: TestClient,
    collection_task,
) -> None:
    response = client.get(f'/connector/v1/tasks/{collection_task.id}')

    assert response.status_code == 200
    body = response.json()
    assert body['task_id'] == collection_task.id
    assert 'request_text' not in body
    assert 'SENSITIVE_TASK_REQUEST' not in str(body)
    assert 'phone' not in str(body).lower()
    assert 'CONTACT_VALUE' not in str(body)
    assert 'bearer' not in str(body).lower()


def test_connector_creates_task_without_accepting_erp_configuration(client: TestClient) -> None:
    response = client.post('/connector/v1/tasks', json={
        'request_text': '寻找深圳市全案软装公司',
        'models': [],
    })

    assert response.status_code == 201
    body = response.json()
    assert body['task_id']
    assert body['status'] != 'planned'
    assert body['delivery_enabled'] is False
    assert 'target_url' not in body
    assert 'bearer_token' not in body


def test_connector_expands_single_soft_furnishing_query_until_verified_target(client: TestClient) -> None:
    response = client.post('/connector/v1/tasks', json={
        'request_text': '查询深圳市软装公司，最多返回1条有公开联系方式和公开证据的有效企业信息',
        'models': [],
    })

    assert response.status_code == 201
    task = client.app.state.collection_service.get_task(response.json()['task_id'])
    assert task.intent.target_valid_contacts == 1
    assert {'软装公司', '软装设计公司', '住宅软装', '室内软装', '全案设计公司'} <= set(task.intent.keywords)
    assert len(task.work_units) > 1


def test_connector_returns_only_completed_amap_contact_results(client: TestClient, collection_task) -> None:
    collection_task.results = [
        LeadRecord(
            id='amap-contact-lead',
            task_id=collection_task.id,
            city='深圳市',
            company_name='深圳高德软装有限公司',
            address='深圳市南山区公开地址',
            telephone='0755-12345678',
            contact_person_name='不应展示',
            source_urls=['https://amap.example/poi'],
            company_name_verification_status='verified_map',
            contact_verification_status='captured',
            source_metadata={'provider': 'amap_web', 'detail_verified': True},
            delivery_status='display_only',
        ),
        LeadRecord(
            id='incomplete-lead',
            task_id=collection_task.id,
            city='深圳市',
            company_name='未完成高德详情企业',
            mobile='PRIVATE_CONTACT',
            source_urls=['https://amap.example/incomplete'],
            company_name_verification_status='verified_map',
            contact_verification_status='captured',
            source_metadata={'provider': 'amap_web', 'detail_verified': False},
        ),
    ]

    response = client.get(f'/connector/v1/tasks/{collection_task.id}/results')

    assert response.status_code == 200
    assert response.json() == {
        'task_id': collection_task.id,
        'status': 'planned',
        'items': [{
            'company_name': '深圳高德软装有限公司',
            'city': '深圳市',
            'address': '深圳市南山区公开地址',
            'contact': '0755-12345678',
            'evidence_url': 'https://amap.example/poi',
            'verification_status': 'amap_collected',
        }],
    }


def test_connector_controls_existing_task(client: TestClient, collection_task) -> None:
    task_id = collection_task.id

    paused = client.post(f'/connector/v1/tasks/{task_id}/pause')
    resumed = client.post(f'/connector/v1/tasks/{task_id}/resume')
    cancelled = client.post(f'/connector/v1/tasks/{task_id}/cancel')

    assert paused.status_code == 200
    assert resumed.status_code == 200
    assert cancelled.status_code == 200
    assert cancelled.json()['task_id'] == task_id


def test_connector_task_scope_isolation_is_enforced_by_trusted_header(
    client: TestClient,
) -> None:
    service = client.app.state.collection_service
    first = service.create_from_text(
        '深圳软装公司，找 1 条有效信息。',
        account_scope='tenant-a:member-1',
    )
    second = service.create_from_text(
        '深圳软装公司，找 1 条有效信息。',
        account_scope='tenant-b:member-2',
    )

    scoped = client.get(
        '/connector/v1/tasks',
        headers={'X-MapSearch-Account-Scope': 'tenant-a:member-1'},
    )

    assert scoped.status_code == 200
    assert [item['task_id'] for item in scoped.json()['items']] == [first.id]
    assert client.get(
        f'/connector/v1/tasks/{second.id}',
        headers={'X-MapSearch-Account-Scope': 'tenant-a:member-1'},
    ).status_code == 404


def test_connector_search_consumes_cached_results_before_creating_task(client: TestClient) -> None:
    service = client.app.state.collection_service
    cached = service.create_from_text(
        '查询深圳软装公司，找 1 条有效信息。',
        account_scope='tenant-a:member-1',
    )
    cached.status = 'completed'
    cached.results = [
        LeadRecord(
            id='cached-lead',
            task_id=cached.id,
            city='深圳市',
            company_name='深圳缓存软装有限公司',
            telephone='0755-12345678',
            source_urls=['https://example.com/cached'],
            company_name_verification_status='verified',
            contact_verification_status='verified',
        )
    ]

    first = client.post(
        '/connector/v1/search',
        headers={'X-MapSearch-Account-Scope': 'tenant-a:member-1'},
        json={'request_text': '查询深圳软装公司，找 1 条有效信息。'},
    )
    second = client.post(
        '/connector/v1/search',
        headers={'X-MapSearch-Account-Scope': 'tenant-a:member-1'},
        json={'request_text': '查询深圳软装公司，找 1 条有效信息。'},
    )

    assert first.status_code == 200
    assert first.json()['mode'] == 'cached'
    assert first.json()['task_id'] is None
    assert first.json()['items'][0]['company_name'] == '深圳缓存软装有限公司'
    assert second.status_code == 200
    assert second.json()['mode'] == 'task'
    assert second.json()['task_id']
    assert second.json()['task_id'] != cached.id


def test_connector_search_allocates_verified_cached_result_globally_once(
    client: TestClient,
) -> None:
    service = client.app.state.collection_service
    cached = service.create_from_text(
        '查询深圳软装公司，找 1 条有效信息。',
        account_scope='tenant-a:member-1',
    )
    cached.status = 'completed'
    cached.results = [
        LeadRecord(
            id='other-account-lead',
            task_id=cached.id,
            city='深圳市',
            company_name='深圳隔离软装有限公司',
            telephone='0755-87654321',
            company_name_verification_status='verified',
            contact_verification_status='verified',
        )
    ]

    first = client.post(
        '/connector/v1/search',
        headers={'X-MapSearch-Account-Scope': 'tenant-b:member-2'},
        json={'request_text': '查询深圳软装公司，找 1 条有效信息。'},
    )
    second = client.post(
        '/connector/v1/search',
        headers={'X-MapSearch-Account-Scope': 'tenant-c:member-3'},
        json={'request_text': '查询深圳软装公司，找 1 条有效信息。'},
    )

    assert first.status_code == 200
    assert first.json()['mode'] == 'cached'
    assert first.json()['items'][0]['company_name'] == '深圳隔离软装有限公司'
    assert second.status_code == 200
    assert second.json()['mode'] == 'task'
    assert second.json()['items'] == []


def test_connector_search_reuses_same_city_and_industry_cached_result_when_text_differs(
    client: TestClient,
) -> None:
    service = client.app.state.collection_service
    cached = service.create_from_text(
        '寻找深圳市室内设计公司，需要 1 条有效信息。',
        account_scope='tenant-a:member-1',
    )
    cached.status = 'completed'
    cached.results = [
        LeadRecord(
            id='same-industry-cached-lead',
            task_id=cached.id,
            city='深圳市',
            company_name='深圳室内设计有限公司',
            telephone='0755-10000001',
            source_urls=['https://example.com/same-industry-cached'],
            company_name_verification_status='verified',
            contact_verification_status='verified',
        )
    ]

    response = client.post(
        '/connector/v1/search',
        headers={'X-MapSearch-Account-Scope': 'tenant-a:member-1'},
        json={'request_text': '查询深圳软装公司，找 1 条有效信息。'},
    )

    assert response.status_code == 200
    assert response.json()['mode'] == 'cached'
    assert response.json()['items'][0]['company_name'] == '深圳室内设计有限公司'


def test_connector_search_does_not_consume_same_city_result_with_mismatched_lead_keyword(
    client: TestClient,
) -> None:
    service = client.app.state.collection_service
    cached = service.create_from_text(
        '查询深圳软装公司，找 1 条有效信息。',
        account_scope='tenant-a:member-1',
    )
    cached.status = 'completed'
    cached.results = [
        LeadRecord(
            id='wrong-industry-cached-lead',
            task_id=cached.id,
            city='深圳市',
            company_name='深圳餐饮服务有限公司',
            telephone='0755-10000008',
            source_urls=['https://example.com/wrong-industry-cached'],
            company_name_verification_status='verified',
            contact_verification_status='verified',
            source_metadata={'matched_keywords': ['餐饮服务']},
        )
    ]

    response = client.post(
        '/connector/v1/search',
        headers={'X-MapSearch-Account-Scope': 'tenant-a:member-1'},
        json={'request_text': '查询深圳软装公司，找 1 条有效信息。'},
    )

    assert response.status_code == 200
    assert response.json()['mode'] == 'task'
    assert response.json()['items'] == []


def test_connector_search_returns_requested_number_of_matching_unconsumed_results(
    client: TestClient,
) -> None:
    service = client.app.state.collection_service
    cached = service.create_from_text(
        '寻找深圳软装公司，找 2 条有效信息。',
        account_scope='tenant-a:member-1',
    )
    cached.status = 'completed'
    cached.results = [
        LeadRecord(
            id='first-shenzhen-lead',
            task_id=cached.id,
            city='深圳市',
            company_name='深圳第一软装有限公司',
            telephone='0755-10000001',
            company_name_verification_status='verified',
            contact_verification_status='verified',
        ),
        LeadRecord(
            id='second-shenzhen-lead',
            task_id=cached.id,
            city='深圳市',
            company_name='深圳第二软装有限公司',
            telephone='0755-10000002',
            company_name_verification_status='verified',
            contact_verification_status='verified',
        ),
        LeadRecord(
            id='guangzhou-lead',
            task_id=cached.id,
            city='广州市',
            company_name='广州软装有限公司',
            telephone='020-10000003',
            company_name_verification_status='verified',
            contact_verification_status='verified',
        ),
        LeadRecord(
            id='captured-shenzhen-lead',
            task_id=cached.id,
            city='深圳市',
            company_name='深圳未核验软装有限公司',
            telephone='0755-10000004',
            company_name_verification_status='verified',
            contact_verification_status='captured',
        ),
    ]

    response = client.post(
        '/connector/v1/search',
        headers={'X-MapSearch-Account-Scope': 'tenant-a:member-1'},
        json={'request_text': '查询深圳室内设计公司，找 1 条有效信息。'},
    )

    assert response.status_code == 200
    assert response.json()['mode'] == 'cached'
    assert [item['company_name'] for item in response.json()['items']] == [
        '深圳第一软装有限公司',
    ]
