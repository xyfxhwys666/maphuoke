from __future__ import annotations

import httpx
import pytest
from backend.app.providers.amap_api import AmapApiProvider, AmapApiProviderError


class FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return self.payload


class FakeClient:
    def __init__(self, responses: list[FakeResponse | Exception]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, object]] = []

    def get(self, url: str, **kwargs):
        self.calls.append({'url': url, **kwargs})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def test_place_text_maps_company_address_and_marker_without_contact_filtering() -> None:
    client = FakeClient([
        FakeResponse({
            'status': '1',
            'count': '1',
            'pois': [{
                'id': 'B0001',
                'name': '深圳示例科技有限公司',
                'address': '南山区示例路 1 号',
                'tel': '',
                'location': '113.9300,22.5300',
                'type': '软件服务',
            }],
        })
    ])
    provider = AmapApiProvider(api_key='key', client=client, request_interval_seconds=0)

    candidates = provider.search_company(company_name='深圳示例科技', city='深圳市')

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.company_name == '深圳示例科技有限公司'
    assert candidate.address == '南山区示例路 1 号'
    assert candidate.mobile is None
    assert candidate.poi_id == 'B0001'
    assert candidate.evidence_snapshot_id == candidate.source_metadata['evidence_snapshot_id']
    assert '113.93' in (candidate.source_url or '')
    assert '深圳市' in str(client.calls[0]['params'])
    assert client.calls[0]['params']['citylimit'] == 'true'


def test_place_text_retries_network_error_and_reads_multiple_pages() -> None:
    page = lambda name: FakeResponse({
        'status': '1',
        'count': '50',
        'pois': [{
            'id': name,
            'name': f'{name} 科技有限公司',
            'address': '示例路 1 号',
            'location': '113.93,22.53',
            'tel': '0755-12345678',
        }],
    })
    client = FakeClient([httpx.ReadTimeout('temporary'), page('B0001'), page('B0002')])
    provider = AmapApiProvider(
        api_key='key',
        client=client,
        request_interval_seconds=0,
        retry_limit=1,
        max_pages=2,
        sleep_fn=lambda _: None,
    )

    candidates = provider.search_company(company_name='示例科技', city='深圳市')

    assert [candidate.poi_id for candidate in candidates] == ['B0001', 'B0002']
    assert len(client.calls) == 3
    assert client.calls[1]['params']['page'] == 1
    assert client.calls[2]['params']['page'] == 2


def test_unconfigured_api_fails_explicitly() -> None:
    provider = AmapApiProvider(api_key=None)

    with pytest.raises(AmapApiProviderError, match='not configured'):
        provider.search_company(company_name='示例科技', city='深圳市')
