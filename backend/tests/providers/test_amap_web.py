from __future__ import annotations

from typing import Any

import pytest
from backend.app.browser.lifecycle import ChallengeRequired
from backend.app.domain.models import MapPoiCandidate
from backend.app.providers.amap_selectors import merge_detail_candidate, parse_result_card_text
from backend.app.providers.amap_web import AmapPageAdapter, AmapWebProvider


class FakeLocator:
    def __init__(
        self,
        items: list[FakeLocator] | None = None,
        *,
        text: str = '',
        attrs: dict[str, str] | None = None,
        on_click=None,
        on_press=None,
    ) -> None:
        self.items = items
        self.text = text
        self.attrs = attrs or {}
        self.on_click = on_click
        self.on_press = on_press
        self.filled: str | None = None
        self.pressed: str | None = None

    def count(self) -> int:
        return len(self.items) if self.items is not None else 1

    @property
    def first(self) -> FakeLocator:
        return self.items[0] if self.items else self

    def nth(self, index: int) -> FakeLocator:
        assert self.items is not None
        return self.items[index]

    def inner_text(self, **_: Any) -> str:
        return self.text

    def get_attribute(self, name: str) -> str | None:
        return self.attrs.get(name)

    def fill(self, value: str) -> None:
        self.filled = value

    def press(self, key: str) -> None:
        self.pressed = key
        if self.on_press is not None:
            self.on_press(key)

    def click(self, **_: Any) -> None:
        if self.on_click is not None:
            self.on_click()


class FakePage:
    def __init__(
        self,
        *,
        body_text: str,
        cards: list[FakeLocator],
        cards_after_wait: list[FakeLocator] | None = None,
        body_after_wait: str | None = None,
        hidden_phone_text: str = '',
        detail_phone_text: str = '',
        panel_text: str | None = None,
    ) -> None:
        self.body_text = body_text
        self.initial_body_text = body_text
        self.cards = cards
        self.cards_after_wait = cards_after_wait
        self.body_after_wait = body_after_wait
        self.hidden_phone_text = hidden_phone_text
        self.detail_phone_text = detail_phone_text
        self.panel_text = panel_text
        self.search_input = FakeLocator()
        self.calls: list[tuple[str, str]] = []
        self.visited: str | None = None
        self.wait_calls: list[float] = []
        self.url = 'https://www.amap.com/search?query=深圳市%20示例科技'

    def goto(self, url: str, **_: Any) -> None:
        self.visited = url
        self.url = url

    def get_by_role(self, role: str, **_: Any) -> FakeLocator:
        self.calls.append(('role', role))
        return FakeLocator([])

    def locator(self, selector: str) -> FakeLocator:
        self.calls.append(('locator', selector))
        if selector == 'input[placeholder*="搜索"]':
            return self.search_input
        if selector == '.poi-item':
            return FakeLocator(self.cards)
        if selector == 'body':
            return FakeLocator(text=self.body_text)
        if selector == '.place-panel':
            return FakeLocator(text=self.panel_text or self.body_text)
        if selector == '[class*="phone"]' and self.hidden_phone_text:
            return FakeLocator(text=self.hidden_phone_text)
        if selector == '.place-panel .placeinfo .feedphone' and self.detail_phone_text:
            return FakeLocator(text=self.detail_phone_text)
        return FakeLocator([])

    def wait_for_timeout(self, timeout: float) -> None:
        self.wait_calls.append(timeout)
        if self.cards_after_wait is not None:
            self.cards = self.cards_after_wait
            self.cards_after_wait = None
        if self.body_after_wait is not None:
            self.body_text = self.body_after_wait
            self.body_after_wait = None

    def show_detail(
        self,
        *,
        text: str,
        url: str,
        panel_text: str | None = None,
    ) -> None:
        self.body_text = text
        self.panel_text = panel_text
        self.url = url

    def go_back(self, **_: Any) -> None:
        self.body_text = self.initial_body_text
        self.url = 'https://www.amap.com/search'


