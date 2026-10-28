from __future__ import annotations

import re
from html.parser import HTMLParser
from ipaddress import ip_address
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from backend.app.collection.models import CompanyNameCandidate
from backend.app.domain.models import EvidenceResult, EvidenceValue
from backend.app.domain.normalization import normalize_company_name, normalize_email, normalize_mobile

_COMPANY_NAME_PATTERN = re.compile(
    r'[\u4e00-\u9fffA-Za-z0-9（）()·]{2,60}?(?:有限责任公司|有限公司|工作室|设计院|事务所)'
)
_GENERIC_COMPANY_TITLE_TERMS = (
    '公司推荐',
    '推荐排行',
    '排行榜',
    '哪家好',
    '十大公司',
    '本地装修公司',
    '专业软装公司',
)


class _PublicSearchResultParser(HTMLParser):
    """Parse the stable result containers shared by major Chinese search pages."""

    def __init__(self) -> None:
        super().__init__()
        self.results: list[dict[str, str]] = []
        self._in_result = False
        self._result_tag = ''
        self._result_depth = 0
        self._in_heading = False
        self._href = ''
        self._title: list[str] = []
        self._snippet: list[str] = []
        self._ignored_tag: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._ignored_tag is not None:
            return
        if tag in {'script', 'style', 'noscript', 'svg', 'template'}:
            self._ignored_tag = tag
            return
        values = dict(attrs)
        classes = set((values.get('class') or '').split())
        if not self._in_result and tag in {'li', 'div'} and classes & {'b_algo', 'vrwrap', 'res-list'}:
            self._in_result = True
            self._result_tag = tag
            self._result_depth = 1
            self._href = ''
            self._title = []
            self._snippet = []
            return
        if not self._in_result:
            return
        if tag == self._result_tag:
            self._result_depth += 1
        if tag in {'h2', 'h3'}:
            self._in_heading = True
        elif self._in_heading and tag == 'a' and not self._href:
            self._href = values.get('href') or ''

    def handle_endtag(self, tag: str) -> None:
        if tag == self._ignored_tag:
            self._ignored_tag = None
            return
        if self._ignored_tag is not None or not self._in_result:
            return
        if tag in {'h2', 'h3'}:
            self._in_heading = False
        if tag != self._result_tag:
            return
        self._result_depth -= 1
        if self._result_depth != 0:
            return
        if self._href and self._title:
            self.results.append({
                'url': self._href,
                'title': ' '.join(self._title).strip(),
                'snippet': ' '.join(self._snippet).strip(),
            })
        self._in_result = False

    def handle_data(self, data: str) -> None:
        if self._ignored_tag is not None or not self._in_result:
            return
        value = data.strip()
        if value:
            (self._title if self._in_heading else self._snippet).append(value)


def _clean_company_name(title: str) -> str:
    cleaned = re.sub(r'\s+', '', title).strip(' -_|—–·')
    if any(term in cleaned for term in _GENERIC_COMPANY_TITLE_TERMS):
        return ''
    matches = _COMPANY_NAME_PATTERN.findall(cleaned)
    if not matches:
        return ''
    name = matches[-1]
    if name in {'装修公司', '软装公司', '设计公司', '整装公司'}:
        return ''
    return name


