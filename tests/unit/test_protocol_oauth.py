import base64
import json
import time
from urllib.parse import parse_qs, urlparse

import pytest

from autoteam import protocol_oauth
from autoteam.codex_auth import CODEX_CLIENT_ID, CODEX_REDIRECT_URI
from autoteam.exceptions import PhoneVerificationRequiredError


def _jwt(payload):
    header = base64.urlsafe_b64encode(b'{"alg":"none"}').decode().rstrip("=")
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"{header}.{body}.sig"


def test_build_codex_authorize_url_uses_pkce_and_offline_scope():
    url = protocol_oauth.build_codex_authorize_url(code_challenge="challenge-1", state="state-1")
    parsed = urlparse(url)
    params = parse_qs(parsed.query)

    assert parsed.scheme == "https"
    assert parsed.netloc == "auth.openai.com"
    assert params["client_id"] == [CODEX_CLIENT_ID]
    assert params["redirect_uri"] == [CODEX_REDIRECT_URI]
    assert params["code_challenge"] == ["challenge-1"]
    assert params["code_challenge_method"] == ["S256"]
    assert params["state"] == ["state-1"]
    assert "offline_access" in params["scope"][0]
    assert params["codex_cli_simplified_flow"] == ["true"]


def test_parse_callback_code_validates_state():
    callback = f"{CODEX_REDIRECT_URI}?code=abc&state=good"

    assert protocol_oauth.parse_callback_code(callback, "good") == "abc"
    with pytest.raises(protocol_oauth.ProtocolOauthStateError):
        protocol_oauth.parse_callback_code(callback, "bad")
    with pytest.raises(ValueError):
        protocol_oauth.parse_callback_code(f"{CODEX_REDIRECT_URI}?state=good", "good")


class _Cookie:
    def __init__(self, name, value, domain):
        self.name = name
        self.value = value
        self.domain = domain


class _Cookies:
    def __init__(self):
        self._items = []

    def set(self, name, value, domain=None, path="/"):
        self._items.append(_Cookie(name, value, domain or ""))

    def get(self, name, default=""):
        for item in reversed(self._items):
            if item.name == name:
                return item.value
        return default

    def __iter__(self):
        return iter(self._items)


class _Response:
    def __init__(self, status_code=200, data=None, text="", headers=None):
        self.status_code = status_code
        self._data = data or {}
        self.text = text
        self.headers = headers or {}

    def json(self):
        return self._data


class _TokenSession:
    def __init__(self, response):
        self.response = response
        self.cookies = _Cookies()
        self.posts = []
        self.cookies.set("__Secure-next-auth.session-token", "sess-1", domain=".chatgpt.com")
        self.cookies.set("oai-did", "did-1", domain=".chatgpt.com")

    def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        return self.response


def test_exchange_callback_for_bundle_builds_oauth_bundle_and_cookie_header():
    id_token = _jwt(
        {
            "email": "user@example.com",
            "https://api.openai.com/auth": {
                "chatgpt_account_id": "acc-1",
                "chatgpt_plan_type": "team",
            },
        }
    )
    session = _TokenSession(
        _Response(
            data={
                "access_token": "at-1",
                "refresh_token": "rt-1",
                "id_token": id_token,
                "expires_in": 3600,
            }
        )
    )

    bundle = protocol_oauth.exchange_callback_for_bundle(
        session,
        f"{CODEX_REDIRECT_URI}?code=code-1&state=state-1",
        expected_state="state-1",
        code_verifier="verifier-1",
        fallback_email="fallback@example.com",
    )

    assert bundle["refresh_token"] == "rt-1"
    assert bundle["access_token"] == "at-1"
    assert bundle["email"] == "user@example.com"
    assert bundle["account_id"] == "acc-1"
    assert bundle["plan_type"] == "team"
    assert "__Secure-next-auth.session-token=sess-1" in bundle["cookie_header"]
    assert session.posts[0][0].endswith("/oauth/token")
    assert session.posts[0][1]["data"]["code_verifier"] == "verifier-1"


