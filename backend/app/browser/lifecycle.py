from __future__ import annotations

import os
import shutil
import socket
import subprocess
import tempfile
import time
from collections.abc import Callable
from enum import Enum
from pathlib import Path

from backend.app.browser.actor import BrowserActor, BrowserCommandTimeout
from backend.app.providers.protocols import ProviderPaused


class BrowserState(str, Enum):
    STOPPED = 'stopped'
    STARTING = 'starting'
    READY = 'ready'
    SEARCHING = 'searching'
    DETAIL_LOADING = 'detail_loading'
    EXTRACTING = 'extracting'
    WAITING_FOR_LOGIN = 'waiting_for_login'
    WAITING_FOR_CHALLENGE = 'waiting_for_challenge'
    FAILED = 'failed'
    RECONNECTING = 'reconnecting'


class BrowserError(RuntimeError):
    pass


class BrowserPortInUse(BrowserError):
    pass


class BrowserUnavailable(BrowserError):
    pass


class BrowserDisconnected(BrowserError):
    pass


class BrowserPaused(ProviderPaused, BrowserError):
    def __init__(self, message: str, *, state: BrowserState) -> None:
        ProviderPaused.__init__(self, message, task_status=state.value, browser_state=state.value)
        self.state = state


class LoginRequired(BrowserPaused):
    def __init__(self, message: str = 'Amap login is required') -> None:
        super().__init__(message, state=BrowserState.WAITING_FOR_LOGIN)


class ChallengeRequired(BrowserPaused):
    def __init__(self, message: str = 'Amap security challenge requires manual handling') -> None:
        super().__init__(message, state=BrowserState.WAITING_FOR_CHALLENGE)


def detect_pause_state(visible_text: str) -> BrowserState | None:
    normalized_text = visible_text.casefold()
    challenge_markers = (
        '验证码',
        '安全验证',
        '人机验证',
        '拖动滑块',
        '滑块验证',
        '访问异常',
        '请完成验证',
        'captcha',
        'challenge',
        'slider',
        '/verify',
    )
    if any(marker in normalized_text for marker in challenge_markers):
        return BrowserState.WAITING_FOR_CHALLENGE
    login_markers = ('请登录', '登录后继续', '手机号登录', '账号登录', '登录高德')
    if any(marker in visible_text for marker in login_markers):
        return BrowserState.WAITING_FOR_LOGIN
    return None


def _is_port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        return sock.connect_ex(('127.0.0.1', port)) == 0