class PublicCompanyNameDiscoveryProvider:
    """Discover company names from public search results for exact map lookup."""

    id = 'public_web_company_names'
    label = '公开网页公司名称发现'
    configured = True

    def __init__(
        self,
        *,
        client: Any | None = None,
        search_url: str = 'https://www.sogou.com/web',
        max_search_pages: int = 1,
        request_interval_seconds: float = 0.0,
    ) -> None:
        self.client = client or httpx.Client(timeout=15.0, follow_redirects=True)
        self.search_url = search_url
        self.max_search_pages = max(max_search_pages, 1)
        self.request_interval_seconds = max(request_interval_seconds, 0.0)

    def discover_company_names(
        self,
        *,
        city: str,
        keyword: str,
        request_text: str,
        max_results: int,
    ) -> list[CompanyNameCandidate]:
        del request_text
        limit = max(max_results, 1)
        city_short = city.removesuffix('市')
        queries = (
            f'{city} {keyword} 公司 官网 联系方式',
            f'{city_short} {keyword} 手机',
            f'{city_short} {keyword} 联系我们',
        )
        sources = (
            (self.search_url, 'query'),
            ('https://www.so.com/s', 'q'),
            ('https://cn.bing.com/search', 'q'),
        )
        found: dict[tuple[str, str], CompanyNameCandidate] = {}
        successful_requests = 0
        for query in queries:
            for source_url, parameter in sources:
                for page in range(1, self.max_search_pages + 1):
                    params: dict[str, str | int] = {parameter: query}
                    if 'bing.com' in source_url:
                        params['first'] = (page - 1) * 10 + 1
                    elif 'so.com' in source_url:
                        params['pn'] = page
                    else:
                        params['page'] = page
                    try:
                        response = self.client.get(
                            source_url,
                            params=params,
                            headers={'User-Agent': 'Mozilla/5.0 (compatible; MapSearch/1.0)'},
                        )
                        response.raise_for_status()
                    except (httpx.HTTPError, OSError, ValueError):
                        continue
                    successful_requests += 1
                    parser = _PublicSearchResultParser()
                    parser.feed(response.text)
                    for result in parser.results:
                        company_name = _clean_company_name(result['title'])
                        if not company_name:
                            continue
                        evidence_text = f"{result['title']} {result['snippet']}"
                        keyword_core = keyword.removesuffix('公司')
                        if keyword_core and keyword_core not in evidence_text and not any(
                            term in evidence_text for term in ('软装', '设计', '装饰', '整装', '家居')
                        ):
                            continue
                        result_url = urljoin(str(response.url), result['url'])
                        parsed = urlparse(result_url)
                        if parsed.scheme not in {'http', 'https'} or not parsed.netloc:
                            continue
                        key = (city_short, company_name.casefold())
                        item = found.get(key)
                        quote = (result['snippet'] or result['title']).strip()[:300]
                        if item is None:
                            found[key] = CompanyNameCandidate(
                                company_name=company_name,
                                city=city,
                                matched_keyword=keyword,
                                source_urls=[result_url],
                                evidence_quotes=[quote] if quote else [],
                            )
                        else:
                            item.source_urls = list(dict.fromkeys([*item.source_urls, result_url]))
                            if quote:
                                item.evidence_quotes = list(dict.fromkeys([*item.evidence_quotes, quote]))
                        if len(found) >= limit:
                            break
                    if len(found) >= limit:
                        break
                if len(found) >= limit:
                    break
            if len(found) >= limit:
                break
        if successful_requests == 0:
            raise RuntimeError('public web company-name discovery failed')
        return list(found.values())[:limit]


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        value = data.strip()
        if value:
            self.parts.append(value)