def test_run_protocol_oauth_with_browser_context_captures_callback_and_exchanges(monkeypatch):
    expected_state = "c3RhdGUtMQ"

    class RouteRequest:
        url = f"{CODEX_REDIRECT_URI}?code=code-1&state={expected_state}"

    class Route:
        request = RouteRequest()

        def abort(self):
            self.aborted = True

    class Context:
        def __init__(self):
            self.routes = []
            self.unroutes = []

        def route(self, pattern, handler):
            self.routes.append((pattern, handler))

        def unroute(self, pattern, handler):
            self.unroutes.append((pattern, handler))

        def cookies(self):
            return [
                {
                    "name": "__Secure-next-auth.session-token",
                    "value": "sess-browser",
                    "domain": ".chatgpt.com",
                }
            ]

    class Page:
        def __init__(self, context):
            self.context = context
            self.url = "https://chatgpt.com/admin/members"
            self.goto_urls = []

        def goto(self, url, **_kwargs):
            self.goto_urls.append(url)
            self.context.routes[0][1](Route())
            self.url = "chrome-error://chromewebdata/"

        def wait_for_timeout(self, _timeout):
            raise AssertionError("callback should be captured by route")

    context = Context()
    page = Page(context)
    session = _TokenSession(_Response())
    monkeypatch.setattr(protocol_oauth, "create_protocol_session", lambda: session)
    monkeypatch.setattr(protocol_oauth, "build_pkce_pair", lambda: ("verifier-1", "challenge-1"))
    monkeypatch.setattr(protocol_oauth.secrets, "token_bytes", lambda _size: b"state-1")
    monkeypatch.setattr(
        protocol_oauth,
        "exchange_callback_for_bundle",
        lambda _session, callback_url, **kwargs: {
            "email": "user@example.com",
            "access_token": "at-1",
            "refresh_token": "rt-1",
            "id_token": "id-1",
            "account_id": "acc-1",
            "plan_type": "team",
            "expired": 2000000000,
            "callback_url": callback_url,
            "code_verifier": kwargs["code_verifier"],
        },
    )

    result = protocol_oauth.run_protocol_oauth_login_with_browser_context(page, "user@example.com")

    assert result.bundle["refresh_token"] == "rt-1"
    assert result.bundle["credential_source"] == "oauth"
    assert result.bundle["callback_url"] == f"{CODEX_REDIRECT_URI}?code=code-1&state={expected_state}"
    assert result.bundle["code_verifier"] == "verifier-1"
    assert "prompt=login" not in page.goto_urls[0]
    assert session.cookies.get("__Secure-next-auth.session-token") == "sess-browser"
    assert context.unroutes


def test_run_protocol_oauth_with_browser_context_logs_in_when_authorize_lands_on_log_in(monkeypatch):
    expected_state = "c3RhdGUtMQ"

    class RouteRequest:
        url = f"{CODEX_REDIRECT_URI}?code=code-1&state={expected_state}"

    class Route:
        request = RouteRequest()

        def abort(self):
            self.aborted = True

    class FakeLocator:
        def __init__(self, page, kind):
            self.page = page
            self.kind = kind

        @property
        def first(self):
            return self

        def is_visible(self, timeout=0):
            if self.kind == "email":
                return self.page.url == "https://auth.openai.com/log-in"
            if self.kind == "password":
                return self.page.url == "https://auth.openai.com/log-in/password"
            if self.kind == "submit":
                return self.page.url.startswith("https://auth.openai.com/log-in")
            return False

        def is_editable(self, timeout=0):
            return self.is_visible(timeout=timeout)

        def fill(self, value):
            self.page.fills.append((self.kind, value))

        def click(self):
            self.page.clicks.append(self.kind)
            if self.page.url == "https://auth.openai.com/log-in":
                self.page.url = "https://auth.openai.com/log-in/password"
            elif self.page.url == "https://auth.openai.com/log-in/password":
                self.page.url = "https://auth.openai.com/authorize/continue"

        def locator(self, _selector):
            return FakeLocator(self.page, "missing")

        def get_by_role(self, *_args, **_kwargs):
            return FakeLocator(self.page, "missing")

        def press(self, _key):
            self.click()

    class Context:
        def __init__(self):
            self.routes = []
            self.unroutes = []

        def route(self, pattern, handler):
            self.routes.append((pattern, handler))

        def unroute(self, pattern, handler):
            self.unroutes.append((pattern, handler))

        def cookies(self):
            return []

    class Page:
        def __init__(self, context):
            self.context = context
            self.url = "https://chatgpt.com/admin/members"
            self.goto_urls = []
            self.fills = []
            self.clicks = []

        def goto(self, url, **_kwargs):
            self.goto_urls.append(url)
            if len(self.goto_urls) == 1:
                self.url = "https://auth.openai.com/log-in"
            else:
                self.context.routes[0][1](Route())
                self.url = "chrome-error://chromewebdata/"

        def locator(self, selector):
            if "email" in selector or "username" in selector:
                return FakeLocator(self, "email")
            if "password" in selector:
                return FakeLocator(self, "password")
            if "submit" in selector or "Continue" in selector or "Log in" in selector:
                return FakeLocator(self, "submit")
            return FakeLocator(self, "missing")

        def wait_for_timeout(self, _timeout):
            pass

    context = Context()
    page = Page(context)
    session = _TokenSession(_Response())
    monkeypatch.setattr(protocol_oauth, "create_protocol_session", lambda: session)
    monkeypatch.setattr(protocol_oauth, "build_pkce_pair", lambda: ("verifier-1", "challenge-1"))
    monkeypatch.setattr(protocol_oauth.secrets, "token_bytes", lambda _size: b"state-1")
    monkeypatch.setattr(
        protocol_oauth,
        "exchange_callback_for_bundle",
        lambda _session, callback_url, **_kwargs: {
            "email": "user@example.com",
            "access_token": "at-1",
            "refresh_token": "rt-1",
            "id_token": "id-1",
            "account_id": "acc-1",
            "plan_type": "team",
            "expired": 2000000000,
            "callback_url": callback_url,
        },
    )

    result = protocol_oauth.run_protocol_oauth_login_with_browser_context(
        page,
        "user@example.com",
        password="pw-1",
        timeout_ms=1000,
        login_timeout_ms=5000,
    )

    assert result.bundle["refresh_token"] == "rt-1"
    assert page.fills == [("email", "user@example.com"), ("password", "pw-1")]
    assert len(page.goto_urls) == 2
    assert "prompt=login" not in page.goto_urls[0]
    assert result.callback_url == f"{CODEX_REDIRECT_URI}?code=code-1&state={expected_state}"


