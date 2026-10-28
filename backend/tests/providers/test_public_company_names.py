import httpx
from backend.app.providers.public_web import PublicCompanyNameDiscoveryProvider


def test_public_web_discovery_extracts_real_company_names_and_source_evidence() -> None:
    html = '''
    <html><body>
      <li class="res-list">
        <h3><a href="https://www.zhilin.example/">深圳智林装饰软装设计工程有限公司</a></h3>
        <p>深圳智林装饰软装设计工程有限公司，提供住宅软装设计与全案服务，联系电话见官网。</p>
      </li>
      <li class="res-list">
        <h3><a href="https://www.example.com/rank">深圳软装公司推荐排行榜</a></h3>
        <p>深圳软装公司推荐，选择正规服务商。</p>
      </li>
      <li class="res-list">
        <h3><a href="https://www.example.com/question">深圳有什么好的软装设计公司</a></h3>
        <p>知乎问答：深圳有什么好的软装设计公司？</p>
      </li>
      <li class="res-list">
        <h3><a href="https://www.example.com/seo">一站式专业软装设计公司</a></h3>
        <p>一站式专业软装设计服务。</p>
      </li>
    </body></html>
    '''

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=html, request=request)

    provider = PublicCompanyNameDiscoveryProvider(
        client=httpx.Client(transport=httpx.MockTransport(handler))
    )

    candidates = provider.discover_company_names(
        city='深圳市',
        keyword='软装设计公司',
        request_text='找深圳软装设计公司',
        max_results=10,
    )

    assert [candidate.company_name for candidate in candidates] == [
        '深圳智林装饰软装设计工程有限公司'
    ]
    assert candidates[0].source_urls == ['https://www.zhilin.example/']
    assert '联系电话见官网' in candidates[0].evidence_quotes[0]


def test_public_web_discovery_reads_all_configured_pages() -> None:
    requested_pages: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get('page', '1'))
        requested_pages.append(page)
        company_name = (
            '深圳市甲境软装设计有限公司'
            if page == 1
            else '深圳市乙舍室内设计有限公司'
        )
        html = f'''
        <li class="res-list">
          <h3><a href="https://example.com/company-{page}">{company_name}</a></h3>
          <p>{company_name}，提供住宅软装设计与全案服务。</p>
        </li>
        '''
        return httpx.Response(200, text=html, request=request)

    provider = PublicCompanyNameDiscoveryProvider(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        max_search_pages=2,
    )

    candidates = provider.discover_company_names(
        city='深圳市',
        keyword='软装设计',
        request_text='找深圳软装设计公司',
        max_results=100,
    )

    assert set(requested_pages) == {1, 2}
    assert {candidate.company_name for candidate in candidates} == {
        '深圳市甲境软装设计有限公司',
        '深圳市乙舍室内设计有限公司',
    }
