from __future__ import annotations

import time
from threading import Lock
from typing import Any

from backend.app.browser.lifecycle import (
    BrowserState,
    ChallengeRequired,
    LoginRequired,
    detect_pause_state,
)
from backend.app.collection.models import RelevanceDecision
from backend.app.domain.models import MapPoiCandidate
from backend.app.providers.doubao_parser import (
    parse_contact_response,
    parse_intent_keyword_response,
    parse_relevance_response,
)
from backend.app.providers.doubao_prompt import (
    build_contact_prompt,
    build_intent_keyword_prompt,
    build_relevance_prompt,
)


class DoubaoWebGateway:
    id = 'doubao_web'

    def __init__(
        self,
        *,
        browser: Any,
        request_interval_seconds: float = 1.0,
        command_timeout: float = 60.0,
        chat_url: str = 'https://www.doubao.com/chat/',
    ) -> None:
        self.browser = browser
        self.request_interval_seconds = request_interval_seconds
        self.command_timeout = command_timeout
        self.chat_url = chat_url
        self._request_lock = Lock()
        self._last_request_at = 0.0
        self.last_state = BrowserState.STOPPED
        self.last_prompt: str | None = None

    @property
    def configured(self) -> bool:
        return self.browser is not None

    def enrich_company(
        self,
        *,
        company_name: str,
        city: str,
        requested_contacts: list[str],
        known_fields: dict[str, Any],
    ):
        prompt = build_contact_prompt(
            company_name=company_name,
            city=city,
            requested_contacts=requested_contacts,
            known_fields=known_fields,
        )
        self.last_prompt = prompt
        self._pace()

        def operation(page: Any | None = None) -> str:
            current_page = page if page is not None else self.browser.page()
            return self._ask_page(current_page, prompt)

        self._ensure_browser_started()
        self.last_state = BrowserState.SEARCHING
        if hasattr(self.browser, 'run_with_reconnect'):
            response = self.browser.run_with_reconnect(operation, timeout=self.command_timeout)
        else:
            response = self.browser.run(operation, timeout=self.command_timeout)
        enrichment = parse_contact_response(response, company_name=company_name)
        self.last_state = BrowserState.READY
        return enrichment

    def parse_intent_keywords(self, request_text: str) -> list[str]:
        prompt = build_intent_keyword_prompt(request_text=request_text)
        self.last_prompt = prompt
        self._pace()

        def operation(page: Any | None = None) -> str:
            current_page = page if page is not None else self.browser.page()
            return self._ask_page(current_page, prompt)

        self._ensure_browser_started()
        self.last_state = BrowserState.SEARCHING
        if hasattr(self.browser, 'run_with_reconnect'):
            response = self.browser.run_with_reconnect(operation, timeout=self.command_timeout)
        else:
            response = self.browser.run(operation, timeout=self.command_timeout)
        keywords = parse_intent_keyword_response(response)
        self.last_state = BrowserState.READY
        return keywords

    def judge_relevance(
        self,
        *,
        request_text: str,
        city: str,
        keyword: str,
        candidate: MapPoiCandidate,
    ) -> RelevanceDecision:
        prompt = build_relevance_prompt(
            request_text=request_text,
            city=city,
            keyword=keyword,
            candidate={
                'candidate_id': candidate.candidate_id,
                'company_name': candidate.company_name,
                'address': candidate.address,
                'category': candidate.category,
                'telephone': candidate.telephone,
                'source_url': candidate.source_url,
            },
        )
        self.last_prompt = prompt
        self._pace()

        def operation(page: Any | None = None) -> str:
            current_page = page if page is not None else self.browser.page()
            return self._ask_page(current_page, prompt)

        self._ensure_browser_started()
        self.last_state = BrowserState.SEARCHING
        if hasattr(self.browser, 'run_with_reconnect'):
            response = self.browser.run_with_reconnect(operation, timeout=self.command_timeout)
        else:
            response = self.browser.run(operation, timeout=self.command_timeout)
        decision = parse_relevance_response(
            response,
            candidate_id=candidate.candidate_id,
            model_id=self.id,
        )
        self.last_state = BrowserState.READY
        return decision

    def _ensure_browser_started(self) -> None:
        state = getattr(self.browser, 'state', None)
        start = getattr(self.browser, 'start', None)
        if state == BrowserState.STOPPED and callable(start):
            start()

    def _pace(self) -> None:
        with self._request_lock:
            wait_seconds = self.request_interval_seconds - (time.monotonic() - self._last_request_at)
            if wait_seconds > 0:
                time.sleep(wait_seconds)
            self._last_request_at = time.monotonic()

    def _ask_page(self, page: Any, prompt: str) -> str:
        if hasattr(page, 'goto'):
            try:
                page.goto(self.chat_url, wait_until='domcontentloaded')
            except TypeError:
                page.goto(self.chat_url)
        visible_text = self._wait_for_page_text(page)
        pause_state = detect_pause_state(visible_text)
        if pause_state is None and self._is_login_home(visible_text):
            pause_state = BrowserState.WAITING_FOR_LOGIN
        if pause_state == BrowserState.WAITING_FOR_LOGIN:
            raise LoginRequired('Doubao login is required')
        if pause_state == BrowserState.WAITING_FOR_CHALLENGE:
            raise ChallengeRequired('Doubao security challenge requires manual handling')
        if hasattr(page, 'ask'):
            return str(page.ask(prompt))

        input_locator = self._find_input(page)
        input_locator.fill(prompt)
        input_locator.press('Enter')
        if hasattr(page, 'wait_for_timeout'):
            page.wait_for_timeout(800)
        for selector in ('[data-testid*="message"]', '[class*="message"]', '[class*="markdown"]'):
            locator = page.locator(selector)
            if locator.count():
                return str(locator.last.inner_text())
        raise LookupError('Doubao response message was not found')

    @staticmethod
    def _is_login_home(visible_text: str) -> bool:
        return all(marker in visible_text for marker in ('豆包', '新对话', '登录'))

    @staticmethod
    def _wait_for_page_text(page: Any, *, timeout_seconds: float = 3.0) -> str:
        deadline = time.monotonic() + max(timeout_seconds, 0)
        while True:
            visible_text = getattr(page, 'visible_text', None)
            if visible_text is None:
                try:
                    visible_text = page.locator('body').inner_text()
                except Exception:  # noqa: BLE001 - page fixtures may expose no body locator
                    visible_text = ''
            visible_text = str(visible_text)
            if detect_pause_state(visible_text) is not None or DoubaoWebGateway._is_login_home(visible_text):
                return visible_text
            wait_for_timeout = getattr(page, 'wait_for_timeout', None)
            if not callable(wait_for_timeout) or time.monotonic() >= deadline:
                return visible_text
            wait_for_timeout(100)

    @staticmethod
    def _find_input(page: Any) -> Any:
        for locator in (
            page.get_by_role('textbox'),
            page.locator('textarea'),
            page.locator('[contenteditable="true"]'),
        ):
            if locator.count():
                return locator.last
        raise LookupError('Doubao input was not found')
