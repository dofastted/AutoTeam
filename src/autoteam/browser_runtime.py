"""Single-process Playwright browser lease management."""

from __future__ import annotations

import json
import logging
import os
import queue
import shlex
import signal
import subprocess
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener

from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)

_CDP_READY_TIMEOUT_SECONDS = 8.0

_BROWSER_LEASE_LOCK = threading.Lock()
_BROWSER_LEASE_STATE: dict[str, object] = {
    "max_leases": 1,
    "active": [],
}
_BROWSER_LEASE_LIMIT_OVERRIDE: int | None = None
_PERSISTENT_KEEPALIVE_LOCK = threading.Lock()
_PERSISTENT_KEEPALIVE: dict[str, object] = {}
_PERSISTENT_WORKER_STOP = object()
_PERSISTENT_CONTEXT_OPTION_KEYS = {
    "accept_downloads",
    "args",
    "base_url",
    "bypass_csp",
    "channel",
    "chromium_sandbox",
    "color_scheme",
    "device_scale_factor",
    "env",
    "executable_path",
    "extra_http_headers",
    "forced_colors",
    "geolocation",
    "handle_sighup",
    "handle_sigint",
    "handle_sigterm",
    "has_touch",
    "headless",
    "http_credentials",
    "ignore_default_args",
    "ignore_https_errors",
    "is_mobile",
    "java_script_enabled",
    "locale",
    "no_viewport",
    "offline",
    "permissions",
    "proxy",
    "record_har_content",
    "record_har_mode",
    "record_har_omit_content",
    "record_har_path",
    "record_har_url_filter",
    "record_video_dir",
    "record_video_size",
    "reduced_motion",
    "screen",
    "service_workers",
    "slow_mo",
    "strict_selectors",
    "timeout",
    "traces_dir",
    "user_agent",
    "viewport",
}


class BrowserLeaseError(RuntimeError):
    """Raised when another browser automation flow is already running."""


class _PersistentBrowserWorker:
    def __init__(self, sync_playwright_factory: Callable):
        self.sync_playwright_factory = sync_playwright_factory
        self.queue: queue.Queue = queue.Queue()
        self.ready = threading.Event()
        self.thread = threading.Thread(target=self._worker, name="autoteam-persistent-browser", daemon=True)
        self.playwright = None
        self.thread.start()
        self.ready.wait(timeout=5)

    def _worker(self) -> None:
        self.playwright = self.sync_playwright_factory().start()
        self.ready.set()
        while True:
            item = self.queue.get()
            if item is _PERSISTENT_WORKER_STOP:
                break
            func, args, kwargs, result_event, result_holder = item
            try:
                result_holder["result"] = func(*args, **kwargs)
            except BaseException as exc:
                result_holder["error"] = exc
            finally:
                result_event.set()
        if self.playwright is not None:
            try:
                self.playwright.stop()
            except Exception as exc:
                logger.debug("[浏览器] 停止持久化 Playwright 失败: %s", exc)

    def run(self, func, *args, **kwargs):
        if not self.thread.is_alive() or self.playwright is None:
            raise BrowserLeaseError("持久化 Chromium worker 未就绪")
        if threading.current_thread() is self.thread:
            return func(*args, **kwargs)
        result_event = threading.Event()
        result_holder: dict[str, object] = {}
        self.queue.put((func, args, kwargs, result_event, result_holder))
        result_event.wait()
        if "error" in result_holder:
            raise result_holder["error"]
        return result_holder.get("result")

    def stop(self) -> None:
        if self.thread.is_alive():
            self.queue.put(_PERSISTENT_WORKER_STOP)
            self.thread.join(timeout=5)


_PROXY_SIMPLE_TYPES = (str, bytes, int, float, bool, type(None))


def _unwrap_persistent_value(value):
    if isinstance(value, _PersistentObjectProxy):
        return value._target
    if isinstance(value, tuple):
        return tuple(_unwrap_persistent_value(item) for item in value)
    if isinstance(value, list):
        return [_unwrap_persistent_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _unwrap_persistent_value(item) for key, item in value.items()}
    return value