def test_run_protocol_oauth_with_browser_context_raises_on_add_phone(monkeypatch):
    class Context:
        def route(self, _pattern, _handler):
            pass

        def unroute(self, _pattern, _handler):
            pass

        def cookies(self):
            return []

    class Page:
        def __init__(self):
            self.context = Context()
            self.url = "https://chatgpt.com/admin/members"

        def goto(self, _url, **_kwargs):
            self.url = "https://auth.openai.com/add-phone"

        def on(self, _event_name, _handler):
            pass

        def off(self, _event_name, _handler):
            pass

    monkeypatch.setattr(protocol_oauth, "build_pkce_pair", lambda: ("verifier-1", "challenge-1"))
    monkeypatch.setattr(protocol_oauth.secrets, "token_bytes", lambda _size: b"state-1")

    with pytest.raises(PhoneVerificationRequiredError, match="手机号验证"):
        protocol_oauth.run_protocol_oauth_login_with_browser_context(
            Page(),
            "risk@example.com",
            password="pw-1",
            timeout_ms=1000,
            login_timeout_ms=1000,
        )


def test_click_browser_account_chooser_prefers_matching_email():
    class Locator:
        def __init__(self, page, selector):
            self.page = page
            self.selector = selector

        @property
        def first(self):
            return self

        def is_visible(self, timeout=0):
            return "user@example.com" in self.selector

        def click(self, **_kwargs):
            self.page.clicks.append(self.selector)

    class Page:
        def __init__(self):
            self.clicks = []

        def locator(self, selector):
            return Locator(self, selector)

    page = Page()

    assert protocol_oauth._click_browser_account_chooser(page, email="user@example.com")
    assert page.clicks
    assert "user@example.com" in page.clicks[0]


def test_drive_browser_auth_login_clicks_use_different_account(monkeypatch):
    class Locator:
        def __init__(self, page, selector):
            self.page = page
            self.selector = selector

        @property
        def first(self):
            return self

        def is_visible(self, timeout=0):
            return "Use a different account" in self.selector

        def click(self, **_kwargs):
            self.page.clicks.append(self.selector)
            self.page.url = f"{CODEX_REDIRECT_URI}?code=code-1&state=state-1"

    class Page:
        def __init__(self):
            self.url = "https://auth.openai.com/choose-an-account"
            self.clicks = []
            self.load_states = []

        def locator(self, selector):
            return Locator(self, selector)

        def wait_for_load_state(self, state, **_kwargs):
            self.load_states.append(state)

        def wait_for_timeout(self, _timeout):
            pass

    page = Page()
    monkeypatch.setattr(protocol_oauth, "_wait_browser_auth_page_ready", lambda _page: None)

    protocol_oauth._drive_browser_auth_login(
        page,
        email="user@example.com",
        password="pw-1",
        mail_client=None,
        callback_holder={"url": ""},
        expected_state="state-1",
        redirect_uri=CODEX_REDIRECT_URI,
        auth_url="https://auth.openai.com/oauth/authorize",
        timeout_ms=10000,
    )

    assert any("Use a different account" in selector for selector in page.clicks)
    assert "networkidle" in page.load_states