def test_parse_result_card_text_keeps_map_fields_and_evidence() -> None:
    candidate = parse_result_card_text(
        '''深圳示例科技有限公司
地址：广东省深圳市南山区示例路 1 号
电话：0755-1234 5678
分类：软件和信息技术服务业
坐标：113.9300, 22.5300
POI ID：poi-1''',
        city='深圳市',
        source_url='https://uri.amap.com/marker?pid=poi-1',
    )

    assert isinstance(candidate, MapPoiCandidate)
    assert candidate.company_name == '深圳示例科技有限公司'
    assert candidate.address == '广东省深圳市南山区示例路 1 号'
    assert candidate.telephone == '0755-1234 5678'
    assert candidate.category == '软件和信息技术服务业'
    assert candidate.longitude == 113.93
    assert candidate.latitude == 22.53
    assert candidate.poi_id == 'poi-1'
    assert candidate.source_url == 'https://uri.amap.com/marker?pid=poi-1'
    assert candidate.discovery_channel == 'amap_web'
    assert candidate.raw_text and '示例科技有限公司' in candidate.raw_text


def test_parse_result_card_text_uses_actual_city_from_amap_address() -> None:
    candidate = parse_result_card_text(
        '''深圳智林装饰软装设计工程有限公司
地址：广东省广州市天河区示例路 1 号
POI ID：poi-cross-city''',
        city='深圳市',
        source_url='https://www.amap.com/place/poi-cross-city',
        company_name_hint='深圳智林装饰软装设计工程有限公司',
    )

    assert candidate.city == '广州市'
    assert candidate.source_metadata['requested_city'] == '深圳市'
    assert candidate.source_metadata['actual_city'] == '广州市'


def test_page_adapter_uses_fallback_selectors_and_submits_city_query() -> None:
    page = FakePage(
        body_text='搜索结果',
        cards=[
            FakeLocator(
                text='深圳示例科技有限公司\n地址：广东省深圳市南山区示例路 1 号\n电话：0755-12345678',
                attrs={'href': 'https://uri.amap.com/marker?pid=poi-1'},
            )
        ],
    )
    adapter = AmapPageAdapter(page)

    candidates = adapter.search_keyword(keyword='深圳示例科技', city='深圳市', max_results=5)

    assert page.search_input.filled == '深圳市 深圳示例科技'
    assert page.search_input.pressed == 'Enter'
    assert ('locator', 'input[placeholder*="搜索"]') in page.calls
    assert ('locator', '.poi-item') in page.calls
    assert candidates[0].poi_id == 'poi-1'


def test_page_adapter_searches_keyword_with_city_query() -> None:
    page = FakePage(
        body_text='搜索结果',
        cards=[
            FakeLocator(
                text='深圳示例软装公司\n地址：广东省深圳市南山区示例路 1 号',
                attrs={'href': 'https://uri.amap.com/marker?pid=poi-keyword-1'},
            )
        ],
    )

    candidates = AmapPageAdapter(page).search_keyword(
        keyword='软装公司',
        city='深圳市',
        max_results=5,
    )

    assert page.search_input.filled == '深圳市 软装公司'
    assert candidates[0].company_name == '深圳示例软装公司'
    assert candidates[0].address == '广东省深圳市南山区示例路 1 号'


def test_web_provider_returns_candidates_without_contacts() -> None:
    page = FakePage(
        body_text='搜索结果',
        cards=[FakeLocator(text='深圳示例科技有限公司\n地址：示例路 1 号')],
    )

    class FakeBrowser:
        def run(self, command, **_: Any):
            return command(page)

    candidates = AmapWebProvider(browser=FakeBrowser()).search_keyword(
        keyword='深圳示例科技',
        city='深圳市',
    )

    assert candidates[0].company_name == '深圳示例科技有限公司'
    assert candidates[0].address == '示例路 1 号'
    assert candidates[0].mobile is None
    assert candidates[0].evidence_snapshot_id == candidates[0].source_metadata['evidence_snapshot_id']
    assert page.visited is None


