"""Proxy node API integration.

This module keeps provider-specific node fetching separate from the existing
outbound proxy selector. The selector still owns task-local proxy choice; this
module only refreshes the configured pool when requested.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlsplit

from autoteam import outbound_proxy
from autoteam.textio import parse_env_value

logger = logging.getLogger(__name__)

PROVIDER_NONE = "none"
PROVIDER_WEBSHARE = "webshare"
SUPPORTED_PROVIDERS = {PROVIDER_NONE, PROVIDER_WEBSHARE}
DEFAULT_PROVIDER = PROVIDER_NONE
DEFAULT_PROTOCOL = "http"
SUPPORTED_PROTOCOLS = {"http", "socks5", "socks5h"}
DEFAULT_WEB_SHARE_BASE_URL = "https://proxy.webshare.io/api/v2"
DEFAULT_POLL_INTERVAL_SECONDS = 5
DEFAULT_POLL_TIMEOUT_SECONDS = 120

_refresh_lock = threading.Lock()
_last_refresh: dict[str, Any] = {}


class ProxyNodeError(RuntimeError):
    """Raised when proxy node fetching or normalization fails."""


class ProxyNodeQuotaExhausted(ProxyNodeError):
    """Raised when the remote provider has no replacement quota left."""


@dataclass(frozen=True)
class ProxyNodeConfig:
    provider: str
    api_key: str
    base_url: str
    protocol: str
    enabled: bool
    auto_refresh: bool
    refresh_before_task: bool
    poll_interval_seconds: int
    poll_timeout_seconds: int
    country: str
    apply_to_outbound_pool: bool


def _bool_env(name: str, default: bool) -> bool:
    raw = parse_env_value(os.environ.get(name, "true" if default else "false")).strip().lower()
    if raw in {"1", "true", "yes", "y", "on"}:
        return True
    if raw in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _int_env(name: str, default: int, *, minimum: int = 1) -> int:
    raw = parse_env_value(os.environ.get(name, str(default))).strip()
    try:
        value = int(raw)
    except Exception:
        value = default
    return max(minimum, value)


def _normalize_provider(value: str) -> str:
    provider = parse_env_value(value or DEFAULT_PROVIDER).strip().lower() or DEFAULT_PROVIDER
    return provider if provider in SUPPORTED_PROVIDERS else DEFAULT_PROVIDER


def _normalize_protocol(value: str) -> str:
    protocol = parse_env_value(value or DEFAULT_PROTOCOL).strip().lower() or DEFAULT_PROTOCOL
    if protocol not in SUPPORTED_PROTOCOLS:
        raise ProxyNodeError(f"不支持的代理节点协议: {protocol}")
    return protocol


def get_config() -> ProxyNodeConfig:
    provider = _normalize_provider(os.environ.get("PROXY_NODE_PROVIDER", DEFAULT_PROVIDER))
    return ProxyNodeConfig(
        provider=provider,
        api_key=parse_env_value(os.environ.get("PROXY_NODE_API_KEY", "")).strip(),
        base_url=parse_env_value(os.environ.get("PROXY_NODE_BASE_URL", DEFAULT_WEB_SHARE_BASE_URL)).strip()
        or DEFAULT_WEB_SHARE_BASE_URL,
        protocol=_normalize_protocol(os.environ.get("PROXY_NODE_PROTOCOL", DEFAULT_PROTOCOL)),
        enabled=_bool_env("PROXY_NODE_ENABLED", provider != PROVIDER_NONE),
        auto_refresh=_bool_env("PROXY_NODE_AUTO_REFRESH", False),
        refresh_before_task=_bool_env("PROXY_NODE_REFRESH_BEFORE_TASK", True),
        poll_interval_seconds=_int_env(
            "PROXY_NODE_POLL_INTERVAL_SECONDS",
            DEFAULT_POLL_INTERVAL_SECONDS,
            minimum=1,
        ),
        poll_timeout_seconds=_int_env(
            "PROXY_NODE_POLL_TIMEOUT_SECONDS",
            DEFAULT_POLL_TIMEOUT_SECONDS,
            minimum=1,
        ),
        country=parse_env_value(os.environ.get("PROXY_NODE_COUNTRY", "")).strip().upper(),
        apply_to_outbound_pool=_bool_env("PROXY_NODE_APPLY_TO_OUTBOUND_POOL", True),
    )


def _provider_headers(config: ProxyNodeConfig) -> dict[str, str]:
    if not config.api_key:
        raise ProxyNodeError("PROXY_NODE_API_KEY 为空")
    return {
        "Authorization": f"Token {config.api_key}",
        "Content-Type": "application/json",
    }


def _provider_url(config: ProxyNodeConfig, path: str) -> str:
    return config.base_url.rstrip("/") + "/" + path.lstrip("/")


def _request_json(config: ProxyNodeConfig, method: str, path: str, **kwargs):
    response = outbound_proxy.request(
        method,
        _provider_url(config, path),
        headers=_provider_headers(config),
        timeout=kwargs.pop("timeout", 30),
        **kwargs,
    )
    if response.status_code >= 400:
        body = ""
        try:
            body = response.text[:300]
        except Exception:
            body = ""
        lowered = body.lower()
        if response.status_code in (402, 429) or "quota" in lowered or "exhaust" in lowered or "limit" in lowered:
            raise ProxyNodeQuotaExhausted(f"节点 API 配额不足: http={response.status_code} body={body}")
        raise ProxyNodeError(f"节点 API 请求失败: http={response.status_code} body={body}")
    if response.status_code == 204:
        return None
    try:
        return response.json()
    except Exception as exc:
        raise ProxyNodeError("节点 API 返回了非 JSON 响应") from exc


def get_replacement_quota(config: ProxyNodeConfig | None = None) -> dict[str, Any]:
    config = config or get_config()
    data = _request_json(config, "GET", "/subscription/plan/")
    plans = data.get("results") if isinstance(data, dict) else []
    plan = next((item for item in plans or [] if item.get("status") == "active"), None)
    plan = plan or ((plans or [{}])[0] if isinstance(plans, list) else {})
    return {
        "total": int(plan.get("proxy_replacements_total", 0) or 0),
        "used": int(plan.get("proxy_replacements_used", 0) or 0),
        "available": int(plan.get("proxy_replacements_available", 0) or 0),
        "updated_at": plan.get("updated_at", ""),
    }


def _webshare_current_proxy(config: ProxyNodeConfig | None = None) -> dict[str, Any]:
    config = config or get_config()
    data = _request_json(config, "GET", "/proxy/list/?mode=direct&page=1&page_size=5")
    results = data.get("results") if isinstance(data, dict) else []
    if not results:
        raise ProxyNodeError("节点 API 代理列表为空")
    return results[0]


def _refresh_webshare_pool(config: ProxyNodeConfig) -> None:
    kwargs = {}
    if config.country:
        kwargs["json"] = {"countries": {config.country: 1}}
    response = outbound_proxy.request(
        "POST",
        _provider_url(config, "/proxy/list/refresh/"),
        headers=_provider_headers(config),
        timeout=30,
        **kwargs,
    )
    if response.status_code == 204:
        return
    body_text = ""
    try:
        body_text = response.text[:300]
    except Exception:
        pass
    lowered = body_text.lower()
    if response.status_code in (402, 429) or "quota" in lowered or "exhaust" in lowered or "limit" in lowered:
        raise ProxyNodeQuotaExhausted(f"节点 API 配额不足: http={response.status_code} body={body_text}")
    raise ProxyNodeError(f"节点 API refresh 失败: http={response.status_code} body={body_text}")


def _wait_for_fresh_webshare_proxy(config: ProxyNodeConfig, *, previous_ip: str = "") -> dict[str, Any]:
    deadline = time.time() + config.poll_timeout_seconds
    last = None
    while time.time() < deadline:
        try:
            current = _webshare_current_proxy(config)
            last = current
            address = str(current.get("proxy_address") or "")
            if current.get("valid") and (not previous_ip or address != previous_ip):
                return current
        except Exception as exc:
            logger.warning("[代理节点] 查询当前节点失败: %s", exc)
        time.sleep(config.poll_interval_seconds)
    if last is not None:
        return last
    raise ProxyNodeError("等待新代理节点超时")


def _proxy_url_from_node(node: dict[str, Any], protocol: str) -> str:
    address = str(node.get("proxy_address") or node.get("host") or "").strip()
    port = str(node.get("port") or "").strip()
    username = str(node.get("username") or "").strip()
    password = str(node.get("password") or "").strip()
    if not address or not port:
        raise ProxyNodeError("节点缺少 proxy_address 或 port")
    auth = ""
    if username:
        auth = quote(username, safe="")
        if password:
            auth += ":" + quote(password, safe="")
        auth += "@"
    return outbound_proxy.normalize_proxy_url(f"{protocol}://{auth}{address}:{port}")


def get_current_proxy_node(config: ProxyNodeConfig | None = None) -> dict[str, Any]:
    config = config or get_config()
    if config.provider != PROVIDER_WEBSHARE:
        raise ProxyNodeError(f"未知代理节点提供者: {config.provider}")
    node = _webshare_current_proxy(config)
    proxy_url = _proxy_url_from_node(node, config.protocol)
    return {
        "provider": config.provider,
        "proxy_url": proxy_url,
        "node": _sanitize_node(node),
    }


def _sanitize_node(node: dict[str, Any]) -> dict[str, Any]:
    result = dict(node or {})
    if result.get("password"):
        result["password"] = "***"
    return result


def _current_outbound_pool() -> str:
    return os.environ.get("OUTBOUND_PROXY_POOL", outbound_proxy.DEFAULT_PROXY_URL).strip()


def _apply_proxy_url_to_outbound_pool(proxy_url: str) -> None:
    os.environ["OUTBOUND_PROXY_ENABLED"] = "true"
    os.environ["OUTBOUND_PROXY_POOL"] = proxy_url


def refresh_proxy_node(
    config: ProxyNodeConfig | None = None,
    *,
    force_rotate: bool = True,
    apply: bool | None = None,
) -> dict[str, Any]:
    config = config or get_config()
    if not config.enabled or config.provider == PROVIDER_NONE:
        return {
            "enabled": False,
            "provider": config.provider,
            "message": "代理节点接口未启用",
            "applied": False,
        }
    if config.provider != PROVIDER_WEBSHARE:
        raise ProxyNodeError(f"未知代理节点提供者: {config.provider}")

    with _refresh_lock:
        previous = None
        previous_ip = ""
        if force_rotate:
            try:
                previous = _webshare_current_proxy(config)
                previous_ip = str(previous.get("proxy_address") or "")
            except Exception as exc:
                logger.warning("[代理节点] 读取旧节点失败，继续 refresh: %s", exc)
            quota = get_replacement_quota(config)
            if quota["available"] <= 0:
                raise ProxyNodeQuotaExhausted(f"节点替换额度不足: {quota}")
            _refresh_webshare_pool(config)
            node = _wait_for_fresh_webshare_proxy(config, previous_ip=previous_ip)
        else:
            quota = get_replacement_quota(config)
            node = _webshare_current_proxy(config)

        proxy_url = _proxy_url_from_node(node, config.protocol)
        applied = config.apply_to_outbound_pool if apply is None else bool(apply)
        before_pool = _current_outbound_pool()
        if applied:
            _apply_proxy_url_to_outbound_pool(proxy_url)
        result = {
            "enabled": True,
            "provider": config.provider,
            "protocol": config.protocol,
            "proxy_url": proxy_url,
            "applied": applied,
            "previous_proxy_pool": before_pool,
            "quota": quota,
            "node": _sanitize_node(node),
            "previous_node": _sanitize_node(previous or {}),
            "refreshed_at": time.time(),
        }
        _last_refresh.clear()
        _last_refresh.update(result)
        return result


def maybe_refresh_before_task() -> dict[str, Any] | None:
    config = get_config()
    if not (config.enabled and config.auto_refresh and config.refresh_before_task):
        return None
    return refresh_proxy_node(config, force_rotate=True, apply=config.apply_to_outbound_pool)


def status() -> dict[str, Any]:
    config = get_config()
    current = {}
    if config.enabled and config.provider != PROVIDER_NONE and config.api_key:
        try:
            current = get_current_proxy_node(config)
        except Exception as exc:
            current = {"error": str(exc)}
    return {
        "enabled": config.enabled,
        "provider": config.provider,
        "protocol": config.protocol,
        "auto_refresh": config.auto_refresh,
        "refresh_before_task": config.refresh_before_task,
        "poll_interval_seconds": config.poll_interval_seconds,
        "poll_timeout_seconds": config.poll_timeout_seconds,
        "country": config.country,
        "apply_to_outbound_pool": config.apply_to_outbound_pool,
        "outbound_proxy_pool": _current_outbound_pool(),
        "current": current,
        "last_refresh": dict(_last_refresh),
    }


def protocol_from_proxy_url(proxy_url: str) -> str:
    scheme = urlsplit(proxy_url).scheme.lower()
    if scheme in SUPPORTED_PROTOCOLS:
        return scheme
    return ""
