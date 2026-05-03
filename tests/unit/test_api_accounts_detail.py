import json

import pytest
from fastapi import HTTPException
from starlette.routing import Match

from autoteam import api


def _set_api_defaults(monkeypatch):
    monkeypatch.setattr(api, "_maybe_reload_runtime_config_from_env_file", lambda *args, **kwargs: False)
    monkeypatch.setattr(api, "API_KEY", "")


def _patch_load_accounts(monkeypatch, accounts_data):
    monkeypatch.setattr("autoteam.accounts.load_accounts", lambda: [dict(item) for item in accounts_data])


def test_get_account_detail_returns_aggregated_detail_for_sub_account(tmp_path, monkeypatch):
    oauth_file = tmp_path / "codex-bob-team-abc-oauth.json"
    oauth_file.write_text(json.dumps({"tokens": {"refresh_token": "rt-1"}}), encoding="utf-8")
    session_file = tmp_path / "codex-bob-team-abc-session.json"
    session_file.write_text(json.dumps({"credential_source": "chatgpt_session"}), encoding="utf-8")
    legacy_file = tmp_path / "codex-bob-team-legacy-oauth.json"
    legacy_file.write_text(json.dumps({"tokens": {"refresh_token": "rt-legacy"}}), encoding="utf-8")
    account = {
        "email": "bob@x.com",
        "password": "secret",
        "registration_status": "registered",
        "health_status": "valid",
        "usage_status": "normal",
        "cpa_status": "success",
        "rt_auth_file": str(oauth_file),
        "session_auth_file": str(session_file),
        "auth_file": str(legacy_file),
        "allocation": {"seat_id": "s-1"},
        "sale": {"channel": "none"},
        "remote": {
            "cpa": {"status": "present", "checked_at": 123},
            "sub2api": {"status": "missing", "checked_at": 124},
        },
        "notes": "detail target",
    }
    _patch_load_accounts(monkeypatch, [account])
    monkeypatch.setattr(api, "_is_main_account_email", lambda _email: False)

    result = api.get_account_detail("Bob@X.com")

    assert result["account"]["email"] == "bob@x.com"
    assert result["category"] == "inventory"
    assert result["credentials"]["rt_auth_file"] == {
        "path": str(oauth_file),
        "exists": True,
        "type": "oauth_rt",
    }
    assert result["credentials"]["session_auth_file"] == {
        "path": str(session_file),
        "exists": True,
        "type": "session",
    }
    assert result["credentials"]["auth_file"] == {
        "path": str(legacy_file),
        "exists": True,
        "type": "oauth_rt",
    }
    assert result["remote"] == account["remote"]
    assert result["allocation"] == {"seat_id": "s-1"}
    assert result["sale"] == {"channel": "none"}
    assert result["health"] == {
        "health_status": "valid",
        "invalid_reason": "",
        "is_invalid": False,
        "is_quota_exhausted": False,
    }
    assert result["events"] == []
    assert "password" not in result["account"]


def test_get_account_detail_marks_missing_files(tmp_path, monkeypatch):
    missing_file = tmp_path / "missing-oauth.json"
    account = {
        "email": "missing@x.com",
        "registration_status": "registered",
        "health_status": "valid",
        "usage_status": "normal",
        "rt_auth_file": str(missing_file),
    }
    _patch_load_accounts(monkeypatch, [account])
    monkeypatch.setattr(api, "_is_main_account_email", lambda _email: False)

    result = api.get_account_detail("missing@x.com")

    assert result["credentials"]["rt_auth_file"] == {
        "path": str(missing_file),
        "exists": False,
        "type": "missing",
    }
    assert result["credentials"]["session_auth_file"] == {
        "path": "",
        "exists": False,
        "type": "missing",
    }
    assert result["credentials"]["auth_file"] == {
        "path": "",
        "exists": False,
        "type": "missing",
    }


