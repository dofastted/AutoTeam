"""Outbound proxy selection and requests helpers."""

from __future__ import annotations

import contextlib
import contextvars
import logging
import os
import random
import threading
from urllib.parse import urlsplit

from autoteam.textio import parse_env_value

logger = logging.getLogger(__name__)

DEFAULT_PROXY_URL = "http://127.0.0.1:10808"
DEFAULT_BYPASS = "localhost,127.0.0.1,::1"
SUPPORTED_PROXY_SCHEMES = {"http", "https", "socks5", "socks5h"}
DIRECT_MARKERS = {"direct", "none"}
DEFAULT_STRATEGY = "task-sticky"
SUPPORTED_STRATEGIES = {"task-sticky", "round-robin", "random"}

_UNSET = object()
_task_proxy_var = contextvars.ContextVar("autoteam_outbound_proxy", default=_UNSET)
_selection_lock = threading.Lock()
_selection_index = 0


def _get_bool_env(name: str, default: bool) -> bool:
    raw = parse_env_value(os.environ.get(name, "true" if default else "false")).strip().lower()
    if raw in {"1", "true", "yes", "y", "on"}:
        return True
    if raw in {"0", "false", "no", "n", "off"}:
        return False
    return default


def outbound_proxy_enabled() -> bool:
    return _get_bool_env("OUTBOUND_PROXY_ENABLED", True)


def failover_enabled() -> bool:
    return _get_bool_env("OUTBOUND_PROXY_FAILOVER", True)


def _proxy_strategy() -> str:
    raw = os.environ.get("OUTBOUND_PROXY_STRATEGY", DEFAULT_STRATEGY)
    value = parse_env_value(raw).strip().lower()
    if value in SUPPORTED_STRATEGIES:
        return value
    return DEFAULT_STRATEGY


def _split_pool(raw: str) -> list[str]:
    values = []
    for chunk in str(raw or "").replace("\n", ",").split(","):
        value = chunk.strip()
        if value:
            values.append(value)
    return values


def _format_proxy_host(hostname: str) -> str:
    if ":" in hostname and not hostname.startswith("["):
        return f"[{hostname}]"
    return hostname


def normalize_proxy_url(value: str) -> str:
    raw = str(value or "").strip()
    lowered = raw.lower()
    if not raw:
        return ""
    if lowered in DIRECT_MARKERS:
        return "direct"
    if "://" not in raw:
        raw = f"http://{raw}"

    parsed = urlsplit(raw)
    if not parsed.scheme or not parsed.hostname:
        raise ValueError(f"代理地址缺少协议或主机: {value}")
    if parsed.scheme not in SUPPORTED_PROXY_SCHEMES:
        raise ValueError(f"不支持的代理协议: {parsed.scheme}")

    host = _format_proxy_host(parsed.hostname)
    auth = ""
    if parsed.username:
        auth = parsed.username
        if parsed.password:
            auth = f"{auth}:{parsed.password}"
        auth = f"{auth}@"
    port = f":{parsed.port}" if parsed.port else ""
    return f"{parsed.scheme}://{auth}{host}{port}"


def configured_proxy_pool() -> list[str]:
    if not outbound_proxy_enabled():
        return []

    raw = (
        os.environ.get("OUTBOUND_PROXY_POOL", "").strip()
        or os.environ.get("OUTBOUND_PROXY_URL", "").strip()
        or DEFAULT_PROXY_URL
    )
    pool = []
    for item in _split_pool(raw):
        normalized = normalize_proxy_url(item)
        if normalized and normalized not in pool:
            pool.append(normalized)
    return pool


def _bypass_patterns() -> list[str]:
    raw = os.environ.get("OUTBOUND_PROXY_BYPASS", "").strip() or DEFAULT_BYPASS
    return [item.strip().lower() for item in raw.replace("\n", ",").split(",") if item.strip()]


def should_bypass_proxy(url: str) -> bool:
    parsed = urlsplit(str(url or ""))
    host = (parsed.hostname or "").strip().lower()
    if not host:
        return True

    for pattern in _bypass_patterns():
        if pattern == "*":
            return True
        if pattern.startswith(".") and host.endswith(pattern):
            return True
        if host == pattern or host.endswith(f".{pattern}"):
            return True
    return False


def _pool_key_for_proxy(pool: list[str], proxy_url: str | None) -> str:
    value = str(proxy_url or "").strip()
    if not value:
        return "direct" if "direct" in pool else ""
    if value == "direct":
        return "direct"
    try:
        return normalize_proxy_url(value)
    except ValueError:
        return value


def _proxy_output(value: str) -> str:
    return "" if value == "direct" else value


def _select_round_robin(pool: list[str], *, after: str | None = None) -> str:
    global _selection_index
    with _selection_lock:
        after_key = _pool_key_for_proxy(pool, after)
        if after_key and after_key in pool:
            index = (pool.index(after_key) + 1) % len(pool)
            _selection_index = (index + 1) % len(pool)
        else:
            index = _selection_index % len(pool)
            _selection_index = (_selection_index + 1) % len(pool)
        selected = pool[index]
    return _proxy_output(selected)


