from __future__ import annotations

from typing import Any

import pytest
from backend.app.browser.lifecycle import BrowserState, LoginRequired
from backend.app.domain.models import DoubaoEnrichment, MapPoiCandidate
from backend.app.providers.doubao_parser import (
    DoubaoWebResponseError,
    parse_contact_response,
    parse_intent_keyword_response,
)
from backend.app.providers.doubao_prompt import build_contact_prompt, build_intent_keyword_prompt
from backend.app.providers.doubao_web import DoubaoWebGateway


def test_parse_fenced_json_normalizes_contacts_and_keeps_evidence() -> None:
    response = '''```json
{"company_name":"深圳示例科技有限公司","mobile":"138 0013 8000","contact_person_name":"张三","contact_person_role":"负责人","email":"Sales@Example.COM","wechat":"example_sales","address":"广东省深圳市南山区示例路 1 号","service_intro":"企业软件服务","source_urls":["https://example.com/company"],"evidence_quotes":["深圳示例科技有限公司 联系电话 13800138000"]}
```'''

    result = parse_contact_response(response, company_name='深圳示例科技有限公司')

    assert result.mobile == '13800138000'
    assert result.email == 'sales@example.com'
    assert result.contact_person_name == '张三'
    assert result.source_urls == ['https://example.com/company']
    assert result.evidence_quotes == ['深圳示例科技有限公司 联系电话 13800138000']


def test_parse_rejects_malformed_json_and_company_mismatch() -> None:
    with pytest.raises(DoubaoWebResponseError, match='JSON'):
        parse_contact_response('{"company_name":', company_name='深圳示例科技有限公司')

    with pytest.raises(DoubaoWebResponseError, match='公司名'):
        parse_contact_response(
            '{"company_name":"另一家科技有限公司","mobile":"13800138000"}',
            company_name='深圳示例科技有限公司',
        )


def test_parse_natural_language_requires_requested_company_and_valid_mobile() -> None:
    result = parse_contact_response(
        '深圳示例科技有限公司公开联系电话：138-0013-8000。',
        company_name='深圳示例科技有限公司',
    )

    assert result.mobile == '13800138000'
    assert result.source_urls == []
    assert result.evidence_quotes == []


def test_parse_drops_contacts_explicitly_marked_as_guessed() -> None:
    result = parse_contact_response(
        '{"company_name":"深圳示例科技有限公司","mobile":{"value":"13800138000","status":"guessed"},'
        '"contact_person_name":{"value":"张三","status":"inferred"},'
        '"email":"sales@example.com"}',
        company_name='深圳示例科技有限公司',
    )

    assert result.mobile is None
    assert result.contact_person_name is None
    assert result.email == 'sales@example.com'


def test_prompt_includes_known_map_context_and_no_guessing_rule() -> None:
    prompt = build_contact_prompt(
        company_name='深圳示例科技有限公司',
        city='深圳市',
        requested_contacts=['mobile', 'email', 'wechat'],
        known_fields={
            'address': '广东省深圳市南山区示例路 1 号',
            'telephone': '0755-12345678',
            'source_url': 'https://uri.amap.com/marker?pid=poi-1',
            'category': '软件服务',
            'poi_id': 'poi-1',
        },
    )

    assert '示例路 1 号' in prompt
    assert '0755-12345678' in prompt
    assert 'poi-1' in prompt
    assert '不得根据手机号、公司名称或常识推测' in prompt


def test_intent_keyword_prompt_and_parser_keep_only_json_keywords() -> None:
    prompt = build_intent_keyword_prompt(request_text='我是做家具的，找深圳全案软装公司。')

    assert '提取高德地图搜索用的客户类型关键词' in prompt
    assert parse_intent_keyword_response(
        '{"keywords":["轻奢软装设计公司","别墅室内设计公司","轻奢软装设计公司"]}'
    ) == ['轻奢软装设计公司', '别墅室内设计公司']


def test_gateway_calls_visible_page_and_returns_typed_enrichment() -> None:
    class FakePage:
        visible_text = '豆包对话'

        def __init__(self) -> None:
            self.visited: str | None = None

        def goto(self, url: str, **_: Any) -> None:
            self.visited = url

        def ask(self, prompt: str) -> str:
            assert '广东省深圳市南山区示例路 1 号' in prompt
            return '{"company_name":"深圳示例科技有限公司","mobile":"13800138000"}'

    class FakeBrowser:
        state = BrowserState.READY
        page_instance = FakePage()

        def run(self, command, **_: Any):
            return command(self.page_instance)

    result = DoubaoWebGateway(browser=FakeBrowser()).enrich_company(
        company_name='深圳示例科技有限公司',
        city='深圳市',
        requested_contacts=['mobile'],
        known_fields={'address': '广东省深圳市南山区示例路 1 号'},
    )

    assert isinstance(result, DoubaoEnrichment)
    assert result.mobile == '13800138000'
    assert FakeBrowser.page_instance.visited == 'https://www.doubao.com/chat/'


