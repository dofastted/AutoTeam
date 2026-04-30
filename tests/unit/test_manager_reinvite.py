import types

from autoteam import accounts, manager


def test_reinvite_account_uses_unified_oauth_login_and_marks_active(monkeypatch):
    updates = []
    calls = []

    def fake_login(email, password, mail_client=None, mail_account_id=None):
        calls.append(
            {
                "email": email,
                "password": password,
                "mail_client": mail_client,
                "mail_account_id": mail_account_id,
            }
        )
        return {
            "email": email,
            "access_token": "token-1",
            "refresh_token": "refresh-1",
            "plan_type": "team",
        }

    monkeypatch.setattr(manager, "login_codex_via_browser", fake_login)
    monkeypatch.setattr(manager, "save_auth_file", lambda bundle, source=None: f"/tmp/{bundle['email']}.json")
    monkeypatch.setattr(
        manager,
        "update_account",
        lambda email, **kwargs: updates.append((email, kwargs)),
    )
    monkeypatch.setattr(manager.time, "time", lambda: 1234567890)
    monkeypatch.setattr(
        manager,
        "_is_email_in_team",
        lambda email: (_ for _ in ()).throw(AssertionError("should not check team membership separately")),
    )

    result = manager.reinvite_account(
        types.SimpleNamespace(browser=False),
        None,
        {"email": "tmp-user@example.com", "password": "secret", "mail_account_id": "mail-42"},
    )

    assert result is True
    assert calls == [
        {
            "email": "tmp-user@example.com",
            "password": "secret",
            "mail_client": None,
            "mail_account_id": "mail-42",
        }
    ]
    assert updates == [
        (
            "tmp-user@example.com",
            {
                "status": accounts.STATUS_ACTIVE,
                "last_active_at": 1234567890,
                "auth_file": "/tmp/tmp-user@example.com.json",
                "rt_auth_file": "/tmp/tmp-user@example.com.json",
            },
        )
    ]


def test_reinvite_account_marks_standby_when_oauth_login_returns_non_team(monkeypatch):
    updates = []
    calls = []

    def fake_login(email, password, mail_client=None, mail_account_id=None):
        calls.append(mail_account_id)
        return {
            "email": email,
            "access_token": "token-1",
            "refresh_token": "refresh-1",
            "plan_type": "free",
        }

    monkeypatch.setattr(manager, "login_codex_via_browser", fake_login)
    monkeypatch.setattr(
        manager,
        "update_account",
        lambda email, **kwargs: updates.append((email, kwargs)),
    )
    monkeypatch.setattr(
        manager,
        "_is_email_in_team",
        lambda email: (_ for _ in ()).throw(AssertionError("should not check team membership separately")),
    )

    result = manager.reinvite_account(
        types.SimpleNamespace(browser=False),
        None,
        {"email": "tmp-user@example.com", "password": "", "mail_account_id": "mail-99"},
    )

    assert result is False
    assert calls == ["mail-99"]
    assert updates == [("tmp-user@example.com", {"status": accounts.STATUS_STANDBY})]