def _wrap_persistent_value(worker: _PersistentBrowserWorker | None, value):
    if worker is None or isinstance(value, _PROXY_SIMPLE_TYPES):
        return value
    if isinstance(value, tuple):
        return tuple(_wrap_persistent_value(worker, item) for item in value)
    if isinstance(value, list):
        return [_wrap_persistent_value(worker, item) for item in value]
    if isinstance(value, dict):
        return {key: _wrap_persistent_value(worker, item) for key, item in value.items()}
    module = getattr(type(value), "__module__", "")
    if module.startswith(("builtins", "pathlib", "datetime")):
        return value
    return _PersistentObjectProxy(worker, value)


class _PersistentObjectProxy:
    """Run Playwright object access on the persistent browser worker thread."""

    def __init__(self, worker: _PersistentBrowserWorker, target):
        object.__setattr__(self, "_worker", worker)
        object.__setattr__(self, "_target", target)

    def __getattr__(self, name: str):
        worker = object.__getattribute__(self, "_worker")
        target = object.__getattribute__(self, "_target")

        attr_is_callable = worker.run(lambda: callable(getattr(target, name)))
        if attr_is_callable:
            def _method(*args, **kwargs):
                def _call():
                    attr = getattr(target, name)
                    return attr(*_unwrap_persistent_value(args), **_unwrap_persistent_value(kwargs))

                return _wrap_persistent_value(worker, worker.run(_call))

            return _method
        attr = worker.run(lambda: getattr(target, name))
        return _wrap_persistent_value(worker, attr)

    def __setattr__(self, name: str, value) -> None:
        worker = object.__getattribute__(self, "_worker")
        target = object.__getattribute__(self, "_target")
        worker.run(lambda: setattr(target, name, _unwrap_persistent_value(value)))

    def __bool__(self) -> bool:
        return True

    def __len__(self) -> int:
        worker = object.__getattribute__(self, "_worker")
        target = object.__getattribute__(self, "_target")
        return int(worker.run(lambda: len(target)))

    def __iter__(self):
        worker = object.__getattribute__(self, "_worker")
        target = object.__getattribute__(self, "_target")
        return iter(_wrap_persistent_value(worker, worker.run(lambda: list(target))))

    def __getitem__(self, key):
        worker = object.__getattribute__(self, "_worker")
        target = object.__getattribute__(self, "_target")
        return _wrap_persistent_value(worker, worker.run(lambda: target[key]))

    def __enter__(self):
        worker = object.__getattribute__(self, "_worker")
        target = object.__getattribute__(self, "_target")
        entered = worker.run(lambda: target.__enter__())
        return _wrap_persistent_value(worker, entered)

    def __exit__(self, exc_type, exc, tb):
        worker = object.__getattribute__(self, "_worker")
        target = object.__getattribute__(self, "_target")
        return worker.run(lambda: target.__exit__(exc_type, exc, tb))

    def __repr__(self) -> str:
        target = object.__getattribute__(self, "_target")
        return f"<PersistentObjectProxy target={target!r}>"


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


def _resolve_cdp_endpoint(cdp_url: str, timeout: float = _CDP_READY_TIMEOUT_SECONDS) -> str:
    if cdp_url.startswith("ws://") or cdp_url.startswith("wss://"):
        return cdp_url
    version_url = cdp_url.rstrip("/") + "/json/version"
    deadline = time.time() + timeout
    last_error = None
    while time.time() < deadline:
        try:
            opener = build_opener(ProxyHandler({}))
            with opener.open(version_url, timeout=1) as response:  # noqa: S310
                if response.status == 200:
                    payload = json.loads(response.read().decode("utf-8", errors="replace"))
                    ws_url = str(payload.get("webSocketDebuggerUrl") or "").strip()
                    return ws_url or cdp_url
                last_error = RuntimeError(f"HTTP {response.status}")
        except (OSError, URLError) as exc:
            last_error = exc
        time.sleep(0.25)
    raise BrowserLeaseError(f"Chrome CDP 未就绪: {version_url}: {last_error}")


def _get_playwright_user_data_dir() -> str:
    return os.environ.get("PLAYWRIGHT_USER_DATA_DIR", "").strip()


def _live_thread_ids() -> set[int]:
    return {thread.ident for thread in threading.enumerate() if thread.ident is not None}


