import json
import logging
import threading
import time

import pytest
from fastapi import HTTPException

from autoteam import accounts, api


def _set_pool_runtime_config(monkeypatch):
    monkeypatch.setattr(api, "_maybe_reload_runtime_config_from_env_file", lambda *args, **kwargs: False)
    monkeypatch.setattr("autoteam.setup_wizard._read_env", lambda: {})
    monkeypatch.setenv("MAIL_PROVIDER", "cloudmail")
    monkeypatch.setenv("CLOUDMAIL_BASE_URL", "http://mail.example.com")
    monkeypatch.setenv("CLOUDMAIL_EMAIL", "admin@example.com")
    monkeypatch.setenv("CLOUDMAIL_PASSWORD", "secret")
    monkeypatch.setenv("CLOUDMAIL_DOMAIN", "@example.com")
    monkeypatch.setenv("CPA_URL", "http://127.0.0.1:8317")
    monkeypatch.setenv("CPA_KEY", "key-1")


def test_get_status_normalizes_main_account_status_from_saved_auth(tmp_path, monkeypatch):
    main_email = "owner@example.com"
    auth_file = tmp_path / "codex-main.json"
    auth_file.write_text(json.dumps({"access_token": "token-main"}), encoding="utf-8")

    monkeypatch.setattr(
        "autoteam.accounts.load_accounts",
        lambda: [
            {
                "email": main_email,
                "status": "exhausted",
                "auth_file": "/app/auths/codex-main.json",
                "last_quota": {
                    "primary_pct": 8,
                    "primary_resets_at": 1710000000,
                    "weekly_pct": 1,
                    "weekly_resets_at": 1710600000,
                },
            }
        ],
    )
    monkeypatch.setattr(api, "_is_main_account_email", lambda email: email == main_email)
    monkeypatch.setattr("autoteam.codex_auth.get_saved_main_auth_file", lambda: str(auth_file))
    monkeypatch.setattr(
        "autoteam.codex_auth.check_codex_quota",
        lambda access_token: (
            "ok",
            {
                "primary_pct": 8,
                "primary_resets_at": 1710000000,
                "weekly_pct": 1,
                "weekly_resets_at": 1710600000,
            },
        ),
    )

    result = api.get_status()

    assert result["quota_cache"][main_email]["primary_pct"] == 8
    assert result["accounts"][0]["is_main_account"] is True
    assert result["accounts"][0]["status"] == "active"
    assert result["summary"] == {
        "active": 1,
        "standby": 0,
        "exhausted": 0,
        "pending": 0,
        "unavailable": 0,
        "sold": 0,
        "total": 1,
    }
    assert result["usage_summary"]["normal"] == 1
    assert result["cpa_summary"]["inventory_missing_to_100"] == 100


def test_get_status_can_skip_live_quota_checks(tmp_path, monkeypatch):
    auth_file = tmp_path / "codex-user.json"
    auth_file.write_text(json.dumps({"access_token": "token-user"}), encoding="utf-8")

    monkeypatch.setattr(
        "autoteam.accounts.load_accounts",
        lambda: [
            {
                "email": "user@example.com",
                "status": "active",
                "auth_file": str(auth_file),
                "last_quota": {
                    "primary_pct": 30,
                    "primary_resets_at": 1710000000,
                    "weekly_pct": 5,
                    "weekly_resets_at": 1710600000,
                },
            }
        ],
    )

    def fail_check_quota(_access_token):
        raise AssertionError("live quota check should not run")

    monkeypatch.setattr("autoteam.codex_auth.check_codex_quota", fail_check_quota)

    result = api.get_status(realtime_quota=False)

    assert result["quota_cache"] == {}
    assert result["accounts"][0]["last_quota"]["primary_pct"] == 30
    assert result["summary"]["active"] == 1
    assert result["usage_summary"]["normal"] == 1


def test_get_status_includes_unavailable_summary(tmp_path, monkeypatch):
    auth_file = tmp_path / "codex-unavailable.json"
    auth_file.write_text(json.dumps({"access_token": "token-user"}), encoding="utf-8")

    monkeypatch.setattr(
        "autoteam.accounts.load_accounts",
        lambda: [
            {
                "email": "dead@example.com",
                "status": "unavailable",
                "auth_file": str(auth_file),
                "sync_disabled": True,
                "unavailable_reason": "account_deactivated",
            }
        ],
    )

    result = api.get_status(realtime_quota=False)

    assert result["summary"] == {
        "active": 0,
        "standby": 0,
        "exhausted": 0,
        "pending": 0,
        "unavailable": 1,
        "sold": 0,
        "total": 1,
    }
    assert result["usage_summary"]["normal"] == 1
    assert result["accounts"][0]["status"] == "unavailable"
    assert result["accounts"][0]["sync_disabled"] is True


def test_post_sell_account_marks_sold_and_deletes_configured_targets(tmp_path, monkeypatch):
    auth_file = tmp_path / "codex-sold@example.com-team.json"
    auth_file.write_text("{}", encoding="utf-8")
    archive_file = tmp_path / "archive" / auth_file.name
    accounts_data = [
        {
            "email": "sold@example.com",
            "status": "active",
            "auth_file": str(auth_file),
        }
    ]
    cleanup_calls = []

    monkeypatch.setattr("autoteam.accounts.load_accounts", lambda: list(accounts_data))
    monkeypatch.setattr(api, "_is_main_account_email", lambda _email: False)
    monkeypatch.setattr("autoteam.auth_archive.archive_account_auth_file", lambda _email, _auth: str(archive_file))
    monkeypatch.setattr(
        "autoteam.sync_targets.delete_account_from_configured_targets",
        lambda email, **kwargs: cleanup_calls.append((email, kwargs)) or {"cpa": {"count": 1}},
    )

    def fake_update(email, **kwargs):
        accounts_data[0].update(kwargs)
        return accounts_data[0]

    monkeypatch.setattr("autoteam.accounts.update_account", fake_update)
    monkeypatch.setattr(
        "autoteam.accounts.mark_account_sold",
        lambda email, remote_cleanup=None: fake_update(
            email,
            status="sold",
            sync_disabled=True,
            sold_at=123,
            sale_remote_cleanup=remote_cleanup or {},
        ),
    )

    result = api.post_sell_account("sold@example.com")

    assert cleanup_calls == [("sold@example.com", {"auth_names": [auth_file.name]})]
    assert result["status"] == "sold"
    assert result["cpa_archive_file"] == str(archive_file)
    assert accounts_data[0]["status"] == "sold"
    assert accounts_data[0]["sync_disabled"] is True


def test_post_self_use_account_marks_usage_and_deletes_configured_targets(tmp_path, monkeypatch):
    auth_file = tmp_path / "codex-self@example.com-team.json"
    auth_file.write_text("{}", encoding="utf-8")
    archive_file = tmp_path / "archive" / auth_file.name
    accounts_data = [
        {
            "email": "self@example.com",
            "status": "active",
            "auth_file": str(auth_file),
        }
    ]
    cleanup_calls = []

    monkeypatch.setattr("autoteam.accounts.load_accounts", lambda: list(accounts_data))
    monkeypatch.setattr(api, "_is_main_account_email", lambda _email: False)
    monkeypatch.setattr("autoteam.auth_archive.archive_account_auth_file", lambda _email, _auth: str(archive_file))
    monkeypatch.setattr(
        "autoteam.sync_targets.delete_account_from_configured_targets",
        lambda email, **kwargs: cleanup_calls.append((email, kwargs)) or {"cpa": {"count": 1}},
    )

    def fake_update(email, **kwargs):
        accounts_data[0].update(kwargs)
        return accounts_data[0]

    monkeypatch.setattr("autoteam.accounts.update_account", fake_update)
    monkeypatch.setattr(
        "autoteam.accounts.mark_account_self_use",
        lambda email, remote_cleanup=None: fake_update(
            email,
            usage_status="self_use",
            sync_disabled=True,
            self_use_at=123,
            self_use_remote_cleanup=remote_cleanup or {},
        ),
    )

    result = api.post_self_use_account("self@example.com")

    assert cleanup_calls == [("self@example.com", {"auth_names": [auth_file.name]})]
    assert result["usage_status"] == "self_use"
    assert result["cpa_archive_file"] == str(archive_file)
    assert accounts_data[0]["usage_status"] == "self_use"
    assert accounts_data[0]["sync_disabled"] is True