def test_web_provider_paces_searches_and_cools_down_each_batch() -> None:
    page = FakePage(
        body_text='搜索结果',
        cards=[FakeLocator(text='深圳示例科技有限公司\n地址：示例路 1 号')],
    )
    delays: list[float] = []

    class FakeBrowser:
        def run(self, command, **_: Any):
            return command(page)

    provider = AmapWebProvider(
        browser=FakeBrowser(),
        search_delay_range=(1.0, 1.0),
        batch_size=2,
        batch_cooldown_range=(5.0, 5.0),
        sleep=delays.append,
    )

    provider.search_keyword(keyword='软装公司', city='深圳市')
    provider.search_keyword(keyword='整装公司', city='深圳市')

    assert delays == [1.0, 5.0]


def test_web_provider_refreshes_cdp_connection_between_search_batches() -> None:
    page = FakePage(
        body_text='\u641c\u7d22\u7ed3\u679c',
        cards=[FakeLocator(text='\u6df1\u5733\u793a\u4f8b\u8bbe\u8ba1\u516c\u53f8\n\u5730\u5740\uff1a\u793a\u4f8b\u8def 1 \u53f7')],
    )

    class FakeBrowser:
        refresh_count = 0
        reconnect_count = 0

        def refresh_connection(self) -> None:
            self.refresh_count += 1

        def reconnect(self) -> None:
            self.reconnect_count += 1

        def run(self, command, **_: Any):
            return command(page)

    browser = FakeBrowser()
    provider = AmapWebProvider(
        browser=browser,
        connection_refresh_interval=1,
        search_delay_range=(0, 0),
    )

    provider.search_keyword(keyword='\u8f6f\u88c5\u8bbe\u8ba1', city='\u6df1\u5733\u5e02')
    provider.search_keyword(keyword='\u6574\u88c5\u516c\u53f8', city='\u6df1\u5733\u5e02')

    assert browser.refresh_count == 1
    assert browser.reconnect_count == 0


def test_web_provider_reuses_an_open_amap_search_page_for_next_company_lookup() -> None:
    page = FakePage(
        body_text='搜索结果',
        cards=[FakeLocator(text='深圳示例科技有限公司\n地址：示例路 1 号')],
    )

    class FakeBrowser:
        def run(self, command, **_: Any):
            return command(page)

    AmapWebProvider(browser=FakeBrowser()).search_company(
        company_name='深圳示例科技',
        city='深圳市',
    )

    assert page.visited is None
    assert page.search_input.filled == '深圳市 深圳示例科技'


def test_page_adapter_waits_for_async_result_cards_before_extracting() -> None:
    page = FakePage(
        body_text='\u6b63\u5728\u641c\u7d22',
        cards=[],
        cards_after_wait=[
            FakeLocator(text='\u6df1\u5733\u793a\u4f8b\u79d1\u6280\u6709\u9650\u516c\u53f8\n\u5730\u5740\uff1a\u793a\u4f8b\u8def 1 \u53f7')
        ],
    )

    candidates = AmapPageAdapter(page, result_timeout=0.2, poll_interval=0).search_keyword(
        keyword='\u6df1\u5733\u793a\u4f8b\u79d1\u6280',
        city='\u6df1\u5733\u5e02',
    )

    assert candidates[0].address == '\u793a\u4f8b\u8def 1 \u53f7'
    assert page.wait_calls


def test_page_adapter_detects_challenge_at_result_timeout() -> None:
    class BoundaryChallengePage(FakePage):
        body_reads = 0

        def locator(self, selector: str) -> FakeLocator:
            if selector == 'body':
                self.body_reads += 1
                if self.body_reads >= 2:
                    self.body_text = '访问异常，请完成验证，拖动滑块'
            return super().locator(selector)

    page = BoundaryChallengePage(body_text='正在搜索', cards=[])

    with pytest.raises(ChallengeRequired):
        AmapPageAdapter(page, result_timeout=0, poll_interval=0).search_keyword(
            keyword='软装公司',
            city='深圳市',
        )