def _persistent_keepalive_thread_is_alive() -> bool:
    worker = _PERSISTENT_KEEPALIVE.get("worker")
    if isinstance(worker, _PersistentBrowserWorker):
        return worker.thread.is_alive()
    thread_id = _PERSISTENT_KEEPALIVE.get("thread_id")
    if not thread_id:
        return False
    thread = _PERSISTENT_KEEPALIVE.get("thread")
    if isinstance(thread, threading.Thread):
        return thread.is_alive()
    try:
        return int(thread_id) in _live_thread_ids()
    except Exception:
        return False


def _persistent_keepalive_matches_current_thread() -> bool:
    if isinstance(_PERSISTENT_KEEPALIVE.get("worker"), _PersistentBrowserWorker):
        return True
    thread = _PERSISTENT_KEEPALIVE.get("thread")
    if isinstance(thread, threading.Thread):
        return thread is threading.current_thread()
    thread_id = _PERSISTENT_KEEPALIVE.get("thread_id")
    if not thread_id:
        return False
    try:
        return int(thread_id) == threading.get_ident()
    except Exception:
        return False


def _adapt_persistent_context_options(launch_options: dict[str, object]) -> dict[str, object]:
    adapted = {key: value for key, value in launch_options.items() if key in _PERSISTENT_CONTEXT_OPTION_KEYS}
    dropped = sorted(set(launch_options) - set(adapted))
    if dropped:
        logger.debug("[浏览器] 持久化 profile 已忽略不支持的启动参数: %s", ", ".join(dropped))
    return adapted


def _persistent_keepalive_is_alive() -> bool:
    if not _persistent_keepalive_thread_is_alive():
        return False
    context = _PERSISTENT_KEEPALIVE.get("context")
    browser = _PERSISTENT_KEEPALIVE.get("browser")
    worker = _PERSISTENT_KEEPALIVE.get("worker")

    def _check_alive() -> bool:
        if context is not None:
            pages = list(getattr(context, "pages", []) or [])
            for page in pages:
                is_closed = getattr(page, "is_closed", None)
                if callable(is_closed):
                    is_closed()
            if getattr(context, "closed", False):
                return False
        if browser is None:
            return False
        is_connected = getattr(browser, "is_connected", None)
        if callable(is_connected):
            return bool(is_connected())
        return True

    if isinstance(worker, _PersistentBrowserWorker):
        try:
            return bool(worker.run(_check_alive))
        except Exception:
            return False

    try:
        return _check_alive()
    except Exception:
        return False


def _cleanup_persistent_profile_locks(user_data_dir: str) -> None:
    if not user_data_dir:
        return
    for name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        path = os.path.join(user_data_dir, name)
        try:
            if os.path.lexists(path):
                os.remove(path)
        except Exception as exc:
            logger.debug("[浏览器] 清理持久化 profile 锁文件失败: %s: %s", path, exc)


def _terminate_process_tree(pid: int) -> None:
    if pid <= 0:
        return
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        except Exception as exc:
            logger.debug("[浏览器] taskkill Chromium 失败: pid=%s error=%s", pid, exc)
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except Exception as exc:
        logger.debug("[浏览器] 终止 Chromium 失败: pid=%s error=%s", pid, exc)


def _kill_chromium_processes_for_profile(user_data_dir: str) -> None:
    if not user_data_dir:
        return
    profile = os.path.abspath(user_data_dir)
    psutil = None
    try:
        import psutil as _psutil  # type: ignore

        psutil = _psutil
    except Exception:
        psutil = None

    if psutil is not None:
        for proc in psutil.process_iter(["pid", "cmdline"]):
            try:
                cmdline = proc.info.get("cmdline") or []
                text = " ".join(str(part) for part in cmdline)
                if profile in text or user_data_dir in text:
                    proc.kill()
            except Exception:
                continue
        return

    try:
        output = subprocess.check_output(["ps", "-eo", "pid=,args="], text=True, stderr=subprocess.DEVNULL)
    except Exception as exc:
        logger.debug("[浏览器] 无法扫描 Chromium 进程: %s", exc)
        return
    for line in output.splitlines():
        if profile not in line and user_data_dir not in line:
            continue
        parts = line.strip().split(maxsplit=1)
        if not parts:
            continue
        try:
            _terminate_process_tree(int(parts[0]))
        except Exception:
            continue