def test_post_account_login_only_requires_local_mail_and_keeps_old_session(tmp_path, monkeypatch):
    session_file = tmp_path / "codex-user@example.com-team-abc-session.json"
    session_file.write_text("{}", encoding="utf-8")
    oauth_file = tmp_path / "codex-user@example.com-team-abc-oauth.json"
    oauth_file.write_text("{}", encoding="utf-8")
    archive_file = tmp_path / "archive" / oauth_file.name
    accounts_data = [
        {
            "email": "user@example.com",
            "status": "standby",
            "password": "secret",
            "auth_file": str(session_file),
            "session_auth_file": str(session_file),
            "mail_provider": "cloudmail",
            "mail_account_id": 7,
        }
    ]
    updates = []
    quota_calls = []

    monkeypatch.setattr("autoteam.accounts.load_accounts", lambda: list(accounts_data))
    monkeypatch.setattr(api, "_is_main_account_email", lambda _email: False)
    monkeypatch.setattr("autoteam.auth_archive.archive_account_auth_file", lambda _email, _path: str(archive_file))
    monkeypatch.setattr(api, "_require_account_mail_configs", lambda _acc, _label: None)
    monkeypatch.setattr(
        api,
        "_require_sync_target_configs",
        lambda _label: (_ for _ in ()).throw(AssertionError("sync target config should not be required")),
    )

    class FakeMailClient:
        def login(self):
            return None

    monkeypatch.setattr(
        "autoteam.mail_provider.get_mail_client_for_account",
        lambda _acc: FakeMailClient(),
    )
    monkeypatch.setattr("autoteam.mail_provider.get_account_mail_account_id", lambda _acc: 7)
    monkeypatch.setattr(
        "autoteam.codex_auth.login_codex_via_browser",
        lambda *args, **kwargs: {
            "email": "user@example.com",
            "plan_type": "team",
            "access_token": "token-1",
        },
    )
    monkeypatch.setattr(
        "autoteam.codex_auth.check_codex_quota",
        lambda token, account_id=None: quota_calls.append((token, account_id)) or ("ok", {"primary_pct": 10}),
    )
    monkeypatch.setattr("autoteam.codex_auth.save_auth_file", lambda _bundle: str(oauth_file))

    def fake_update(email, **kwargs):
        updates.append((email, kwargs))
        accounts_data[0].update(kwargs)
        return accounts_data[0]

    monkeypatch.setattr("autoteam.accounts.update_account", fake_update)
    monkeypatch.setattr(api, "_start_task", lambda command, func, params, *args, **kwargs: {"task_id": "task-1", "command": command, "params": params, "result": func(*args, **kwargs)})

    result = api.post_account_login(api.LoginAccountParams(email="user@example.com"))

    assert result["result"]["rt_auth_file"] == str(oauth_file)
    assert quota_calls == [("token-1", None)]
    assert accounts_data[0]["auth_file"] == str(oauth_file)
    assert accounts_data[0]["rt_auth_file"] == str(oauth_file)
    assert accounts_data[0]["session_auth_file"] == str(session_file)
    assert accounts_data[0]["status"] == "active"
    assert any("rt_auth_file" in item[1] for item in updates)


def test_post_account_login_marks_unavailable_on_account_deactivated(tmp_path, monkeypatch):
    accounts_data = [
        {
            "email": "dead@example.com",
            "status": "standby",
            "password": "secret",
            "mail_provider": "cloudmail",
            "mail_account_id": 7,
        }
    ]
    updates = []

    monkeypatch.setattr("autoteam.accounts.load_accounts", lambda: list(accounts_data))
    monkeypatch.setattr(api, "_is_main_account_email", lambda _email: False)
    monkeypatch.setattr(api, "_require_account_mail_configs", lambda _acc, _label: None)
    monkeypatch.setattr(
        api,
        "_require_sync_target_configs",
        lambda _label: (_ for _ in ()).throw(AssertionError("sync target config should not be required")),
    )

    class FakeMailClient:
        def login(self):
            return None

    monkeypatch.setattr(
        "autoteam.mail_provider.get_mail_client_for_account",
        lambda _acc: FakeMailClient(),
    )
    monkeypatch.setattr("autoteam.mail_provider.get_account_mail_account_id", lambda _acc: 7)
    monkeypatch.setattr(
        "autoteam.codex_auth.login_codex_via_browser",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr("autoteam.codex_auth.LAST_OAUTH_FAILURE_REASON", "account_deactivated")

    def fake_update(email, **kwargs):
        updates.append((email, kwargs))
        accounts_data[0].update(kwargs)
        return accounts_data[0]

    monkeypatch.setattr("autoteam.accounts.update_account", fake_update)
    def fake_start_task(command, func, params, *args, **kwargs):
        try:
            func(*args, **kwargs)
        except RuntimeError as exc:
            return {
                "task_id": "task-1",
                "command": command,
                "params": params,
                "status": "failed",
                "error": str(exc),
            }
        raise AssertionError("expected account_deactivated failure")

    monkeypatch.setattr(api, "_start_task", fake_start_task)

    result = api.post_account_login(api.LoginAccountParams(email="dead@example.com"))

    assert result["status"] == "failed"
    assert "account_deactivated" in result["error"]
    assert accounts_data[0]["status"] == accounts.STATUS_UNAVAILABLE
    assert accounts_data[0]["sync_disabled"] is True
    assert accounts_data[0]["unavailable_reason"] == "account_deactivated"
    assert any(item[1].get("unavailable_reason") == "account_deactivated" for item in updates)


def test_post_account_login_requires_force_for_sync_disabled(monkeypatch):
    accounts_data = [
        {
            "email": "dead@example.com",
            "status": "unavailable",
            "sync_disabled": True,
            "unavailable_reason": "account_deactivated",
            "mail_provider": "cloudmail",
        }
    ]

    monkeypatch.setattr("autoteam.accounts.load_accounts", lambda: list(accounts_data))
    monkeypatch.setattr(api, "_is_main_account_email", lambda _email: False)
    monkeypatch.setattr(api, "_require_account_mail_configs", lambda _acc, _label: None)
    monkeypatch.setattr(
        api,
        "_start_task",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("task should not start")),
    )

    with pytest.raises(HTTPException) as exc:
        api.post_account_login(api.LoginAccountParams(email="dead@example.com"))

    assert exc.value.status_code == 400
    assert "force=true" in exc.value.detail


def test_post_account_login_force_allows_sync_disabled(tmp_path, monkeypatch):
    oauth_file = tmp_path / "codex-dead@example.com-team-abc-oauth.json"
    oauth_file.write_text("{}", encoding="utf-8")
    accounts_data = [
        {
            "email": "dead@example.com",
            "status": "unavailable",
            "sync_disabled": True,
            "unavailable_reason": "account_deactivated",
            "password": "secret",
            "mail_provider": "cloudmail",
            "mail_account_id": 7,
        }
    ]

    monkeypatch.setattr("autoteam.accounts.load_accounts", lambda: list(accounts_data))
    monkeypatch.setattr(api, "_is_main_account_email", lambda _email: False)
    monkeypatch.setattr(api, "_require_account_mail_configs", lambda _acc, _label: None)
    monkeypatch.setattr("autoteam.auth_archive.archive_account_auth_file", lambda _email, _path: "")

    class FakeMailClient:
        def login(self):
            return None

    monkeypatch.setattr("autoteam.mail_provider.get_mail_client_for_account", lambda _acc: FakeMailClient())
    monkeypatch.setattr("autoteam.mail_provider.get_account_mail_account_id", lambda _acc: 7)
    monkeypatch.setattr(
        "autoteam.codex_auth.login_codex_via_browser",
        lambda *args, **kwargs: {
            "email": "dead@example.com",
            "plan_type": "unknown",
            "access_token": "token-1",
        },
    )
    monkeypatch.setattr("autoteam.codex_auth.save_auth_file", lambda _bundle: str(oauth_file))

    def fake_update(email, **kwargs):
        accounts_data[0].update(kwargs)
        return accounts_data[0]

    monkeypatch.setattr("autoteam.accounts.update_account", fake_update)
    monkeypatch.setattr(
        api,
        "_start_task",
        lambda command, func, params, *args, **kwargs: {
            "task_id": "task-1",
            "command": command,
            "params": params,
            "result": func(*args, **kwargs),
        },
    )

    result = api.post_account_login(api.LoginAccountParams(email="dead@example.com", force=True))

    assert result["result"]["auth_file"] == str(oauth_file)


def test_post_account_usage_status_allows_normal_inventory_only(monkeypatch):
    accounts_data = [{"email": "stock@example.com", "status": "active", "usage_status": "normal"}]

    monkeypatch.setattr("autoteam.accounts.load_accounts", lambda: list(accounts_data))

    def fake_mark(email, usage_status):
        accounts_data[0]["usage_status"] = usage_status
        return accounts_data[0]

    monkeypatch.setattr("autoteam.accounts.mark_account_usage_status", fake_mark)

    result = api.post_account_usage_status("stock@example.com", api.UsageStatusParams(usage_status="inventory"))

    assert result == {"email": "stock@example.com", "usage_status": "inventory"}


def test_sanitize_account_keeps_exportable_main_account_active_without_live_quota(tmp_path, monkeypatch):
    main_email = "owner@example.com"
    auth_file = tmp_path / "codex-main.json"
    auth_file.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(api, "_is_main_account_email", lambda email: email == main_email)
    monkeypatch.setattr("autoteam.codex_auth.get_saved_main_auth_file", lambda: str(auth_file))

    sanitized = api._sanitize_account(
        {"email": main_email, "status": "exhausted", "auth_file": "/app/auths/missing.json"}
    )

    assert sanitized["is_main_account"] is True
    assert sanitized["status"] == "active"


def test_post_setup_save_only_requires_api_key_and_generates_one(monkeypatch):
    written = {}

    def fake_write_env(key, value):
        written[key] = value

    monkeypatch.setattr("autoteam.setup_wizard._write_env", fake_write_env)
    monkeypatch.setattr("autoteam.setup_wizard._verify_mail_provider", lambda provider=None: True)
    monkeypatch.setattr("autoteam.setup_wizard._verify_cpa", lambda: True)
    monkeypatch.setattr("secrets.token_urlsafe", lambda _n: "generated-token")
    monkeypatch.setattr("importlib.reload", lambda module: module)
    monkeypatch.setattr(api, "API_KEY", "")
    monkeypatch.delenv("CPA_URL", raising=False)
    monkeypatch.delenv("MAIL_PROVIDER", raising=False)
    monkeypatch.delenv("MO_EMAIL_API_KEY", raising=False)
    monkeypatch.delenv("CLOUDMAIL_BASE_URL", raising=False)
    monkeypatch.delenv("CLOUDMAIL_EMAIL", raising=False)
    monkeypatch.delenv("CLOUDMAIL_PASSWORD", raising=False)
    monkeypatch.delenv("CLOUDMAIL_DOMAIN", raising=False)
    monkeypatch.delenv("API_KEY", raising=False)

    result = api.post_setup_save(
        api.SetupConfig(
            CLOUDMAIL_BASE_URL="http://mail.example.com",
            CLOUDMAIL_EMAIL="admin@example.com",
            CLOUDMAIL_PASSWORD="secret",
            CLOUDMAIL_DOMAIN="@example.com",
            CPA_URL="",
            CPA_KEY="key-1",
            PLAYWRIGHT_PROXY_URL="",
            PLAYWRIGHT_PROXY_BYPASS="",
            API_KEY="",
        )
    )

    assert written["API_KEY"] == "generated-token"
    assert result["api_key"] == "generated-token"
    assert api.API_KEY == "generated-token"
    assert "CPA_URL" not in written