def test_drive_browser_auth_login_logs_out_when_account_chooser_has_no_visible_options(monkeypatch):
    class Locator:
        def __init__(self, page, kind):
            self.page = page
            self.kind = kind

        @property
        def first(self):
            return self

        def is_visible(self, timeout=0):
            if self.kind == "email":
                return self.page.url == "https://auth.openai.com/log-in"
            if self.kind == "password":
                return self.page.url == "https://auth.openai.com/log-in/password"
            if self.kind == "submit":
                return self.page.url.startswith("https://auth.openai.com/log-in")
            return False

        def is_editable(self, timeout=0):
            return self.kind in {"email", "password"} and self.is_visible(timeout=timeout)

        def fill(self, value):
            self.page.fills.append((self.kind, value))

        def click(self, **_kwargs):
            self.page.clicks.append(self.kind)
            if self.page.url == "https://auth.openai.com/log-in":
                self.page.url = "https://auth.openai.com/log-in/password"
            elif self.page.url == "https://auth.openai.com/log-in/password":
                self.page.url = f"{CODEX_REDIRECT_URI}?code=code-1&state=state-1"

        def locator(self, _selector):
            return Locator(self.page, "missing")

        def get_by_role(self, *_args, **_kwargs):
            return Locator(self.page, "missing")

    class Context:
        def __init__(self, page):
            self.page = page
            self.clear_count = 0

        def clear_cookies(self):
            self.clear_count += 1

    class Page:
        def __init__(self):
            self.url = "https://auth.openai.com/choose-an-account"
            self.goto_urls = []
            self.fills = []
            self.clicks = []
            self.context = Context(self)

        def locator(self, selector):
            if self.url == "https://auth.openai.com/choose-an-account":
                return Locator(self, "missing")
            if "email" in selector or "username" in selector:
                return Locator(self, "email")
            if "password" in selector:
                return Locator(self, "password")
            if "submit" in selector or "Continue" in selector or "Log in" in selector:
                return Locator(self, "submit")
            return Locator(self, "missing")

        def goto(self, url, **_kwargs):
            self.goto_urls.append(url)
            if url == "https://auth.openai.com/logout":
                self.url = "https://auth.openai.com/loggedout"
            else:
                self.url = "https://auth.openai.com/log-in"

        def wait_for_load_state(self, *_args, **_kwargs):
            pass

        def wait_for_timeout(self, _timeout):
            pass

        def evaluate(self, _script):
            pass

    page = Page()
    monkeypatch.setattr(protocol_oauth.time, "sleep", lambda _seconds: None)

    protocol_oauth._drive_browser_auth_login(
        page,
        email="user@example.com",
        password="pw-1",
        mail_client=None,
        callback_holder={"url": ""},
        expected_state="state-1",
        redirect_uri=CODEX_REDIRECT_URI,
        auth_url="https://auth.openai.com/oauth/authorize",
        timeout_ms=10000,
    )

    assert page.goto_urls[:2] == ["https://auth.openai.com/logout", "https://auth.openai.com/oauth/authorize"]
    assert page.context.clear_count == 1
    assert page.fills == [("email", "user@example.com"), ("password", "pw-1")]


