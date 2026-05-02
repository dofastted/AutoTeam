import pytest

from autoteam import manager
from autoteam.exceptions import PhoneVerificationRequiredError


class _FakeChatGPT:
    def __init__(self):
        self.browser = True
        self.started = 0
        self.stopped = 0

    def start(self):
        self.browser = True
        self.started += 1

    def stop(self):
        self.browser = False
        self.stopped += 1


class _FakeMailClient:
    def login(self):
        return None


class _FakeBody:
    def __init__(self, text):
        self._text = text

    @property
    def first(self):
        return self

    def is_visible(self, timeout=300):
        return True

    def inner_text(self, timeout=300):
        return self._text

    def text_content(self, timeout=300):
        return self._text


class _FakeVisibleLocator:
    def __init__(self, visible=True, editable=True):
        self._visible = visible
        self._editable = editable
        self.clicked = 0

    @property
    def first(self):
        return self

    def is_visible(self, timeout=300):
        return self._visible

    def is_editable(self, timeout=300):
        return self._editable

    def click(self, timeout=3000, force=False):
        self.clicked += 1


class _FakePage:
    def __init__(self, url="", body="", locators=None, title="", html=""):
        self.url = url
        self._body = body
        self._locators = locators or {}
        self._title = title
        self._html = html

    def locator(self, selector):
        for key, value in self._locators.items():
            if key in selector or selector in key:
                return value
        assert selector == "body"
        return _FakeBody(self._body)

    def title(self):
        return self._title

    def content(self):
        return self._html


def test_is_session_ended_page_detects_auth_page():
    page = _FakePage(
        url="https://auth.openai.com/log-in-or-create-account",
        body="Your session has ended Continue by logging in",
    )

    assert manager._is_session_ended_page(page) is True


def test_try_activate_direct_signup_locator_uses_href():
    calls = []

    class FakeLocator:
        def evaluate(self, expression):
            calls.append(("evaluate", expression))
            return "https://auth.openai.com/create-account"

    class FakePage:
        def goto(self, url, wait_until=None, timeout=None):
            calls.append(("goto", url, wait_until, timeout))

    assert manager._try_activate_direct_signup_locator(FakePage(), FakeLocator(), "Sign up for free") is True
    assert calls[-1] == ("goto", "https://auth.openai.com/create-account", "domcontentloaded", 60000)


def test_detect_direct_register_step_handles_organization_url(monkeypatch):
    page = _FakePage(url="https://chatgpt.com/organization/create")

    monkeypatch.setattr(manager, "_is_google_redirect", lambda _page: False)
    monkeypatch.setattr(manager, "_is_cloudflare_verifying", lambda _page: False)

    assert manager._detect_direct_register_step(page) == "workspace"


def test_detect_direct_register_step_handles_create_organization_body(monkeypatch):
    page = _FakePage(url="https://auth.openai.com/create-account", body="Create organization Continue")

    monkeypatch.setattr(manager, "_is_google_redirect", lambda _page: False)
    monkeypatch.setattr(manager, "_is_cloudflare_verifying", lambda _page: False)
    monkeypatch.setattr(manager, "_first_visible_editable_locator", lambda *_args, **_kwargs: None)

    assert manager._detect_direct_register_step(page) == "workspace"


def test_detect_direct_register_step_handles_add_phone_url(monkeypatch):
    page = _FakePage(url="https://auth.openai.com/add-phone")

    monkeypatch.setattr(manager, "_is_google_redirect", lambda _page: False)

    assert manager._detect_direct_register_step(page) == "add_phone"
    with pytest.raises(PhoneVerificationRequiredError, match="OpenAI 风控要求手机号"):
        manager._raise_if_add_phone_url(page.url, "risk@example.com")


def test_direct_register_failure_diagnostics_include_step_url_title_and_html(monkeypatch):
    page = _FakePage(
        url="https://auth.openai.com/email-verification",
        title="Verify email",
        html="<html><body>Verification page markup with code input</body></html>",
    )

    monkeypatch.setattr(manager, "_is_google_redirect", lambda _page: False)
    monkeypatch.setattr(manager, "_is_cloudflare_verifying", lambda _page: False)
    monkeypatch.setattr(manager, "_first_visible_editable_locator", lambda *_args, **_kwargs: None)

    message = manager._direct_register_failure_diagnostics(page, reason="未收到验证码")

    assert "step=code" in message
    assert "url=https://auth.openai.com/email-verification" in message
    assert "title=Verify email" in message
    assert "html_excerpt=<html><body>Verification page markup" in message
    assert "reason=未收到验证码" in message