def _discard_stale_persistent_keepalive(user_data_dir: str) -> None:
    keepalive_dir = str(_PERSISTENT_KEEPALIVE.get("user_data_dir") or user_data_dir or "")
    worker = _PERSISTENT_KEEPALIVE.get("worker")
    if _PERSISTENT_KEEPALIVE:
        logger.info(
            "[浏览器] 丢弃旧持久化 Chromium keepalive: profile=%s thread=%s current_thread=%s",
            keepalive_dir,
            _PERSISTENT_KEEPALIVE.get("thread_id"),
            threading.get_ident(),
        )
    _PERSISTENT_KEEPALIVE.clear()
    if isinstance(worker, _PersistentBrowserWorker):
        worker.stop()
    if keepalive_dir:
        _kill_chromium_processes_for_profile(keepalive_dir)
        _cleanup_persistent_profile_locks(keepalive_dir)


def _persistent_keepalive_playwright(user_data_dir: str):
    keepalive_dir = str(_PERSISTENT_KEEPALIVE.get("user_data_dir") or "")
    keepalive_alive = _persistent_keepalive_is_alive()
    if keepalive_dir and (not keepalive_alive or not _persistent_keepalive_matches_current_thread()):
        _discard_stale_persistent_keepalive(keepalive_dir)
        keepalive_dir = ""
        keepalive_alive = False
    if keepalive_dir and keepalive_dir != user_data_dir and keepalive_alive:
        raise BrowserLeaseError(f"已有持久化 Chromium 正在使用 profile: {keepalive_dir}")
    if (
        keepalive_dir == user_data_dir
        and keepalive_alive
        and _persistent_keepalive_matches_current_thread()
        and not isinstance(_PERSISTENT_KEEPALIVE.get("worker"), _PersistentBrowserWorker)
    ):
        playwright = _PERSISTENT_KEEPALIVE.get("playwright")
        if playwright is not None:
            return playwright
    return None


def _ensure_persistent_keepalive_page(context) -> None:
    try:
        pages = list(getattr(context, "pages", []) or [])
        if not pages:
            context.new_page()
    except Exception as exc:
        logger.debug("[浏览器] 创建持久化保活页失败: %s", exc)


def _ensure_persistent_keepalive_page_on_worker(worker: _PersistentBrowserWorker | None, context) -> None:
    if worker is None:
        _ensure_persistent_keepalive_page(context)
        return
    worker.run(lambda: _ensure_persistent_keepalive_page(context))


class PersistentContextBrowser:
    """Adapt a persistent BrowserContext to the Browser methods used downstream."""

    def __init__(
        self,
        persistent_context,
        *,
        owns_playwright: bool,
        user_data_dir: str = "",
        launch_options: dict[str, object] | None = None,
        worker: _PersistentBrowserWorker | None = None,
        browser=None,
    ):
        self.worker = worker
        self.persistent_context = persistent_context
        self._browser = browser if browser is not None else self._run_on_worker(lambda: persistent_context.browser)
        self.owns_playwright = owns_playwright
        self.user_data_dir = user_data_dir
        self.launch_options = dict(launch_options or {})
        self._contexts = []

    def new_context(self, *args, **kwargs):
        try:
            if self._browser is None:
                raise BrowserLeaseError("持久化浏览器未返回 Browser 引用，无法创建隔离 context")
            context = self._run_on_worker(
                lambda: self._browser.new_context(*_unwrap_persistent_value(args), **_unwrap_persistent_value(kwargs))
            )
            self._contexts.append(context)
            return _wrap_persistent_value(self.worker, context)
        except Exception as exc:
            if not _looks_like_browser_closed_error(exc) or not self.user_data_dir:
                raise
            logger.warning("[浏览器] 持久化 Chromium 已失联，重启 profile 后重试: %s", exc)
            replacement = _restart_persistent_browser_after_disconnect(self.user_data_dir, self.launch_options)
            self.persistent_context = replacement.persistent_context
            self._browser = replacement._browser
            self.worker = replacement.worker
            context = self._run_on_worker(
                lambda: self._browser.new_context(*_unwrap_persistent_value(args), **_unwrap_persistent_value(kwargs))
            )
            self._contexts.append(context)
            return _wrap_persistent_value(self.worker, context)

    def _run_on_worker(self, func):
        if self.worker is None:
            return func()
        return self.worker.run(func)

    def close(self) -> None:
        self.close_transient_contexts()

    def close_transient_contexts(self) -> None:
        contexts = list(self._contexts)
        self._contexts = []
        for context in contexts:
            try:
                self._run_on_worker(lambda context=context: context.close())
            except Exception as exc:
                logger.debug("[浏览器] 关闭临时 context 失败: %s", exc)

    def __getattr__(self, name: str):
        if self._browser is None:
            raise AttributeError(name)
        if self.worker is None:
            return getattr(self._browser, name)
        return getattr(_PersistentObjectProxy(self.worker, self._browser), name)