class PublicEvidenceVerifier:
    _DEFAULT_SEARCH_ENDPOINTS = (
        ('https://www.sogou.com/web', 'query'),
        ('https://www.so.com/s', 'q'),
        ('https://cn.bing.com/search', 'q'),
    )

    def __init__(
        self,
        *,
        client: Any | None = None,
        timeout_seconds: float = 15.0,
        search_endpoints: tuple[tuple[str, str], ...] | None = None,
        max_discovered_urls: int = 5,
    ) -> None:
        self.client = client or httpx.Client(timeout=timeout_seconds, follow_redirects=True)
        self.timeout_seconds = timeout_seconds
        self.search_endpoints = search_endpoints or self._DEFAULT_SEARCH_ENDPOINTS
        self.max_discovered_urls = max(max_discovered_urls, 1)

    def verify_contact(
        self,
        *,
        company_name: str,
        mobile: str | None = None,
        email: str | None = None,
        source_urls: list[str] | None = None,
    ) -> EvidenceResult:
        expected_name = self._compact(company_name)
        expected_mobile = normalize_mobile(mobile)
        expected_email = normalize_email(email)
        urls = [url for url in dict.fromkeys(source_urls or []) if self._valid_url(url)]
        if not expected_name or not expected_mobile and not expected_email:
            return EvidenceResult(contact_verification_status='captured', source_urls=urls)
        verified = self._verify_urls(
            urls=urls,
            expected_name=expected_name,
            expected_mobile=expected_mobile,
            expected_email=expected_email,
        )
        if verified is not None:
            return verified
        discovered_urls = self._discover_evidence_urls(company_name)
        verified = self._verify_urls(
            urls=discovered_urls,
            expected_name=expected_name,
            expected_mobile=expected_mobile,
            expected_email=expected_email,
        )
        if verified is not None:
            return verified
        return EvidenceResult(
            company_name_verification_status='verified_map' if urls else None,
            contact_verification_status='captured',
            source_urls=urls,
            quotes=[],
        )

    def _verify_urls(
        self,
        *,
        urls: list[str],
        expected_name: str,
        expected_mobile: str | None,
        expected_email: str | None,
    ) -> EvidenceResult | None:
        for url in urls:
            try:
                response = self.client.get(
                    url,
                    headers={'User-Agent': 'Mozilla/5.0 (compatible; MapLeadPlatform/1.0)'},
                    timeout=self.timeout_seconds,
                )
                response.raise_for_status()
            except (httpx.HTTPError, OSError, ValueError):
                continue
            visible_text = self._visible_text(str(getattr(response, 'text', '')))
            compact_text = self._compact(visible_text)
            mobile_match = bool(expected_mobile and expected_mobile in ''.join(char for char in visible_text if char.isdigit()))
            email_match = bool(expected_email and expected_email in visible_text.casefold())
            if expected_name in compact_text and (mobile_match or email_match):
                quote = self._quote(visible_text, expected_mobile or expected_email or '')
                response_url = str(getattr(response, 'url', url))
                field_evidence = {}
                if mobile_match and expected_mobile:
                    field_evidence['mobile'] = EvidenceValue(
                        value=expected_mobile,
                        status='verified',
                        source_urls=[response_url],
                        quotes=[quote] if quote else [],
                    )
                if email_match and expected_email:
                    field_evidence['email'] = EvidenceValue(
                        value=expected_email,
                        status='verified',
                        source_urls=[response_url],
                        quotes=[quote] if quote else [],
                    )
                return EvidenceResult(
                    company_name_verification_status='verified_public_web',
                    contact_verification_status='verified_public_web',
                    source_urls=[response_url],
                    quotes=[quote] if quote else [],
                    field_evidence=field_evidence,
                    grade='A',
                    score=95,
                )
        return None

    def _discover_evidence_urls(self, company_name: str) -> list[str]:
        discovered: list[str] = []
        search_hosts = {urlparse(url).netloc.casefold() for url, _ in self.search_endpoints}
        for search_url, parameter in self.search_endpoints:
            try:
                response = self.client.get(
                    search_url,
                    params={parameter: f'{company_name} 联系方式'},
                    headers={'User-Agent': 'Mozilla/5.0 (compatible; MapLeadPlatform/1.0)'},
                    timeout=self.timeout_seconds,
                )
                response.raise_for_status()
            except (httpx.HTTPError, OSError, ValueError):
                continue
            parser = _PublicSearchResultParser()
            parser.feed(str(getattr(response, 'text', '')))
            for result in parser.results:
                candidate_url = urljoin(str(getattr(response, 'url', search_url)), result['url'])
                parsed = urlparse(candidate_url)
                if (
                    not self._valid_discovered_url(candidate_url)
                    or parsed.netloc.casefold() in search_hosts
                    or candidate_url in discovered
                ):
                    continue
                discovered.append(candidate_url)
                if len(discovered) >= self.max_discovered_urls:
                    return discovered
        return discovered

    @staticmethod
    def _visible_text(source: str) -> str:
        parser = _VisibleTextParser()
        parser.feed(source)
        return ' '.join(parser.parts) or re.sub(r'\s+', ' ', source)

    @staticmethod
    def _compact(value: str) -> str:
        normalized = normalize_company_name(value) or ''
        return re.sub(r'\s+', '', normalized).casefold()

    @staticmethod
    def _valid_url(value: str) -> bool:
        parsed = urlparse(value)
        return parsed.scheme in {'http', 'https'} and bool(parsed.netloc)

    @classmethod
    def _valid_discovered_url(cls, value: str) -> bool:
        if not cls._valid_url(value):
            return False
        host = urlparse(value).hostname
        if not host or host.casefold() == 'localhost' or host.casefold().endswith('.local'):
            return False
        try:
            address = ip_address(host)
        except ValueError:
            return True
        return not (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_multicast
            or address.is_reserved
            or address.is_unspecified
        )

    @staticmethod
    def _quote(text: str, token: str) -> str:
        for sentence in re.split(r'[。！？!?.\n]', text):
            if token and token in sentence.replace(' ', ''):
                return sentence.strip()
        return text[:300].strip()
