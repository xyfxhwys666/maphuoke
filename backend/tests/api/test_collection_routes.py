from time import monotonic, sleep

from backend.app.collection.service import CollectionService
from backend.app.domain.models import LeadRecord, MapPoiCandidate
from backend.app.main import create_app
from tools.collection_continuation import (
    browser_needs_reopen,
    daily_progress,
    should_stop_for_target,
    should_resume_daily_pause,
    task_used_keywords,
)
from backend.app.providers.fake import (
    FakeDoubaoGateway,
    FakeErpAdapter,
    FakeEvidenceVerifier,
    FakeMapDiscoveryProvider,
    FakeRelevanceJudge,
)
from backend.app.services.search_task import CompanySearchService
from fastapi.testclient import TestClient


class ApiKeywordProvider:
    id = 'amap_web'
    label = 'Fake Amap keyword provider'
    configured = True

    def __init__(self) -> None:
        self.search_calls = 0
        self.browser = FakeCollectionBrowser()

    def search_keyword(self, *, city: str, keyword: str, max_results: int = 20) -> list[MapPoiCandidate]:
        self.search_calls += 1
        return [
            MapPoiCandidate(
                candidate_id='api-poi-1',
                company_name=f'{city}示例软装公司',
                city=city,
                address=f'{city}示例路 1 号',
                mobile='13800138000',
                source_url='https://uri.amap.com/marker?pid=api-poi-1',
            )
        ][:max_results]


class FakeCollectionBrowser:
    state = 'stopped'

    def __init__(self) -> None:
        self.opened_urls: list[str] = []

    def start(self) -> None:
        self.state = 'ready'

    def open_url(self, url: str) -> None:
        self.opened_urls.append(url)


class IntentKeywordJudge(FakeRelevanceJudge):
    def parse_intent_keywords(self, request_text: str) -> list[str]:
        assert '家具' in request_text
        return ['轻奢软装设计公司', '建材供应商']


def make_client() -> tuple[TestClient, ApiKeywordProvider]:
    keyword_provider = ApiKeywordProvider()
    collection_service = CollectionService(
        map_provider=keyword_provider,
        relevance_judges={'doubao': FakeRelevanceJudge()},
        enrichment_gateway=FakeDoubaoGateway(),
        evidence_verifier=FakeEvidenceVerifier(),
        erp_adapter=FakeErpAdapter(),
        configured_models={'doubao'},
    )
    legacy_service = CompanySearchService(
        map_provider=FakeMapDiscoveryProvider(),
        doubao_gateway=FakeDoubaoGateway(),
        evidence_verifier=FakeEvidenceVerifier(),
        erp_adapter=FakeErpAdapter(),
    )
    return TestClient(create_app(service=legacy_service, collection_service=collection_service)), keyword_provider


def create_collection_task(client: TestClient) -> dict:
    response = client.post(
        '/api/v1/collection-tasks/from-natural-language',
        json={
            'request_text': '深圳找软装公司，需要手机号，使用豆包',
            'models': ['doubao'],
        },
    )
    assert response.status_code == 201
    return response.json()


def test_create_collection_task_returns_plan_without_searching() -> None:
    client, provider = make_client()

    body = create_collection_task(client)

    assert body['status'] == 'planned'
    assert body['plan']['work_unit_count'] > 0
    assert body['intent']['cities'] == ['深圳市']
    assert provider.search_calls == 0


def test_create_collection_task_allows_map_only_plan_without_model_selection() -> None:
    client, _provider = make_client()

    response = client.post(
        '/api/v1/collection-tasks/from-natural-language',
        json={'request_text': '找深圳的软装设计公司，需要电话和地址。'},
    )

    assert response.status_code == 201
    assert response.json()['intent']['models'] == []


def test_create_collection_task_accepts_explicit_keywords_without_default_matrix() -> None:
    client, _provider = make_client()

    response = client.post(
        '/api/v1/collection-tasks/from-natural-language',
        json={
            'request_text': '我是做家具的，找深圳别墅全案软装公司，需要手机号。',
            'keywords': ['荔枝公园住宅软装顾问', '红岭家装设计工作室'],
        },
    )

    assert response.status_code == 201
    assert response.json()['plan']['keywords'] == [
        '荔枝公园住宅软装顾问',
        '红岭家装设计工作室',
    ]
    assert response.json()['plan']['work_unit_count'] == 2