def test_web_provider_circuit_breaker_pauses_after_two_result_timeouts() -> None:
    class TimeoutBrowser:
        def run(self, command, **_: Any):
            raise TimeoutError('Amap search results did not load before the timeout')

    provider = AmapWebProvider(
        browser=TimeoutBrowser(),
        suspicious_failure_threshold=2,
        search_delay_range=(0, 0),
    )

    with pytest.raises(TimeoutError):
        provider.search_keyword(keyword='软装公司', city='深圳市')
    with pytest.raises(ChallengeRequired):
        provider.search_keyword(keyword='整装公司', city='深圳市')


def test_web_provider_success_resets_suspicious_failure_counter() -> None:
    page = FakePage(
        body_text='搜索结果',
        cards=[FakeLocator(text='深圳示例设计有限公司\n地址：示例路 1 号')],
    )

    class FlakyBrowser:
        calls = 0

        def run(self, command, **_: Any):
            self.calls += 1
            if self.calls in {1, 3}:
                raise TimeoutError('Amap search results did not load before the timeout')
            return command(page)

    provider = AmapWebProvider(
        browser=FlakyBrowser(),
        suspicious_failure_threshold=2,
        search_delay_range=(0, 0),
    )

    with pytest.raises(TimeoutError):
        provider.search_keyword(keyword='软装公司', city='深圳市')
    provider.search_keyword(keyword='设计公司', city='深圳市')
    with pytest.raises(TimeoutError):
        provider.search_keyword(keyword='整装公司', city='深圳市')

    assert provider.consecutive_suspicious_failures == 1


def test_web_provider_adaptive_delay_grows_after_suspicious_failure() -> None:
    delays: list[float] = []

    class TimeoutBrowser:
        def run(self, command, **_: Any):
            raise TimeoutError('Amap search results did not load before the timeout')

    provider = AmapWebProvider(
        browser=TimeoutBrowser(),
        suspicious_failure_threshold=3,
        search_delay_range=(2, 2),
        sleep=delays.append,
    )

    with pytest.raises(TimeoutError):
        provider.search_keyword(keyword='软装公司', city='深圳市')
    with pytest.raises(TimeoutError):
        provider.search_keyword(keyword='设计公司', city='深圳市')

    assert delays == [2, 4]


def test_page_adapter_waits_for_target_company_on_async_detail_page() -> None:
    page = FakePage(
        body_text='高德地图加载中',
        body_after_wait='深圳甲设计有限公司\n地址：详情路 2 号',
        cards=[],
    )

    detail_text = AmapPageAdapter(
        page,
        detail_timeout=0.2,
        poll_interval=0,
    )._wait_for_page_text(page, company_name='深圳甲设计有限公司')

    assert detail_text == '深圳甲设计有限公司\n地址：详情路 2 号'


def test_page_adapter_merges_detail_fields_without_losing_list_fields() -> None:
    detail_text = (
        '\u6df1\u5733\u793a\u4f8b\u79d1\u6280\u6709\u9650\u516c\u53f8\n'
        '\u7535\u8bdd\uff1a0755-12345678\n'
        '\u5206\u7c7b\uff1a\u8f6f\u4ef6\u548c\u4fe1\u606f\u6280\u672f\u670d\u52a1\n'
        '\u5750\u6807\uff1a113.93,22.53\n'
        'POI ID\uff1apoi-detail'
    )
    page = FakePage(
        body_text='\u641c\u7d22\u7ed3\u679c',
        cards=[],
    )
    card = FakeLocator(
        text='\u6df1\u5733\u793a\u4f8b\u79d1\u6280\u6709\u9650\u516c\u53f8\n\u5730\u5740\uff1a\u793a\u4f8b\u8def 1 \u53f7',
        on_click=lambda: page.show_detail(text=detail_text, url='https://www.amap.com/detail/poi-detail'),
    )
    page.cards = [card]

    candidates = AmapPageAdapter(page, result_timeout=0.2, poll_interval=0).search_company(
        company_name='\u6df1\u5733\u793a\u4f8b\u79d1\u6280',
        city='\u6df1\u5733\u5e02',
    )

    candidate = candidates[0]
    assert candidate.address == '\u793a\u4f8b\u8def 1 \u53f7'
    assert candidate.telephone == '0755-12345678'
    assert candidate.category == '\u8f6f\u4ef6\u548c\u4fe1\u606f\u6280\u672f\u670d\u52a1'
    assert candidate.longitude == 113.93
    assert candidate.latitude == 22.53
    assert candidate.poi_id == 'poi-detail'
    assert candidate.source_url == 'https://www.amap.com/detail/poi-detail'
    assert page.url.startswith('https://www.amap.com/search')


