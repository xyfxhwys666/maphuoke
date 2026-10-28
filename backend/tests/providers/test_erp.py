from __future__ import annotations

import httpx
from backend.app.domain.models import DeliveryResult, LeadRecord
from backend.app.domain.task_state import SearchTask
from backend.app.providers.erp import ErpHttpAdapter


class FakeResponse:
    def __init__(self, payload: dict[str, object], status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError('failed', request=httpx.Request('POST', 'https://erp.test'), response=httpx.Response(self.status_code))

    def json(self) -> dict[str, object]:
        return self.payload


class FakeClient:
    def __init__(self, response: FakeResponse | Exception) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def post(self, url: str, **kwargs):
        self.calls.append({'url': url, **kwargs})
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def make_task_and_lead() -> tuple[SearchTask, LeadRecord]:
    task = SearchTask(id='task-1', company_name='深圳示例科技有限公司', city='深圳市')
    task.__dict__['request_text'] = '我是做家具的，寻找深圳软装设计公司，需要手机号码。'
    lead = LeadRecord(
        id='lead-poi-1',
        task_id=task.id,
        city=task.city,
        company_name=task.company_name,
        mobile='13800138000',
        telephone='0755-12345678',
        wechat='wx_test_001',
        address='示例路 1 号',
        source_url='https://uri.amap.com/marker?pid=poi-1',
        source_urls=['https://uri.amap.com/marker?pid=poi-1'],
        source_metadata={
            'captured_at': '2026-08-07T08:30:00+08:00',
            'amap_poi_id': 'poi-1',
        },
        company_name_verification_status='verified_map',
        contact_verification_status='verified_public_web',
    )
    return task, lead


def test_erp_payload_matches_the_documented_customer_lead_contract() -> None:
    task, lead = make_task_and_lead()
    adapter = ErpHttpAdapter(target_url='https://erp.test/leads')

    first = adapter.build_payload(task, lead)
    second = adapter.build_payload(task, lead)

    assert first['customerAccountGuid'] == second['customerAccountGuid']
    assert first['sourceAccountName'] == '高德地图'
    assert first['userRealUniqueUuid'] == 'poi-1'
    assert first['customerSourceChannel'] == '高德地图'
    assert first['customerCapturedAt'] == '2026-08-07 08:30:00'
    assert first['customerAccountName'] == '深圳示例科技有限公司'
    assert first['customerType'] == 'B端客资'
    assert first['cEndCustomerRequirement'] == '我是做家具的，寻找深圳软装设计公司，需要手机号码。'
    assert first['sourceMethod'] == '高德地图网页精确查询'
    assert first['contactInfo']['contactInfoType'] == '手机号、微信号'
    assert first['contactInfo']['mobilePhone'] == '13800138000'
    assert 'wechat' not in first['contactInfo']
    assert first['contactInfo']['wechatId'] == 'wx_test_001'
    assert '示例路 1 号' in first['contactInfo']['otherContact']
    assert 'https://uri.amap.com/marker?pid=poi-1' in first['contactInfo']['otherContact']
    assert 'otherContact' not in first
    assert adapter.fingerprint(first) == adapter.fingerprint({
        **second,
        'customerCapturedAt': '2026-08-08T09:00:00+08:00',
    })


def test_erp_success_and_nonzero_error_are_reported_without_secret_logging() -> None:
    task, lead = make_task_and_lead()
    success_client = FakeClient(FakeResponse({'errCode': 0, 'operationId': 'op-1'}))
    success = ErpHttpAdapter(target_url='https://erp.test/leads', bearer_token='secret', client=success_client)
    result = success.deliver(success.build_payload(task, lead))

    assert result == DeliveryResult(status='delivered', operation_id='op-1')
    assert 'Authorization' in success_client.calls[0]['headers']
    assert success_client.calls[0]['headers']['Authorization'] == 'Bearer secret'
    assert 'secret' not in str(result.model_dump())

    failure_client = FakeClient(FakeResponse({'errCode': 1001, 'errMsg': 'invalid'}))
    failure = ErpHttpAdapter(target_url='https://erp.test/leads', client=failure_client)
    failed = failure.deliver(failure.build_payload(task, lead))
    assert failed.status == 'failed'
    assert failed.error == 'invalid'


def test_erp_success_records_documented_result_request_id() -> None:
    task, lead = make_task_and_lead()
    client = FakeClient(FakeResponse({
        'errCode': 0,
        'errMsg': None,
        'result': {'requestId': 'request-1'},
    }))
    adapter = ErpHttpAdapter(target_url='https://erp.test/leads', client=client)

    result = adapter.deliver(adapter.build_payload(task, lead))

    assert result == DeliveryResult(status='delivered', operation_id='request-1')


def test_erp_timeout_becomes_retryable_failure() -> None:
    task, lead = make_task_and_lead()
    client = FakeClient(httpx.ReadTimeout('timed out'))
    adapter = ErpHttpAdapter(target_url='https://erp.test/leads', client=client)

    result = adapter.deliver(adapter.build_payload(task, lead))

    assert result.status == 'failed'
    assert result.error == 'timed out'
