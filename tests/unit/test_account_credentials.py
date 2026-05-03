import json

from autoteam.account_credentials import (
    CREDENTIAL_TYPE_INVALID,
    CREDENTIAL_TYPE_MAIN,
    CREDENTIAL_TYPE_MISSING,
    CREDENTIAL_TYPE_OAUTH_RT,
    CREDENTIAL_TYPE_SESSION,
    identify_credential_file,
    is_uploadable_oauth_rt,
    migrate_account_credentials,
    migrate_accounts_credentials,
)


def _write_json(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_identify_credential_file_returns_missing_for_absent_path(tmp_path):
    result = identify_credential_file(tmp_path / "nope.json")

    assert result["type"] == CREDENTIAL_TYPE_MISSING
    assert result["error"] is None


def test_identify_credential_file_detects_main_auth_without_parsing_json(tmp_path):
    auth_file = tmp_path / "codex-main-abc123.json"
    auth_file.write_text("not-json", encoding="utf-8")

    result = identify_credential_file(auth_file)

    assert result["type"] == CREDENTIAL_TYPE_MAIN
    assert result["error"] is None


def test_identify_credential_file_detects_session_via_credential_source(tmp_path):
    auth_file = _write_json(
        tmp_path / "codex-user-team-auth.json",
        {"credential_source": "chatgpt_session", "session": {"accessToken": "abc"}},
    )

    result = identify_credential_file(auth_file)

    assert result["type"] == CREDENTIAL_TYPE_SESSION


def test_identify_credential_file_detects_session_via_filename(tmp_path):
    auth_file = _write_json(tmp_path / "codex-foo-team-xx-session.json", {})

    result = identify_credential_file(auth_file)

    assert result["type"] == CREDENTIAL_TYPE_SESSION


def test_identify_credential_file_detects_oauth_rt_via_filename(tmp_path):
    auth_file = _write_json(
        tmp_path / "codex-foo-team-xx-oauth.json",
        {"tokens": {"refresh_token": "RT123"}},
    )

    result = identify_credential_file(auth_file)

    assert result["type"] == CREDENTIAL_TYPE_OAUTH_RT
    assert result["details"]["has_refresh_token"] is True


def test_identify_credential_file_detects_oauth_rt_via_refresh_token(tmp_path):
    auth_file = _write_json(
        tmp_path / "codex-foo-team-xx.json",
        {"tokens": {"refresh_token": "RT456"}},
    )

    result = identify_credential_file(auth_file)

    assert result["type"] == CREDENTIAL_TYPE_OAUTH_RT
    assert result["details"]["has_refresh_token"] is True


def test_identify_credential_file_returns_invalid_json_on_parse_error(tmp_path):
    auth_file = tmp_path / "broken.json"
    auth_file.write_text("not-json", encoding="utf-8")

    result = identify_credential_file(auth_file)

    assert result["type"] == CREDENTIAL_TYPE_INVALID
    assert result["error"]


def test_is_uploadable_oauth_rt_requires_refresh_token(tmp_path):
    oauth_file = _write_json(
        tmp_path / "codex-foo-team-xx-oauth.json",
        {"tokens": {"refresh_token": "RT123"}},
    )
    session_file = _write_json(
        tmp_path / "codex-foo-team-xx-session.json",
        {"credential_source": "chatgpt_session"},
    )

    assert is_uploadable_oauth_rt(oauth_file) is True
    assert is_uploadable_oauth_rt(session_file) is False


def test_migrate_account_credentials_promotes_legacy_oauth_auth_file(tmp_path):
    auth_file = _write_json(
        tmp_path / "codex-user-team-xx-oauth.json",
        {"tokens": {"refresh_token": "rt"}},
    )
    account = {"email": "user@example.com", "auth_file": str(auth_file)}

    result = migrate_account_credentials(account)

    assert result["changed"] is True
    assert any(action["type"] == "rt_auth_file_set" for action in result["actions"])
    assert account["rt_auth_file"] == str(auth_file)
    assert account["credentials"]["oauth_rt"]["file"] == str(auth_file)
    assert account["credentials"]["oauth_rt"]["present"] is True


def test_migrate_account_credentials_promotes_legacy_session_auth_file(tmp_path):
    auth_file = _write_json(
        tmp_path / "codex-user-team-xx-session.json",
        {"credential_source": "chatgpt_session"},
    )
    account = {"email": "user@example.com", "auth_file": str(auth_file)}

    result = migrate_account_credentials(account)

    assert result["changed"] is True
    assert any(action["type"] == "session_auth_file_set" for action in result["actions"])
    assert account["session_auth_file"] == str(auth_file)
    assert "rt_auth_file" not in account
    assert account["credentials"]["session"]["file"] == str(auth_file)
    assert account["credentials"]["session"]["present"] is True


def test_migrate_account_credentials_keeps_existing_valid_rt_auth_file(tmp_path):
    rt_auth_file = _write_json(
        tmp_path / "codex-user-team-xx-oauth.json",
        {"tokens": {"refresh_token": "rt"}},
    )
    account = {
        "email": "user@example.com",
        "auth_file": str(tmp_path / "legacy.json"),
        "rt_auth_file": str(rt_auth_file),
    }

    result = migrate_account_credentials(account)

    assert result["changed"] is False
    assert account["rt_auth_file"] == str(rt_auth_file)
    assert any(action["type"] == "existing_oauth_rt_kept" for action in result["actions"])


def test_migrate_account_credentials_skips_main_auth_file(tmp_path):
    auth_file = tmp_path / "codex-main-foo.json"
    auth_file.write_text("not-json", encoding="utf-8")
    account = {"email": "main@example.com", "auth_file": str(auth_file)}

    result = migrate_account_credentials(account)

    assert result["changed"] is False
    assert any(action["type"] == "skipped_main" for action in result["actions"])
    assert "rt_auth_file" not in account


def test_migrate_account_credentials_reports_missing_legacy_auth_file(tmp_path):
    missing_file = tmp_path / "missing-oauth.json"
    account = {"email": "user@example.com", "auth_file": str(missing_file)}

    result = migrate_account_credentials(account)

    assert result["changed"] is False
    assert any(action["type"] == "missing" for action in result["actions"])


def test_migrate_account_credentials_reports_invalid_json(tmp_path):
    auth_file = tmp_path / "broken.json"
    auth_file.write_text("{oops", encoding="utf-8")
    account = {"email": "user@example.com", "auth_file": str(auth_file)}

    result = migrate_account_credentials(account)

    assert result["changed"] is False
    assert any(action["type"] == "invalid_json" for action in result["actions"])
    assert result["errors"]


def test_migrate_accounts_credentials_summarizes_changed_count(tmp_path):
    oauth_file = _write_json(
        tmp_path / "codex-user-team-xx-oauth.json",
        {"tokens": {"refresh_token": "rt"}},
    )
    session_file = _write_json(
        tmp_path / "codex-user-team-yy-session.json",
        {"credential_source": "chatgpt_session"},
    )
    missing_file = tmp_path / "missing.json"
    accounts = [
        {"email": "oauth@example.com", "auth_file": str(oauth_file)},
        {"email": "session@example.com", "auth_file": str(session_file)},
        {"email": "missing@example.com", "auth_file": str(missing_file)},
    ]

    result = migrate_accounts_credentials(accounts)

    assert result["total"] == 3
    assert result["changed"] == 2
    assert result["unchanged"] == 1
    assert len(result["actions"]) == 3