def test_gateway_starts_stopped_browser_before_judging_relevance() -> None:
    class FakePage:
        visible_text = '豆包对话'

        def ask(self, _prompt: str) -> str:
            return '{"status":"relevant","reason":"匹配","confidence":0.9}'

    class FakeBrowser:
        state = BrowserState.STOPPED

        def __init__(self) -> None:
            self.start_calls = 0

        def start(self) -> None:
            self.start_calls += 1
            self.state = BrowserState.READY

        def run(self, command, **_: Any):
            return command(FakePage())

    browser = FakeBrowser()

    result = DoubaoWebGateway(browser=browser).judge_relevance(
        request_text='找家装设计公司',
        city='深圳市',
        keyword='设计公司',
        candidate=MapPoiCandidate(
            candidate_id='candidate-1',
            company_name='深圳示例设计有限公司',
            city='深圳市',
        ),
    )

    assert result.status == 'relevant'
    assert browser.start_calls == 1


def test_gateway_requests_intent_keyword_suggestions_from_visible_page() -> None:
    class FakePage:
        visible_text = '豆包对话'

        def ask(self, prompt: str) -> str:
            assert '家具' in prompt
            return '{"keywords":["轻奢软装设计公司"]}'

    class FakeBrowser:
        state = BrowserState.READY

        def run(self, command, **_: Any):
            return command(FakePage())

    result = DoubaoWebGateway(browser=FakeBrowser(), request_interval_seconds=0).parse_intent_keywords(
        '我是做家具的，找深圳全案软装公司。'
    )

    assert result == ['轻奢软装设计公司']


def test_gateway_judges_candidate_relevance_from_visible_response() -> None:
    class FakePage:
        visible_text = '豆包对话'

        def ask(self, prompt: str) -> str:
            assert '找家装设计公司' in prompt
            assert '深圳示例设计有限公司' in prompt
            return '{"status":"relevant","reason":"公司名称和业务关键词匹配","confidence":0.92}'

    class FakeBrowser:
        state = BrowserState.READY

        def run(self, command, **_: Any):
            return command(FakePage())

    result = DoubaoWebGateway(browser=FakeBrowser()).judge_relevance(
        request_text='找家装设计公司',
        city='深圳市',
        keyword='设计公司',
        candidate=MapPoiCandidate(
            candidate_id='candidate-1',
            company_name='深圳示例设计有限公司',
            city='深圳市',
            address='示例路 1 号',
        ),
    )

    assert result.status == 'relevant'
    assert result.confidence == 0.92


def test_gateway_converts_login_page_to_pause_error() -> None:
    class LoginPage:
        visible_text = '请登录豆包后继续'

    class FakeBrowser:
        state = BrowserState.READY

        def run(self, command, **_: Any):
            return command(LoginPage())

    with pytest.raises(LoginRequired):
        DoubaoWebGateway(browser=FakeBrowser()).enrich_company(
            company_name='深圳示例科技有限公司',
            city='深圳市',
            requested_contacts=['mobile'],
            known_fields={},
        )


def test_gateway_detects_doubao_home_login_link_as_pause_state() -> None:
    class LoginHomePage:
        visible_text = '豆包\n新对话\n登录\n有什么我能帮你的吗？'

    class FakeBrowser:
        state = BrowserState.READY

        def run(self, command, **_: Any):
            return command(LoginHomePage())

    with pytest.raises(LoginRequired):
        DoubaoWebGateway(browser=FakeBrowser()).enrich_company(
            company_name='深圳示例科技有限公司',
            city='深圳市',
            requested_contacts=['mobile'],
            known_fields={},
        )


def test_gateway_waits_for_hydrated_doubao_login_state() -> None:
    class HydratingLoginHomePage:
        visible_text = '豆包\n新对话\n有什么我能帮你的吗？'

        def wait_for_timeout(self, _timeout: int) -> None:
            self.visible_text = '豆包\n新对话\n登录\n有什么我能帮你的吗？'

    class FakeBrowser:
        state = BrowserState.READY

        def run(self, command, **_: Any):
            return command(HydratingLoginHomePage())

    with pytest.raises(LoginRequired):
        DoubaoWebGateway(browser=FakeBrowser()).enrich_company(
            company_name='深圳示例科技有限公司',
            city='深圳市',
            requested_contacts=['mobile'],
            known_fields={},
        )