def test_drive_browser_auth_login_rejects_when_logout_still_returns_account_chooser(monkeypatch):
    class Locator:
        @property
        def first(self):
            return self

        def is_visible(self, timeout=0):
            return False

    class Page:
        def __init__(self):
            self.url = "https://auth.openai.com/choose-an-account"
            self.goto_urls = []
            self.context = self

        def locator(self, _selector):
            return Locator()

        def goto(self, url, **_kwargs):
            self.goto_urls.append(url)
            self.url = "https://auth.openai.com/choose-an-account"

        def wait_for_load_state(self, *_args, **_kwargs):
            pass

        def clear_cookies(self):
            pass

    monkeypatch.setattr(protocol_oauth.time, "sleep", lambda _seconds: None)

    with pytest.raises(protocol_oauth.ProtocolOauthLoginRejected, match="choose-an-account"):
        protocol_oauth._drive_browser_auth_login(
            Page(),
            email="user@example.com",
            password="pw-1",
            mail_client=None,
            callback_holder={"url": ""},
            expected_state="state-1",
            redirect_uri=CODEX_REDIRECT_URI,
            auth_url="https://auth.openai.com/oauth/authorize",
            timeout_ms=10000,
        )


def test_run_protocol_oauth_with_browser_context_clicks_consent_after_login(monkeypatch):
    expected_state = "c3RhdGUtMQ"

    class RouteRequest:
        url = f"{CODEX_REDIRECT_URI}?code=code-1&state={expected_state}"

    class Route:
        request = RouteRequest()

        def abort(self):
            self.aborted = True

    class FakeLocator:
        def __init__(self, page, kind):
            self.page = page
            self.kind = kind

        @property
        def first(self):
            return self

        def is_visible(self, timeout=0):
            if self.kind == "email":
                return self.page.url == "https://auth.openai.com/log-in"
            if self.kind == "password":
                return self.page.url == "https://auth.openai.com/log-in/password"
            if self.kind == "submit":
                return self.page.url.startswith("https://auth.openai.com/log-in")
            if self.kind == "consent":
                return self.page.url == "https://auth.openai.com/sign-in-with-chatgpt/codex/consent"
            return False

        def is_editable(self, timeout=0):
            return self.kind in {"email", "password"} and self.is_visible(timeout=timeout)

        def fill(self, value):
            self.page.fills.append((self.kind, value))

        def click(self, **_kwargs):
            self.page.clicks.append(self.kind)
            if self.page.url == "https://auth.openai.com/log-in":
                self.page.url = "https://auth.openai.com/log-in/password"
            elif self.page.url == "https://auth.openai.com/log-in/password":
                self.page.url = "https://auth.openai.com/sign-in-with-chatgpt/codex/consent"
            elif self.page.url == "https://auth.openai.com/sign-in-with-chatgpt/codex/consent":
                self.page.context.routes[0][1](Route())
                self.page.url = "chrome-error://chromewebdata/"

        def locator(self, _selector):
            return FakeLocator(self.page, "missing")

        def get_by_role(self, *_args, **_kwargs):
            return FakeLocator(self.page, "missing")

        def press(self, _key):
            self.click()

    class Context:
        def __init__(self):
            self.routes = []
            self.unroutes = []

        def route(self, pattern, handler):
            self.routes.append((pattern, handler))

        def unroute(self, pattern, handler):
            self.unroutes.append((pattern, handler))

        def cookies(self):
            return []

    class Page:
        def __init__(self, context):
            self.context = context
            self.url = "https://chatgpt.com/admin/members"
            self.goto_urls = []
            self.fills = []
            self.clicks = []

        def goto(self, url, **_kwargs):
            self.goto_urls.append(url)
            self.url = "https://auth.openai.com/log-in"

        def locator(self, selector):
            if "email" in selector or "username" in selector:
                return FakeLocator(self, "email")
            if "password" in selector:
                return FakeLocator(self, "password")
            if "Authorize" in selector or "Allow" in selector or "Continue" in selector or "Approve" in selector:
                if self.url.endswith("/consent") and "button" in selector:
                    return FakeLocator(self, "consent")
                return FakeLocator(self, "submit")
            if "submit" in selector:
                return FakeLocator(self, "submit")
            return FakeLocator(self, "missing")

        def wait_for_timeout(self, _timeout):
            pass

        def wait_for_load_state(self, *_args, **_kwargs):
            pass

        def content(self):
            return "<html><button>Authorize</button></html>"

    context = Context()
    page = Page(context)
    session = _TokenSession(_Response())
    monkeypatch.setattr(protocol_oauth, "create_protocol_session", lambda: session)
    monkeypatch.setattr(protocol_oauth, "build_pkce_pair", lambda: ("verifier-1", "challenge-1"))
    monkeypatch.setattr(protocol_oauth.secrets, "token_bytes", lambda _size: b"state-1")
    monkeypatch.setattr(
        protocol_oauth,
        "exchange_callback_for_bundle",
        lambda _session, callback_url, **_kwargs: {
            "email": "user@example.com",
            "access_token": "at-1",
            "refresh_token": "rt-1",
            "id_token": "id-1",
            "account_id": "acc-1",
            "plan_type": "team",
            "expired": 2000000000,
            "callback_url": callback_url,
        },
    )

    result = protocol_oauth.run_protocol_oauth_login_with_browser_context(
        page,
        "user@example.com",
        password="pw-1",
        timeout_ms=1000,
        login_timeout_ms=5000,
    )

    assert result.bundle["refresh_token"] == "rt-1"
    assert page.fills == [("email", "user@example.com"), ("password", "pw-1")]
    assert "consent" in page.clicks
    assert result.callback_url == f"{CODEX_REDIRECT_URI}?code=code-1&state={expected_state}"


