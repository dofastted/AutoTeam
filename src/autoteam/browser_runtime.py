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
    "max_leases": 1,
    "active": [],
}
_BROWSER_LEASE_LIMIT_OVERRIDE: int | None = None


class BrowserLeaseError(RuntimeError):
    """Raised when another browser automation flow is already running."""


def _configured_max_leases() -> int:
    override = _BROWSER_LEASE_LIMIT_OVERRIDE
    if override is not None:
        return min(3, max(1, int(override)))
    return 1


def _active_leases() -> list[dict[str, object]]:
    active = _BROWSER_LEASE_STATE.setdefault("active", [])
    if not isinstance(active, list):
        active = []
        _BROWSER_LEASE_STATE["active"] = active
    return active


@dataclass
class BrowserLease:
    owner: str
    sync_playwright_factory: Callable = sync_playwright

    def __post_init__(self) -> None:
        self.playwright = None
        self.browser = None
        self.acquired_at = 0.0
        self.slot = 0
        self._active = False

    def __enter__(self) -> BrowserLease:
        with _BROWSER_LEASE_LOCK:
            max_leases = _configured_max_leases()
            active = _active_leases()
            if len(active) >= max_leases:
                active_owner = str(active[0].get("owner") or "unknown") if active else "unknown"
                raise BrowserLeaseError(f"已有浏览器流程在运行: {active_owner}")

            used_slots = {int(item.get("slot") or 0) for item in active}
            for slot in range(1, max_leases + 1):
                if slot not in used_slots:
                    self.slot = slot
                    break
            self.acquired_at = time.time()
            self._active = True
            active.append({"owner": self.owner, "slot": self.slot, "acquired_at": self.acquired_at})
            _BROWSER_LEASE_STATE["max_leases"] = max_leases
        logger.debug("[浏览器] 已获取租约: %s slot=%s", self.owner, self.slot)
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
            with _BROWSER_LEASE_LOCK:
                active = _active_leases()
                _BROWSER_LEASE_STATE["active"] = [
                    item for item in active if not (item.get("slot") == self.slot and item.get("owner") == self.owner)
                ]
                self._active = False
            logger.debug("[浏览器] 已释放租约: %s slot=%s", self.owner, self.slot)


@contextmanager
def acquire_browser_lease(
    owner: str,
    *,
    sync_playwright_factory: Callable = sync_playwright,
) -> Iterator[BrowserLease]:
    lease = BrowserLease(owner=owner, sync_playwright_factory=sync_playwright_factory)
    with lease:
        yield lease


@contextmanager
def browser_parallel_limit(max_leases: int) -> Iterator[None]:
    global _BROWSER_LEASE_LIMIT_OVERRIDE
    previous = _BROWSER_LEASE_LIMIT_OVERRIDE
    with _BROWSER_LEASE_LOCK:
        _BROWSER_LEASE_LIMIT_OVERRIDE = min(3, max(1, int(max_leases or 1)))
    try:
        yield
    finally:
        with _BROWSER_LEASE_LOCK:
            _BROWSER_LEASE_LIMIT_OVERRIDE = previous


def browser_lease_status() -> dict[str, object]:
    return dict(_BROWSER_LEASE_STATE)