def test_get_account_detail_reports_quota_exhausted_health(monkeypatch):
    account = {
        "email": "quota@x.com",
        "registration_status": "registered",
        "health_status": "quota_exhausted",
        "invalid_reason": "quota_exhausted",
        "usage_status": "in_use",
    }
    _patch_load_accounts(monkeypatch, [account])
    monkeypatch.setattr(api, "_is_main_account_email", lambda _email: False)

    result = api.get_account_detail("quota@x.com")

    assert result["health"]["is_quota_exhausted"] is True
    assert result["health"]["is_invalid"] is False


def test_get_account_detail_reports_invalid_health(monkeypatch):
    account = {
        "email": "invalid@x.com",
        "registration_status": "registered",
        "health_status": "invalid",
        "invalid_reason": "auth_error",
        "usage_status": "normal",
    }
    _patch_load_accounts(monkeypatch, [account])
    monkeypatch.setattr(api, "_is_main_account_email", lambda _email: False)

    result = api.get_account_detail("invalid@x.com")

    assert result["health"]["is_invalid"] is True
    assert result["health"]["is_quota_exhausted"] is False


def test_get_account_detail_for_main_account_returns_main_category(monkeypatch):
    account = {
        "email": "owner@x.com",
        "health_status": "valid",
        "allocation": {"seat_id": "main-seat"},
        "sale": {"channel": "internal"},
        "remote": {"cpa": {"status": "present"}, "sub2api": {"status": "present"}},
    }
    _patch_load_accounts(monkeypatch, [account])
    monkeypatch.setattr(api, "_is_main_account_email", lambda email: email == "owner@x.com")

    result = api.get_account_detail("OWNER@x.com")

    assert result["category"] == "main"
    assert result["allocation"] == {}
    assert result["sale"] == {}
    assert result["account"]["is_main_account"] is True


def test_get_account_detail_raises_404_when_email_missing(monkeypatch):
    _patch_load_accounts(monkeypatch, [])
    monkeypatch.setattr(api, "_is_main_account_email", lambda _email: False)

    with pytest.raises(HTTPException) as exc_info:
        api.get_account_detail("none@x.com")

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "账号不存在"


def _match_get_route(path: str):
    scope = {
        "type": "http",
        "path": path,
        "method": "GET",
        "root_path": "",
        "scheme": "http",
        "headers": [],
        "query_string": b"",
        "server": ("testserver", 80),
        "client": ("testclient", 50000),
    }
    for route in api.app.router.routes:
        match, child_scope = route.matches(scope)
        if match is Match.FULL:
            return route, child_scope
    return None, None


def test_get_account_detail_route_does_not_break_codex_auth(tmp_path, monkeypatch):
    account = {
        "email": "route@x.com",
        "registration_status": "registered",
        "health_status": "valid",
        "usage_status": "normal",
    }
    auth_file = tmp_path / "codex-route-team-abc-oauth.json"
    auth_file.write_text(
        json.dumps(
            {
                "id_token": "id-1",
                "access_token": "access-1",
                "refresh_token": "refresh-1",
                "account_id": "acc-1",
            }
        ),
        encoding="utf-8",
    )
    account["auth_file"] = str(auth_file)
    _patch_load_accounts(monkeypatch, [account])
    monkeypatch.setattr(api, "_is_main_account_email", lambda _email: False)

    detail_route, detail_scope = _match_get_route("/api/accounts/route@x.com")
    codex_route, codex_scope = _match_get_route("/api/accounts/route@x.com/codex-auth")

    assert detail_route is not None
    assert detail_route.endpoint is api.get_account_detail
    assert detail_scope["path_params"]["email"] == "route@x.com"

    assert codex_route is not None
    assert codex_route.endpoint is api.get_codex_auth
    assert codex_scope["path_params"]["email"] == "route@x.com"

    detail_result = api.get_account_detail("route@x.com")
    codex_result = api.get_codex_auth("route@x.com")

    assert detail_result["account"]["email"] == "route@x.com"
    assert codex_result["email"] == "route@x.com"
    assert codex_result["codex_auth"]["tokens"]["refresh_token"] == "refresh-1"