def test_page_adapter_reads_phone_dom_after_detail_page_changes() -> None:
    page = FakePage(
        body_text='深圳市鸿艺源建筑室内设计有限公司\n沙河街道创意文化园',
        cards=[],
        detail_phone_text='0755-82793362  13689550791',
    )
    page.cards = [
        FakeLocator(
            text='深圳市鸿艺源建筑室内设计有限公司\n沙河街道创意文化园',
            on_click=lambda: page.show_detail(
                text='深圳市鸿艺源建筑室内设计有限公司\n详情页',
                url='https://www.amap.com/detail/B02F38U2X2',
            ),
        )
    ]

    candidates = AmapPageAdapter(
        page,
        result_timeout=0.2,
        detail_timeout=0.01,
        poll_interval=0,
    ).search_company(
        company_name='深圳市鸿艺源建筑室内设计有限公司',
        city='深圳市',
    )

    assert candidates[0].mobile == '13689550791'
    assert candidates[0].telephone is None


def test_page_adapter_holds_current_detail_panel_before_capture() -> None:
    page = FakePage(body_text='搜索结果', cards=[])
    page.cards = [
        FakeLocator(
            text='深圳甲设计有限公司\n地址：甲路 1 号\nPOI ID：poi-a',
            on_click=lambda: page.show_detail(
                text='深圳甲设计有限公司\n地址：甲路 1 号\n电话：13900139000',
                url='https://www.amap.com/place/poi-a',
            ),
        )
    ]

    candidates = AmapPageAdapter(
        page,
        result_timeout=0.2,
        detail_timeout=0.01,
        detail_settle_delay=0.8,
        return_settle_delay=0.4,
        poll_interval=0,
    ).search_company(
        company_name='深圳甲设计有限公司',
        city='深圳市',
    )

    assert candidates[0].mobile == '13900139000'
    assert 800 in page.wait_calls
    assert 400 in page.wait_calls


def test_page_adapter_rejects_phone_outside_current_detail_panel() -> None:
    page = FakePage(
        body_text='搜索结果',
        cards=[],
        hidden_phone_text='19926530442',
    )
    page.cards = [
        FakeLocator(
            text='深圳无电话设计有限公司\n地址：甲路 1 号\nPOI ID：poi-no-phone',
            on_click=lambda: page.show_detail(
                text='页面其他区域电话：19926530442\n深圳无电话设计有限公司\n地址：甲路 1 号',
                panel_text='深圳无电话设计有限公司\n地址：甲路 1 号',
                url='https://www.amap.com/place/poi-no-phone',
            ),
        )
    ]

    candidates = AmapPageAdapter(
        page,
        result_timeout=0.2,
        detail_timeout=0.01,
        poll_interval=0,
    ).search_company(
        company_name='深圳无电话设计有限公司',
        city='深圳市',
    )

    assert candidates[0].mobile is None


def test_page_adapter_does_not_copy_global_phone_across_result_cards() -> None:
    page = FakePage(
        body_text='深圳甲设计有限公司\n深圳乙设计有限公司\n搜索结果',
        cards=[
            FakeLocator(text='深圳甲设计有限公司\n地址：甲路 1 号', on_click=lambda: None),
            FakeLocator(text='深圳乙设计有限公司\n地址：乙路 1 号', on_click=lambda: None),
        ],
        hidden_phone_text='13689550791',
    )

    candidates = AmapPageAdapter(
        page,
        result_timeout=0.2,
        detail_timeout=0.01,
        poll_interval=0,
    ).search_company(
        company_name='深圳设计公司',
        city='深圳市',
    )

    assert candidates == []


