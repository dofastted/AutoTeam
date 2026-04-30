import threading

import pytest

from autoteam import api, chatgpt_api


def test_launch_browser_stops_playwright_when_browser_launch_fails(tmp_path, monkeypatch):
    class FakePlaywright:
        def __init__(self):
            self.stopped = False
            self.chromium = self

        def launch(self, **_kwargs):
            raise RuntimeError("proxy launch failed")

        def stop(self):
            self.stopped = True

    class FakeSyncPlaywright:
        def __init__(self, playwright):
            self._playwright = playwright

        def start(self):
            return self._playwright

    fake_playwright = FakePlaywright()
    monkeypatch.setattr(chatgpt_api, "SCREENSHOT_DIR", tmp_path)
    monkeypatch.setattr(chatgpt_api, "get_playwright_launch_options", lambda: {"proxy": {"server": "http://proxy"}})
    monkeypatch.setattr(chatgpt_api, "sync_playwright", lambda: FakeSyncPlaywright(fake_playwright))

    client = chatgpt_api.ChatGPTTeamAPI()

    with pytest.raises(RuntimeError, match="proxy launch failed"):
        client._launch_browser()

    assert fake_playwright.stopped is True
    assert client.playwright is None
    assert client.browser is None
    assert client.context is None
    assert client.page is None


def test_post_admin_login_start_stops_api_when_begin_login_fails(monkeypatch):
    instances = []

    class FakeChatGPTTeamAPI:
        def __init__(self):
            self.stopped = False
            instances.append(self)

        def begin_admin_login(self, _email):
            raise RuntimeError("proxy launch failed")

        def stop(self):
            self.stopped = True

    monkeypatch.setattr(api, "_playwright_lock", threading.Lock())
    monkeypatch.setattr(api, "_admin_login_api", None)
    monkeypatch.setattr(api, "_admin_login_step", None)
    monkeypatch.setattr(api._pw_executor, "run", lambda func, *args, **kwargs: func(*args, **kwargs))
    monkeypatch.setattr("autoteam.chatgpt_api.ChatGPTTeamAPI", FakeChatGPTTeamAPI)

    with pytest.raises(api.HTTPException) as exc:
        api.post_admin_login_start(api.AdminEmailParams(email="admin@example.com"))

    assert exc.value.status_code == 400
    assert "proxy launch failed" in str(exc.value.detail)
    assert len(instances) == 1
    assert instances[0].stopped is True
    assert api._admin_login_api is None
    assert api._playwright_lock.locked() is False


def test_get_team_members_stops_chatgpt_when_start_fails(monkeypatch):
    instances = []

    class FakeChatGPTTeamAPI:
        def __init__(self):
            self.stopped = False
            instances.append(self)

        def start(self):
            raise RuntimeError("http proxy failed")

        def stop(self):
            self.stopped = True

    monkeypatch.setattr(api, "_playwright_lock", threading.Lock())
    monkeypatch.setattr(api._pw_executor, "run", lambda func, *args, **kwargs: func(*args, **kwargs))
    monkeypatch.setattr("autoteam.admin_state.get_admin_session_token", lambda: "session")
    monkeypatch.setattr("autoteam.admin_state.get_chatgpt_account_id", lambda: "acc-1")
    monkeypatch.setattr("autoteam.chatgpt_api.ChatGPTTeamAPI", FakeChatGPTTeamAPI)

    with pytest.raises(api.HTTPException) as exc:
        api.get_team_members(allow_browser=True)

    assert exc.value.status_code == 502
    assert "http proxy failed" in str(exc.value.detail)
    assert len(instances) == 1
    assert instances[0].stopped is True
    assert api._playwright_lock.locked() is False


def test_get_team_members_returns_local_snapshot_without_cached_token(monkeypatch):
    def fail_if_browser_runs(*_args, **_kwargs):
        raise AssertionError("browser path should not run")

    monkeypatch.setattr(api, "_playwright_lock", threading.Lock())
    monkeypatch.setattr(api._pw_executor, "run", fail_if_browser_runs)
    monkeypatch.setattr("autoteam.admin_state.get_admin_session_token", lambda: "session")
    monkeypatch.setattr("autoteam.admin_state.get_chatgpt_account_id", lambda: "acc-1")
    monkeypatch.setattr("autoteam.admin_state.get_chatgpt_access_token", lambda: "")
    monkeypatch.setattr("autoteam.team_cache.load_team_members_cache", lambda: {})
    monkeypatch.setattr(
        "autoteam.accounts.load_accounts",
        lambda: [
            {"email": "one@example.com", "status": "active"},
            {"email": "two@example.com", "status": "standby"},
        ],
    )

    result = api.get_team_members(refresh=True)

    assert result["cached"] is True
    assert result["local_snapshot"] is True
    assert result["total"] == 2
    assert result["members"][0]["email"] == "one@example.com"
    assert result["members"][0]["status"] == "active"
    assert "access token" in result["refresh_error"]


def test_get_team_members_enriches_cached_members_with_local_sold_status(monkeypatch):
    monkeypatch.setattr("autoteam.admin_state.get_admin_session_token", lambda: "session")
    monkeypatch.setattr("autoteam.admin_state.get_chatgpt_account_id", lambda: "acc-1")
    monkeypatch.setattr(api, "_is_main_account_email", lambda _email: False)
    monkeypatch.setattr(
        "autoteam.team_cache.load_team_members_cache",
        lambda: {
            "members": [
                {
                    "email": "sold@example.com",
                    "role": "member",
                    "user_id": "user-1",
                    "is_local": False,
                    "type": "member",
                }
            ],
            "total": 1,
            "invites": 0,
            "cached": False,
        },
    )
    monkeypatch.setattr(
        "autoteam.accounts.load_accounts",
        lambda: [
            {
                "email": "sold@example.com",
                "status": "sold",
                "sync_disabled": True,
                "auth_file": "/tmp/auth.json",
                "cpa_archive_file": "/tmp/archive/auth.json",
                "sold_at": 123,
            }
        ],
    )

    result = api.get_team_members(refresh=False)

    member = result["members"][0]
    assert result["cached"] is True
    assert member["is_local"] is True
    assert member["status"] == "sold"
    assert member["sync_disabled"] is True
    assert member["has_auth_file"] is True
    assert member["has_cpa_archive_file"] is True
    assert member["sold_at"] == 123
