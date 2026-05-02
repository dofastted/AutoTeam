import json

from autoteam.account_credentials import (
    CREDENTIAL_TYPE_INVALID,
    CREDENTIAL_TYPE_MAIN,
    CREDENTIAL_TYPE_MISSING,
    CREDENTIAL_TYPE_OAUTH_RT,
    CREDENTIAL_TYPE_SESSION,
    identify_credential_file,
    is_uploadable_oauth_rt,
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