def test_page_adapter_rejects_global_phone_after_search_page_text_only_change() -> None:
    page = FakePage(
        body_text='深圳甲设计有限公司\n深圳乙设计有限公司\n搜索结果',
        cards=[],
        hidden_phone_text='13689550791',
    )
    page.cards = [
        FakeLocator(
            text='深圳甲设计有限公司\n地址：甲路 1 号',
            on_click=lambda: page.show_detail(
                text='深圳甲设计有限公司\n深圳乙设计有限公司\n已选择甲公司',
                url='https://www.amap.com/search?query=深圳设计公司',
            ),
        ),
        FakeLocator(
            text='深圳乙设计有限公司\n地址：乙路 1 号',
            on_click=lambda: page.show_detail(
                text='深圳甲设计有限公司\n深圳乙设计有限公司\n已选择乙公司',
                url='https://www.amap.com/search?query=深圳设计公司',
            ),
        ),
    ]

    candidates = AmapPageAdapter(
        page,
        result_timeout=0.2,
        detail_timeout=0.01,
        poll_interval=0,
    ).search_company(company_name='深圳设计公司', city='深圳市')

    assert candidates == []


def test_exact_company_search_uses_detail_mobile_even_when_list_card_is_complete() -> None:
    page = FakePage(body_text='搜索结果', cards=[])
    page.cards = [
        FakeLocator(
            text=(
                '深圳甲设计有限公司\n地址：甲路 1 号\n电话：13800138000\n'
                '分类：室内设计\n坐标：113.93,22.53\nPOI ID：poi-甲'
            ),
            on_click=lambda: page.show_detail(
                text='深圳甲设计有限公司\n地址：详情路 2 号\n电话：13900139000',
                url='https://www.amap.com/place/poi-甲',
            ),
        )
    ]

    candidates = AmapPageAdapter(page, result_timeout=0.2, poll_interval=0).search_company(
        company_name='深圳甲设计有限公司',
        city='深圳市',
    )

    assert candidates[0].mobile == '13900139000'
    assert candidates[0].address == '详情路 2 号'


def test_exact_company_search_rejects_detail_url_for_another_poi() -> None:
    page = FakePage(body_text='搜索结果', cards=[])
    page.cards = [
        FakeLocator(
            text='深圳甲设计有限公司\n地址：甲路 1 号\nPOI ID：poi-a',
            on_click=lambda: page.show_detail(
                text='深圳甲设计有限公司\n地址：错误详情路 2 号\n电话：13900139000',
                url='https://www.amap.com/place/poi-b',
            ),
        )
    ]

    candidates = AmapPageAdapter(page, result_timeout=0.2, poll_interval=0).search_company(
        company_name='深圳甲设计有限公司',
        city='深圳市',
    )

    assert candidates == []


def test_detail_merge_uses_actual_detail_city() -> None:
    candidate = parse_result_card_text(
        '深圳甲设计有限公司\n地址：深圳市南山区甲路 1 号',
        city='深圳市',
        source_url='https://www.amap.com/search?query=深圳甲设计有限公司',
    )
    detail = parse_result_card_text(
        '深圳甲设计有限公司\n地址：广州市天河区乙路 2 号',
        city='深圳市',
        source_url='https://www.amap.com/place/poi-cross-city',
        company_name_hint='深圳甲设计有限公司',
    )

    merged = merge_detail_candidate(candidate, detail)

    assert merged.city == '广州市'


def test_parse_result_card_text_keeps_landline_out_of_mobile() -> None:
    candidate = parse_result_card_text(
        '深圳座机设计有限公司\n电话：0755-82793362',
        city='深圳市',
        source_url='https://www.amap.com/place/landline-only',
    )

    assert candidate.mobile is None
    assert candidate.telephone == '0755-82793362'


def test_page_adapter_drops_list_candidate_when_detail_click_times_out() -> None:
    def fail_click() -> None:
        raise RuntimeError('Locator.click: Timeout 3000ms exceeded')

    page = FakePage(
        body_text='搜索结果',
        cards=[
            FakeLocator(
                text='深圳示例科技有限公司\n地址：示例路 1 号',
                on_click=fail_click,
            )
        ],
    )

    candidates = AmapPageAdapter(page, result_timeout=0.2, poll_interval=0).search_company(
        company_name='深圳示例科技',
        city='深圳市',
    )

    assert candidates == []