def _launch_or_reuse_persistent_browser(playwright, user_data_dir: str, launch_options: dict[str, object]):
    with _PERSISTENT_KEEPALIVE_LOCK:
        keepalive_dir = str(_PERSISTENT_KEEPALIVE.get("user_data_dir") or "")
        keepalive_alive = _persistent_keepalive_is_alive()
        if keepalive_dir and (not keepalive_alive or not _persistent_keepalive_matches_current_thread()):
            _discard_stale_persistent_keepalive(keepalive_dir)
            keepalive_dir = ""
            keepalive_alive = False
        if keepalive_dir and keepalive_dir != user_data_dir and keepalive_alive:
            raise BrowserLeaseError(f"已有持久化 Chromium 正在使用 profile: {keepalive_dir}")

        if keepalive_dir == user_data_dir and keepalive_alive and _persistent_keepalive_matches_current_thread():
            context = _PERSISTENT_KEEPALIVE["context"]
            _ensure_persistent_keepalive_page_on_worker(_PERSISTENT_KEEPALIVE.get("worker"), context)
            logger.debug("[浏览器] 复用持久化 Chromium profile: %s", user_data_dir)
            return PersistentContextBrowser(
                context,
                owns_playwright=True,
                user_data_dir=user_data_dir,
                launch_options=launch_options,
                worker=_PERSISTENT_KEEPALIVE.get("worker"),
            )

        adapted_options = _adapt_persistent_context_options(launch_options)
        context = playwright.chromium.launch_persistent_context(user_data_dir, **adapted_options)
        browser = context.browser
        _ensure_persistent_keepalive_page(context)
        _PERSISTENT_KEEPALIVE.clear()
        _PERSISTENT_KEEPALIVE.update(
            {
                "user_data_dir": user_data_dir,
                "playwright": playwright,
                "context": context,
                "browser": browser,
                "thread_id": threading.get_ident(),
                "thread": threading.current_thread(),
            }
        )
        logger.info("[浏览器] 已启动持久化 Chromium profile: %s", user_data_dir)
        return PersistentContextBrowser(
            context,
            owns_playwright=True,
            user_data_dir=user_data_dir,
            launch_options=launch_options,
            worker=_PERSISTENT_KEEPALIVE.get("worker"),
            browser=browser,
        )


def _looks_like_browser_closed_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return (
        "target page, context or browser has been closed" in text
        or "browser has been closed" in text
        or "context has been closed" in text
    )


def _restart_persistent_browser_after_disconnect(user_data_dir: str, launch_options: dict[str, object]):
    with _PERSISTENT_KEEPALIVE_LOCK:
        _discard_stale_persistent_keepalive(user_data_dir)
        return _launch_persistent_browser_in_worker(user_data_dir, launch_options, sync_playwright)


def _launch_persistent_browser_in_worker(
    user_data_dir: str,
    launch_options: dict[str, object],
    sync_playwright_factory: Callable,
):
    worker = _PersistentBrowserWorker(sync_playwright_factory)
    adapted_options = _adapt_persistent_context_options(launch_options)

    def _launch():
        context = worker.playwright.chromium.launch_persistent_context(user_data_dir, **adapted_options)
        _ensure_persistent_keepalive_page(context)
        return context

    context = worker.run(_launch)
    browser = worker.run(lambda: context.browser)
    _PERSISTENT_KEEPALIVE.clear()
    _PERSISTENT_KEEPALIVE.update(
        {
            "user_data_dir": user_data_dir,
            "playwright": worker.playwright,
            "context": context,
            "browser": browser,
            "thread_id": worker.thread.ident,
            "thread": worker.thread,
            "worker": worker,
        }
    )
    logger.info("[浏览器] 已在专用线程启动持久化 Chromium profile: %s", user_data_dir)
    return PersistentContextBrowser(
        context,
        owns_playwright=True,
        user_data_dir=user_data_dir,
        launch_options=launch_options,
        worker=worker,
        browser=browser,
    )