def test_raise_direct_register_failure_includes_visible_error_text(monkeypatch):
    error_locator = _FakeBody("Sorry, registration is blocked")
    page = _FakePage(
        url="https://chatgpt.com/auth/error",
        title="Error",
        html="<html><body><h1>Sorry</h1></body></html>",
        locators={"[class*=error]": error_locator},
    )

    monkeypatch.setattr(manager, "_is_google_redirect", lambda _page: False)
    monkeypatch.setattr(manager, "_is_cloudflare_verifying", lambda _page: False)

    with pytest.raises(RuntimeError) as exc_info:
        manager._raise_direct_register_failure(page, reason="认证错误页")

    message = str(exc_info.value)
    assert "直注注册未完成:" in message
    assert "step=auth_error" in message
    assert "url=https://chatgpt.com/auth/error" in message
    assert "title=Error" in message
    assert "error_text=Sorry, registration is blocked" in message


def test_raise_direct_register_failure_detects_ip_blocked_error(monkeypatch):
    error_locator = _FakeBody("Failed to create account")
    page = _FakePage(
        url="https://auth.openai.com/create",
        title="Create account",
        html="<html><body>Failed to create account</body></html>",
        locators={"[class*=error]": error_locator},
    )

    monkeypatch.setattr(manager, "_is_google_redirect", lambda _page: False)
    monkeypatch.setattr(manager, "_is_cloudflare_verifying", lambda _page: False)

    with pytest.raises(manager.OpenAiCreateAccountBlockedError) as exc_info:
        manager._raise_direct_register_failure(page, reason="提交注册失败")

    message = str(exc_info.value)
    assert "直注注册未完成:" in message
    assert "error_text=Failed to create account" in message
    assert "reason=ip_blocked" in message


