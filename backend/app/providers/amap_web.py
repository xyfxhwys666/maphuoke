from __future__ import annotations

import random
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse

from backend.app.browser.actor import BrowserCommandTimeout
from backend.app.browser.lifecycle import (
    BrowserDisconnected,
    BrowserPaused,
    BrowserState,
    ChallengeRequired,
    DedicatedBrowser,
    detect_pause_state,
)
from backend.app.domain.models import MapPoiCandidate
from backend.app.domain.normalization import normalize_company_name
from backend.app.providers.amap_selectors import (
    extract_visible_candidate_cards,
    find_detail_link,
    find_result_cards,
    find_search_input,
    merge_detail_candidate,
    parse_result_card_text,
)
from backend.app.providers.map_evidence import attach_map_snapshot


class AmapPageAdapter:
    """Translate visible Amap page operations into provider-neutral values."""

    def __init__(
        self,
        page: Any,
        *,
        result_timeout: float = 8.0,
        detail_timeout: float = 3.0,
        detail_settle_delay: float = 0.8,
        return_settle_delay: float = 0.8,
        poll_interval: float = 0.2,
        max_detail_attempts: int = 2,
    ) -> None:
        self.page = page
        self.result_timeout = result_timeout
        self.detail_timeout = detail_timeout
        self.detail_settle_delay = max(detail_settle_delay, 0)
        self.return_settle_delay = max(return_settle_delay, 0)
        self.poll_interval = poll_interval
        self.max_detail_attempts = max(max_detail_attempts, 0)

    def search_company(self, *, company_name: str, city: str, max_results: int = 5) -> list[MapPoiCandidate]:
        return self._search(
            query=company_name,
            city=city,
            max_results=max_results,
            require_detail=True,
        )

    def search_keyword(self, *, keyword: str, city: str, max_results: int = 20) -> list[MapPoiCandidate]:
        return self._search(
            query=keyword,
            city=city,
            max_results=max_results,
            require_detail=False,
        )

    def _search(
        self,
        *,
        query: str,
        city: str,
        max_results: int,
        require_detail: bool,
    ) -> list[MapPoiCandidate]:
        self._ensure_accessible()
        search_input = find_search_input(self.page)
        search_input.fill(f'{city} {query}')
        search_input.press('Enter')
        self._wait_for_results()
        candidates = extract_visible_candidate_cards(
            self.page,
            city=city,
            company_name=query,
            max_results=max_results,
        )
        if require_detail:
            expected_name = normalize_company_name(query)
            candidates.sort(
                key=lambda item: (
                    normalize_company_name(item[0].company_name) != expected_name
                )
            )
        enriched_candidates: list[MapPoiCandidate] = []
        detail_attempts = 0
        for candidate, card in candidates:
            if not require_detail:
                enriched_candidates.append(candidate)
                continue
            if detail_attempts >= self.max_detail_attempts:
                continue
            detail_attempts += 1
            detail = self._extract_detail(candidate, card, city=city)
            if detail is not None:
                enriched_candidates.append(detail)
        return [attach_map_snapshot(candidate) for candidate in enriched_candidates]

    def _wait_for_results(self) -> Any | None:
        deadline = time.monotonic() + max(self.result_timeout, 0)
        while True:
            self._ensure_accessible()
            cards = find_result_cards(self.page)
            if cards is not None:
                return cards
            if self._is_empty_result():
                return None
            if time.monotonic() >= deadline:
                self._ensure_accessible()
                raise TimeoutError('Amap search results did not load before the timeout')
            self._wait(self.poll_interval)

    def _extract_detail(
        self,
        candidate: MapPoiCandidate,
        card: Any,
        *,
        city: str,
    ) -> MapPoiCandidate | None:
        try:
            return self._extract_detail_from_page(candidate, card, city=city)
        except (BrowserPaused, BrowserDisconnected):
            raise
        except Exception:  # noqa: BLE001 - one detail-card failure must not abort the search
            return None

    def _extract_detail_from_page(
        self,
        candidate: MapPoiCandidate,
        card: Any,
        *,
        city: str,
    ) -> MapPoiCandidate | None:
        detail_url = find_detail_link(card)
        if detail_url:
            detail = self._extract_from_new_page(detail_url, candidate, city=city)
            if detail is not None:
                return merge_detail_candidate(candidate, detail)

        # Playwright locators do not expose an on_click attribute; the check keeps
        # lightweight page fixtures from treating a no-op fake click as navigation.
        if hasattr(card, 'on_click') and card.on_click is None:
            return None
        click = getattr(card, 'click', None)
        if not callable(click):
            return None

        before_url = getattr(self.page, 'url', None)
        before_text = self._detail_panel_text(self.page)
        try:
            try:
                click(timeout=max(int(self.detail_timeout * 1000), 1))
            except TypeError:
                click()
            detail_text = self._wait_for_detail_text(
                before_url=before_url,
                before_text=before_text,
                company_name=candidate.company_name,
            )
            if detail_text is None:
                return None
            self._wait(self.detail_settle_delay)
            detail_text = self._detail_panel_text(self.page)
            current_url = getattr(self.page, 'url', None)
            if (
                not self._is_detail_url(current_url)
                or not self._detail_url_matches_candidate(current_url, candidate)
                or not self._detail_matches_candidate(detail_text, candidate.company_name)
            ):
                return None
            phone_text = self._page_phone_text(self.page)
            if phone_text:
                detail_text = f'{detail_text}\n电话：{phone_text}'
            detail = parse_result_card_text(
                detail_text,
                city=city,
                source_url=getattr(self.page, 'url', None),
                company_name_hint=candidate.company_name,
            )
            return merge_detail_candidate(candidate, detail)
        finally:
            current_url = getattr(self.page, 'url', None)
            if (current_url != before_url or self._detail_panel_text(self.page) != before_text) and hasattr(self.page, 'go_back'):
                try:
                    self.page.go_back(wait_until='domcontentloaded')
                except TypeError:
                    self.page.go_back()
                self._wait(self.return_settle_delay)

    def _extract_from_new_page(
        self,
        detail_url: str,
        candidate: MapPoiCandidate,
        *,
        city: str,
    ) -> MapPoiCandidate | None:
        context = getattr(self.page, 'context', None)
        new_page = getattr(context, 'new_page', None)
        if not callable(new_page):
            return None
        detail_page = new_page()
        try:
            target_url = urljoin(getattr(self.page, 'url', '') or '', detail_url)
            goto = getattr(detail_page, 'goto', None)
            if not callable(goto):
                return None
            try:
                goto(target_url, wait_until='domcontentloaded')
            except TypeError:
                goto(target_url)
            detail_text = self._wait_for_page_text(
                detail_page,
                company_name=candidate.company_name,
            )
            if detail_text is None:
                return None
            self._wait(self.detail_settle_delay, page=detail_page)
            detail_text = self._detail_panel_text(detail_page)
            current_url = getattr(detail_page, 'url', None) or target_url
            if (
                not self._is_detail_url(current_url)
                or not self._detail_url_matches_candidate(current_url, candidate)
                or not self._detail_matches_candidate(detail_text, candidate.company_name)
            ):
                return None
            phone_text = self._page_phone_text(detail_page)
            if phone_text:
                detail_text = f'{detail_text}\n电话：{phone_text}'
            return parse_result_card_text(
                detail_text,
                city=city,
                source_url=getattr(detail_page, 'url', None) or target_url,
                company_name_hint=candidate.company_name,
            )
        finally:
            close = getattr(detail_page, 'close', None)
            if callable(close):
                close()
            self._wait(self.return_settle_delay)

    def _wait_for_detail_text(
        self,
        *,
        before_url: str | None,
        before_text: str,
        company_name: str,
    ) -> str | None:
        deadline = time.monotonic() + max(self.detail_timeout, 0)
        while True:
            self._ensure_accessible()
            text = self._detail_panel_text(self.page)
            current_url = getattr(self.page, 'url', None)
            if (
                text.strip()
                and (current_url != before_url or text != before_text)
                and self._is_detail_url(current_url)
                and self._detail_matches_candidate(text, company_name)
            ):
                return text
            if time.monotonic() >= deadline:
                self._ensure_accessible()
                return None
            self._wait(self.poll_interval)

    def _wait_for_page_text(
        self,
        page: Any,
        *,
        company_name: str | None = None,
    ) -> str | None:
        deadline = time.monotonic() + max(self.detail_timeout, 0)
        while True:
            self._ensure_accessible(page)
            text = self._detail_panel_text(page)
            if text.strip() and (
                company_name is None
                or self._detail_matches_candidate(text, company_name)
            ):
                return text
            if time.monotonic() >= deadline:
                self._ensure_accessible(page)
                return None
            self._wait(self.poll_interval, page=page)

    @staticmethod
    def _page_phone_text(page: Any) -> str | None:
        locator_method = getattr(page, 'locator', None)
        if not callable(locator_method):
            return None
        for selector in (
            '.place-panel .placeinfo .feedphone',
            '.place-panel .placeinfo [class*="phone"]',
            '.place-panel .placeinfo [class*="telephone"]',
        ):
            try:
                locator = locator_method(selector)
                if not locator.count():
                    continue
                text = locator.first.inner_text().strip()
            except (AttributeError, TypeError):
                continue
            if text:
                return text
        return None

    @staticmethod
    def _detail_panel_text(page: Any) -> str:
        locator_method = getattr(page, 'locator', None)
        if not callable(locator_method):
            return ''
        try:
            panel = locator_method('.place-panel')
            if not panel.count():
                return ''
            return panel.first.inner_text()
        except (AttributeError, TypeError):
            return ''

    @staticmethod
    def _is_detail_url(url: str | None) -> bool:
        path = urlparse(url or '').path.casefold()
        return any(segment in path for segment in ('/place/', '/detail/', '/marker'))

    @staticmethod
    def _detail_url_matches_candidate(
        url: str | None,
        candidate: MapPoiCandidate,
    ) -> bool:
        if not candidate.poi_id:
            return True
        parsed = urlparse(url or '')
        path_parts = [part for part in parsed.path.split('/') if part]
        detail_id = path_parts[-1] if len(path_parts) > 1 else None
        if not detail_id or detail_id.casefold() in {'place', 'detail', 'marker'}:
            query = parse_qs(parsed.query)
            detail_id = next(
                (query[key][0] for key in ('pid', 'poi_id', 'id') if query.get(key)),
                None,
            )
        return bool(detail_id and detail_id.casefold() == candidate.poi_id.casefold())

    @staticmethod
    def _detail_matches_candidate(text: str, company_name: str) -> bool:
        expected = normalize_company_name(company_name)
        actual_text = normalize_company_name(text)
        return bool(expected and actual_text and expected.casefold() in actual_text.casefold())

    def _is_empty_result(self) -> bool:
        visible_text = self._visible_text(self.page)
        return any(marker in visible_text for marker in ('\u65e0\u641c\u7d22\u7ed3\u679c', '\u672a\u627e\u5230\u76f8\u5173', '\u6ca1\u6709\u627e\u5230', '\u6682\u65e0\u641c\u7d22\u7ed3\u679c'))

    def _wait(self, delay: float, *, page: Any | None = None) -> None:
        target = page or self.page
        wait_for_timeout = getattr(target, 'wait_for_timeout', None)
        if callable(wait_for_timeout):
            wait_for_timeout(max(int(delay * 1000), 0))
        elif delay > 0:
            time.sleep(delay)

    def _ensure_accessible(self, page: Any | None = None) -> None:
        target = page or self.page
        pause_state = detect_pause_state(self._pause_diagnostic_text(target))
        if pause_state == BrowserState.WAITING_FOR_LOGIN:
            from backend.app.browser.lifecycle import LoginRequired

            raise LoginRequired()
        if pause_state == BrowserState.WAITING_FOR_CHALLENGE:
            raise ChallengeRequired()

    def _pause_diagnostic_text(self, page: Any) -> str:
        parts = [self._visible_text(page), str(getattr(page, 'url', '') or '')]
        title = getattr(page, 'title', None)
        if callable(title):
            try:
                parts.append(str(title() or ''))
            except (AttributeError, TypeError):
                pass
        return '\n'.join(parts)

    @staticmethod
    def _visible_text(page: Any) -> str:
        locator = getattr(page, 'locator', None)
        if callable(locator):
            return locator('body').inner_text()
        return page.inner_text()