def test_run_protocol_oauth_with_browser_context_captures_callback_from_request_event(monkeypatch):
    expected_state = "c3RhdGUtMQ"

    class Request:
        url = f"{CODEX_REDIRECT_URI}?code=code-1&state={expected_state}"

    class FakeLocator:
        def __init__(self, page, kind):
            self.page = page
            self.kind = kind

        @property
        def first(self):
            return self

        def is_visible(self, timeout=0):
            if self.kind == "email":
                return self.page.url == "https://auth.openai.com/log-in"
            if self.kind == "password":
                return self.page.url == "https://auth.openai.com/log-in/password"
            if self.kind == "submit":
                return self.page.url.startswith("https://auth.openai.com/log-in")
            if self.kind == "consent":
                return self.page.url == "https://auth.openai.com/sign-in-with-chatgpt/codex/consent"
            return False

        def is_editable(self, timeout=0):
            return self.kind in {"email", "password"} and self.is_visible(timeout=timeout)

        def fill(self, value):
            self.page.fills.append((self.kind, value))

        def click(self, **_kwargs):
            self.page.clicks.append(self.kind)
            if self.page.url == "https://auth.openai.com/log-in":
                self.page.url = "https://auth.openai.com/log-in/password"
            elif self.page.url == "https://auth.openai.com/log-in/password":
                self.page.url = "https://auth.openai.com/sign-in-with-chatgpt/codex/consent"
            elif self.page.url == "https://auth.openai.com/sign-in-with-chatgpt/codex/consent":
                self.page.handlers["request"](Request())
                self.page.url = "chrome-error://chromewebdata/"

        def locator(self, _selector):
            return FakeLocator(self.page, "missing")

        def get_by_role(self, *_args, **_kwargs):
            return FakeLocator(self.page, "missing")

        def press(self, _key):
            self.click()

    class Context:
        def __init__(self):
            self.routes = []
            self.unroutes = []

        def route(self, pattern, handler):
            self.routes.append((pattern, handler))

        def unroute(self, pattern, handler):
            self.unroutes.append((pattern, handler))

        def cookies(self):
            return []

    class Page:
        def __init__(self, context):
            self.context = context
            self.url = "https://chatgpt.com/admin/members"
            self.goto_urls = []
            self.fills = []
            self.clicks = []
            self.handlers = {}
            self.off_calls = []

        def goto(self, url, **_kwargs):
            self.goto_urls.append(url)
            self.url = "https://auth.openai.com/log-in"

        def locator(self, selector):
            if "email" in selector or "username" in selector:
                return FakeLocator(self, "email")
            if "password" in selector:
                return FakeLocator(self, "password")
            if "Authorize" in selector or "Allow" in selector or "Continue" in selector or "Approve" in selector:
                if self.url.endswith("/consent") and "button" in selector:
                    return FakeLocator(self, "consent")
                return FakeLocator(self, "submit")
            if "submit" in selector:
                return FakeLocator(self, "submit")
            return FakeLocator(self, "missing")

        def wait_for_timeout(self, _timeout):
            pass

        def wait_for_load_state(self, *_args, **_kwargs):
            pass

        def content(self):
            return "<html><button>Authorize</button></html>"

        def on(self, event_name, handler):
            self.handlers[event_name] = handler

        def off(self, event_name, handler):
            self.off_calls.append((event_name, handler))

    context = Context()
    page = Page(context)
    session = _TokenSession(_Response())
    monkeypatch.setattr(protocol_oauth, "create_protocol_session", lambda: session)
    monkeypatch.setattr(protocol_oauth, "build_pkce_pair", lambda: ("verifier-1", "challenge-1"))
    monkeypatch.setattr(protocol_oauth.secrets, "token_bytes", lambda _size: b"state-1")
    monkeypatch.setattr(
        protocol_oauth,
        "exchange_callback_for_bundle",
        lambda _session, callback_url, **_kwargs: {
            "email": "user@example.com",
            "access_token": "at-1",
            "refresh_token": "rt-1",
            "id_token": "id-1",
            "account_id": "acc-1",
            "plan_type": "team",
            "expired": 2000000000,
            "callback_url": callback_url,
        },
    )

    result = protocol_oauth.run_protocol_oauth_login_with_browser_context(
        page,
        "user@example.com",
        password="pw-1",
        timeout_ms=1000,
        login_timeout_ms=5000,
    )

    assert result.bundle["refresh_token"] == "rt-1"
    assert result.callback_url == f"{CODEX_REDIRECT_URI}?code=code-1&state={expected_state}"
    assert page.url == "chrome-error://chromewebdata/"
    assert "consent" in page.clicks
    assert {event_name for event_name, _handler in page.off_calls} == {"request", "framenavigated"}