def test_register_direct_once_raises_detailed_runtime_error_on_unknown_step(monkeypatch):
    class FakeBrowser:
        def __init__(self, page):
            self.page = page
            self.closed = False

        def new_context(self, **_kwargs):
            return self

        def new_page(self):
            return self.page

        def close(self):
            self.closed = True

    class FakeLease:
        def __init__(self, browser):
            self.browser = browser

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def launch_chromium(self, **_kwargs):
            return self.browser

    page = _FakePage(
        url="https://auth.openai.com/custom-state",
        title="Custom Signup",
        html="<html><body>Unexpected signup page</body></html>",
    )

    def fake_goto(url, **_kwargs):
        page.url = "https://auth.openai.com/custom-state"

    page.goto = fake_goto
    browser = FakeBrowser(page)

    monkeypatch.setattr(manager, "get_playwright_launch_options", lambda: {})
    monkeypatch.setattr(manager, "acquire_browser_lease", lambda *_args, **_kwargs: FakeLease(browser))
    monkeypatch.setattr(manager, "_wait_for_direct_cloudflare", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(manager, "_is_session_ended_page", lambda _page: False)
    monkeypatch.setattr(manager, "_safe_invite_screenshot", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(manager, "_click_direct_signup_entry", lambda _page: False)
    monkeypatch.setattr(manager, "_wait_for_direct_register_step", lambda *_args, **_kwargs: "unknown")
    monkeypatch.setattr(manager.time, "sleep", lambda _seconds: None)

    with pytest.raises(RuntimeError) as exc_info:
        manager._register_direct_once(_FakeMailClient(), "diag@example.com", "pw-1")

    message = str(exc_info.value)
    assert "直注注册未完成:" in message
    assert "step=unknown" in message
    assert "url=https://auth.openai.com/custom-state" in message
    assert "title=Custom Signup" in message
    assert "html_excerpt=<html><body>Unexpected signup page</body></html>" in message
    assert "reason=未识别到邮箱步骤" in message
    assert browser.closed is True


def test_detect_direct_register_step_prefers_visible_password_input(monkeypatch):
    page = _FakePage(
        url="https://auth.openai.com/email-verification",
        locators={"input[type=\"password\"]": _FakeVisibleLocator()},
    )

    monkeypatch.setattr(manager, "_is_google_redirect", lambda _page: False)
    monkeypatch.setattr(manager, "_is_cloudflare_verifying", lambda _page: False)

    assert manager._detect_direct_register_step(page) == "password"


def test_click_direct_continue_with_password_clicks_visible_entry(monkeypatch):
    locator = _FakeVisibleLocator()
    page = _FakePage(locators={"Continue with password": locator})
    sleeps = []

    monkeypatch.setattr(manager.time, "sleep", lambda seconds: sleeps.append(seconds))

    assert manager._click_direct_continue_with_password(page) is True
    assert locator.clicked == 1
    assert sleeps == [2]


def test_find_direct_code_inputs_accepts_numeric_otp_inputs():
    class FakeInput:
        def is_visible(self, timeout=200):
            return True

    class FakeLocator:
        def __init__(self, items):
            self._items = items
            self.first = items[0]

        def all(self):
            return self._items

    class FakePage:
        def locator(self, selector):
            assert "inputmode" in selector
            return FakeLocator([FakeInput() for _ in range(6)])

    assert len(manager._find_direct_code_inputs(FakePage())) == 6


def test_cmd_fill_tries_other_reusable_accounts_before_creating_new(monkeypatch):
    chatgpt = _FakeChatGPT()
    count_values = iter([4, 5])
    events = []

    monkeypatch.setattr(manager, "ChatGPTTeamAPI", lambda: chatgpt)
    monkeypatch.setattr(manager, "CloudMailClient", lambda: _FakeMailClient())
    monkeypatch.setattr(manager, "get_team_member_count", lambda _chatgpt: next(count_values))
    monkeypatch.setattr(
        manager,
        "get_standby_accounts",
        lambda: [
            {"email": "old-1@example.com", "_quota_recovered": True},
            {"email": "old-2@example.com", "_quota_recovered": True},
        ],
    )

    def fake_reinvite(_chatgpt, _mail, acc):
        events.append(("reinvite", acc["email"]))
        return acc["email"] == "old-2@example.com"

    monkeypatch.setattr(manager, "reinvite_account", fake_reinvite)
    monkeypatch.setattr(
        manager,
        "create_new_account",
        lambda _chatgpt, _mail: events.append(("create", None)) or True,
    )
    monkeypatch.setattr(manager, "sync_to_cpa", lambda: events.append(("sync", None)))
    monkeypatch.setattr(manager, "cmd_status", lambda: events.append(("status", None)))

    manager.cmd_fill(target=5)

    assert events == [
        ("reinvite", "old-1@example.com"),
        ("reinvite", "old-2@example.com"),
        ("sync", None),
        ("status", None),
    ]
    assert chatgpt.stopped == 1


def test_cmd_fill_skips_google_accounts_during_auto_reuse(monkeypatch):
    chatgpt = _FakeChatGPT()
    count_values = iter([4, 5])
    events = []

    monkeypatch.setattr(manager, "ChatGPTTeamAPI", lambda: chatgpt)
    monkeypatch.setattr(manager, "CloudMailClient", lambda: _FakeMailClient())
    monkeypatch.setattr(manager, "get_team_member_count", lambda _chatgpt: next(count_values))
    monkeypatch.setattr(
        manager,
        "get_standby_accounts",
        lambda: [
            {"email": "bubblehuntr@gmail.com", "_quota_recovered": True},
            {"email": "old-2@example.com", "_quota_recovered": True},
        ],
    )

    def fake_reinvite(_chatgpt, _mail, acc):
        events.append(("reinvite", acc["email"]))
        return True

    monkeypatch.setattr(manager, "reinvite_account", fake_reinvite)
    monkeypatch.setattr(
        manager,
        "create_new_account",
        lambda _chatgpt, _mail: events.append(("create", None)) or True,
    )
    monkeypatch.setattr(manager, "sync_to_cpa", lambda: events.append(("sync", None)))
    monkeypatch.setattr(manager, "cmd_status", lambda: events.append(("status", None)))

    manager.cmd_fill(target=5)

    assert events == [
        ("reinvite", "old-2@example.com"),
        ("sync", None),
        ("status", None),
    ]
    assert chatgpt.stopped == 1


def test_cmd_fill_stops_early_when_refreshed_team_count_hits_target(monkeypatch):
    chatgpt = _FakeChatGPT()
    count_values = iter([3, 5])
    events = []

    monkeypatch.setattr(manager, "ChatGPTTeamAPI", lambda: chatgpt)
    monkeypatch.setattr(manager, "CloudMailClient", lambda: _FakeMailClient())
    monkeypatch.setattr(manager, "get_team_member_count", lambda _chatgpt: next(count_values))
    monkeypatch.setattr(manager, "get_standby_accounts", lambda: [])
    monkeypatch.setattr(
        manager,
        "create_new_account",
        lambda _chatgpt, _mail: events.append(("create", None)) or False,
    )
    monkeypatch.setattr(manager, "sync_to_cpa", lambda: events.append(("sync", None)))
    monkeypatch.setattr(manager, "cmd_status", lambda: events.append(("status", None)))

    manager.cmd_fill(target=5)

    assert events == [
        ("create", None),
        ("sync", None),
        ("status", None),
    ]
    assert chatgpt.stopped == 1


def test_cmd_fill_syncs_cpa_after_each_configured_batch(monkeypatch):
    chatgpt = _FakeChatGPT()
    count_values = iter(range(0, 14))
    events = []

    import autoteam.config as config

    monkeypatch.setattr(config, "FILL_BATCH_SIZE", 10)
    monkeypatch.setattr(config, "TEAM_TARGET_SEATS", 999)
    monkeypatch.setattr(config, "MAX_TEAM_SEATS", 999)
    monkeypatch.setattr(manager, "ChatGPTTeamAPI", lambda: chatgpt)
    monkeypatch.setattr(manager, "CloudMailClient", lambda: _FakeMailClient())
    monkeypatch.setattr(manager, "get_team_member_count", lambda _chatgpt: next(count_values))
    monkeypatch.setattr(manager, "get_standby_accounts", lambda: [])
    monkeypatch.setattr(
        manager,
        "create_new_account",
        lambda _chatgpt, _mail: events.append(("create", None)) or True,
    )
    monkeypatch.setattr(manager, "sync_to_cpa", lambda: events.append(("sync", None)) or {"uploaded": 1})
    monkeypatch.setattr(manager, "cmd_status", lambda: events.append(("status", None)))

    result = manager.cmd_fill(target=13)

    assert [event for event in events if event[0] == "sync"] == [("sync", None), ("sync", None)]
    assert events[-1] == ("status", None)
    assert result["attempted"] == 13
    assert result["succeeded"] == 13
    assert [batch["attempted"] for batch in result["batches"]] == [10, 3]
    assert chatgpt.stopped == 1


def test_cmd_fill_uses_parallel_creator_for_new_accounts(monkeypatch):
    chatgpt = _FakeChatGPT()
    count_values = iter([0, 3])
    events = []

    import autoteam.config as config

    monkeypatch.setattr(config, "FILL_BATCH_SIZE", 10)
    monkeypatch.setattr(config, "TEAM_TARGET_SEATS", 999)
    monkeypatch.setattr(config, "MAX_TEAM_SEATS", 999)
    monkeypatch.setattr(manager, "ChatGPTTeamAPI", lambda: chatgpt)
    monkeypatch.setattr(manager, "CloudMailClient", lambda: _FakeMailClient())
    monkeypatch.setattr(manager, "get_team_member_count", lambda _chatgpt: next(count_values))
    monkeypatch.setattr(manager, "get_standby_accounts", lambda: [])

    def fake_parallel(total, *, parallel_workers=None, stop_after_success=None):
        events.append(("parallel", total, parallel_workers))
        return {
            "attempted": 3,
            "succeeded": 3,
            "failed": 0,
            "emails": ["a@example.com", "b@example.com", "c@example.com"],
            "worker_reports": [
                {"worker_index": 1, "target": 1, "attempted": 1, "succeeded": 1, "failed": 0},
                {"worker_index": 2, "target": 1, "attempted": 1, "succeeded": 1, "failed": 0},
                {"worker_index": 3, "target": 1, "attempted": 1, "succeeded": 1, "failed": 0},
            ],
            "parallel_workers": 3,
        }

    monkeypatch.setattr(manager, "_create_new_accounts_parallel", fake_parallel)
    monkeypatch.setattr(manager, "sync_to_cpa", lambda: events.append(("sync", None)) or {"uploaded": 3})
    monkeypatch.setattr(manager, "cmd_status", lambda: events.append(("status", None)))

    result = manager.cmd_fill(target=3, parallel_workers=3)

    assert events[0] == ("parallel", 3, 3)
    assert result["succeeded"] == 3
    assert result["parallel_workers"] == 3
    assert len(result["worker_reports"]) == 3


def test_auto_reuse_skip_reason_detects_google_provider_and_gmail():
    assert manager._auto_reuse_skip_reason({"email": "bubblehuntr@gmail.com"}) == "Google 登录账号暂不支持自动复用"
    assert (
        manager._auto_reuse_skip_reason({"email": "user@example.com", "login_provider": "google"})
        == "Google 登录账号暂不支持自动复用"
    )
    assert manager._auto_reuse_skip_reason({"email": "user@example.com"}) is None


def test_complete_direct_about_you_uses_shared_fill_logic(monkeypatch):
    calls = []

    class FakePage:
        url = "https://chatgpt.com/auth/about-you"

    def fake_fill(page, *, email=None, logger=None, log_prefix=None, submit_timeout=12, deadline=None):
        calls.append(
            {
                "page": page,
                "email": email,
                "logger": logger,
                "log_prefix": log_prefix,
                "submit_timeout": submit_timeout,
                "deadline": deadline,
            }
        )
        return True

    monkeypatch.setattr(manager, "fill_about_you_page", fake_fill)

    result = manager._complete_direct_about_you(FakePage())

    assert result is True
    assert calls == [
        {
            "page": calls[0]["page"],
            "email": None,
            "logger": manager.logger,
            "log_prefix": "[直接注册]",
            "submit_timeout": 12,
            "deadline": calls[0]["deadline"],
        }
    ]
    assert calls[0]["deadline"] is not None


def test_complete_direct_about_you_raises_on_timeout(monkeypatch):
    class FakePage:
        url = "https://auth.openai.com/about-you"

        def title(self):
            return "Tell us about you"

        def locator(self, selector):
            assert selector == "body"
            return _FakeBody("About you form")

    monotonic_values = iter([100.0, 191.0, 191.0])

    def fake_fill(page, *, deadline=None, **_kwargs):
        assert page.url.endswith("/about-you")
        assert deadline == 190.0
        return False

    monkeypatch.setattr(manager.time, "monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr(manager, "fill_about_you_page", fake_fill)

    with pytest.raises(manager.OpenAiCreateAccountBlockedError) as exc_info:
        manager._complete_direct_about_you(FakePage(), email="timeout@example.com", timeout=90)

    assert "about-you 超时" in str(exc_info.value)
    assert exc_info.value.email == "timeout@example.com"
    assert exc_info.value.reason == "about_you_timeout"


def test_complete_direct_about_you_raises_on_oops_title(monkeypatch):
    class FakePage:
        url = "https://auth.openai.com/about-you"

        def title(self):
            return "Oops, an error occurred"

    monkeypatch.setattr(
        manager,
        "fill_about_you_page",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should fail before filling")),
    )

    with pytest.raises(manager.OpenAiCreateAccountBlockedError) as exc_info:
        manager._complete_direct_about_you(FakePage(), email="oops@example.com")

    assert "about-you Oops" in str(exc_info.value)
    assert exc_info.value.email == "oops@example.com"
    assert exc_info.value.reason == "about_you_oops"


def test_wait_for_direct_admin_members_access_requires_admin_members(monkeypatch):
    visited = []

    class FakePage:
        url = "https://chatgpt.com/"

        def goto(self, url, **_kwargs):
            visited.append(url)
            self.url = url

        def wait_for_load_state(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(manager, "complete_workspace_selection", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(manager, "_page_excerpt", lambda _page, limit=500: "Members")

    assert manager._wait_for_direct_admin_members_access(FakePage(), timeout=1) is True
    assert visited == ["https://chatgpt.com/admin/members"]
