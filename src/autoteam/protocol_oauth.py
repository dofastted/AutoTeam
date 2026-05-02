"""Protocol Codex OAuth login for account pool users."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import secrets
import time
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, parse_qsl, urlencode, urljoin, urlparse, urlunparse

import requests

from autoteam import outbound_proxy
from autoteam.codex_auth import (
    CODEX_AUTH_URL,
    CODEX_CLIENT_ID,
    CODEX_REDIRECT_URI,
    exchange_authorization_code,
)
from autoteam.exceptions import PhoneVerificationRequiredError, is_openai_add_phone_url

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
)

try:
    from curl_cffi.requests import Session as CurlCffiSession

    _HAS_CURL_CFFI = True
except Exception:  # pragma: no cover - depends on optional dependency
    CurlCffiSession = None
    _HAS_CURL_CFFI = False


class ProtocolOauthError(RuntimeError):
    """Base error for protocol OAuth failures."""

    reason = "protocol_oauth_error"


class ProtocolOauthStateError(ProtocolOauthError):
    reason = "state_mismatch"


class ProtocolOauthOtpTimeout(ProtocolOauthError):
    reason = "otp_timeout"


class ProtocolOauthTokenExchangeError(ProtocolOauthError):
    reason = "token_exchange_failed"


class ProtocolOauthAccountDeactivated(ProtocolOauthError):
    reason = "account_deactivated"


class ProtocolOauthNoValidOrganizations(ProtocolOauthError):
    reason = "no_valid_organizations"


class ProtocolOauthAddPhoneRequired(ProtocolOauthError):
    reason = "add-phone"

    def __init__(self, message: str = "Codex 协议登录命中 add-phone", *, email: str = ""):
        super().__init__(message)
        self.email = (email or "").strip().lower()


class ProtocolOauthRateLimited(ProtocolOauthError):
    reason = "rate_limited"


class ProtocolOauthPasswordRejected(ProtocolOauthError):
    reason = "password_rejected"


class ProtocolOauthLoginRejected(ProtocolOauthError):
    reason = "login_rejected"


class ProtocolOauthBrowserCallbackTimeout(ProtocolOauthError):
    reason = "browser_callback_timeout"


@dataclass
class ProtocolOauthResult:
    bundle: dict[str, Any]
    cookie_header: str
    callback_url: str
    final_url: str


def _b64url_no_pad(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")


def build_pkce_pair(raw_bytes: int = 64) -> tuple[str, str]:
    verifier = _b64url_no_pad(secrets.token_bytes(max(32, int(raw_bytes))))
    if len(verifier) < 43:
        verifier = (verifier + ("A" * 43))[:43]
    if len(verifier) > 128:
        verifier = verifier[:128]
    challenge = _b64url_no_pad(hashlib.sha256(verifier.encode("utf-8")).digest())
    return verifier, challenge


def build_codex_authorize_url(
    *,
    code_challenge: str,
    state: str,
    prompt: str | None = "login",
    client_id: str = CODEX_CLIENT_ID,
    redirect_uri: str = CODEX_REDIRECT_URI,
) -> str:
    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": "openid email profile offline_access",
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "id_token_add_organizations": "true",
        "codex_cli_simplified_flow": "true",
    }
    if prompt:
        params["prompt"] = prompt
    return f"{CODEX_AUTH_URL}?{urlencode(params)}"


def parse_callback_code(callback_url: str, expected_state: str = "") -> str:
    qs = parse_qs(urlparse(callback_url or "").query)
    code = (qs.get("code", [""])[0] or "").strip()
    got_state = (qs.get("state", [""])[0] or "").strip()
    if not code:
        raise ValueError("callback 缺少 code")
    if expected_state and got_state and got_state != expected_state:
        raise ProtocolOauthStateError(f"callback state 不匹配: expected={expected_state[:12]} got={got_state[:12]}")
    return code


def classify_protocol_failure(text: str) -> str:
    value = (text or "").lower()
    if "account_deactivated" in value:
        return "account_deactivated"
    if "no_valid_organizations" in value:
        return "no_valid_organizations"
    if "add-phone" in value or "add_phone" in value:
        return "add-phone"
    if "invalid_username_or_password" in value or ("密码登录失败" in value and "http 401" in value):
        return "password_rejected"
    if "rate limit" in value or "rate_limit" in value or "http 429" in value:
        return "rate_limited"
    if "otp" in value and ("timeout" in value or "超时" in value):
        return "otp_timeout"
    if "token" in value and ("exchange" in value or "交换" in value):
        return "token_exchange_failed"
    return ""


def _raise_classified(message: str) -> None:
    reason = classify_protocol_failure(message)
    if reason == "account_deactivated":
        raise ProtocolOauthAccountDeactivated(message)
    if reason == "no_valid_organizations":
        raise ProtocolOauthNoValidOrganizations(message)
    if reason == "add-phone":
        raise ProtocolOauthAddPhoneRequired(message)
    if reason == "rate_limited":
        raise ProtocolOauthRateLimited(message)
    if reason == "password_rejected":
        raise ProtocolOauthPasswordRejected(message)
    if reason == "otp_timeout":
        raise ProtocolOauthOtpTimeout(message)
    if reason == "token_exchange_failed":
        raise ProtocolOauthTokenExchangeError(message)
    raise ProtocolOauthError(message)


def _raise_if_browser_add_phone(page, email: str) -> None:
    current_url = str(getattr(page, "url", "") or "")
    if is_openai_add_phone_url(current_url):
        raise PhoneVerificationRequiredError("OpenAI 风控要求手机号验证, 跳过该账号", email=email)


def _normalize_proxy_for_curl(proxy: str) -> str:
    if proxy.startswith("socks5://"):
        return "socks5h://" + proxy[len("socks5://") :]
    return proxy


def create_protocol_session(proxy_url: str | None = None, *, impersonate: str = "chrome136"):
    proxy = outbound_proxy.current_proxy_url() if proxy_url is None else (proxy_url or "")
    if proxy == "direct":
        proxy = ""

    if _HAS_CURL_CFFI and CurlCffiSession is not None:
        session = CurlCffiSession(impersonate=impersonate)
        session.trust_env = False
        if proxy:
            normalized = _normalize_proxy_for_curl(proxy)
            session.proxies = {"http": normalized, "https": normalized}
        else:
            session.proxies = {"http": "", "https": ""}
        logger.info("[协议OAuth] HTTP client=curl_cffi impersonate=%s proxy=%s", impersonate, proxy or "direct")
        return session

    session = requests.Session()
    session.trust_env = False
    session.headers["User-Agent"] = USER_AGENT
    if proxy:
        session.proxies = {"http": proxy, "https": proxy}
    logger.info("[协议OAuth] HTTP client=requests proxy=%s", proxy or "direct")
    return session


def build_cookie_header(session, *, domain_filter: str = "chatgpt.com") -> str:
    pairs: list[tuple[str, str]] = []
    seen: set[str] = set()
    try:
        cookies = list(session.cookies)
    except Exception:
        cookies = []

    for cookie in cookies:
        name = str(getattr(cookie, "name", "") or "").strip()
        value = str(getattr(cookie, "value", "") or "")
        domain = str(getattr(cookie, "domain", "") or "").lower()
        if not name or not value or name in seen:
            continue
        if domain_filter and domain and domain_filter not in domain:
            continue
        seen.add(name)
        pairs.append((name, value))

    critical_names = (
        "__Secure-next-auth.session-token",
        "__Host-next-auth.csrf-token",
        "__Secure-next-auth.callback-url",
        "oai-did",
        "oai-sc",
        "cf_clearance",
        "__cf_bm",
        "_cfuvid",
        "oai-client-auth-info",
        "oai-gn",
        "oai-nav-state",
        "_account",
    )
    for name in critical_names:
        if name in seen:
            continue
        try:
            value = session.cookies.get(name, "")
        except Exception:
            value = ""
        if value:
            seen.add(name)
            pairs.append((name, value))

    return "; ".join(f"{name}={value}" for name, value in pairs)


def _cookie_value(session, name: str) -> str:
    try:
        return str(session.cookies.get(name, "") or "")
    except Exception:
        return ""


def _set_cookie(session, name: str, value: str, *, domain: str) -> None:
    if value:
        try:
            session.cookies.set(name, value, domain=domain, path="/")
        except Exception:
            session.cookies.set(name, value)


def _apply_cookie_header(session, cookie_header: str, *, domain: str) -> None:
    for raw in (cookie_header or "").split(";"):
        if "=" not in raw:
            continue
        name, value = raw.split("=", 1)
        name = name.strip()
        value = value.strip()
        if name and value:
            _set_cookie(session, name, value, domain=domain)


def _apply_existing_session(session, reusable_session: dict | None) -> None:
    reusable_session = reusable_session or {}
    cookie_header = str(reusable_session.get("cookie_header") or "").strip()
    if cookie_header:
        _apply_cookie_header(session, cookie_header, domain=".chatgpt.com")
        _apply_cookie_header(session, cookie_header, domain=".auth.openai.com")
    session_token = str(reusable_session.get("session_token") or "").strip()
    if session_token:
        _set_cookie(session, "__Secure-next-auth.session-token", session_token, domain=".chatgpt.com")
    device_id = str(reusable_session.get("device_id") or reusable_session.get("oai_did") or "").strip()
    if not device_id:
        match = re.search(r"(?:^|;\s*)oai-did=([^;]+)", cookie_header)
        if match:
            device_id = match.group(1)
    if not device_id:
        device_id = str(uuid.uuid4())
    _set_cookie(session, "oai-did", device_id, domain=".chatgpt.com")
    _set_cookie(session, "oai-did", device_id, domain=".auth.openai.com")

    account_id = str(reusable_session.get("account_id") or "").strip()
    if account_id:
        _set_cookie(session, "_account", account_id, domain=".chatgpt.com")
        _set_cookie(session, "_account", account_id, domain=".auth.openai.com")


def _common_headers(session, referer: str = "https://chatgpt.com/") -> dict[str, str]:
    origin = "https://chatgpt.com"
    try:
        parsed = urlparse(referer or "")
        if parsed.scheme and parsed.netloc:
            origin = f"{parsed.scheme}://{parsed.netloc}"
    except Exception:
        pass
    headers = {
        "Accept": "application/json",
        "Referer": referer,
        "Origin": origin,
        "User-Agent": USER_AGENT,
    }
    try:
        if "auth.openai.com" in (urlparse(origin).netloc or "").lower():
            device_id = _cookie_value(session, "oai-did")
            if device_id:
                headers["oai-device-id"] = device_id
    except Exception:
        pass
    return headers


def _response_json(resp) -> dict:
    try:
        data = resp.json()
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _extract_page_type(resp_json: dict | None) -> str:
    page = (resp_json or {}).get("page")
    if not isinstance(page, dict):
        return ""
    return str(page.get("type") or "").strip()


def _extract_continue_url(resp_json: dict | None) -> str:
    data = resp_json or {}
    continue_url = str(data.get("continue_url") or "").strip()
    if continue_url:
        return continue_url
    page = data.get("page")
    if not isinstance(page, dict):
        return ""
    payload = page.get("payload")
    if isinstance(payload, dict):
        return str(payload.get("url") or "").strip()
    return ""


def _normalize_url(value: str, base: str = "https://auth.openai.com") -> str:
    out = (value or "").strip()
    if out.startswith("/"):
        return urljoin(base, out)
    return out


def _drop_query_keys(url: str, drop_keys: set[str]) -> str:
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        params = parse_qsl(parsed.query, keep_blank_values=True)
        kept = [(key, val) for key, val in params if (key or "").strip() not in drop_keys]
        return urlunparse(parsed._replace(query=urlencode(kept)))
    except Exception:
        return url


def _callback_has_code(url: str, redirect_uri: str) -> bool:
    if not url:
        return False
    try:
        cb_base = (redirect_uri or "").split("?", 1)[0].rstrip("/")
        target = url.split("?", 1)[0].rstrip("/")
        return bool(cb_base and target == cb_base and (parse_qs(urlparse(url).query).get("code", [""])[0] or ""))
    except Exception:
        return False


def _callback_matches_redirect_prefix(url: str, redirect_uri: str) -> bool:
    if not url:
        return False
    try:
        parsed_redirect = urlparse(redirect_uri or CODEX_REDIRECT_URI)
        parsed_url = urlparse(url)
        if parsed_redirect.scheme and parsed_url.scheme != parsed_redirect.scheme:
            return False
        if parsed_redirect.netloc and parsed_url.netloc != parsed_redirect.netloc:
            return False
        redirect_path = (parsed_redirect.path or "").rstrip("/")
        url_path = (parsed_url.path or "").rstrip("/")
        return bool(redirect_path and url_path == redirect_path)
    except Exception:
        return False


def _extract_workspace_id_from_cookie(session) -> str:
    raw = _cookie_value(session, "oai-client-auth-session")
    for segment in (raw or "").split(".")[:2]:
        segment = segment.strip()
        if not segment:
            continue
        try:
            payload = json.loads(base64.urlsafe_b64decode((segment + "=" * (-len(segment) % 4)).encode()).decode())
        except Exception:
            continue
        if isinstance(payload, dict):
            workspace_id = str(payload.get("workspace_id") or "").strip()
            if workspace_id:
                return workspace_id
            workspaces = payload.get("workspaces")
            if isinstance(workspaces, list):
                for item in workspaces:
                    if isinstance(item, dict) and item.get("id"):
                        return str(item["id"]).strip()
    return ""


def _extract_workspace_id_from_html(html_text: str) -> str:
    text = (html_text or "").replace('\\"', '"')
    for pattern in (
        r'workspaces".{0,1600}?"id","([0-9a-fA-F-]{36})"',
        r'"workspace_id"\s*:\s*"([0-9a-fA-F-]{36})"',
        r'"workspaceId"\s*:\s*"([0-9a-fA-F-]{36})"',
    ):
        match = re.search(pattern, text, flags=re.DOTALL | re.IGNORECASE)
        if match:
            return (match.group(1) or "").strip()
    return ""


def _extract_unified_session_id_from_html(html_text: str) -> str:
    text = html_text or ""
    candidates: list[str] = []
    for pattern in (
        r'"id","(us_[A-Za-z0-9]+)"',
        r'\\"id\\",\\"(us_[A-Za-z0-9]+)\\"',
        r"\bus_[A-Za-z0-9]+\b",
    ):
        for match in re.finditer(pattern, text):
            value = (match.group(1) if match.groups() else match.group(0)).strip()
            if value and value != "us_capture" and value not in candidates:
                candidates.append(value)
    return candidates[0] if candidates else ""


def _session_has_chatgpt_login(session) -> bool:
    if _cookie_value(session, "__Secure-next-auth.session-token"):
        return True
    try:
        return any(
            str(getattr(cookie, "name", "") or "").startswith("__Secure-next-auth.session-token")
            for cookie in session.cookies
        )
    except Exception:
        return False


def _select_unified_session(session, unified_session_id: str) -> str:
    if not unified_session_id:
        return ""
    headers = _common_headers(session, "https://auth.openai.com/choose-an-account")
    headers["Content-Type"] = "application/json"
    resp = session.post(
        "https://auth.openai.com/api/accounts/session/select",
        headers=headers,
        json={"session_id": unified_session_id},
        timeout=30,
        allow_redirects=False,
    )
    if resp.status_code in (301, 302, 303, 307, 308):
        return _normalize_url(str(resp.headers.get("Location", "") or ""))
    if resp.status_code != 200:
        return ""
    return _normalize_url(_extract_continue_url(_response_json(resp)))


def _workspace_select(session, workspace_id: str) -> str:
    if not workspace_id:
        return ""
    headers = _common_headers(session, "https://auth.openai.com/sign-in-with-chatgpt/codex/consent")
    headers["Content-Type"] = "application/json"
    resp = session.post(
        "https://auth.openai.com/api/accounts/workspace/select",
        headers=headers,
        json={"workspace_id": workspace_id},
        timeout=30,
    )
    if resp.status_code != 200:
        return ""
    return _normalize_url(_extract_continue_url(_response_json(resp)))


def follow_authorize_for_callback(session, start_url: str, redirect_uri: str = CODEX_REDIRECT_URI) -> tuple[str, str]:
    current = start_url
    callback_url = ""
    for _ in range(12):
        if _callback_has_code(current, redirect_uri):
            return current, current
        resp = session.get(
            current,
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Referer": "https://chatgpt.com/",
                "User-Agent": USER_AGENT,
            },
            timeout=30,
            allow_redirects=False,
        )
        body = str(getattr(resp, "text", "") or "")
        if resp.status_code == 200 and "/choose-an-account" in current:
            unified_session_id = _extract_unified_session_id_from_html(body)
            next_url = _select_unified_session(session, unified_session_id)
            if next_url:
                current = next_url
                continue
        if resp.status_code == 200 and any(marker in current for marker in ("/workspace", "/consent", "/sign-in-with-chatgpt/")):
            workspace_id = _extract_workspace_id_from_cookie(session) or _extract_workspace_id_from_html(body)
            next_url = _workspace_select(session, workspace_id)
            if next_url:
                current = next_url
                continue
        if resp.status_code == 200 and any(marker in current for marker in ("/log-in", "/create-account")):
            return "", current
        if resp.status_code not in (301, 302, 303, 307, 308):
            _raise_classified(f"Codex OAuth 未获得 callback: status={resp.status_code} url={current} body={body[:240]}")
        location = str(resp.headers.get("Location", "") or "").strip()
        if not location:
            break
        if location.startswith("/"):
            location = urljoin(current, location)
        if _callback_has_code(location, redirect_uri):
            callback_url = location
            current = location
            break
        current = location
    return callback_url, current


def exchange_callback_for_bundle(
    session,
    callback_url: str,
    *,
    expected_state: str,
    code_verifier: str,
    fallback_email: str = "",
    client_id: str = CODEX_CLIENT_ID,
    redirect_uri: str = CODEX_REDIRECT_URI,
) -> dict[str, Any]:
    del client_id, redirect_uri
    code = parse_callback_code(callback_url, expected_state)
    bundle = exchange_authorization_code(code, code_verifier, fallback_email=fallback_email)
    if not bundle:
        raise ProtocolOauthTokenExchangeError("Codex token 交换失败")
    bundle["plan_type"] = str(bundle.get("plan_type") or "unknown").strip().lower()
    bundle["cookie_header"] = build_cookie_header(session)
    if not bundle["refresh_token"]:
        raise ProtocolOauthTokenExchangeError("Codex token 交换成功但未返回 refresh_token")
    return bundle


def _browser_object_page(page_or_context):
    if hasattr(page_or_context, "goto") and hasattr(page_or_context, "url"):
        return page_or_context
    if hasattr(page_or_context, "new_page"):
        return page_or_context.new_page()
    raise ProtocolOauthError("浏览器 OAuth 需要 Page 或 BrowserContext")


def _safe_browser_context_for_page(page):
    try:
        return page.context
    except Exception:
        return None


def _browser_context_cookies_to_session(session, context) -> None:
    if context is None:
        return
    try:
        cookies = context.cookies()
    except Exception:
        return
    for cookie in cookies or []:
        if not isinstance(cookie, dict):
            continue
        name = str(cookie.get("name") or "").strip()
        value = str(cookie.get("value") or "")
        domain = str(cookie.get("domain") or "").strip()
        if not name or not value:
            continue
        if not domain:
            domain = ".chatgpt.com"
        _set_cookie(session, name, value, domain=domain)


def _extract_browser_callback_url(page, expected_state: str, redirect_uri: str) -> str:
    candidates: list[str] = []
    try:
        candidates.append(str(page.url or ""))
    except Exception:
        pass
    for url in reversed(candidates):
        if _callback_has_code(url, redirect_uri):
            try:
                parse_callback_code(url, expected_state)
            except Exception:
                continue
            return url
    return ""


def _browser_wait_for_callback(page, *, expected_state: str, redirect_uri: str, timeout_ms: int) -> str:
    deadline = time.time() + max(3, int(timeout_ms or 60000) / 1000)
    while time.time() < deadline:
        callback_url = _extract_browser_callback_url(page, expected_state, redirect_uri)
        if callback_url:
            return callback_url
        try:
            page.wait_for_timeout(500)
        except Exception:
            time.sleep(0.5)
    raise ProtocolOauthBrowserCallbackTimeout(f"浏览器 OAuth 未获取 callback: {getattr(page, 'url', '')}")


_BROWSER_AUTH_EMAIL_SELECTORS = (
    'input[type="email"], input[name="email"], input[name="username"], '
    'input[autocomplete="username"], input[autocomplete="email"], '
    'input[id="email-input"], input[id="email"], '
    'input[placeholder*="email" i], input[placeholder*="Email" i]'
)
_BROWSER_AUTH_PASSWORD_SELECTORS = 'input[type="password"], input[name="password"], input[id="password"]'
_BROWSER_AUTH_CODE_SELECTORS = (
    'input[name="code"], input[name="otp"], input[autocomplete="one-time-code"], '
    'input[placeholder*="验证码"], input[placeholder*="code" i], '
    'input[inputmode="numeric"], input[maxlength="1"], input[type="text"]'
)


def _is_browser_auth_login_url(url: str) -> bool:
    parsed = urlparse(url or "")
    if parsed.netloc != "auth.openai.com":
        return False
    path = (parsed.path or "").rstrip("/") or "/"
    return path == "/log-in" or path.startswith("/log-in/") or path.startswith("/log-in-or-create-account")


def _is_browser_oauth_consent_url(url: str) -> bool:
    path = (urlparse(url or "").path or "").lower()
    return (
        "/sign-in-with-chatgpt" in path
        or "/consent" in path
        or "/oauth/authorize/consent" in path
    )


def _is_browser_oauth_account_chooser_url(url: str) -> bool:
    host_path = str(url or "").split("?")[0].lower()
    return "auth.openai.com/choose-an-account" in host_path


def _visible_browser_locator(page, selectors: str, *, timeout_ms: int = 1000):
    try:
        locator = page.locator(selectors).first
        if locator.is_visible(timeout=timeout_ms):
            return locator
    except Exception:
        return None
    return None


def _editable_browser_locator(page, selectors: str, *, timeout_ms: int = 1000):
    locator = _visible_browser_locator(page, selectors, timeout_ms=timeout_ms)
    if locator is None:
        return None
    try:
        if not locator.is_editable(timeout=timeout_ms):
            return None
    except Exception:
        pass
    return locator


def _wait_browser_auth_page_ready(page) -> None:
    try:
        page.wait_for_load_state("domcontentloaded")
    except Exception:
        pass
    try:
        page.wait_for_load_state("networkidle", timeout=8000)
    except Exception:
        pass


def _browser_page_content_excerpt(page, limit: int = 800) -> str:
    try:
        content = page.content()
    except Exception as exc:
        return f"<content unavailable: {exc}>"
    return str(content or "")[:limit].replace("\n", " ")


def _retry_editable_browser_locator(
    page,
    selectors: str,
    *,
    timeout_ms: int = 8000,
    retry_sleep_seconds: float = 1.5,
):
    locator = _editable_browser_locator(page, selectors, timeout_ms=timeout_ms)
    if locator is not None:
        return locator
    time.sleep(retry_sleep_seconds)
    return _editable_browser_locator(page, selectors, timeout_ms=timeout_ms)


def _click_browser_auth_continue(page, field=None) -> bool:
    labels = ["Continue", "继续", "Log in", "登录", "Verify", "Submit", "Allow"]
    label_re = re.compile(rf"^(?:{'|'.join(re.escape(label) for label in labels)})$", re.I)

    if field is not None:
        try:
            form = field.locator("xpath=ancestor::form[1]").first
            btn = form.get_by_role("button", name=label_re).first
            if btn.is_visible(timeout=1500):
                btn.click()
                return True
        except Exception:
            pass
        try:
            form = field.locator("xpath=ancestor::form[1]").first
            btn = form.locator('button[type="submit"], input[type="submit"]').first
            if btn.is_visible(timeout=1500):
                btn.click()
                return True
        except Exception:
            pass

    for selector in (
        'button[type="submit"]',
        'button:has-text("Continue")',
        'button:has-text("继续")',
        'button:has-text("Log in")',
        'button:has-text("登录")',
        'button:has-text("Verify")',
        'button:has-text("Submit")',
        'button:has-text("Allow")',
    ):
        try:
            btn = page.locator(selector).first
            if btn.is_visible(timeout=500):
                btn.click()
                return True
        except Exception:
            pass

    if field is not None:
        try:
            field.press("Enter")
            return True
        except Exception:
            pass
    return False


def _click_browser_oauth_consent(page) -> bool:
    labels = ["Authorize", "Allow", "Continue", "Approve", "继续", "授权", "同意"]
    selectors = []
    for label in labels:
        selectors.append(f'button:has-text("{label}")')
    selectors.extend(
        [
            'button[type="submit"]',
            '[role="button"]:has-text("Authorize")',
            '[role="button"]:has-text("Allow")',
            '[role="button"]:has-text("Continue")',
            '[role="button"]:has-text("Approve")',
            '[role="button"]:has-text("继续")',
            '[role="button"]:has-text("授权")',
            '[role="button"]:has-text("同意")',
        ]
    )
    for selector in selectors:
        try:
            target = page.locator(selector).first
            if target.is_visible(timeout=1500):
                target.click(timeout=3000)
                return True
        except Exception:
            pass
    return False


def _click_browser_account_chooser(page, *, email: str) -> bool:
    email = (email or "").strip().lower()
    if email:
        escaped_email = email.replace("\\", "\\\\").replace('"', '\\"')
        for selector in (
            f'a:has-text("{escaped_email}")',
            f'button:has-text("{escaped_email}")',
            f'[role="button"]:has-text("{escaped_email}")',
            f'div.account-item:has-text("{escaped_email}")',
            f'[data-testid*="account"]:has-text("{escaped_email}")',
            f'[class*="account"]:has-text("{escaped_email}")',
        ):
            try:
                target = page.locator(selector).first
                if target.is_visible(timeout=1000):
                    target.click(timeout=3000)
                    return True
            except Exception:
                pass

    labels = [
        "Use a different account",
        "Use another account",
        "Continue with another account",
        "继续使用其它账号",
        "继续使用其他账号",
        "使用其他账号",
        "使用其它账号",
    ]
    for label in labels:
        escaped_label = label.replace("\\", "\\\\").replace('"', '\\"')
        for selector in (
            f'a:has-text("{escaped_label}")',
            f'button:has-text("{escaped_label}")',
            f'[role="button"]:has-text("{escaped_label}")',
        ):
            try:
                target = page.locator(selector).first
                if target.is_visible(timeout=1000):
                    target.click(timeout=3000)
                    return True
            except Exception:
                pass
    return False


def _force_logout_and_retry_oauth(page, *, oauth_url: str, max_attempts: int = 1) -> bool:
    """Visit OpenAI logout, clear browser state best-effort, then retry OAuth."""
    attempts = max(1, int(max_attempts or 1))
    for _attempt in range(attempts):
        page.goto("https://auth.openai.com/logout", wait_until="networkidle", timeout=20000)
        time.sleep(1.0)
        try:
            page.evaluate("() => { localStorage.clear(); sessionStorage.clear(); }")
        except Exception:
            pass
        try:
            page.context.clear_cookies()
        except Exception:
            pass
        page.goto(oauth_url, wait_until="domcontentloaded", timeout=30000)
        _wait_browser_auth_page_ready(page)
        if not _is_browser_oauth_account_chooser_url(str(getattr(page, "url", "") or "")):
            return True
    return False


def _handle_browser_account_chooser(page, *, email: str, oauth_url: str) -> None:
    if _click_browser_account_chooser(page, email=email):
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass
        return

    logger.warning("[协议OAuth] 账号选择页无法点击目标项，尝试 logout 后重新进入 OAuth: %s", email)
    if not _force_logout_and_retry_oauth(page, oauth_url=oauth_url):
        raise ProtocolOauthLoginRejected("OpenAI /choose-an-account 页无法识别选项")


def _handle_browser_oauth_consent(page, *, callback_holder: dict[str, str] | None = None) -> None:
    for attempt in range(2):
        _wait_browser_auth_page_ready(page)
        if callback_holder and callback_holder.get("url"):
            return
        if not _is_browser_oauth_consent_url(str(getattr(page, "url", "") or "")):
            return
        logger.info("[协议OAuth] 浏览器登录步骤: 点击 Codex 授权按钮 attempt=%d", attempt + 1)
        if not _click_browser_oauth_consent(page):
            continue
        wait_deadline = time.time() + 3
        while time.time() < wait_deadline:
            if callback_holder and callback_holder.get("url"):
                return
            if not _is_browser_oauth_consent_url(str(getattr(page, "url", "") or "")):
                return
            try:
                page.wait_for_timeout(500)
            except Exception:
                time.sleep(0.5)

    if _is_browser_oauth_consent_url(str(getattr(page, "url", "") or "")):
        raise ProtocolOauthError(
            "Codex consent 页缺少 Authorize 按钮: "
            f"url={getattr(page, 'url', '')} callback_holder={dict(callback_holder or {})} "
            f"html={_browser_page_content_excerpt(page)}"
        )


def _browser_auth_step(page, *, expected_state: str, redirect_uri: str) -> str:
    try:
        current_url = str(page.url or "")
    except Exception:
        current_url = ""
    if _callback_has_code(current_url, redirect_uri):
        try:
            parse_callback_code(current_url, expected_state)
            return "callback"
        except Exception:
            pass

    parsed = urlparse(current_url)
    path = (parsed.path or "").lower()
    if is_openai_add_phone_url(current_url):
        return "add_phone"
    if "password" in path or _editable_browser_locator(page, _BROWSER_AUTH_PASSWORD_SELECTORS, timeout_ms=300):
        return "password"
    if (
        "verify" in path
        or "verification" in path
        or "email-otp" in path
        or _visible_browser_locator(page, _BROWSER_AUTH_CODE_SELECTORS, timeout_ms=300)
    ):
        return "otp"
    if _is_browser_auth_login_url(current_url):
        return "email"
    if _is_browser_oauth_consent_url(current_url):
        return "consent"
    if "authorize" in path:
        return "authorize"
    if _editable_browser_locator(page, _BROWSER_AUTH_EMAIL_SELECTORS, timeout_ms=300):
        return "email"
    return "unknown"


def _wait_browser_auth_step_change(page, previous: str, *, expected_state: str, redirect_uri: str, timeout_seconds: int) -> str:
    deadline = time.time() + max(1, int(timeout_seconds or 1))
    current = previous
    while time.time() < deadline:
        current = _browser_auth_step(page, expected_state=expected_state, redirect_uri=redirect_uri)
        if current != previous or current in {"callback", "authorize"}:
            return current
        try:
            page.wait_for_timeout(500)
        except Exception:
            time.sleep(0.5)
    return current


def _find_browser_otp_inputs(page, *, timeout_ms: int = 8000) -> list:
    try:
        inputs = [
            item
            for item in page.locator('input[maxlength="1"], input[inputmode="numeric"]').all()
            if item.is_visible(timeout=200)
        ]
        if len(inputs) >= 4:
            return inputs
    except Exception:
        pass
    locator = _visible_browser_locator(page, _BROWSER_AUTH_CODE_SELECTORS, timeout_ms=timeout_ms)
    return [locator] if locator is not None else []


def _fill_browser_otp(page, otp: str) -> bool:
    inputs = _find_browser_otp_inputs(page, timeout_ms=8000)
    if not inputs or not otp:
        return False
    if len(inputs) >= 4:
        for index, char in enumerate(str(otp)):
            if index >= len(inputs):
                break
            inputs[index].fill(char)
            time.sleep(0.05)
        return True
    inputs[0].fill(str(otp))
    return True


def _drive_browser_auth_login(
    page,
    *,
    email: str,
    password: str,
    mail_client,
    mail_account_id=None,
    callback_holder: dict[str, str],
    expected_state: str,
    redirect_uri: str,
    auth_url: str,
    timeout_ms: int,
) -> None:
    deadline = time.time() + max(10, int(timeout_ms or 90000) / 1000)
    email_submitted = False
    password_submitted = False
    otp_submitted = False
    retried_authorize = False

    logger.info("[协议OAuth] auth.openai.com 需要重新登录: %s", email)
    while time.time() < deadline:
        _wait_browser_auth_page_ready(page)
        _raise_if_browser_add_phone(page, email)
        if _is_browser_oauth_account_chooser_url(str(getattr(page, "url", "") or "")):
            logger.info("[协议OAuth] 浏览器登录步骤: 处理账号选择页 %s", email)
            _handle_browser_account_chooser(page, email=email, oauth_url=auth_url)
            continue
        callback_url = callback_holder.get("url") or _extract_browser_callback_url(page, expected_state, redirect_uri)
        if callback_url:
            return

        step = _browser_auth_step(page, expected_state=expected_state, redirect_uri=redirect_uri)
        if step == "add_phone":
            _raise_if_browser_add_phone(page, email)
        if step == "email":
            logger.info("[协议OAuth] 浏览器登录步骤: 输入邮箱 %s", email)
            email_input = _retry_editable_browser_locator(page, _BROWSER_AUTH_EMAIL_SELECTORS, timeout_ms=8000)
            if email_input is None:
                logger.warning(
                    "[协议OAuth] 浏览器 OAuth 登录页缺少邮箱输入框 url=%s html=%s",
                    getattr(page, "url", ""),
                    _browser_page_content_excerpt(page),
                )
                raise ProtocolOauthError(f"浏览器 OAuth 登录页缺少邮箱输入框: {getattr(page, 'url', '')}")
            email_input.fill(email)
            if not _click_browser_auth_continue(page, email_input):
                raise ProtocolOauthError("浏览器 OAuth 邮箱页无法点击 Continue")
            email_submitted = True
            _wait_browser_auth_step_change(
                page,
                "email",
                expected_state=expected_state,
                redirect_uri=redirect_uri,
                timeout_seconds=12,
            )
            _raise_if_browser_add_phone(page, email)
            continue

        if step == "password":
            if not password:
                raise ProtocolOauthError("浏览器 OAuth 密码页缺少密码")
            logger.info("[协议OAuth] 浏览器登录步骤: 输入密码")
            password_input = _retry_editable_browser_locator(page, _BROWSER_AUTH_PASSWORD_SELECTORS, timeout_ms=8000)
            if password_input is None:
                logger.warning(
                    "[协议OAuth] 浏览器 OAuth 密码页缺少密码输入框 url=%s html=%s",
                    getattr(page, "url", ""),
                    _browser_page_content_excerpt(page),
                )
                raise ProtocolOauthError(f"浏览器 OAuth 密码页缺少密码输入框: {getattr(page, 'url', '')}")
            password_input.fill(password)
            if not _click_browser_auth_continue(page, password_input):
                raise ProtocolOauthError("浏览器 OAuth 密码页无法点击 Continue")
            password_submitted = True
            _wait_browser_auth_step_change(
                page,
                "password",
                expected_state=expected_state,
                redirect_uri=redirect_uri,
                timeout_seconds=15,
            )
            _raise_if_browser_add_phone(page, email)
            continue

        if step == "otp":
            if mail_client is None:
                raise ProtocolOauthError("浏览器 OAuth OTP 页缺少邮箱客户端")
            logger.info("[协议OAuth] 浏览器登录步骤: 等待邮箱验证码")
            otp_timeout = max(15, min(90, int(deadline - time.time())))
            otp = _poll_email_otp(
                mail_client,
                email,
                mail_account_id=mail_account_id,
                timeout_seconds=otp_timeout,
            )
            logger.info("[协议OAuth] 浏览器登录步骤: 输入邮箱验证码")
            if not _fill_browser_otp(page, otp):
                logger.warning(
                    "[协议OAuth] 浏览器 OAuth OTP 页缺少验证码输入框 url=%s html=%s",
                    getattr(page, "url", ""),
                    _browser_page_content_excerpt(page),
                )
                raise ProtocolOauthError("浏览器 OAuth OTP 页无法填写验证码")
            otp_inputs = _find_browser_otp_inputs(page, timeout_ms=8000)
            field = otp_inputs[0] if otp_inputs else None
            if not _click_browser_auth_continue(page, field):
                logger.debug("[协议OAuth] OTP 输入后未找到 Continue，等待页面自动提交")
            otp_submitted = True
            _wait_browser_auth_step_change(
                page,
                "otp",
                expected_state=expected_state,
                redirect_uri=redirect_uri,
                timeout_seconds=15,
            )
            _raise_if_browser_add_phone(page, email)
            continue

        if step == "consent":
            _handle_browser_oauth_consent(page, callback_holder=callback_holder)
            continue

        if step in {"authorize", "unknown"}:
            if not retried_authorize and (email_submitted or password_submitted or otp_submitted):
                retried_authorize = True
                try:
                    page.goto(auth_url, wait_until="domcontentloaded", timeout=max(5000, min(timeout_ms, 30000)))
                    _raise_if_browser_add_phone(page, email)
                except Exception as exc:
                    if isinstance(exc, PhoneVerificationRequiredError):
                        raise
                    current_url = str(getattr(page, "url", "") or "")
                    if callback_holder.get("url") or _callback_has_code(current_url, redirect_uri):
                        return
                    logger.debug("[协议OAuth] 重新访问 authorize 后仍未到 callback: %s", exc)
                continue

        try:
            page.wait_for_timeout(500)
        except Exception:
            time.sleep(0.5)

    raise ProtocolOauthBrowserCallbackTimeout(f"浏览器 OAuth 登录后未获取 callback: {getattr(page, 'url', '')}")


def run_protocol_oauth_login_with_browser_context(
    page_or_context,
    email: str,
    *,
    password: str = "",
    mail_client=None,
    mail_account_id=None,
    timeout_ms: int = 60000,
    login_timeout_ms: int = 90000,
    client_id: str = CODEX_CLIENT_ID,
    redirect_uri: str = CODEX_REDIRECT_URI,
) -> ProtocolOauthResult:
    """Use the already logged-in browser context to complete Codex PKCE OAuth."""
    email = (email or "").strip().lower()
    password = password or ""
    if not email:
        raise ProtocolOauthError("浏览器 OAuth 缺少邮箱")

    page = _browser_object_page(page_or_context)
    context = _safe_browser_context_for_page(page)
    verifier, challenge = build_pkce_pair()
    state = _b64url_no_pad(secrets.token_bytes(24))
    auth_url = build_codex_authorize_url(
        code_challenge=challenge,
        state=state,
        prompt=None,
        client_id=client_id,
        redirect_uri=redirect_uri,
    )
    callback_holder: dict[str, str] = {"url": ""}
    route_registered = False
    event_handlers: list[tuple[str, Any]] = []

    def remember_callback_url(url: str, *, source: str) -> bool:
        value = str(url or "").strip()
        if not _callback_matches_redirect_prefix(value, redirect_uri):
            return False
        callback_holder["url"] = value
        callback_holder["source"] = source
        logger.info("[协议OAuth] 捕获浏览器 OAuth callback: source=%s url=%s", source, value)
        return True

    def capture_callback(route):
        try:
            remember_callback_url(route.request.url, source="route")
        except Exception:
            pass
        try:
            route.abort()
        except Exception:
            pass

    if context is not None:
        try:
            context.route("**/auth/callback*", capture_callback)
            route_registered = True
        except Exception as exc:
            logger.debug("[协议OAuth] callback route 注册失败，改用 URL 轮询: %s", exc)

    def capture_request(request):
        try:
            remember_callback_url(request.url, source="request")
        except Exception:
            pass

    def capture_frame_navigation(frame):
        try:
            remember_callback_url(frame.url, source="framenavigated")
        except Exception:
            pass

    try:
        page.on("request", capture_request)
        event_handlers.append(("request", capture_request))
    except Exception as exc:
        logger.debug("[协议OAuth] request 事件监听失败: %s", exc)
    try:
        page.on("framenavigated", capture_frame_navigation)
        event_handlers.append(("framenavigated", capture_frame_navigation))
    except Exception as exc:
        logger.debug("[协议OAuth] framenavigated 事件监听失败: %s", exc)

    try:
        logger.info("[协议OAuth] 浏览器内打开 Codex PKCE OAuth: %s", email)
        try:
            page.goto(auth_url, wait_until="domcontentloaded", timeout=timeout_ms)
            _raise_if_browser_add_phone(page, email)
            if _is_browser_oauth_account_chooser_url(str(getattr(page, "url", "") or "")):
                logger.info("[协议OAuth] 浏览器 OAuth 进入账号选择页: %s", email)
                _handle_browser_account_chooser(page, email=email, oauth_url=auth_url)
        except Exception as exc:
            if isinstance(exc, PhoneVerificationRequiredError):
                raise
            current_url = str(getattr(page, "url", "") or "")
            if callback_holder.get("url") or _callback_has_code(current_url, redirect_uri):
                logger.debug("[协议OAuth] callback 导航被本地端口拒绝，继续交换 token: %s", exc)
            else:
                raise

        callback_url = callback_holder.get("url") or _extract_browser_callback_url(page, state, redirect_uri)
        if not callback_url:
            current_url = str(getattr(page, "url", "") or "")
            _raise_if_browser_add_phone(page, email)
            if _is_browser_oauth_account_chooser_url(current_url):
                logger.info("[协议OAuth] 浏览器 OAuth 等待 callback 前处理账号选择页: %s", email)
                _handle_browser_account_chooser(page, email=email, oauth_url=auth_url)
                current_url = str(getattr(page, "url", "") or "")
                callback_url = callback_holder.get("url") or _extract_browser_callback_url(page, state, redirect_uri)
            if _is_browser_auth_login_url(current_url):
                _drive_browser_auth_login(
                    page,
                    email=email,
                    password=password,
                    mail_client=mail_client,
                    mail_account_id=mail_account_id,
                    callback_holder=callback_holder,
                    expected_state=state,
                    redirect_uri=redirect_uri,
                    auth_url=auth_url,
                    timeout_ms=login_timeout_ms,
                )
                callback_url = callback_holder.get("url") or _extract_browser_callback_url(page, state, redirect_uri)
            if not callback_url:
                _raise_if_browser_add_phone(page, email)
                callback_url = _browser_wait_for_callback(
                    page,
                    expected_state=state,
                    redirect_uri=redirect_uri,
                    timeout_ms=timeout_ms,
                )
        parse_callback_code(callback_url, state)

        session = create_protocol_session()
        _browser_context_cookies_to_session(session, context)
        bundle = exchange_callback_for_bundle(
            session,
            callback_url,
            expected_state=state,
            code_verifier=verifier,
            fallback_email=email,
            client_id=client_id,
            redirect_uri=redirect_uri,
        )
        bundle["credential_source"] = "oauth"
        if not bundle.get("cookie_header"):
            bundle["cookie_header"] = build_cookie_header(session)
        logger.info("[协议OAuth] 浏览器内 Codex RT 获取成功: %s plan=%s", email, bundle.get("plan_type"))
        return ProtocolOauthResult(
            bundle=bundle,
            cookie_header=str(bundle.get("cookie_header") or ""),
            callback_url=callback_url,
            final_url=str(getattr(page, "url", "") or ""),
        )
    finally:
        if route_registered and context is not None:
            try:
                context.unroute("**/auth/callback*", capture_callback)
            except Exception:
                pass
        for event_name, handler in event_handlers:
            try:
                page.off(event_name, handler)
            except Exception:
                pass


def _poll_email_otp(mail_client, email: str, *, mail_account_id=None, timeout_seconds: int = 180) -> str:
    deadline = time.time() + max(30, int(timeout_seconds or 180))
    seen: set[object] = set()
    while time.time() < deadline:
        try:
            emails = mail_client.search_emails_by_recipient(email, size=5, account_id=mail_account_id)
        except TypeError:
            emails = mail_client.search_emails_by_recipient(email, size=5)
        except Exception:
            emails = []
        for item in emails or []:
            email_id = item.get("emailId") or item.get("id")
            if email_id in seen:
                continue
            sender = str(item.get("sendEmail") or item.get("sender") or item.get("from") or "").lower()
            subject = str(item.get("subject") or "").lower()
            if "invite" in subject or "invited" in subject:
                continue
            if sender and not any(keyword in sender for keyword in ("openai", "chatgpt")):
                continue
            detail = item
            get_by_id = getattr(mail_client, "get_email_by_id", None)
            if callable(get_by_id) and email_id is not None:
                try:
                    detail = get_by_id(mail_account_id, email_id, to_email=email)
                except TypeError:
                    detail = get_by_id(mail_account_id, email_id)
                except Exception:
                    detail = item
            if detail is None:
                detail = item
            otp = mail_client.extract_verification_code(detail)
            if otp:
                return str(otp)
        time.sleep(3)
    raise ProtocolOauthOtpTimeout(f"等待邮箱 OTP 超时: {email}")


def _send_or_resend_otp(session) -> None:
    for method, url, referer in (
        ("POST", "https://auth.openai.com/api/accounts/passwordless/send-otp", "https://auth.openai.com/create-account/password"),
        ("POST", "https://auth.openai.com/api/accounts/email-otp/resend", "https://auth.openai.com/email-verification"),
        ("GET", "https://auth.openai.com/api/accounts/email-otp/send", "https://auth.openai.com/create-account/password"),
    ):
        headers = _common_headers(session, referer)
        headers["Content-Type"] = "application/json"
        resp = session.request(method, url, headers=headers, timeout=30)
        if resp.status_code == 200:
            return
    raise ProtocolOauthError("邮箱 OTP 发送失败")


def _authorize_continue(session, email: str, *, screen_hint: str, referer: str) -> dict[str, Any]:
    headers = _common_headers(session, referer)
    headers["Content-Type"] = "application/json"
    resp = session.post(
        "https://auth.openai.com/api/accounts/authorize/continue",
        headers=headers,
        json={"username": {"value": email, "kind": "email"}, "screen_hint": screen_hint},
        timeout=30,
    )
    if resp.status_code != 200:
        _raise_classified(f"authorize/continue 失败: HTTP {resp.status_code} {(resp.text or '')[:260]}")
    return _response_json(resp)


def _login_password_verify(session, password: str) -> dict[str, Any]:
    headers = _common_headers(session, "https://auth.openai.com/log-in/password")
    headers["Content-Type"] = "application/json"
    resp = session.post(
        "https://auth.openai.com/api/accounts/password/verify",
        headers=headers,
        json={"password": password},
        timeout=30,
    )
    if resp.status_code != 200:
        _raise_classified(f"密码登录失败: HTTP {resp.status_code} {(resp.text or '')[:260]}")
    return _response_json(resp)


def _validate_email_otp(session, otp_code: str) -> dict[str, Any]:
    headers = _common_headers(session, "https://auth.openai.com/email-verification")
    headers["Content-Type"] = "application/json"
    resp = session.post(
        "https://auth.openai.com/api/accounts/email-otp/validate",
        headers=headers,
        json={"code": otp_code},
        timeout=30,
    )
    if resp.status_code != 200:
        _raise_classified(f"OTP 验证失败: HTTP {resp.status_code} {(resp.text or '')[:260]}")
    return _response_json(resp)


def _drive_email_otp_verification(session, mail_client, email: str, *, mail_account_id=None) -> dict[str, Any]:
    _send_or_resend_otp(session)
    otp = _poll_email_otp(
        mail_client,
        email,
        mail_account_id=mail_account_id,
        timeout_seconds=int(os.getenv("EMAIL_POLL_TIMEOUT", "180") or 180),
    )
    return _validate_email_otp(session, otp)


def _drive_login_from_log_in(
    session,
    *,
    email: str,
    password: str,
    mail_client,
    mail_account_id=None,
) -> str:
    step = _authorize_continue(session, email, screen_hint="login", referer="https://auth.openai.com/log-in")
    page_type = _extract_page_type(step).lower()
    continue_url = _normalize_url(_extract_continue_url(step))
    if page_type == "login_password" or "/log-in/password" in continue_url:
        try:
            step = _login_password_verify(session, password)
        except ProtocolOauthPasswordRejected as exc:
            logger.warning("[协议OAuth] 密码登录被拒，改用邮箱 OTP 登录: %s", exc)
            step = _drive_email_otp_verification(
                session,
                mail_client,
                email,
                mail_account_id=mail_account_id,
            )
        page_type = _extract_page_type(step).lower()
        continue_url = _normalize_url(_extract_continue_url(step))

    if page_type == "add_phone" or "add-phone" in continue_url:
        raise ProtocolOauthAddPhoneRequired("Codex 协议登录命中 add-phone")

    if page_type == "email_otp_verification" or "/email-verification" in continue_url:
        step = _drive_email_otp_verification(session, mail_client, email, mail_account_id=mail_account_id)
        continue_url = _normalize_url(_extract_continue_url(step))
        page_type = _extract_page_type(step).lower()
        if page_type == "add_phone" or "add-phone" in continue_url:
            raise ProtocolOauthAddPhoneRequired("Codex 协议登录命中 add-phone")
    return continue_url


def get_chatgpt_auth_session(session) -> tuple[str, str, dict[str, Any]]:
    try:
        resp = session.get(
            "https://chatgpt.com/api/auth/session",
            headers=_common_headers(session, "https://chatgpt.com/"),
            timeout=30,
        )
    except Exception as exc:
        logger.warning("[协议OAuth] ChatGPT session 补充读取失败，继续保留 OAuth RT: %s", exc)
        return "", "", {}
    if resp.status_code != 200:
        return "", "", {}
    data = _response_json(resp)
    session_token = _cookie_value(session, "__Secure-next-auth.session-token")
    access_token = str(data.get("accessToken") or data.get("access_token") or "")
    return session_token, access_token, data


def run_protocol_oauth_login(
    email: str,
    password: str,
    *,
    mail_client,
    mail_account_id=None,
    reusable_session: dict | None = None,
    hcaptcha_solver=None,
) -> ProtocolOauthResult:
    """Log in through HTTP protocol and exchange Codex OAuth code for RT."""
    email = (email or "").strip().lower()
    if not email:
        raise ProtocolOauthError("协议 OAuth 缺少邮箱")
    if mail_client is None:
        raise ProtocolOauthError("协议 OAuth 缺少邮箱客户端")
    session = create_protocol_session()
    _apply_existing_session(session, reusable_session)

    if callable(hcaptcha_solver):
        logger.info("[协议OAuth] hCaptcha solver 已配置，可在协议链路需要时调用")

    verifier, challenge = build_pkce_pair()
    state = _b64url_no_pad(secrets.token_bytes(24))
    has_reusable_login = _session_has_chatgpt_login(session)
    prompt = None if has_reusable_login else "login"
    auth_url = build_codex_authorize_url(code_challenge=challenge, state=state, prompt=prompt)
    callback_url, final_url = follow_authorize_for_callback(session, auth_url)

    if not callback_url and has_reusable_login:
        no_prompt_url = _drop_query_keys(auth_url, {"prompt"})
        callback_url, final_url = follow_authorize_for_callback(session, no_prompt_url)

    if not callback_url and "/log-in" in (final_url or ""):
        continue_url = _drive_login_from_log_in(
            session,
            email=email,
            password=password,
            mail_client=mail_client,
            mail_account_id=mail_account_id,
        )
        if continue_url:
            callback_url, final_url = follow_authorize_for_callback(session, continue_url)

    if not callback_url:
        no_prompt_url = _drop_query_keys(auth_url, {"prompt"})
        callback_url, final_url = follow_authorize_for_callback(session, no_prompt_url)

    if not callback_url:
        _raise_classified(f"Codex 协议 OAuth 未获取 callback: {final_url}")

    bundle = exchange_callback_for_bundle(
        session,
        callback_url,
        expected_state=state,
        code_verifier=verifier,
        fallback_email=email,
    )
    session_token, access_token, _session_data = get_chatgpt_auth_session(session)
    if session_token:
        bundle["session_token"] = session_token
    if access_token:
        bundle["chatgpt_access_token"] = access_token
    bundle["cookie_header"] = build_cookie_header(session)
    bundle["credential_source"] = "oauth"
    logger.info("[协议OAuth] Codex RT 获取成功: %s plan=%s", bundle.get("email") or email, bundle.get("plan_type"))
    return ProtocolOauthResult(
        bundle=bundle,
        cookie_header=str(bundle.get("cookie_header") or ""),
        callback_url=callback_url,
        final_url=final_url,
    )


def solve_hcaptcha_remote(
    *,
    api_key: str,
    website_url: str,
    website_key: str,
    api_url: str = "",
    rqdata: str = "",
    is_invisible: bool = True,
    max_retries: int = 3,
    poll_attempts: int = 60,
) -> tuple[str, str]:
    """Minimal createTask/getTaskResult hCaptcha client migrated for optional protocol use."""
    api_base = (api_url or os.getenv("HCAPTCHA_API_URL", "") or os.getenv("CTF_CAPTCHA_API_URL", "")).rstrip("/")
    client_key = (api_key or os.getenv("HCAPTCHA_API_KEY", "") or os.getenv("CTF_CAPTCHA_API_KEY", "")).strip()
    if not api_base or not client_key:
        raise ProtocolOauthError("hCaptcha solver 缺少 API 地址或 API Key")

    for retry in range(max(1, int(max_retries))):
        if retry:
            time.sleep(3)
        task = {
            "type": "HCaptchaTaskProxyless",
            "websiteURL": website_url,
            "websiteKey": website_key,
            "isEnterprise": True,
            "userAgent": USER_AGENT,
        }
        if is_invisible:
            task["isInvisible"] = True
        if rqdata:
            task["rqdata"] = rqdata
        create_resp = requests.post(f"{api_base}/createTask", json={"clientKey": client_key, "task": task}, timeout=15)
        create_data = create_resp.json()
        if create_data.get("errorId", 1) != 0:
            continue
        task_id = create_data.get("taskId")
        for _ in range(max(1, int(poll_attempts))):
            time.sleep(3)
            result_resp = requests.post(
                f"{api_base}/getTaskResult",
                json={"clientKey": client_key, "taskId": task_id},
                timeout=10,
            )
            result_data = result_resp.json()
            if result_data.get("status") != "ready":
                continue
            solution = result_data.get("solution") or {}
            token = solution.get("gRecaptchaResponse") or solution.get("token") or ""
            ekey = solution.get("eKey") or solution.get("respKey") or solution.get("ekey") or ""
            if token:
                return token, ekey
    raise ProtocolOauthError("hCaptcha solver 未返回可用 token")