def test_get_setup_status_only_requires_api_key(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("", encoding="utf-8")

    monkeypatch.setattr("autoteam.setup_wizard.ENV_FILE", env_file)
    monkeypatch.setattr("autoteam.setup_wizard.ENV_EXAMPLE", tmp_path / ".env.example")
    for key in ("API_KEY", "CLOUDMAIL_BASE_URL", "CPA_KEY"):
        monkeypatch.delenv(key, raising=False)

    result = api.get_setup_status()

    assert result["configured"] is False
    assert result["fields"] == [
        {
            "key": "API_KEY",
            "prompt": "API 鉴权密钥（回车自动生成）",
            "default": "",
            "optional": False,
            "configured": False,
        }
    ]


def test_get_runtime_config_returns_current_values_from_env_file(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "CLOUDMAIL_BASE_URL=http://mail.example.com",
                "MAIL_PROVIDER=cloudmail",
                "CLOUDMAIL_EMAIL=admin@example.com",
                "CLOUDMAIL_PASSWORD=secret",
                "CLOUDMAIL_DOMAIN=@example.com",
                "CPA_URL=http://127.0.0.1:8317",
                "CPA_KEY=key-1",
                "PLAYWRIGHT_BROWSER_MODE=visible",
                "PLAYWRIGHT_HEADLESS=false",
                "PLAYWRIGHT_PROXY_URL=socks5://127.0.0.1:1080",
                "PLAYWRIGHT_PROXY_BYPASS=localhost,127.0.0.1",
                "OUTBOUND_PROXY_ENABLED=true",
                "OUTBOUND_PROXY_POOL=http://127.0.0.1:10808",
                "OUTBOUND_PROXY_BYPASS=localhost,127.0.0.1,::1",
                "OUTBOUND_PROXY_STRATEGY=task-sticky",
                "OUTBOUND_PROXY_FAILOVER=true",
                "API_KEY=runtime-key",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr("autoteam.setup_wizard.ENV_FILE", env_file)
    for key in (
        "CLOUDMAIL_BASE_URL",
        "MAIL_PROVIDER",
        "MO_EMAIL_API_KEY",
        "CLOUDMAIL_EMAIL",
        "CLOUDMAIL_PASSWORD",
        "CLOUDMAIL_DOMAIN",
        "CPA_URL",
        "CPA_KEY",
        "PLAYWRIGHT_BROWSER_MODE",
        "PLAYWRIGHT_HEADLESS",
        "PLAYWRIGHT_PROXY_URL",
        "PLAYWRIGHT_PROXY_BYPASS",
        "OUTBOUND_PROXY_ENABLED",
        "OUTBOUND_PROXY_POOL",
        "OUTBOUND_PROXY_BYPASS",
        "OUTBOUND_PROXY_STRATEGY",
        "OUTBOUND_PROXY_FAILOVER",
        "API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)

    result = api.get_runtime_config()
    fields = {field["key"]: field for field in result["fields"]}

    assert result["configured"] is True
    assert fields["CLOUDMAIL_EMAIL"]["value"] == "admin@example.com"
    assert fields["CLOUDMAIL_EMAIL"]["runtime_required"] is True
    assert fields["CPA_KEY"]["value"] == "key-1"
    assert fields["CPA_KEY"]["runtime_required"] is True
    assert fields["PLAYWRIGHT_BROWSER_MODE"]["value"] == "visible"
    assert fields["PLAYWRIGHT_BROWSER_MODE"]["runtime_required"] is False
    assert fields["PLAYWRIGHT_HEADLESS"]["value"] == "false"
    assert fields["PLAYWRIGHT_HEADLESS"]["runtime_required"] is False
    assert fields["PLAYWRIGHT_PROXY_URL"]["value"] == "socks5://127.0.0.1:1080"
    assert fields["PLAYWRIGHT_PROXY_URL"]["runtime_required"] is False
    assert fields["PLAYWRIGHT_PROXY_BYPASS"]["value"] == "localhost,127.0.0.1"
    assert fields["OUTBOUND_PROXY_ENABLED"]["value"] == "true"
    assert fields["OUTBOUND_PROXY_POOL"]["value"] == "http://127.0.0.1:10808"
    assert fields["OUTBOUND_PROXY_BYPASS"]["value"] == "localhost,127.0.0.1,::1"
    assert fields["OUTBOUND_PROXY_FAILOVER"]["value"] == "true"
    assert fields["API_KEY"]["value"] == "runtime-key"
    assert fields["API_KEY"]["runtime_required"] is True


def test_get_runtime_config_switches_required_mail_fields_to_mo_email(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "MAIL_PROVIDER=mo_email",
                "MO_EMAIL_BASE_URL=https://mo.gymbro.cloud",
                "MO_EMAIL_API_KEY=secret",
                "MO_EMAIL_DOMAIN=gymbro.cloud",
                "MO_EMAIL_NAME_PREFIX=abc",
                "MO_EMAIL_START_INDEX=1",
                "MO_EMAIL_EXPIRY_TIME=3600000",
                "API_KEY=runtime-key",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr("autoteam.setup_wizard.ENV_FILE", env_file)
    for key in (
        "MAIL_PROVIDER",
        "MO_EMAIL_BASE_URL",
        "MO_EMAIL_API_KEY",
        "MO_EMAIL_DOMAIN",
        "MO_EMAIL_NAME_PREFIX",
        "MO_EMAIL_START_INDEX",
        "MO_EMAIL_EXPIRY_TIME",
        "CLOUDMAIL_BASE_URL",
        "CLOUDMAIL_EMAIL",
        "CF_TEMP_EMAIL_BASE_URL",
        "CF_TEMP_EMAIL_ADMIN_PASSWORD",
        "API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)

    result = api.get_runtime_config()
    fields = {field["key"]: field for field in result["fields"]}

    assert result["configured"] is True
    assert fields["MAIL_PROVIDER"]["value"] == "mo_email"
    assert fields["MO_EMAIL_API_KEY"]["runtime_required"] is True
    assert fields["MO_EMAIL_DOMAIN"]["runtime_required"] is True
    assert fields["CLOUDMAIL_BASE_URL"]["runtime_required"] is False
    assert fields["CF_TEMP_EMAIL_BASE_URL"]["runtime_required"] is False


def test_get_runtime_config_switches_required_mail_fields_by_provider(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "MAIL_PROVIDER=cloudflare_temp_email",
                "CF_TEMP_EMAIL_BASE_URL=https://tempmail.example.com/admin",
                "CF_TEMP_EMAIL_ADMIN_PASSWORD=secret",
                "CF_TEMP_EMAIL_DOMAIN=example.com",
                "API_KEY=runtime-key",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr("autoteam.setup_wizard.ENV_FILE", env_file)
    for key in (
        "MAIL_PROVIDER",
        "CF_TEMP_EMAIL_BASE_URL",
        "CF_TEMP_EMAIL_ADMIN_PASSWORD",
        "CF_TEMP_EMAIL_DOMAIN",
        "CLOUDMAIL_BASE_URL",
        "CLOUDMAIL_EMAIL",
        "CLOUDMAIL_PASSWORD",
        "CLOUDMAIL_DOMAIN",
        "API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)

    result = api.get_runtime_config()
    fields = {field["key"]: field for field in result["fields"]}

    assert result["configured"] is True
    assert fields["MAIL_PROVIDER"]["value"] == "cloudflare_temp_email"
    assert fields["CF_TEMP_EMAIL_BASE_URL"]["runtime_required"] is True
    assert fields["CF_TEMP_EMAIL_ADMIN_PASSWORD"]["runtime_required"] is True
    assert fields["CF_TEMP_EMAIL_DOMAIN"]["runtime_required"] is True
    assert fields["CLOUDMAIL_BASE_URL"]["runtime_required"] is False
    assert fields["CLOUDMAIL_EMAIL"]["runtime_required"] is False


def test_put_runtime_config_allows_partial_runtime_fields_when_api_key_exists(monkeypatch):
    written = {}

    def fake_write_env(key, value):
        written[key] = value

    monkeypatch.setattr("autoteam.setup_wizard._write_env", fake_write_env)
    monkeypatch.setattr(
        "autoteam.setup_wizard._verify_mail_provider",
        lambda provider=None: (_ for _ in ()).throw(AssertionError("mail provider verify should not run")),
    )
    monkeypatch.setattr(
        "autoteam.setup_wizard._verify_cpa",
        lambda: (_ for _ in ()).throw(AssertionError("cpa verify should not run")),
    )
    monkeypatch.setattr("importlib.reload", lambda module: module)
    monkeypatch.setattr(api, "API_KEY", "old-key")

    monkeypatch.setenv("API_KEY", "old-key")
    monkeypatch.delenv("CLOUDMAIL_BASE_URL", raising=False)
    monkeypatch.delenv("CLOUDMAIL_EMAIL", raising=False)
    monkeypatch.delenv("CLOUDMAIL_PASSWORD", raising=False)
    monkeypatch.delenv("CLOUDMAIL_DOMAIN", raising=False)
    monkeypatch.delenv("CPA_URL", raising=False)
    monkeypatch.delenv("CPA_KEY", raising=False)

    result = api.put_runtime_config(
        api.SetupConfig(
            CLOUDMAIL_BASE_URL="",
            CLOUDMAIL_EMAIL="",
            CLOUDMAIL_PASSWORD="",
            CLOUDMAIL_DOMAIN="",
            CPA_URL="",
            CPA_KEY="",
            PLAYWRIGHT_BROWSER_MODE="embedded",
            PLAYWRIGHT_PROXY_URL="",
            PLAYWRIGHT_PROXY_BYPASS="",
            API_KEY="old-key",
        )
    )

    assert result["message"] == "配置保存成功"
    assert written["API_KEY"] == "old-key"
    assert written["PLAYWRIGHT_BROWSER_MODE"] == "embedded"
    assert written["PLAYWRIGHT_HEADLESS"] == "true"
    assert "CPA_URL" not in written


def test_put_runtime_config_proxy_change_skips_existing_cpa_validation(monkeypatch):
    written = {}

    def fake_write_env(key, value):
        written[key] = value

    monkeypatch.setattr("autoteam.setup_wizard._write_env", fake_write_env)
    monkeypatch.setattr("autoteam.setup_wizard._verify_mail_provider", lambda provider=None: True)
    monkeypatch.setattr(
        "autoteam.setup_wizard._verify_cpa",
        lambda: (_ for _ in ()).throw(AssertionError("cpa verify should not run for proxy-only changes")),
    )
    monkeypatch.setattr("autoteam.setup_wizard._verify_sub2api", lambda: True)
    monkeypatch.setattr("importlib.reload", lambda module: module)
    monkeypatch.setattr(api, "API_KEY", "old-key")

    monkeypatch.setenv("API_KEY", "old-key")
    monkeypatch.setenv("MAIL_PROVIDER", "mo_email")
    monkeypatch.setenv("MO_EMAIL_BASE_URL", "https://mo.gymbro.cloud")
    monkeypatch.setenv("MO_EMAIL_API_KEY", "mail-key")
    monkeypatch.setenv("MO_EMAIL_DOMAIN", "gymbro.cloud")
    monkeypatch.setenv("MO_EMAIL_NAME_PREFIX", "abc")
    monkeypatch.setenv("MO_EMAIL_START_INDEX", "1")
    monkeypatch.setenv("MO_EMAIL_EXPIRY_TIME", "3600000")
    monkeypatch.setenv("SYNC_TARGET_CPA", "true")
    monkeypatch.setenv("CPA_URL", "http://127.0.0.1:8317")
    monkeypatch.setenv("CPA_KEY", "cpa-key")
    monkeypatch.setenv("OUTBOUND_PROXY_ENABLED", "true")
    monkeypatch.setenv("OUTBOUND_PROXY_POOL", "http://127.0.0.1:10808")
    monkeypatch.setenv("OUTBOUND_PROXY_BYPASS", "localhost,127.0.0.1,::1")
    monkeypatch.setenv("OUTBOUND_PROXY_STRATEGY", "task-sticky")
    monkeypatch.setenv("OUTBOUND_PROXY_FAILOVER", "true")

    result = api.put_runtime_config(
        api.SetupConfig(
            MAIL_PROVIDER="mo_email",
            MO_EMAIL_BASE_URL="https://mo.gymbro.cloud",
            MO_EMAIL_API_KEY="mail-key",
            MO_EMAIL_DOMAIN="gymbro.cloud",
            MO_EMAIL_NAME_PREFIX="abc",
            MO_EMAIL_START_INDEX="1",
            MO_EMAIL_EXPIRY_TIME="3600000",
            SYNC_TARGET_CPA="true",
            CPA_URL="http://127.0.0.1:8317",
            CPA_KEY="cpa-key",
            OUTBOUND_PROXY_ENABLED="true",
            OUTBOUND_PROXY_POOL="http://127.0.0.1:10809",
            OUTBOUND_PROXY_BYPASS="localhost,127.0.0.1,::1",
            OUTBOUND_PROXY_STRATEGY="task-sticky",
            OUTBOUND_PROXY_FAILOVER="true",
            API_KEY="old-key",
        )
    )

    assert result["message"] == "配置保存成功"
    assert written["OUTBOUND_PROXY_POOL"] == "http://127.0.0.1:10809"


def test_put_runtime_config_cpa_change_still_validates_cpa(monkeypatch):
    written = {}

    def fake_write_env(key, value):
        written[key] = value

    monkeypatch.setattr("autoteam.setup_wizard._write_env", fake_write_env)
    monkeypatch.setattr("autoteam.setup_wizard._verify_mail_provider", lambda provider=None: True)
    monkeypatch.setattr("autoteam.setup_wizard._verify_cpa", lambda: False)
    monkeypatch.setattr("autoteam.setup_wizard._verify_sub2api", lambda: True)
    monkeypatch.setattr("importlib.reload", lambda module: module)
    monkeypatch.setattr(api, "API_KEY", "old-key")

    monkeypatch.setenv("API_KEY", "old-key")
    monkeypatch.setenv("MAIL_PROVIDER", "mo_email")
    monkeypatch.setenv("MO_EMAIL_BASE_URL", "https://mo.gymbro.cloud")
    monkeypatch.setenv("MO_EMAIL_API_KEY", "mail-key")
    monkeypatch.setenv("MO_EMAIL_DOMAIN", "gymbro.cloud")
    monkeypatch.setenv("MO_EMAIL_NAME_PREFIX", "abc")
    monkeypatch.setenv("MO_EMAIL_START_INDEX", "1")
    monkeypatch.setenv("MO_EMAIL_EXPIRY_TIME", "3600000")
    monkeypatch.setenv("SYNC_TARGET_CPA", "true")
    monkeypatch.setenv("CPA_URL", "http://127.0.0.1:8317")
    monkeypatch.setenv("CPA_KEY", "old-cpa-key")

    result = api.put_runtime_config(
        api.SetupConfig(
            MAIL_PROVIDER="mo_email",
            MO_EMAIL_BASE_URL="https://mo.gymbro.cloud",
            MO_EMAIL_API_KEY="mail-key",
            MO_EMAIL_DOMAIN="gymbro.cloud",
            MO_EMAIL_NAME_PREFIX="abc",
            MO_EMAIL_START_INDEX="1",
            MO_EMAIL_EXPIRY_TIME="3600000",
            SYNC_TARGET_CPA="true",
            CPA_URL="http://127.0.0.1:8317",
            CPA_KEY="new-cpa-key",
            API_KEY="old-key",
        )
    )

    assert result.status_code == 400
    assert json.loads(result.body)["message"] == "CPA 连接失败"
    assert written == {}
    assert api.os.environ["CPA_KEY"] == "old-cpa-key"


def test_get_runtime_config_source_returns_env_content(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("CLOUDMAIL_EMAIL=admin@example.com\nAPI_KEY=test-key\n", encoding="utf-8")

    monkeypatch.setattr("autoteam.setup_wizard.ENV_FILE", env_file)
    monkeypatch.setattr("autoteam.setup_wizard.ENV_EXAMPLE", tmp_path / ".env.example")

    result = api.get_runtime_config_source()

    assert result["path"].endswith(".env")
    assert "CLOUDMAIL_EMAIL=admin@example.com" in result["content"]
    assert "API_KEY=test-key" in result["content"]


def test_runtime_env_file_hot_reload_updates_current_process_without_restart(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "CPA_URL=http://100.78.125.121:8317",
                "API_KEY=new-key",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr("autoteam.setup_wizard.ENV_FILE", env_file)
    monkeypatch.setattr(
        api,
        "_RUNTIME_ENV_BASE",
        {
            "CPA_URL": "http://127.0.0.1:8317",
            "CPA_KEY": "external-key",
            "API_KEY": "old-key",
        },
    )
    monkeypatch.setattr(api, "_runtime_env_reload_state", {"signature": None})
    monkeypatch.setattr(api, "_reload_runtime_config_modules", lambda: None)
    monkeypatch.setattr(
        api, "_sync_runtime_globals", lambda: setattr(api, "API_KEY", api.os.environ.get("API_KEY", ""))
    )

    monkeypatch.setenv("CPA_URL", "http://127.0.0.1:8317")
    monkeypatch.setenv("CPA_KEY", "external-key")
    monkeypatch.setenv("API_KEY", "old-key")

    changed = api._maybe_reload_runtime_config_from_env_file(force=True)

    assert changed is True
    assert api.os.environ["CPA_URL"] == "http://100.78.125.121:8317"
    assert api.os.environ["CPA_KEY"] == "external-key"
    assert api.API_KEY == "new-key"


@pytest.mark.parametrize(
    ("endpoint", "args", "action_label"),
    [
        ("post_rotate", (api.TaskParams(target=5),), "智能轮转"),
        ("post_add", (), "添加新账号"),
        ("post_fill", (api.TaskParams(target=5),), "补满 Team 成员"),
    ],
)
def test_pool_task_endpoints_require_cloudmail_config_first(monkeypatch, endpoint, args, action_label):
    monkeypatch.setattr("autoteam.setup_wizard._read_env", lambda: {})
    monkeypatch.setenv("MAIL_PROVIDER", "cloudmail")
    for key in (
        "CLOUDMAIL_BASE_URL",
        "CLOUDMAIL_EMAIL",
        "CLOUDMAIL_PASSWORD",
        "CLOUDMAIL_DOMAIN",
        "CPA_URL",
        "CPA_KEY",
    ):
        monkeypatch.delenv(key, raising=False)

    with pytest.raises(HTTPException) as exc:
        getattr(api, endpoint)(*args)

    assert exc.value.status_code == 400
    assert action_label in exc.value.detail
    assert "配置面板" in exc.value.detail
    assert "CLOUDMAIL_BASE_URL" in exc.value.detail
    assert "CPA_KEY" not in exc.value.detail


@pytest.mark.parametrize(
    ("endpoint", "args", "action_label"),
    [
        ("post_rotate", (api.TaskParams(target=5),), "智能轮转"),
        ("post_add", (), "添加新账号"),
        ("post_fill", (api.TaskParams(target=5),), "补满 Team 成员"),
    ],
)
def test_pool_task_endpoints_require_enabled_sync_target_after_cloudmail(monkeypatch, endpoint, args, action_label):
    monkeypatch.setattr("autoteam.setup_wizard._read_env", lambda: {})
    monkeypatch.setenv("MAIL_PROVIDER", "cloudmail")
    monkeypatch.setenv("CLOUDMAIL_BASE_URL", "http://mail.example.com")
    monkeypatch.setenv("CLOUDMAIL_EMAIL", "admin@example.com")
    monkeypatch.setenv("CLOUDMAIL_PASSWORD", "secret")
    monkeypatch.setenv("CLOUDMAIL_DOMAIN", "@example.com")
    for key in (
        "SYNC_TARGET_CPA",
        "CPA_URL",
        "CPA_KEY",
        "SYNC_TARGET_SUB2API",
        "SUB2API_URL",
        "SUB2API_EMAIL",
        "SUB2API_PASSWORD",
    ):
        monkeypatch.delenv(key, raising=False)

    with pytest.raises(HTTPException) as exc:
        getattr(api, endpoint)(*args)

    assert exc.value.status_code == 400
    assert action_label in exc.value.detail
    assert "远端同步目标" in exc.value.detail


@pytest.mark.parametrize(
    ("endpoint", "action_label"),
    [
        ("post_sync", "同步远端"),
        ("post_sync_cpa", "同步 CPA"),
        ("post_sync_from_cpa", "拉取 CPA"),
        ("get_cpa_files", "查看 CPA 文件"),
    ],
)
def test_cpa_endpoints_require_cpa_config(monkeypatch, endpoint, action_label):
    monkeypatch.setattr("autoteam.setup_wizard._read_env", lambda: {})
    for key in ("CPA_URL", "CPA_KEY"):
        monkeypatch.delenv(key, raising=False)

    with pytest.raises(HTTPException) as exc:
        getattr(api, endpoint)()

    assert exc.value.status_code == 400
    assert action_label in exc.value.detail
    if endpoint == "post_sync":
        assert "远端同步目标" in exc.value.detail
    else:
        assert "配置面板" in exc.value.detail
        assert "CPA_URL" in exc.value.detail
        assert "CPA_KEY" in exc.value.detail


def test_post_sync_supports_sub2api_only(monkeypatch):
    monkeypatch.setattr("autoteam.setup_wizard._read_env", lambda: {})
    monkeypatch.setenv("SYNC_TARGET_SUB2API", "true")
    monkeypatch.setenv("SUB2API_URL", "http://sub2api.example.com")
    monkeypatch.setenv("SUB2API_EMAIL", "admin@example.com")
    monkeypatch.setenv("SUB2API_PASSWORD", "secret")
    monkeypatch.delenv("SYNC_TARGET_CPA", raising=False)
    monkeypatch.delenv("CPA_URL", raising=False)
    monkeypatch.delenv("CPA_KEY", raising=False)
    monkeypatch.setattr("autoteam.sync_targets.sync_to_configured_targets", lambda: {"sub2api": {"created": 1}})

    result = api.post_sync()

    assert result["message"] == "已同步到 Sub2API"
    assert result["result"] == {"sub2api": {"created": 1}}


def test_post_sync_cpa_uses_cpa_only(monkeypatch):
    monkeypatch.setattr("autoteam.setup_wizard._read_env", lambda: {})
    monkeypatch.setenv("CPA_URL", "http://cpa.example.com")
    monkeypatch.setenv("CPA_KEY", "secret")
    monkeypatch.setenv("SYNC_TARGET_SUB2API", "true")
    monkeypatch.setenv("SUB2API_URL", "http://sub2api.example.com")
    monkeypatch.setenv("SUB2API_EMAIL", "admin@example.com")
    monkeypatch.setenv("SUB2API_PASSWORD", "secret")
    monkeypatch.setattr("autoteam.cpa_sync.sync_to_cpa", lambda: {"uploaded": 1})

    result = api.post_sync_cpa()

    assert result["message"] == "已同步到 CPA"
    assert result["result"] == {"uploaded": 1}


def test_post_sync_sub2api_uses_sub2api_only(monkeypatch):
    monkeypatch.setattr("autoteam.setup_wizard._read_env", lambda: {})
    monkeypatch.setenv("SUB2API_URL", "http://sub2api.example.com")
    monkeypatch.setenv("SUB2API_EMAIL", "admin@example.com")
    monkeypatch.setenv("SUB2API_PASSWORD", "secret")
    monkeypatch.delenv("CPA_URL", raising=False)
    monkeypatch.delenv("CPA_KEY", raising=False)
    monkeypatch.setattr("autoteam.sub2api_sync.sync_to_sub2api", lambda: {"created": 0, "updated": 1})

    result = api.post_sync_sub2api()

    assert result["message"] == "已同步到 Sub2API"
    assert result["result"] == {"created": 0, "updated": 1}


def test_post_sync_sub2api_requires_sub2api_config(monkeypatch):
    monkeypatch.setattr("autoteam.setup_wizard._read_env", lambda: {})
    for key in ("SUB2API_URL", "SUB2API_EMAIL", "SUB2API_PASSWORD"):
        monkeypatch.delenv(key, raising=False)

    with pytest.raises(HTTPException) as exc:
        api.post_sync_sub2api()

    assert exc.value.status_code == 400
    assert "同步 Sub2API" in exc.value.detail
    assert "SUB2API_URL" in exc.value.detail
    assert "SUB2API_EMAIL" in exc.value.detail
    assert "SUB2API_PASSWORD" in exc.value.detail


def test_post_sync_saved_main_codex_requires_saved_auth(monkeypatch):
    monkeypatch.setattr("autoteam.setup_wizard._read_env", lambda: {})
    monkeypatch.setenv("SYNC_TARGET_CPA", "true")
    monkeypatch.setenv("CPA_URL", "http://cpa.example.com")
    monkeypatch.setenv("CPA_KEY", "secret")
    monkeypatch.setattr("autoteam.codex_auth.get_saved_main_auth_file", lambda: "")

    with pytest.raises(HTTPException) as exc:
        api.post_sync_saved_main_codex()

    assert exc.value.status_code == 400
    assert "未找到主号 Codex 凭证" in exc.value.detail


def test_post_sync_saved_main_codex_pushes_existing_auth(monkeypatch):
    monkeypatch.setattr("autoteam.setup_wizard._read_env", lambda: {})
    monkeypatch.setenv("SYNC_TARGET_CPA", "true")
    monkeypatch.setenv("CPA_URL", "http://cpa.example.com")
    monkeypatch.setenv("CPA_KEY", "secret")
    monkeypatch.setattr("autoteam.codex_auth.get_saved_main_auth_file", lambda: "/tmp/codex-main.json")
    monkeypatch.setattr(
        "autoteam.sync_targets.sync_main_codex_to_configured_targets",
        lambda auth_file: {"auth_file": auth_file, "cpa": {"uploaded": 1}},
    )

    result = api.post_sync_saved_main_codex()

    assert result["message"] == "主号 Codex 凭证已同步到已启用远端"
    assert result["result"]["auth_file"] == "/tmp/codex-main.json"


def test_pool_task_endpoint_accepts_sub2api_only_config(monkeypatch):
    monkeypatch.setattr("autoteam.setup_wizard._read_env", lambda: {})
    monkeypatch.setenv("MAIL_PROVIDER", "cloudmail")
    monkeypatch.setenv("CLOUDMAIL_BASE_URL", "http://mail.example.com")
    monkeypatch.setenv("CLOUDMAIL_EMAIL", "admin@example.com")
    monkeypatch.setenv("CLOUDMAIL_PASSWORD", "secret")
    monkeypatch.setenv("CLOUDMAIL_DOMAIN", "@example.com")
    monkeypatch.setenv("SYNC_TARGET_SUB2API", "true")
    monkeypatch.setenv("SUB2API_URL", "http://sub2api.example.com")
    monkeypatch.setenv("SUB2API_EMAIL", "admin@example.com")
    monkeypatch.setenv("SUB2API_PASSWORD", "secret")
    monkeypatch.delenv("SYNC_TARGET_CPA", raising=False)
    monkeypatch.delenv("CPA_URL", raising=False)
    monkeypatch.delenv("CPA_KEY", raising=False)
    monkeypatch.setattr(api, "_start_task", lambda command, func, params, *args, **kwargs: {"task_id": command})

    result = api.post_add()

    assert result == {"task_id": "add"}


def test_put_runtime_config_source_applies_env_and_updates_api_key(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("API_KEY=old-key\n", encoding="utf-8")

    monkeypatch.setattr("autoteam.setup_wizard.ENV_FILE", env_file)
    monkeypatch.setattr("autoteam.setup_wizard.ENV_EXAMPLE", tmp_path / ".env.example")
    monkeypatch.setattr("autoteam.setup_wizard._verify_mail_provider", lambda provider=None: True)
    monkeypatch.setattr("autoteam.setup_wizard._verify_cpa", lambda: True)
    monkeypatch.setattr("importlib.reload", lambda module: module)
    monkeypatch.setattr(api, "API_KEY", "old-key")

    for key in (
        "MAIL_PROVIDER",
        "MO_EMAIL_API_KEY",
        "CLOUDMAIL_BASE_URL",
        "CLOUDMAIL_EMAIL",
        "CLOUDMAIL_PASSWORD",
        "CLOUDMAIL_DOMAIN",
        "CPA_URL",
        "CPA_KEY",
        "PLAYWRIGHT_BROWSER_MODE",
        "PLAYWRIGHT_PROXY_URL",
        "PLAYWRIGHT_PROXY_BYPASS",
        "OUTBOUND_PROXY_ENABLED",
        "OUTBOUND_PROXY_POOL",
        "OUTBOUND_PROXY_BYPASS",
        "OUTBOUND_PROXY_STRATEGY",
        "OUTBOUND_PROXY_FAILOVER",
        "API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)

    result = api.put_runtime_config_source(
        api.SourceConfig(
            content="\n".join(
                [
                    "CLOUDMAIL_BASE_URL=http://mail.example.com",
                    "CLOUDMAIL_EMAIL=admin@example.com",
                    "CLOUDMAIL_PASSWORD=secret",
                    "CLOUDMAIL_DOMAIN=@example.com",
                    "CPA_URL=http://127.0.0.1:8317",
                    "CPA_KEY=key-1",
                    "API_KEY=new-key",
                ]
            )
        )
    )

    assert result["message"] == "源文件保存成功"
    assert result["api_key"] == "new-key"
    assert api.API_KEY == "new-key"
    assert env_file.read_text(encoding="utf-8").splitlines()[0] == "CLOUDMAIL_BASE_URL=http://mail.example.com"


def test_auto_check_skips_rotate_when_pool_configs_are_missing(tmp_path, monkeypatch, caplog):
    auth_file = tmp_path / "active.json"
    auth_file.write_text('{"access_token": "token-low"}', encoding="utf-8")

    updates = []
    started = []

    monkeypatch.setattr(api, "_auto_check_config", {"interval": 0, "threshold": 10, "min_low": 1, "target_seats": 5})
    monkeypatch.setattr(api, "_auto_check_stop", threading.Event())
    monkeypatch.setattr(api, "_auto_check_restart", threading.Event())
    monkeypatch.setattr(api, "_maybe_reload_runtime_config_from_env_file", lambda *args, **kwargs: False)
    monkeypatch.setattr(api, "_is_main_account_email", lambda _email: False)
    monkeypatch.setattr("autoteam.setup_wizard._read_env", lambda: {})
    monkeypatch.setenv("MAIL_PROVIDER", "cloudmail")
    for key in (
        "CLOUDMAIL_BASE_URL",
        "CLOUDMAIL_EMAIL",
        "CLOUDMAIL_PASSWORD",
        "CLOUDMAIL_DOMAIN",
        "CPA_URL",
        "CPA_KEY",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(
        "autoteam.accounts.load_accounts",
        lambda: [{"email": "low@example.com", "status": "active", "auth_file": str(auth_file)}],
    )
    monkeypatch.setattr(
        "autoteam.codex_auth.check_codex_quota",
        lambda _token: ("ok", {"primary_pct": 95, "primary_resets_at": 1234567890, "weekly_pct": 1}),
    )
    monkeypatch.setattr("autoteam.accounts.update_account", lambda email, **kwargs: updates.append((email, kwargs)))
    monkeypatch.setattr(
        api,
        "_start_task",
        lambda command, func, params, *args, **kwargs: started.append((command, params, args, kwargs)),
    )

    stop_event = api._auto_check_stop
    wait_calls = {"count": 0}

    def fake_wait(_seconds):
        wait_calls["count"] += 1
        return wait_calls["count"] > 1

    monkeypatch.setattr(stop_event, "wait", fake_wait)

    with caplog.at_level(logging.WARNING):
        api._auto_check_loop()

    assert updates == []
    assert started == []
    assert "跳过自动轮转/补位" in caplog.text
    assert "配置面板" in caplog.text


def test_auto_check_persists_reuse_blocking_metadata_before_rotate(tmp_path, monkeypatch):
    low_auth = tmp_path / "low.json"
    exhausted_auth = tmp_path / "exhausted.json"
    low_auth.write_text('{"access_token": "token-low"}', encoding="utf-8")
    exhausted_auth.write_text('{"access_token": "token-exhausted"}', encoding="utf-8")

    updates = []

    def fake_update_account(email, **kwargs):
        updates.append((email, kwargs))

    _set_pool_runtime_config(monkeypatch)
    monkeypatch.setattr(api, "_auto_check_config", {"interval": 0, "threshold": 10, "min_low": 2, "target_seats": 5})
    monkeypatch.setattr(api, "_auto_check_stop", __import__("threading").Event())
    monkeypatch.setattr(api, "_auto_check_restart", __import__("threading").Event())
    monkeypatch.setattr(api, "_is_main_account_email", lambda _email: False)
    monkeypatch.setattr(
        "autoteam.accounts.load_accounts",
        lambda: [
            {"email": "low@example.com", "status": "active", "auth_file": str(low_auth)},
            {"email": "exhausted@example.com", "status": "active", "auth_file": str(exhausted_auth)},
        ],
    )
    monkeypatch.setattr(
        "autoteam.codex_auth.check_codex_quota",
        lambda token: (
            ("ok", {"primary_pct": 93, "primary_resets_at": 1234567890, "weekly_pct": 1, "weekly_resets_at": 0})
            if token == "token-low"
            else (
                "exhausted",
                {
                    "resets_at": 2222222222,
                    "quota_info": {
                        "primary_pct": 100,
                        "primary_resets_at": 2222222222,
                        "weekly_pct": 100,
                        "weekly_resets_at": 0,
                    },
                },
            )
        ),
    )
    monkeypatch.setattr("autoteam.accounts.update_account", fake_update_account)
    monkeypatch.setattr("autoteam.manager.cmd_rotate", lambda *args, **kwargs: None)
    monkeypatch.setattr(api, "_start_task", lambda *args, **kwargs: None)

    stop_event = api._auto_check_stop
    wait_calls = {"count": 0}

    def fake_wait(_seconds):
        wait_calls["count"] += 1
        return wait_calls["count"] > 1

    monkeypatch.setattr(stop_event, "wait", fake_wait)

    api._auto_check_loop()

    assert len(updates) == 2
    low_update = next(kwargs for email, kwargs in updates if email == "low@example.com")
    exhausted_update = next(kwargs for email, kwargs in updates if email == "exhausted@example.com")

    assert low_update["status"] == "exhausted"
    assert low_update["quota_exhausted_at"]
    assert low_update["last_quota"] == {
        "primary_pct": 93,
        "primary_resets_at": 1234567890,
        "weekly_pct": 1,
        "weekly_resets_at": 0,
    }
    assert low_update["quota_resets_at"] == 1234567890

    assert exhausted_update["status"] == "exhausted"
    assert exhausted_update["quota_exhausted_at"]
    assert exhausted_update["last_quota"] == {
        "primary_pct": 100,
        "primary_resets_at": 2222222222,
        "weekly_pct": 100,
        "weekly_resets_at": 0,
    }
    assert exhausted_update["quota_resets_at"] == 2222222222


def test_auto_check_falls_back_when_ok_quota_has_no_reset_time(tmp_path, monkeypatch):
    auth_file = tmp_path / "low.json"
    auth_file.write_text('{"access_token": "token-low"}', encoding="utf-8")

    updates = []

    def fake_update_account(email, **kwargs):
        updates.append((email, kwargs))

    _set_pool_runtime_config(monkeypatch)
    monkeypatch.setattr(api, "_auto_check_config", {"interval": 0, "threshold": 10, "min_low": 1, "target_seats": 5})
    monkeypatch.setattr(api, "_auto_check_stop", __import__("threading").Event())
    monkeypatch.setattr(api, "_auto_check_restart", __import__("threading").Event())
    monkeypatch.setattr(api, "_is_main_account_email", lambda _email: False)
    monkeypatch.setattr(
        "autoteam.accounts.load_accounts",
        lambda: [{"email": "low@example.com", "status": "active", "auth_file": str(auth_file)}],
    )
    monkeypatch.setattr(
        "autoteam.codex_auth.check_codex_quota",
        lambda _token: ("ok", {"primary_pct": 93, "weekly_pct": 1, "weekly_resets_at": 0}),
    )
    monkeypatch.setattr("autoteam.accounts.update_account", fake_update_account)
    monkeypatch.setattr("autoteam.manager.cmd_rotate", lambda *args, **kwargs: None)
    monkeypatch.setattr(api, "_start_task", lambda *args, **kwargs: None)
    monkeypatch.setattr("time.time", lambda: 1000)

    stop_event = api._auto_check_stop
    wait_calls = {"count": 0}

    def fake_wait(_seconds):
        wait_calls["count"] += 1
        return wait_calls["count"] > 1

    monkeypatch.setattr(stop_event, "wait", fake_wait)

    api._auto_check_loop()

    assert len(updates) == 1
    low_update = updates[0][1]
    assert low_update["status"] == "exhausted"
    assert low_update["last_quota"] == {"primary_pct": 93, "weekly_pct": 1, "weekly_resets_at": 0}
    assert low_update["quota_resets_at"] == 19000


def test_auto_check_falls_back_when_exhausted_quota_has_no_reset_time(tmp_path, monkeypatch):
    auth_file = tmp_path / "exhausted.json"
    auth_file.write_text('{"access_token": "token-exhausted"}', encoding="utf-8")

    updates = []

    def fake_update_account(email, **kwargs):
        updates.append((email, kwargs))

    _set_pool_runtime_config(monkeypatch)
    monkeypatch.setattr(api, "_auto_check_config", {"interval": 0, "threshold": 10, "min_low": 1, "target_seats": 5})
    monkeypatch.setattr(api, "_auto_check_stop", __import__("threading").Event())
    monkeypatch.setattr(api, "_auto_check_restart", __import__("threading").Event())
    monkeypatch.setattr(api, "_is_main_account_email", lambda _email: False)
    monkeypatch.setattr(
        "autoteam.accounts.load_accounts",
        lambda: [{"email": "exhausted@example.com", "status": "active", "auth_file": str(auth_file)}],
    )
    monkeypatch.setattr(
        "autoteam.codex_auth.check_codex_quota",
        lambda _token: (
            "exhausted",
            {
                "quota_info": {
                    "primary_pct": 100,
                    "weekly_pct": 100,
                    "weekly_resets_at": 0,
                }
            },
        ),
    )
    monkeypatch.setattr("autoteam.accounts.update_account", fake_update_account)
    monkeypatch.setattr("autoteam.manager.cmd_rotate", lambda *args, **kwargs: None)
    monkeypatch.setattr(api, "_start_task", lambda *args, **kwargs: None)
    monkeypatch.setattr("time.time", lambda: 2000)

    stop_event = api._auto_check_stop
    wait_calls = {"count": 0}

    def fake_wait(_seconds):
        wait_calls["count"] += 1
        return wait_calls["count"] > 1

    monkeypatch.setattr(stop_event, "wait", fake_wait)

    api._auto_check_loop()

    assert len(updates) == 1
    exhausted_update = updates[0][1]
    assert exhausted_update["status"] == "exhausted"
    assert exhausted_update["last_quota"] == {
        "primary_pct": 100,
        "weekly_pct": 100,
        "weekly_resets_at": 0,
    }
    assert exhausted_update["quota_resets_at"] == 20000


def test_auto_check_marks_account_unavailable_when_quota_reports_account_deactivated(tmp_path, monkeypatch):
    auth_file = tmp_path / "deactivated.json"
    auth_file.write_text('{"access_token": "token-deactivated"}', encoding="utf-8")

    updates = []
    started = []

    def fake_update_account(email, **kwargs):
        updates.append((email, kwargs))

    _set_pool_runtime_config(monkeypatch)
    monkeypatch.setattr(api, "_auto_check_config", {"interval": 0, "threshold": 10, "min_low": 1, "target_seats": 5})
    monkeypatch.setattr(api, "_auto_check_stop", __import__("threading").Event())
    monkeypatch.setattr(api, "_auto_check_restart", __import__("threading").Event())
    monkeypatch.setattr(api, "_is_main_account_email", lambda _email: False)
    monkeypatch.setattr(
        "autoteam.accounts.load_accounts",
        lambda: [{"email": "dead@example.com", "status": "active", "auth_file": str(auth_file)}],
    )
    monkeypatch.setattr(
        "autoteam.codex_auth.check_codex_quota",
        lambda _token: ("account_deactivated", {"status_code": 403, "body": "account_deactivated"}),
    )
    monkeypatch.setattr("autoteam.accounts.update_account", fake_update_account)
    monkeypatch.setattr(api, "_auto_check_team_member_count", lambda: 5)
    monkeypatch.setattr(api, "_start_task", lambda *args, **kwargs: started.append((args, kwargs)))

    stop_event = api._auto_check_stop
    wait_calls = {"count": 0}

    def fake_wait(_seconds):
        wait_calls["count"] += 1
        return wait_calls["count"] > 1

    monkeypatch.setattr(stop_event, "wait", fake_wait)

    api._auto_check_loop()

    assert len(updates) == 1
    email, payload = updates[0]
    assert email == "dead@example.com"
    assert payload["status"] == "unavailable"
    assert payload["sync_disabled"] is True
    assert payload["unavailable_reason"] == "account_deactivated"
    assert payload["unavailable_at"]
    assert started == []


def test_auto_check_triggers_rotate_when_active_count_is_below_target(tmp_path, monkeypatch):
    auth_files = []
    for idx in range(3):
        auth_file = tmp_path / f"active-{idx}.json"
        auth_file.write_text(json.dumps({"access_token": f"token-{idx}"}), encoding="utf-8")
        auth_files.append(auth_file)

    started = []

    def fake_start_task(command, func, params, *args, **kwargs):
        started.append(
            {
                "command": command,
                "params": params,
                "args": args,
            }
        )

    _set_pool_runtime_config(monkeypatch)
    monkeypatch.setattr(api, "_auto_check_config", {"interval": 0, "threshold": 10, "min_low": 2, "target_seats": 5})
    monkeypatch.setattr(api, "_auto_check_stop", __import__("threading").Event())
    monkeypatch.setattr(api, "_auto_check_restart", __import__("threading").Event())
    monkeypatch.setattr(api, "_is_main_account_email", lambda _email: False)
    monkeypatch.setattr(
        "autoteam.accounts.load_accounts",
        lambda: [
            {"email": f"active-{idx}@example.com", "status": "active", "auth_file": str(auth_files[idx])}
            for idx in range(3)
        ],
    )
    monkeypatch.setattr(
        "autoteam.codex_auth.check_codex_quota",
        lambda _token: ("ok", {"primary_pct": 10, "primary_resets_at": 1234567890, "weekly_pct": 1}),
    )
    monkeypatch.setattr(api, "_auto_check_team_member_count", lambda: 3)
    monkeypatch.setattr("autoteam.accounts.update_account", lambda *args, **kwargs: None)
    monkeypatch.setattr(api, "_start_task", fake_start_task)

    stop_event = api._auto_check_stop
    wait_calls = {"count": 0}

    def fake_wait(_seconds):
        wait_calls["count"] += 1
        return wait_calls["count"] > 1

    monkeypatch.setattr(stop_event, "wait", fake_wait)

    api._auto_check_loop()

    assert len(started) == 1
    assert started[0]["command"] == "auto-rotate"
    assert started[0]["params"]["target"] == 5
    assert started[0]["params"]["trigger"] == "auto-check"
    assert started[0]["params"]["shortage"] == 2
    assert started[0]["params"]["low_accounts"] == 0
    assert started[0]["args"] == (5,)


def test_auto_check_skips_shortage_rotate_when_team_is_already_full(tmp_path, monkeypatch):
    auth_files = []
    for idx in range(3):
        auth_file = tmp_path / f"active-{idx}.json"
        auth_file.write_text(json.dumps({"access_token": f"token-{idx}"}), encoding="utf-8")
        auth_files.append(auth_file)

    started = []

    def fake_start_task(command, func, params, *args, **kwargs):
        started.append((command, params, args, kwargs))

    monkeypatch.setattr(api, "_auto_check_config", {"interval": 0, "threshold": 10, "min_low": 2, "target_seats": 5})
    monkeypatch.setattr(api, "_auto_check_stop", __import__("threading").Event())
    monkeypatch.setattr(api, "_auto_check_restart", __import__("threading").Event())
    monkeypatch.setattr(api, "_is_main_account_email", lambda _email: False)
    monkeypatch.setattr(
        "autoteam.accounts.load_accounts",
        lambda: [
            {"email": f"active-{idx}@example.com", "status": "active", "auth_file": str(auth_files[idx])}
            for idx in range(3)
        ],
    )
    monkeypatch.setattr(
        "autoteam.codex_auth.check_codex_quota",
        lambda _token: ("ok", {"primary_pct": 10, "primary_resets_at": 1234567890, "weekly_pct": 1}),
    )
    monkeypatch.setattr(api, "_auto_check_team_member_count", lambda: 5)
    monkeypatch.setattr("autoteam.accounts.update_account", lambda *args, **kwargs: None)
    monkeypatch.setattr(api, "_start_task", fake_start_task)

    stop_event = api._auto_check_stop
    wait_calls = {"count": 0}

    def fake_wait(_seconds):
        wait_calls["count"] += 1
        return wait_calls["count"] > 1

    monkeypatch.setattr(stop_event, "wait", fake_wait)

    api._auto_check_loop()

    assert started == []


def test_auto_check_logs_threshold_message_when_team_is_full_but_low_accounts_are_below_min_low(
    tmp_path, monkeypatch, caplog
):
    auth_files = []
    for idx in range(3):
        auth_file = tmp_path / f"active-{idx}.json"
        auth_file.write_text(json.dumps({"access_token": f"token-{idx}"}), encoding="utf-8")
        auth_files.append(auth_file)

    monkeypatch.setattr(api, "_auto_check_config", {"interval": 0, "threshold": 10, "min_low": 2, "target_seats": 5})
    monkeypatch.setattr(api, "_auto_check_stop", __import__("threading").Event())
    monkeypatch.setattr(api, "_auto_check_restart", __import__("threading").Event())
    monkeypatch.setattr(api, "_is_main_account_email", lambda _email: False)
    monkeypatch.setattr(
        "autoteam.accounts.load_accounts",
        lambda: [
            {"email": f"active-{idx}@example.com", "status": "active", "auth_file": str(auth_files[idx])}
            for idx in range(3)
        ],
    )

    def fake_check_quota(token):
        if token == "token-0":
            return "ok", {"primary_pct": 100, "primary_resets_at": 1234567890, "weekly_pct": 1}
        return "ok", {"primary_pct": 10, "primary_resets_at": 1234567890, "weekly_pct": 1}

    monkeypatch.setattr("autoteam.codex_auth.check_codex_quota", fake_check_quota)
    monkeypatch.setattr(api, "_auto_check_team_member_count", lambda: 5)
    monkeypatch.setattr("autoteam.accounts.update_account", lambda *args, **kwargs: None)
    monkeypatch.setattr(api, "_start_task", lambda *args, **kwargs: None)

    stop_event = api._auto_check_stop
    wait_calls = {"count": 0}

    def fake_wait(_seconds):
        wait_calls["count"] += 1
        return wait_calls["count"] > 1

    monkeypatch.setattr(stop_event, "wait", fake_wait)

    with caplog.at_level(logging.INFO):
        api._auto_check_loop()

    assert "低额度账号未达到触发阈值（1/2），且 Team 实际成员数已满足（5/5），无需轮转" in caplog.text
    assert "额度正常且 active 数充足（3/5），无需轮转" not in caplog.text


def test_auto_check_triggers_cleanup_when_team_count_exceeds_target(tmp_path, monkeypatch):
    auth_files = []
    for idx in range(4):
        auth_file = tmp_path / f"active-{idx}.json"
        auth_file.write_text(json.dumps({"access_token": f"token-{idx}"}), encoding="utf-8")
        auth_files.append(auth_file)

    started = []

    def fake_start_task(command, func, params, *args, **kwargs):
        started.append(
            {
                "command": command,
                "params": params,
                "args": args,
            }
        )

    monkeypatch.setattr(api, "_auto_check_config", {"interval": 0, "threshold": 10, "min_low": 2, "target_seats": 5})
    monkeypatch.setattr(api, "_auto_check_stop", __import__("threading").Event())
    monkeypatch.setattr(api, "_auto_check_restart", __import__("threading").Event())
    monkeypatch.setattr(api, "_is_main_account_email", lambda _email: False)
    monkeypatch.setattr(
        "autoteam.accounts.load_accounts",
        lambda: [
            {"email": f"active-{idx}@example.com", "status": "active", "auth_file": str(auth_files[idx])}
            for idx in range(4)
        ],
    )

    def fake_check_quota(token):
        if token == "token-0":
            return "ok", {"primary_pct": 99, "primary_resets_at": 1234567890, "weekly_pct": 1}
        return "ok", {"primary_pct": 10, "primary_resets_at": 1234567890, "weekly_pct": 1}

    monkeypatch.setattr("autoteam.codex_auth.check_codex_quota", fake_check_quota)
    monkeypatch.setattr(api, "_auto_check_team_member_count", lambda: 6)
    monkeypatch.setattr("autoteam.accounts.update_account", lambda *args, **kwargs: None)
    monkeypatch.setattr(api, "_start_task", fake_start_task)

    stop_event = api._auto_check_stop
    wait_calls = {"count": 0}

    def fake_wait(_seconds):
        wait_calls["count"] += 1
        return wait_calls["count"] > 1

    monkeypatch.setattr(stop_event, "wait", fake_wait)

    api._auto_check_loop()

    assert len(started) == 1
    assert started[0]["command"] == "auto-cleanup"
    assert started[0]["params"]["max_seats"] == 5
    assert started[0]["params"]["trigger"] == "auto-check"
    assert started[0]["params"]["team_count"] == 6
    assert started[0]["args"] == (5,)


def test_auto_check_team_member_count_times_out_without_blocking(monkeypatch):
    class _SlowChatGPT:
        def __init__(self):
            self.browser = True

        def start(self):
            time.sleep(0.2)

        def stop(self):
            self.browser = False

    monkeypatch.setattr("autoteam.chatgpt_api.ChatGPTTeamAPI", _SlowChatGPT)
    monkeypatch.setattr("autoteam.manager.get_team_member_count", lambda _chatgpt: 5)

    started = time.monotonic()
    result = api._auto_check_team_member_count(timeout_seconds=0.05, retries=1)
    elapsed = time.monotonic() - started

    assert result == -1
    assert elapsed < 0.15


def test_auto_check_team_member_count_retries_three_times_on_timeout(monkeypatch):
    attempts = {"count": 0}

    class _SlowChatGPT:
        def __init__(self):
            self.browser = True

        def start(self):
            attempts["count"] += 1
            time.sleep(0.08)

        def stop(self):
            self.browser = False

    monkeypatch.setattr("autoteam.chatgpt_api.ChatGPTTeamAPI", _SlowChatGPT)
    monkeypatch.setattr("autoteam.manager.get_team_member_count", lambda _chatgpt: 5)

    result = api._auto_check_team_member_count(timeout_seconds=0.01, retries=3)

    assert result == -1
    assert attempts["count"] == 3


def test_auto_check_wait_returns_restart_soon_after_config_update(monkeypatch):
    monkeypatch.setattr(api, "_auto_check_stop", threading.Event())
    monkeypatch.setattr(api, "_auto_check_restart", threading.Event())

    def trigger_restart():
        time.sleep(0.05)
        api._auto_check_restart.set()

    thread = threading.Thread(target=trigger_restart, daemon=True)
    thread.start()

    started = time.monotonic()
    result = api._auto_check_wait(5)
    elapsed = time.monotonic() - started

    assert result == "restart"
    assert elapsed < 1.0


def test_run_task_sets_finished_at_for_completed_task(monkeypatch):
    lock = threading.Lock()
    task = {
        "task_id": "task-finish",
        "command": "check",
        "params": {},
        "status": "pending",
        "created_at": time.time(),
        "started_at": None,
        "finished_at": None,
        "result": None,
        "error": None,
    }

    monkeypatch.setattr(api, "_tasks", {"task-finish": task})
    monkeypatch.setattr(api, "_task_threads", {"task-finish": object()})
    monkeypatch.setattr(api, "_current_task_id", None)
    monkeypatch.setattr(api, "_playwright_lock", lock)

    api._run_task("task-finish", lambda: {"ok": True})

    assert task["status"] == "completed"
    assert task["result"] == {"ok": True}
    assert task["finished_at"] is not None
    assert api._current_task_id is None
    assert "task-finish" not in api._task_threads
    assert lock.locked() is False


def test_post_stop_all_tasks_marks_running_task_stopped(monkeypatch):
    class FakeThread:
        def __init__(self):
            self.joined = False

        def is_alive(self):
            return True

        def join(self, timeout=None):
            self.joined = True

    thread = FakeThread()
    lock = threading.Lock()
    lock.acquire()
    task = {
        "task_id": "task-1",
        "command": "fill",
        "status": "running",
        "created_at": time.time(),
        "started_at": time.time(),
        "finished_at": None,
        "result": None,
        "error": None,
    }

    monkeypatch.setattr(api, "_tasks", {"task-1": task})
    monkeypatch.setattr(api, "_task_threads", {"task-1": thread})
    monkeypatch.setattr(api, "_current_task_id", "task-1")
    monkeypatch.setattr(api, "_playwright_lock", lock)
    monkeypatch.setattr(api, "_admin_login_api", None)
    monkeypatch.setattr(api, "_main_codex_flow", None)
    monkeypatch.setattr(api, "_manual_account_flow", None)
    restart_event = threading.Event()
    monkeypatch.setattr(api, "_auto_check_restart", restart_event)
    monkeypatch.setattr(api, "_raise_thread_exit", lambda _thread: "requested")

    result = api.post_stop_all_tasks()

    assert result["stopped_tasks"] == [
        {
            "task_id": "task-1",
            "command": "fill",
            "thread_stop": "requested",
            "thread_alive": True,
        }
    ]
    assert task["status"] == "stopped"
    assert task["stop_requested"] is True
    assert task["error"] == "用户强制停止"
    assert thread.joined is True
    assert lock.locked() is True
    assert restart_event.is_set() is False


def test_post_stop_all_tasks_stops_pending_flows_and_releases_lock(monkeypatch):
    class FakeFlow:
        def __init__(self, name):
            self.name = name
            self.stopped = False

        def stop(self):
            self.stopped = True

    admin = FakeFlow("admin")
    main = FakeFlow("main")
    manual = FakeFlow("manual")
    lock = threading.Lock()
    lock.acquire()

    monkeypatch.setattr(api, "_tasks", {})
    monkeypatch.setattr(api, "_task_threads", {})
    monkeypatch.setattr(api, "_current_task_id", None)
    monkeypatch.setattr(api, "_playwright_lock", lock)
    monkeypatch.setattr(api, "_admin_login_api", admin)
    monkeypatch.setattr(api, "_admin_login_step", "code_required")
    monkeypatch.setattr(api, "_main_codex_flow", main)
    monkeypatch.setattr(api, "_main_codex_step", "password_required")
    monkeypatch.setattr(api, "_main_codex_action", "login")
    monkeypatch.setattr(api, "_manual_account_flow", manual)
    restart_event = threading.Event()
    monkeypatch.setattr(api, "_auto_check_restart", restart_event)

    result = api.post_stop_all_tasks()

    assert [item["name"] for item in result["stopped_flows"]] == [
        "admin-login",
        "main-codex",
        "manual-account",
    ]
    assert admin.stopped is True
    assert main.stopped is True
    assert manual.stopped is True
    assert api._admin_login_api is None
    assert api._admin_login_step is None
    assert api._main_codex_flow is None
    assert api._main_codex_step is None
    assert api._main_codex_action is None
    assert api._manual_account_flow is None
    assert lock.locked() is False
    assert restart_event.is_set() is False