@dataclass
class BrowserLease:
    owner: str
    sync_playwright_factory: Callable = sync_playwright

    def __post_init__(self) -> None:
        self.playwright = None
        self.browser = None
        self._cdp_process = None
        self.acquired_at = 0.0
        self.slot = 0
        self._active = False
        self._persistent_mode = False

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
            user_data_dir = _get_playwright_user_data_dir()
            if user_data_dir and not os.environ.get("PLAYWRIGHT_BROWSER_CDP_URL", "").strip():
                with _PERSISTENT_KEEPALIVE_LOCK:
                    existing = _persistent_keepalive_playwright(user_data_dir)
                    if existing is not None:
                        self.playwright = existing
                return self.playwright
            self.playwright = self.sync_playwright_factory().start()
        return self.playwright

    def launch_chromium(self, **launch_options):
        playwright = self.start_playwright()
        cdp_url = os.environ.get("PLAYWRIGHT_BROWSER_CDP_URL", "").strip()
        cdp_command = os.environ.get("PLAYWRIGHT_BROWSER_CDP_COMMAND", "").strip()
        user_data_dir = _get_playwright_user_data_dir()
        if cdp_command:
            self._cdp_process = subprocess.Popen(
                shlex.split(cdp_command),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        if cdp_url:
            if cdp_command:
                cdp_url = _resolve_cdp_endpoint(cdp_url)
            self.browser = playwright.chromium.connect_over_cdp(cdp_url)
            return self.browser
        if user_data_dir:
            self._persistent_mode = True
            if playwright is None:
                with _PERSISTENT_KEEPALIVE_LOCK:
                    keepalive_dir = str(_PERSISTENT_KEEPALIVE.get("user_data_dir") or "")
                    keepalive_alive = _persistent_keepalive_is_alive()
                    if keepalive_dir and (not keepalive_alive or keepalive_dir != user_data_dir):
                        _discard_stale_persistent_keepalive(keepalive_dir)
                        keepalive_dir = ""
                        keepalive_alive = False
                    if keepalive_dir == user_data_dir and keepalive_alive:
                        context = _PERSISTENT_KEEPALIVE["context"]
                        _ensure_persistent_keepalive_page_on_worker(_PERSISTENT_KEEPALIVE.get("worker"), context)
                        self.browser = PersistentContextBrowser(
                            context,
                            owns_playwright=True,
                            user_data_dir=user_data_dir,
                            launch_options=dict(launch_options),
                            worker=_PERSISTENT_KEEPALIVE.get("worker"),
                        )
                    else:
                        self.browser = _launch_persistent_browser_in_worker(
                            user_data_dir,
                            dict(launch_options),
                            self.sync_playwright_factory,
                        )
            else:
                self.browser = _launch_or_reuse_persistent_browser(playwright, user_data_dir, dict(launch_options))
            return self.browser
        self.browser = playwright.chromium.launch(**launch_options)
        return self.browser

    def close(self) -> None:
        browser = self.browser
        playwright = self.playwright
        cdp_process = self._cdp_process
        persistent_mode = self._persistent_mode
        self.browser = None
        self.playwright = None
        self._cdp_process = None
        self._persistent_mode = False

        if persistent_mode and isinstance(browser, PersistentContextBrowser):
            browser.close_transient_contexts()
        elif browser is not None:
            try:
                browser.close()
            except Exception as exc:
                logger.debug("[浏览器] 关闭 Chromium 失败: %s", exc)
        if playwright is not None and not persistent_mode:
            try:
                playwright.stop()
            except Exception as exc:
                logger.debug("[浏览器] 停止 Playwright 失败: %s", exc)
        if cdp_process is not None:
            try:
                cdp_process.terminate()
            except Exception as exc:
                logger.debug("[浏览器] 停止 CDP Chrome 失败: %s", exc)

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
