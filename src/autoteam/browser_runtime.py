"""Single-process Playwright browser lease management."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)

_BROWSER_LEASE_LOCK = threading.Lock()
_BROWSER_LEASE_STATE: dict[str, object] = {
    "owner": "",
    "acquired_at": 0.0,
}


class BrowserLeaseError(RuntimeError):
    """Raised when another browser automation flow is already running."""


@dataclass
class BrowserLease:
    owner: str
    sync_playwright_factory: Callable = sync_playwright

    def __post_init__(self) -> None:
        self.playwright = None
        self.browser = None
        self.acquired_at = 0.0
        self._active = False

    def __enter__(self) -> BrowserLease:
        if not _BROWSER_LEASE_LOCK.acquire(blocking=False):
            active_owner = str(_BROWSER_LEASE_STATE.get("owner") or "unknown")
            raise BrowserLeaseError(f"已有浏览器流程在运行: {active_owner}")
        self.acquired_at = time.time()
        self._active = True
        _BROWSER_LEASE_STATE["owner"] = self.owner
        _BROWSER_LEASE_STATE["acquired_at"] = self.acquired_at
        logger.debug("[浏览器] 已获取租约: %s", self.owner)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def start_playwright(self):
        if not self._active:
            raise BrowserLeaseError("浏览器租约未获取")
        if self.playwright is None:
            self.playwright = self.sync_playwright_factory().start()
        return self.playwright

    def launch_chromium(self, **launch_options):
        playwright = self.start_playwright()
        self.browser = playwright.chromium.launch(**launch_options)
        return self.browser

    def close(self) -> None:
        browser = self.browser
        playwright = self.playwright
        self.browser = None
        self.playwright = None

        if browser is not None:
            try:
                browser.close()
            except Exception as exc:
                logger.debug("[浏览器] 关闭 Chromium 失败: %s", exc)
        if playwright is not None:
            try:
                playwright.stop()
            except Exception as exc:
                logger.debug("[浏览器] 停止 Playwright 失败: %s", exc)

        if self._active:
            _BROWSER_LEASE_STATE["owner"] = ""
            _BROWSER_LEASE_STATE["acquired_at"] = 0.0
            self._active = False
            _BROWSER_LEASE_LOCK.release()
            logger.debug("[浏览器] 已释放租约: %s", self.owner)


@contextmanager
def acquire_browser_lease(
    owner: str,
    *,
    sync_playwright_factory: Callable = sync_playwright,
) -> Iterator[BrowserLease]:
    lease = BrowserLease(owner=owner, sync_playwright_factory=sync_playwright_factory)
    with lease:
        yield lease


def browser_lease_status() -> dict[str, object]:
    return dict(_BROWSER_LEASE_STATE)
