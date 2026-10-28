from __future__ import annotations

import socket
import threading
import time
from types import SimpleNamespace

import pytest
from backend.app.browser.actor import BrowserActor, BrowserCommandTimeout
from backend.app.browser.lifecycle import (
    BrowserDisconnected,
    BrowserPortInUse,
    BrowserState,
    DedicatedBrowser,
    detect_pause_state,
)


def make_browser(*, port: int, **kwargs) -> DedicatedBrowser:
    port_open = False

    def probe(_port: int) -> bool:
        return port_open

    def launch(_port: int, _profile) -> object:
        nonlocal port_open
        port_open = True
        return object()

    return DedicatedBrowser(
        port=port,
        port_probe=probe,
        launcher=launch,
        connector=lambda _endpoint: object(),
        **kwargs,
    )


def test_port_collision_is_rejected_before_launch() -> None:
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    sock.listen(1)
    port = sock.getsockname()[1]
    try:
        browser = DedicatedBrowser(port=port, launcher=lambda *_: pytest.fail('must not launch'))
        with pytest.raises(BrowserPortInUse):
            browser.start()
        assert browser.state == BrowserState.FAILED
    finally:
        sock.close()


def test_existing_cdp_browser_is_reused_after_backend_restart() -> None:
    connected_endpoints: list[str] = []
    browser = DedicatedBrowser(
        port=49993,
        port_probe=lambda _port: True,
        launcher=lambda *_: pytest.fail('must reuse the existing browser'),
        connector=lambda endpoint: connected_endpoints.append(endpoint) or object(),
    )

    browser.start()

    try:
        assert browser.state == BrowserState.READY
        assert connected_endpoints == ['http://127.0.0.1:49993']
    finally:
        browser.close()


def test_existing_cdp_connection_is_created_on_browser_actor_thread() -> None:
    main_thread = threading.get_ident()
    connector_threads: list[int] = []
    browser = DedicatedBrowser(
        port=49994,
        port_probe=lambda _port: True,
        launcher=lambda *_: pytest.fail('must reuse the existing browser'),
        connector=lambda endpoint: connector_threads.append(threading.get_ident()) or object(),
    )

    browser.start()

    try:
        assert connector_threads
        assert connector_threads[0] != main_thread
    finally:
        browser.close()


def test_start_waits_for_context_after_cdp_connects() -> None:
    page = object()

    class DelayedContextConnection:
        checks = 0

        @property
        def contexts(self):
            self.checks += 1
            if self.checks < 2:
                return []
            return [SimpleNamespace(pages=[page])]

    browser = DedicatedBrowser(
        port=49995,
        startup_timeout=0.2,
        port_probe=lambda _port: True,
        launcher=lambda *_: pytest.fail('must reuse the existing browser'),
        connector=lambda _endpoint: DelayedContextConnection(),
    )

    browser.start()

    try:
        assert browser.page() is page
    finally:
        browser.close()


def test_pause_state_detects_login_and_challenge() -> None:
    assert detect_pause_state('请登录高德地图后继续') == BrowserState.WAITING_FOR_LOGIN
    assert detect_pause_state('请完成安全验证：拖动滑块') == BrowserState.WAITING_FOR_CHALLENGE
    assert detect_pause_state('搜索结果 3 条') is None


def test_actor_converts_command_timeout() -> None:
    browser = make_browser(port=49991)
    browser.start()
    try:
        with pytest.raises(BrowserCommandTimeout):
            browser.run(lambda: time.sleep(0.05), timeout=0.005)
    finally:
        browser.close()


def test_actor_drops_timed_out_worker_before_accepting_next_command() -> None:
    actor = BrowserActor()
    try:
        with pytest.raises(BrowserCommandTimeout):
            actor.submit(lambda: time.sleep(1.0), timeout=0.005)

        assert actor.submit(lambda: 'next', timeout=0.2) == 'next'
    finally:
        actor.close()


def test_disconnected_command_reconnects_once() -> None:
    reconnects: list[str] = []
    browser = make_browser(port=49992, reconnecter=lambda: reconnects.append('reconnected'))
    browser.start()
    attempts = 0

    def command() -> str:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise BrowserDisconnected('connection lost')
        return 'ok'

    try:
        assert browser.run_with_reconnect(command) == 'ok'
    finally:
        browser.close()

    assert attempts == 2
    assert reconnects == ['reconnected']
    assert browser.reconnect_count == 1


def test_missing_context_reconnects_before_running_command() -> None:
    page = object()

    class ContextDisappearsAfterStartup:
        checks = 0

        @property
        def contexts(self):
            self.checks += 1
            if self.checks <= 2:
                return [SimpleNamespace(pages=[page])]
            return []

    connections = [
        ContextDisappearsAfterStartup(),
        SimpleNamespace(contexts=[SimpleNamespace(pages=[page])]),
    ]
    browser = DedicatedBrowser(
        port=49990,
        startup_timeout=0.1,
        port_probe=lambda _port: True,
        launcher=lambda *_: pytest.fail('must reuse the existing browser'),
        connector=lambda _endpoint: connections.pop(0),
    )
    browser.start()

    try:
        assert browser.run_with_reconnect(browser.page) is page
    finally:
        browser.close()

    assert browser.reconnect_count == 1


def test_refresh_connection_keeps_the_dedicated_chrome_process_alive() -> None:
    class FakeProcess:
        terminate_count = 0

        def poll(self):
            return None

        def terminate(self) -> None:
            self.terminate_count += 1

    page = object()
    connection = SimpleNamespace(contexts=[SimpleNamespace(pages=[page])], close=lambda: None)
    browser = DedicatedBrowser(
        port=49994,
        port_probe=lambda _port: True,
        connector=lambda _endpoint: connection,
    )
    process = FakeProcess()
    browser._process = process
    browser._connection = connection
    browser.state = BrowserState.READY

    try:
        browser.refresh_connection()
        refreshed_state = browser.state
    finally:
        browser._process = None
        browser.close()

    assert process.terminate_count == 0
    assert refreshed_state == BrowserState.READY