def test_build_cookie_header_exports_chatgpt_cookies_only():
    session = _TokenSession(_Response())
    session.cookies.set("ignored", "x", domain=".example.com")
    session.cookies.set("cf_clearance", "cf-1", domain=".chatgpt.com")

    header = protocol_oauth.build_cookie_header(session)

    assert "__Secure-next-auth.session-token=sess-1" in header
    assert "cf_clearance=cf-1" in header
    assert "ignored=x" not in header


def test_get_chatgpt_auth_session_tolerates_network_failure():
    class Session:
        cookies = _Cookies()

        def get(self, *_args, **_kwargs):
            raise OSError("connection reset")

    assert protocol_oauth.get_chatgpt_auth_session(Session()) == ("", "", {})


def test_apply_existing_session_restores_cookie_header():
    session = _TokenSession(_Response())
    session.cookies = _Cookies()

    protocol_oauth._apply_existing_session(
        session,
        {
            "cookie_header": "__Secure-next-auth.session-token=sess-2; cf_clearance=cf-2; oai-did=did-2",
            "account_id": "acc-2",
        },
    )

    assert session.cookies.get("__Secure-next-auth.session-token") == "sess-2"
    assert session.cookies.get("cf_clearance") == "cf-2"
    assert session.cookies.get("oai-did") == "did-2"
    assert session.cookies.get("_account") == "acc-2"


def test_follow_authorize_returns_log_in_page_for_protocol_login():
    class Session:
        cookies = _Cookies()

        def get(self, url, **_kwargs):
            return _Response(status_code=200, text="<html>login</html>")

    callback_url, final_url = protocol_oauth.follow_authorize_for_callback(
        Session(),
        "https://auth.openai.com/log-in",
    )

    assert callback_url == ""
    assert final_url == "https://auth.openai.com/log-in"


def test_follow_authorize_selects_unified_session_before_consent():
    class Session:
        def __init__(self):
            self.cookies = _Cookies()
            self.gets = []
            self.posts = []

        def get(self, url, **_kwargs):
            self.gets.append(url)
            if url == "https://auth.openai.com/oauth/authorize":
                return _Response(status_code=302, headers={"Location": "https://auth.openai.com/choose-an-account"})
            if url == "https://auth.openai.com/choose-an-account":
                return _Response(status_code=200, text='"unified_sessions",[{"id","us_session1"}]')
            if url == "https://auth.openai.com/sign-in-with-chatgpt/codex/consent":
                return _Response(status_code=302, headers={"Location": f"{CODEX_REDIRECT_URI}?code=code-1&state=state-1"})
            raise AssertionError(f"unexpected GET {url}")

        def post(self, url, **kwargs):
            self.posts.append((url, kwargs))
            assert url == "https://auth.openai.com/api/accounts/session/select"
            assert kwargs["json"] == {"session_id": "us_session1"}
            return _Response(
                status_code=200,
                data={"continue_url": "https://auth.openai.com/sign-in-with-chatgpt/codex/consent"},
            )

    callback_url, final_url = protocol_oauth.follow_authorize_for_callback(
        Session(),
        "https://auth.openai.com/oauth/authorize",
    )

    assert callback_url == f"{CODEX_REDIRECT_URI}?code=code-1&state=state-1"
    assert final_url == callback_url