class AmapWebProvider:
    id = 'amap_web'
    label = '高德地图网页'

    def __init__(
        self,
        *,
        browser: DedicatedBrowser | Any,
        max_results: int = 5,
        command_timeout: float = 30.0,
        failure_threshold: int = 3,
        suspicious_failure_threshold: int = 2,
        map_url: str = 'https://www.amap.com/',
        search_delay_range: tuple[float, float] = (5.0, 9.0),
        detail_settle_range: tuple[float, float] = (3.0, 6.0),
        return_settle_range: tuple[float, float] = (3.0, 6.0),
        batch_size: int = 4,
        batch_cooldown_range: tuple[float, float] = (60.0, 120.0),
        connection_refresh_interval: int = 4,
        delay_sampler: Callable[[float, float], float] = random.uniform,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.browser = browser
        self.max_results = max_results
        self.command_timeout = command_timeout
        self.failure_threshold = failure_threshold
        self.suspicious_failure_threshold = max(suspicious_failure_threshold, 1)
        self.map_url = map_url
        self.search_delay_range = search_delay_range
        self.detail_settle_range = detail_settle_range
        self.return_settle_range = return_settle_range
        self.batch_size = max(batch_size, 1)
        self.batch_cooldown_range = batch_cooldown_range
        self.connection_refresh_interval = max(connection_refresh_interval, 0)
        self.delay_sampler = delay_sampler
        self.sleep = sleep
        self.search_count = 0
        self.consecutive_failures = 0
        self.consecutive_suspicious_failures = 0
        self.last_state = BrowserState.STOPPED
        self.last_error: str | None = None

    @property
    def configured(self) -> bool:
        return self.browser is not None

    def search_company(self, *, company_name: str, city: str, max_results: int = 5) -> list[MapPoiCandidate]:
        return self._search(query=company_name, city=city, max_results=max_results, mode='company')

    def search_keyword(self, *, keyword: str, city: str, max_results: int = 20) -> list[MapPoiCandidate]:
        return self._search(query=keyword, city=city, max_results=max_results, mode='keyword')

    def _search(
        self,
        *,
        query: str,
        city: str,
        max_results: int,
        mode: str,
    ) -> list[MapPoiCandidate]:
        if (
            self.connection_refresh_interval
            and self.search_count
            and self.search_count % self.connection_refresh_interval == 0
            and hasattr(self.browser, 'refresh_connection')
        ):
            self.browser.refresh_connection()
        self._pace_search()
        limit = min(max_results, self.max_results)

        def operation(page: Any | None = None) -> list[MapPoiCandidate]:
            current_page = page if page is not None else self.browser.page()
            if hasattr(current_page, 'goto') and not self._is_amap_page(current_page):
                try:
                    current_page.goto(
                        self.map_url,
                        wait_until='domcontentloaded',
                        timeout=max(1, min(int(self.command_timeout * 1000), 10_000)),
                    )
                except TypeError:
                    current_page.goto(self.map_url)
            adapter = AmapPageAdapter(
                current_page,
                result_timeout=min(self.command_timeout, 8.0),
                detail_timeout=min(self.command_timeout, 3.0),
                detail_settle_delay=self._sample_delay(self.detail_settle_range),
                return_settle_delay=self._sample_delay(self.return_settle_range),
            )
            if mode == 'keyword':
                return adapter.search_keyword(keyword=query, city=city, max_results=limit)
            return adapter.search_company(company_name=query, city=city, max_results=limit)

        try:
            browser_state = getattr(self.browser, 'state', None)
            if browser_state == BrowserState.STOPPED and hasattr(self.browser, 'start'):
                self.browser.start()
            self.last_state = BrowserState.SEARCHING
            if hasattr(self.browser, 'run_with_reconnect'):
                candidates = self.browser.run_with_reconnect(operation, timeout=self.command_timeout)
            else:
                candidates = self.browser.run(operation, timeout=self.command_timeout)
            self.consecutive_failures = 0
            self.consecutive_suspicious_failures = 0
            self.last_error = None
            self.last_state = BrowserState.READY
            return candidates
        except BrowserPaused as exc:
            self.last_state = exc.state
            self.last_error = str(exc)
            raise
        except BrowserCommandTimeout as exc:
            self._record_failure(exc, BrowserState.FAILED)
            raise
        except BrowserDisconnected as exc:
            self._record_failure(exc, BrowserState.RECONNECTING)
            raise
        except TimeoutError as exc:
            self._record_suspicious_failure(exc)
            if self.consecutive_suspicious_failures >= self.suspicious_failure_threshold:
                challenge = ChallengeRequired(
                    '高德连续返回异常页面或搜索超时，请在专用 Chrome 中检查并完成人工验证'
                )
                self.last_state = challenge.state
                self.last_error = str(challenge)
                raise challenge from exc
            raise
        except Exception as exc:
            self._record_failure(exc, BrowserState.FAILED)
            raise

    def _pace_search(self) -> None:
        self.search_count += 1
        delay_range = (
            self.batch_cooldown_range
            if self.search_count % self.batch_size == 0
            else self.search_delay_range
        )
        delay = self._sample_delay(delay_range)
        if self.consecutive_suspicious_failures:
            delay *= min(self.consecutive_suspicious_failures + 1, 4)
        if delay > 0:
            self.sleep(delay)

    def _sample_delay(self, delay_range: tuple[float, float]) -> float:
        lower, upper = sorted(float(value) for value in delay_range)
        return max(float(self.delay_sampler(lower, upper)), 0.0)

    def _is_amap_page(self, page: Any) -> bool:
        current_url = str(getattr(page, 'url', '') or '')
        current_host = urlparse(current_url).hostname or ''
        map_host = urlparse(self.map_url).hostname or ''
        return bool(current_host and map_host and (
            current_host == map_host or current_host.endswith(f'.{map_host}')
        ))

    def _record_failure(self, error: Exception, state: BrowserState) -> None:
        self.consecutive_failures += 1
        self.last_state = state
        self.last_error = str(error)
        if self.consecutive_failures >= self.failure_threshold and hasattr(self.browser, 'state'):
            self.browser.state = BrowserState.FAILED

    def _record_suspicious_failure(self, error: Exception) -> None:
        self.consecutive_suspicious_failures += 1
        self._record_failure(error, BrowserState.FAILED)