def _find_chrome() -> str:
    configured = os.getenv('MAPSEARCH_CHROME_PATH')
    candidates = [
        configured,
        shutil.which('chrome'),
        shutil.which('chrome.exe'),
        os.path.join(os.getenv('PROGRAMFILES', ''), 'Google', 'Chrome', 'Application', 'chrome.exe'),
        os.path.join(os.getenv('PROGRAMFILES(X86)', ''), 'Google', 'Chrome', 'Application', 'chrome.exe'),
        os.path.join(os.getenv('LOCALAPPDATA', ''), 'Google', 'Chrome', 'Application', 'chrome.exe'),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    raise BrowserUnavailable('Chrome executable was not found; set MAPSEARCH_CHROME_PATH')


class DedicatedBrowser:
    def __init__(
        self,
        *,
        port: int = 9227,
        user_data_dir: Path | str | None = None,
        chrome_path: str | None = None,
        startup_timeout: float = 15.0,
        command_timeout: float = 30.0,
        port_probe: Callable[[int], bool] | None = None,
        launcher: Callable[[int, Path], object] | None = None,
        connector: Callable[[str], object] | None = None,
        reconnecter: Callable[[], None] | None = None,
    ) -> None:
        self.port = port
        self.user_data_dir = Path(user_data_dir or Path(tempfile.gettempdir()) / 'map-lead-platform' / 'chrome-profile')
        self.chrome_path = chrome_path
        self.startup_timeout = startup_timeout
        self.command_timeout = command_timeout
        self._port_probe = port_probe or _is_port_open
        self._launcher = launcher or self._launch_chrome
        self._connector = connector or self._connect_over_cdp
        self._reconnecter = reconnecter
        self._actor = BrowserActor()
        self._connection: object | None = None
        self._process: subprocess.Popen[bytes] | None = None
        self._playwright: object | None = None
        self._closed = False
        self.state = BrowserState.STOPPED
        self.reconnect_count = 0

    def start(self) -> None:
        if self.state == BrowserState.READY:
            return
        if self._port_probe(self.port):
            try:
                self._actor.submit(self._connect_existing, timeout=self.startup_timeout)
            except Exception as exc:
                self.state = BrowserState.FAILED
                raise BrowserPortInUse(f'CDP port {self.port} is already in use') from exc
            self.state = BrowserState.READY
            return
        self.state = BrowserState.STARTING
        try:
            self.user_data_dir.mkdir(parents=True, exist_ok=True)
            self._actor.submit(self._start_internal, timeout=self.startup_timeout)
            self.state = BrowserState.READY
        except BrowserCommandTimeout:
            self.state = BrowserState.FAILED
            raise
        except Exception:
            self.state = BrowserState.FAILED
            raise

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            if self.state != BrowserState.STOPPED:
                self._actor.submit(self._close_internal, timeout=5)
        except (BrowserCommandTimeout, RuntimeError):
            pass
        self._actor.close()
        self.state = BrowserState.STOPPED

    def run(self, function: Callable[[], object], *, timeout: float | None = None):
        if self.state not in {
            BrowserState.READY,
            BrowserState.SEARCHING,
            BrowserState.DETAIL_LOADING,
            BrowserState.EXTRACTING,
        }:
            raise BrowserError(f'browser is not ready: {self.state.value}')
        return self._actor.submit(function, timeout=timeout or self.command_timeout)

    def run_with_reconnect(self, function: Callable[[], object], *, timeout: float | None = None):
        try:
            return self.run(function, timeout=timeout)
        except BrowserDisconnected:
            self.reconnect()
            return self.run(function, timeout=timeout)

    def open_url(self, url: str) -> None:
        if self.state == BrowserState.STOPPED:
            self.start()

        def navigate() -> None:
            page = self.page()
            page.goto(url, wait_until='domcontentloaded', timeout=int(self.command_timeout * 1000))

        self.run_with_reconnect(navigate)

    def reconnect(self) -> None:
        self.state = BrowserState.RECONNECTING
        try:
            if self._reconnecter is not None:
                self._actor.submit(self._reconnecter, timeout=self.command_timeout)
            else:
                self._actor.submit(self._close_internal, timeout=5)
                reconnect = (
                    self._connect_existing
                    if self._port_probe(self.port)
                    else self._start_internal
                )
                self._actor.submit(reconnect, timeout=self.startup_timeout)
            self.reconnect_count += 1
            self.state = BrowserState.READY
        except Exception:
            self.state = BrowserState.FAILED
            raise

    def refresh_connection(self) -> None:
        """Refresh the Playwright/CDP session without stopping dedicated Chrome."""
        self.state = BrowserState.RECONNECTING
        try:
            self._actor.submit(self._refresh_connection_internal, timeout=self.startup_timeout)
            self.reconnect_count += 1
            self.state = BrowserState.READY
        except Exception:
            self.state = BrowserState.FAILED
            raise

    def page(self):
        if self._connection is None:
            raise BrowserDisconnected('browser connection is not available')
        contexts = getattr(self._connection, 'contexts', None)
        if not contexts:
            raise BrowserDisconnected('browser has no context')
        context = contexts[0]
        pages = getattr(context, 'pages', None) or []
        return pages[0] if pages else context.new_page()

    def _start_internal(self) -> None:
        self._process = self._launcher(self.port, self.user_data_dir)  # type: ignore[assignment]
        if self._port_probe(self.port):
            self._connection = self._connector(f'http://127.0.0.1:{self.port}')
            self._wait_for_context()
            return
        deadline = time.monotonic() + self.startup_timeout
        while time.monotonic() < deadline:
            if self._port_probe(self.port):
                self._connection = self._connector(f'http://127.0.0.1:{self.port}')
                self._wait_for_context()
                return
            time.sleep(0.05)
        raise BrowserUnavailable(f'Chrome did not open CDP port {self.port}')

    def _connect_existing(self) -> None:
        self._connection = self._connector(f'http://127.0.0.1:{self.port}')
        self._wait_for_context()

    def _refresh_connection_internal(self) -> None:
        playwright = self._playwright
        connection = self._connection
        if playwright is not None and hasattr(playwright, 'stop'):
            playwright.stop()
        elif connection is not None and hasattr(connection, 'close'):
            connection.close()
        self._connection = None
        self._playwright = None
        if not self._port_probe(self.port):
            raise BrowserDisconnected(f'Chrome CDP port {self.port} is unavailable')
        self._connect_existing()

    def _wait_for_context(self) -> None:
        connection = self._connection
        if connection is None or not hasattr(connection, 'contexts'):
            return
        deadline = time.monotonic() + self.startup_timeout
        while not getattr(connection, 'contexts', None):
            if time.monotonic() >= deadline:
                raise BrowserUnavailable('Chrome did not create a browser context')
            time.sleep(0.05)

    def _close_internal(self) -> None:
        connection = self._connection
        if connection is not None and hasattr(connection, 'close'):
            connection.close()
        playwright = self._playwright
        if playwright is not None and hasattr(playwright, 'stop'):
            playwright.stop()
        process = self._process
        if process is not None and hasattr(process, 'poll') and process.poll() is None:
            process.terminate()
        self._connection = None

    def _launch_chrome(self, port: int, profile: Path) -> subprocess.Popen[bytes]:
        executable = self.chrome_path or _find_chrome()
        args = [
            executable,
            f'--remote-debugging-port={port}',
            f'--user-data-dir={profile}',
            '--no-first-run',
            '--no-default-browser-check',
            '--disable-popup-blocking',
        ]
        return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _connect_over_cdp(self, endpoint: str) -> object:
        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        return self._playwright.chromium.connect_over_cdp(endpoint)  # type: ignore[attr-defined]