def test_create_collection_task_preserves_more_than_default_explicit_keywords() -> None:
    client, _provider = make_client()
    keywords = [f'custom-query-{index}' for index in range(81)]

    response = client.post(
        '/api/v1/collection-tasks/from-natural-language',
        json={
            'request_text': '\u6211\u662f\u505a\u5bb6\u5177\u7684\uff0c\u627e\u6df1\u5733\u522b\u5885\u5168\u6848\u8f6f\u88c5\u516c\u53f8\uff0c\u9700\u8981\u624b\u673a\u53f7\u3002',
            'keywords': keywords,
        },
    )

    assert response.status_code == 201
    assert response.json()['plan']['keywords'] == keywords
    assert response.json()['plan']['work_unit_count'] == len(keywords)


def test_continuation_reuses_keywords_that_never_received_a_work_unit() -> None:
    assert task_used_keywords(
        {
            'intent': {'keywords': ['completed-query', 'unplanned-query']},
            'work_units': [{'keyword': 'completed-query'}],
        }
    ) == {'completed-query'}


def test_continuation_daily_progress_resets_on_new_calendar_day() -> None:
    assert daily_progress(
        {'daily_date': '2026-08-16', 'daily_start_count': 320},
        current_date='2026-08-17',
        strict_valid_count=390,
    ) == {'daily_date': '2026-08-17', 'daily_start_count': 390, 'daily_valid_count': 0}


def test_continuation_daily_progress_counts_new_valid_records() -> None:
    assert daily_progress(
        {'daily_date': '2026-08-17', 'daily_start_count': 320},
        current_date='2026-08-17',
        strict_valid_count=390,
    ) == {'daily_date': '2026-08-17', 'daily_start_count': 320, 'daily_valid_count': 70}


def test_continuation_only_resumes_its_own_daily_pause() -> None:
    assert should_resume_daily_pause(
        {'daily_paused_task_id': 'task-1'},
        {'id': 'task-1', 'status': 'paused'},
    ) is True
    assert should_resume_daily_pause(
        {'daily_paused_task_id': 'task-1'},
        {'id': 'task-2', 'status': 'paused'},
    ) is False


def test_continuation_reopens_stopped_amap_browser_for_active_task() -> None:
    assert browser_needs_reopen({'checkpoint': {'browser_state': 'stopped'}}) is True
    assert browser_needs_reopen({'checkpoint': {'browser_state': 'ready'}}) is False


def test_continuation_stops_only_when_requested_target_is_reached() -> None:
    assert should_stop_for_target(strict_valid_count=420, target=1000) is False
    assert should_stop_for_target(strict_valid_count=1000, target=1000) is True


def test_create_collection_task_does_not_call_chat_model_for_keyword_expansion() -> None:
    client, provider = make_client()
    client.app.state.collection_service.relevance_judges['doubao'] = IntentKeywordJudge()

    response = client.post(
        '/api/v1/collection-tasks/from-natural-language',
        json={
            'request_text': '我是做家具的，找深圳的全案软装公司，需要手机号。',
            'models': ['doubao'],
        },
    )

    assert response.status_code == 201
    assert '软装设计' in response.json()['plan']['keywords']
    assert '建材供应商' not in response.json()['plan']['keywords']
    assert provider.search_calls == 0


def test_start_collection_task_returns_progress_and_result_summary() -> None:
    client, provider = make_client()
    task = create_collection_task(client)

    response = client.post(f"/api/v1/collection-tasks/{task['id']}/start")

    assert response.status_code == 200
    body = response.json()
    assert body['status'] == 'queued'
    deadline = monotonic() + 2
    while body['status'] not in {'completed', 'completed_with_errors'} and monotonic() < deadline:
        sleep(0.01)
        body = client.get(f"/api/v1/collection-tasks/{task['id']}").json()
    assert body['status'] == 'completed'
    assert body['summary']['candidate_count'] == 1
    assert body['summary']['relevant_count'] == 1
    assert body['results'][0]['mobile'] == '13800138000'
    assert provider.search_calls == 1


def test_task_payload_reports_running_when_a_work_unit_is_running() -> None:
    client, _provider = make_client()
    task = create_collection_task(client)
    stored = client.app.state.collection_service.get_task(task['id'])
    stored.status = 'queued'
    stored.work_units[0].status = 'running'

    response = client.get(f"/api/v1/collection-tasks/{task['id']}")

    assert response.status_code == 200
    assert response.json()['status'] == 'running'


def test_cancel_collection_task_returns_cancelled_state() -> None:
    client, _provider = make_client()
    task = create_collection_task(client)

    response = client.post(f"/api/v1/collection-tasks/{task['id']}/cancel")

    assert response.status_code == 200
    assert response.json()['status'] == 'cancelled'