def test_run_protocol_oauth_prefers_reusable_session_without_password_login(monkeypatch):
    calls = []

    class Session:
        def __init__(self):
            self.cookies = _Cookies()

    session = Session()
    monkeypatch.setattr(protocol_oauth, "create_protocol_session", lambda: session)

    def fake_follow(_session, start_url, redirect_uri=CODEX_REDIRECT_URI):
        calls.append(start_url)
        assert "prompt=login" not in start_url
        return f"{CODEX_REDIRECT_URI}?code=code-1&state=state-1", f"{CODEX_REDIRECT_URI}?code=code-1&state=state-1"

    monkeypatch.setattr(protocol_oauth, "follow_authorize_for_callback", fake_follow)
    monkeypatch.setattr(protocol_oauth, "build_pkce_pair", lambda: ("verifier-1", "challenge-1"))
    monkeypatch.setattr(protocol_oauth.secrets, "token_bytes", lambda _size: b"state-1")
    monkeypatch.setattr(
        protocol_oauth,
        "exchange_callback_for_bundle",
        lambda *_args, **_kwargs: {
            "email": "user@example.com",
            "access_token": "at-1",
            "refresh_token": "rt-1",
            "id_token": "id-1",
            "account_id": "acc-1",
            "plan_type": "team",
            "expired": 2000000000,
        },
    )
    monkeypatch.setattr(protocol_oauth, "get_chatgpt_auth_session", lambda _session: ("sess-1", "chatgpt-at", {}))
    monkeypatch.setattr(
        protocol_oauth,
        "_drive_login_from_log_in",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("password login should not run")),
    )

    result = protocol_oauth.run_protocol_oauth_login(
        "user@example.com",
        "pw",
        mail_client=object(),
        reusable_session={"cookie_header": "__Secure-next-auth.session-token=sess-1"},
    )

    assert result.bundle["refresh_token"] == "rt-1"
    assert result.bundle["credential_source"] == "oauth"
    assert len(calls) == 1


def test_poll_email_otp_times_out(monkeypatch):
    class MailClient:
        def search_emails_by_recipient(self, *_args, **_kwargs):
            return []

    now = [1000.0]
    monkeypatch.setattr(protocol_oauth.time, "time", lambda: now[0])

    def fake_sleep(seconds):
        now[0] += seconds + 100

    monkeypatch.setattr(protocol_oauth.time, "sleep", fake_sleep)

    with pytest.raises(protocol_oauth.ProtocolOauthOtpTimeout):
        protocol_oauth._poll_email_otp(MailClient(), "user@example.com", timeout_seconds=30)


def test_classify_account_deactivated_and_add_phone():
    assert protocol_oauth.classify_protocol_failure("account_deactivated") == "account_deactivated"
    assert protocol_oauth.classify_protocol_failure("continue_url=/add-phone") == "add-phone"
    assert protocol_oauth.classify_protocol_failure("no_valid_organizations") == "no_valid_organizations"
    assert protocol_oauth.classify_protocol_failure("token exchange failed") == "token_exchange_failed"
    assert protocol_oauth.classify_protocol_failure("authorize/continue failed: HTTP 429") == "rate_limited"
    with pytest.raises(protocol_oauth.ProtocolOauthRateLimited):
        protocol_oauth._raise_classified("Rate limit exceeded, please try again later.")


def test_solve_hcaptcha_remote_uses_create_task_protocol(monkeypatch):
    calls = []

    def fake_post(url, json=None, timeout=None):
        calls.append((url, json, timeout))
        if url.endswith("/createTask"):
            return _Response(data={"errorId": 0, "taskId": "task-1"})
        return _Response(data={"errorId": 0, "status": "ready", "solution": {"gRecaptchaResponse": "tok", "eKey": "ek"}})

    monkeypatch.setattr(protocol_oauth.requests, "post", fake_post)
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(protocol_oauth.time, "sleep", lambda _seconds: None)

    token, ekey = protocol_oauth.solve_hcaptcha_remote(
        api_key="key",
        api_url="https://captcha.example.com",
        website_url="https://example.com",
        website_key="site-key",
        rqdata="rq",
        poll_attempts=1,
    )

    assert (token, ekey) == ("tok", "ek")
    assert calls[0][0] == "https://captcha.example.com/createTask"
    assert calls[0][1]["task"]["websiteKey"] == "site-key"
    assert calls[0][1]["task"]["rqdata"] == "rq"