def _select_proxy_from_pool(pool: list[str], *, after: str | None = None) -> str:
    if not pool:
        return ""

    if _proxy_strategy() == "random":
        after_key = _pool_key_for_proxy(pool, after)
        candidates = pool
        if after_key in pool and len(pool) > 1:
            candidates = [item for item in pool if item != after_key]
        return _proxy_output(random.choice(candidates))

    return _select_round_robin(pool, after=after)


def select_proxy(*, after: str | None = None) -> str:
    return _select_proxy_from_pool(configured_proxy_pool(), after=after)


def current_proxy_url() -> str:
    value = _task_proxy_var.get()
    if value is not _UNSET:
        return value
    selected = select_proxy()
    if _proxy_strategy() == DEFAULT_STRATEGY:
        _task_proxy_var.set(selected)
    return selected


def rotate_task_proxy() -> str:
    """Switch the current task/thread to the next configured proxy and return it."""
    current = _task_proxy_var.get()
    if current is _UNSET:
        current = None
    selected = select_proxy(after=current)
    _task_proxy_var.set(selected)
    return selected


@contextlib.contextmanager
def task_proxy_context(proxy_url: str | None = None):
    current = _task_proxy_var.get()
    selected = current if proxy_url is None and current is not _UNSET else (select_proxy() if proxy_url is None else proxy_url)
    token = _task_proxy_var.set(selected)
    try:
        yield selected
    finally:
        _task_proxy_var.reset(token)


def requests_proxies_for(url: str, proxy_url: str | None = None) -> dict[str, str]:
    if should_bypass_proxy(url):
        return {}
    proxy = current_proxy_url() if proxy_url is None else proxy_url
    if not proxy or proxy == "direct":
        return {}
    return {"http": proxy, "https": proxy}


def _network_error(exc: Exception) -> bool:
    import requests

    return isinstance(
        exc,
        (
            requests.exceptions.ConnectionError,
            requests.exceptions.ConnectTimeout,
            requests.exceptions.ProxyError,
            requests.exceptions.Timeout,
        ),
    )


def _request_once(session, method: str, url: str, proxy_url: str, **kwargs):
    import requests

    kwargs.setdefault("proxies", requests_proxies_for(url, proxy_url))

    if session is None:
        with requests.Session() as local_session:
            local_session.trust_env = False
            return local_session.request(method, url, **kwargs)

    session.trust_env = False
    original_request = getattr(session, "_autoteam_original_request", None)
    if original_request is None:
        original_request = requests.Session.request.__get__(session, requests.Session)
    return original_request(method, url, **kwargs)


def request(method: str, url: str, *, session=None, **kwargs):
    import requests

    if "proxies" in kwargs:
        if session is None:
            with requests.Session() as local_session:
                local_session.trust_env = False
                return local_session.request(method, url, **kwargs)
        session.trust_env = False
        original_request = getattr(session, "_autoteam_original_request", None)
        if original_request is None:
            original_request = requests.Session.request.__get__(session, requests.Session)
        return original_request(method, url, **kwargs)

    initial_proxy = "" if should_bypass_proxy(url) else current_proxy_url()
    candidates = [initial_proxy]

    pool = ["" if item == "direct" else item for item in configured_proxy_pool()]
    if failover_enabled() and not should_bypass_proxy(url):
        for item in pool:
            if item not in candidates:
                candidates.append(item)

    last_error = None
    for proxy_url in candidates:
        try:
            response = _request_once(session, method, url, proxy_url, **kwargs)
            if not should_bypass_proxy(url):
                current = _task_proxy_var.get()
                if current is not _UNSET or _proxy_strategy() == DEFAULT_STRATEGY:
                    _task_proxy_var.set(proxy_url)
            return response
        except requests.exceptions.InvalidSchema as exc:
            if "SOCKS" in str(exc).upper():
                raise RuntimeError("当前 Python requests 环境不支持 SOCKS 代理，请安装 requests[socks] 或改用 HTTP 代理") from exc
            raise
        except requests.RequestException as exc:
            last_error = exc
            if not failover_enabled() or not _network_error(exc) or proxy_url == candidates[-1]:
                raise
            logger.warning("[代理] 当前出口不可用，尝试下一个: %s", proxy_url or "direct")

    if last_error:
        raise last_error
    return _request_once(session, method, url, initial_proxy, **kwargs)


class ProxySession:
    def __new__(cls):
        import requests

        session = requests.Session()
        session.trust_env = False
        original_request = session.request
        session._autoteam_original_request = original_request

        def _request(method, url, **kwargs):
            if "proxies" in kwargs:
                return original_request(method, url, **kwargs)
            return request(method, url, session=session, **kwargs)

        session.request = _request
        return session


def new_session():
    return ProxySession()