def test_extend_completed_collection_appends_and_starts_new_keywords() -> None:
    client, provider = make_client()
    task = create_collection_task(client)
    client.post(f"/api/v1/collection-tasks/{task['id']}/start")
    deadline = monotonic() + 2
    current = client.get(f"/api/v1/collection-tasks/{task['id']}").json()
    while current['status'] not in {'completed', 'completed_with_errors'} and monotonic() < deadline:
        sleep(0.01)
        current = client.get(f"/api/v1/collection-tasks/{task['id']}").json()
    original_units = current['summary']['total_work_units']

    response = client.post(
        f"/api/v1/collection-tasks/{task['id']}/extend",
        json={'keywords': ['整装公司']},
    )

    assert response.status_code == 200
    extended = response.json()
    assert extended['status'] == 'queued'
    deadline = monotonic() + 2
    while extended['status'] not in {'completed', 'completed_with_errors'} and monotonic() < deadline:
        sleep(0.01)
        extended = client.get(f"/api/v1/collection-tasks/{task['id']}").json()
    assert extended['summary']['total_work_units'] == original_units + 1
    assert provider.search_calls == 2


def test_collection_models_reject_unconfigured_selection() -> None:
    client, _provider = make_client()

    response = client.post(
        '/api/v1/collection-tasks/from-natural-language',
        json={'request_text': '深圳找软装公司', 'models': ['deepseek']},
    )

    assert response.status_code == 422


def test_collection_models_are_not_exposed_for_map_only_collection() -> None:
    client, _provider = make_client()

    response = client.get('/api/v1/collection-models')

    assert response.status_code == 200
    assert response.json()['items'] == []