def test_page_adapter_reads_poiinfo_attributes_from_compact_result_cards() -> None:
    page = FakePage(
        body_text='搜索结果',
        cards=[
            FakeLocator(
                text='…',
                attrs={
                    'id': 'B0FFFDNUNN',
                    'href': 'https://www.amap.com/place/B0FFFDNUNN',
                    'data-poiinfo-name': '深圳示例科技有限公司',
                    'data-poiinfo-address': '南山科技园 1 号',
                    'data-poiinfo-x': '113.9300',
                    'data-poiinfo-y': '22.5300',
                },
            )
        ],
    )

    candidates = AmapPageAdapter(page, result_timeout=0.2, poll_interval=0).search_keyword(
        keyword='深圳示例科技',
        city='深圳市',
    )

    assert candidates[0].company_name == '深圳示例科技有限公司'
    assert candidates[0].address == '南山科技园 1 号'
    assert candidates[0].longitude == 113.93
    assert candidates[0].latitude == 22.53
    assert candidates[0].poi_id == 'B0FFFDNUNN'


def test_page_adapter_limits_detail_attempts_to_keep_search_bounded() -> None:
    click_count = 0

    def fail_click() -> None:
        nonlocal click_count
        click_count += 1
        raise RuntimeError('detail click failed')

    page = FakePage(
        body_text='搜索结果',
        cards=[
            FakeLocator(text=f'深圳示例科技有限公司 {index}\n地址：示例路 {index} 号', on_click=fail_click)
            for index in range(3)
        ],
    )

    candidates = AmapPageAdapter(
        page,
        result_timeout=0.2,
        detail_timeout=0.01,
        poll_interval=0,
        max_detail_attempts=2,
    ).search_company(company_name='深圳示例科技', city='深圳市')

    assert candidates == []
    assert click_count == 2


def test_exact_company_search_prioritizes_exact_match_beyond_detail_cap() -> None:
    page = FakePage(body_text='搜索结果', cards=[])
    clicked: list[str] = []

    def show_detail(name: str, mobile: str, poi_id: str) -> None:
        clicked.append(name)
        page.show_detail(
            text=f'{name}\n地址：深圳市南山区示例路 1 号\n电话：{mobile}',
            url=f'https://www.amap.com/place/{poi_id}',
        )

    page.cards = [
        FakeLocator(
            text='深圳甲空间设计有限公司\n地址：甲路 1 号\nPOI ID：poi-a',
            on_click=lambda: show_detail(
                '深圳甲空间设计有限公司', '13800138000', 'poi-a'
            ),
        ),
        FakeLocator(
            text='深圳乙空间设计有限公司\n地址：乙路 1 号\nPOI ID：poi-b',
            on_click=lambda: show_detail(
                '深圳乙空间设计有限公司', '13900139000', 'poi-b'
            ),
        ),
        FakeLocator(
            text='深圳目标软装设计有限公司\n地址：目标路 1 号\nPOI ID：poi-target',
            on_click=lambda: show_detail(
                '深圳目标软装设计有限公司', '13700137000', 'poi-target'
            ),
        ),
    ]

    candidates = AmapPageAdapter(
        page,
        result_timeout=0.2,
        detail_timeout=0.01,
        poll_interval=0,
        max_detail_attempts=2,
    ).search_company(
        company_name='深圳目标软装设计有限公司',
        city='深圳市',
    )

    assert clicked[0] == '深圳目标软装设计有限公司'
    assert candidates[0].company_name == '深圳目标软装设计有限公司'
    assert candidates[0].mobile == '13700137000'


def test_page_adapter_does_not_mask_real_locator_errors_with_page_inner_text_fallback() -> None:
    class BrokenLocatorPage:
        def locator(self, selector: str):
            assert selector == 'body'
            raise RuntimeError('execution context was destroyed')

        def inner_text(self, selector: str) -> str:
            return selector

    with pytest.raises(RuntimeError, match='execution context was destroyed'):
        AmapPageAdapter(BrokenLocatorPage())._visible_text(BrokenLocatorPage())