def test_collection_task_preserves_continuous_and_delivery_options() -> None:
    client, _provider = make_client()

    response = client.post(
        '/api/v1/collection-tasks/from-natural-language',
        json={
            'request_text': '深圳找软装公司，使用豆包',
            'models': ['doubao'],
            'continuous_mode': True,
            'auto_deliver': False,
            'verified_auto_deliver': False,
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body['continuous_mode'] is True
    assert body['auto_deliver'] is False
    assert body['verified_auto_deliver'] is False


def test_collection_task_list_returns_persisted_workbench_queue() -> None:
    client, _provider = make_client()
    first = create_collection_task(client)
    second = create_collection_task(client)

    response = client.get('/api/v1/collection-tasks')

    assert response.status_code == 200
    assert [item['id'] for item in response.json()['items']] == [second['id'], first['id']]


def test_open_amap_browser_uses_the_dedicated_collection_browser() -> None:
    client, provider = make_client()

    response = client.post('/api/v1/collection-browser/amap/open')

    assert response.status_code == 200
    assert response.json()['url'] == 'https://www.amap.com/'
    assert provider.browser.opened_urls == ['https://www.amap.com/']


def test_collection_delivery_sends_canonical_amap_fields_to_requested_target() -> None:
    client, _provider = make_client()
    delivered_payloads: list[dict[str, object]] = []

    class CapturingAdapter:
        def build_payload(self, task: object, lead: LeadRecord) -> dict[str, object]:
            return {
                'company_name': lead.company_name,
                'mobile': lead.mobile,
                'address': lead.address,
                'category': lead.source_metadata['amap_category'],
                'coordinates': lead.source_metadata['amap_coordinates'],
                'amap_url': lead.source_url,
            }

        def fingerprint(self, payload: dict[str, object]) -> str:
            return str(payload['company_name'])

        def deliver(self, payload: dict[str, object]):
            delivered_payloads.append(payload)
            return FakeErpAdapter().deliver(payload)

    client.app.state.collection_service.manual_delivery_adapter_factory = (
        lambda target_url, bearer_token: CapturingAdapter()
    )
    task = create_collection_task(client)
    current = client.app.state.collection_service.get_task(task['id'])
    current.results = [
        LeadRecord(
            id='lead-amap-1',
            task_id=current.id,
            city='深圳市',
            company_name='深圳市示例设计有限公司',
            mobile='13800138000',
            address='深圳市南山区示例路 1 号',
            source_url='https://uri.amap.com/marker?pid=amap-1',
            source_metadata={
                'amap_category': '室内设计',
                'amap_coordinates': {'longitude': 113.93, 'latitude': 22.54},
            },
        )
    ]

    response = client.post(
        f"/api/v1/collection-tasks/{task['id']}/deliver",
        json={'target_url': 'https://erp.example.test/leads', 'bearer_token': 'token'},
    )

    assert response.status_code == 200
    assert response.json()['sent'] == 1
    assert delivered_payloads == [
        {
            'company_name': '深圳市示例设计有限公司',
            'mobile': '13800138000',
            'address': '深圳市南山区示例路 1 号',
            'category': '室内设计',
            'coordinates': {'longitude': 113.93, 'latitude': 22.54},
            'amap_url': 'https://uri.amap.com/marker?pid=amap-1',
        }
    ]


def test_collection_single_delivery_rejects_amap_result_without_mobile() -> None:
    client, _provider = make_client()
    task = create_collection_task(client)
    current = client.app.state.collection_service.get_task(task['id'])
    current.results = [
        LeadRecord(
            id='lead-amap-no-phone',
            task_id=current.id,
            city='深圳市',
            company_name='深圳市无电话设计有限公司',
            source_url='https://uri.amap.com/marker?pid=amap-2',
        )
    ]

    response = client.post(
        f"/api/v1/collection-tasks/{task['id']}/leads/lead-amap-no-phone/deliver",
        json={'target_url': 'https://erp.example.test/leads'},
    )

    assert response.status_code == 422
    assert response.json()['detail'] == 'lead has no valid Amap mobile'


def test_collection_batch_delivery_skips_amap_results_without_mobile() -> None:
    client, _provider = make_client()
    adapter = FakeErpAdapter()
    client.app.state.collection_service.manual_delivery_adapter_factory = (
        lambda target_url, bearer_token: adapter
    )
    task = create_collection_task(client)
    current = client.app.state.collection_service.get_task(task['id'])
    current.results = [
        LeadRecord(
            id='lead-with-mobile', task_id=current.id, city='深圳市',
            company_name='深圳市有手机设计有限公司', mobile='13800138000',
        ),
        LeadRecord(
            id='lead-without-phone', task_id=current.id, city='深圳市',
            company_name='深圳市无电话设计有限公司',
        ),
    ]

    response = client.post(
        f"/api/v1/collection-tasks/{task['id']}/deliver",
        json={'target_url': 'https://erp.example.test/leads'},
    )

    assert response.status_code == 200
    assert response.json()['sent'] == 1
    assert len(adapter.payloads) == 1


def test_collection_delivery_deduplicates_per_target_url() -> None:
    client, _provider = make_client()
    delivered_targets: list[str] = []

    class DestinationAdapter:
        def __init__(self, target_url: str) -> None:
            self.target_url = target_url

        def build_payload(self, task: object, lead: LeadRecord) -> dict[str, object]:
            return {'company_name': lead.company_name, 'mobile': lead.mobile}

        def fingerprint(self, payload: dict[str, object]) -> str:
            return 'same-payload'

        def deliver(self, payload: dict[str, object]):
            delivered_targets.append(self.target_url)
            return FakeErpAdapter().deliver(payload)

    client.app.state.collection_service.manual_delivery_adapter_factory = (
        lambda target_url, bearer_token: DestinationAdapter(target_url)
    )
    task = create_collection_task(client)
    current = client.app.state.collection_service.get_task(task['id'])
    current.results = [
        LeadRecord(
            id='lead-target-scope',
            task_id=current.id,
            city='深圳市',
            company_name='深圳市目标隔离设计有限公司',
            mobile='13800138000',
        )
    ]

    first = client.post(
        f"/api/v1/collection-tasks/{task['id']}/deliver",
        json={'target_url': 'https://erp-a.example.test/leads'},
    )
    second = client.post(
        f"/api/v1/collection-tasks/{task['id']}/deliver",
        json={'target_url': 'https://erp-b.example.test/leads'},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert delivered_targets == [
        'https://erp-a.example.test/leads',
        'https://erp-b.example.test/leads',
    ]


def test_collection_delivery_deduplicates_different_companies_by_mobile() -> None:
    client, _provider = make_client()
    adapter = FakeErpAdapter()
    adapter.target_url = 'https://erp.example.test/leads'
    client.app.state.collection_service.manual_delivery_adapter_factory = (
        lambda target_url, bearer_token: adapter
    )
    task = create_collection_task(client)
    current = client.app.state.collection_service.get_task(task['id'])
    current.results = [
        LeadRecord(
            id='lead-store-a', task_id=current.id, city='深圳市',
            company_name='深圳示例装饰南山店', mobile='13800138000',
        ),
        LeadRecord(
            id='lead-store-b', task_id=current.id, city='深圳市',
            company_name='深圳示例装饰福田店', mobile='13800138000',
        ),
    ]

    response = client.post(
        f"/api/v1/collection-tasks/{task['id']}/deliver",
        json={'target_url': 'https://erp.example.test/leads'},
    )

    assert response.status_code == 200
    assert len(adapter.payloads) == 1
    assert [lead.delivery_status for lead in current.results] == ['delivered', 'duplicate']
