import json

from autoteam import codex_auth


def _write_json(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


def test_select_oauth_rt_auth_file_uses_rt_auth_file(tmp_path):
    rt_file = _write_json(
        tmp_path / "codex-user@example.com-team-acc-oauth.json",
        {
            "access_token": "at-1",
            "refresh_token": "rt-1",
            "email": "user@example.com",
        },
    )

    assert codex_auth.select_oauth_rt_auth_file({"rt_auth_file": rt_file}) == rt_file


def test_select_oauth_rt_auth_file_ignores_session_only_account(tmp_path):
    session_file = _write_json(
        tmp_path / "codex-user@example.com-team-acc-session.json",
        {
            "access_token": "session-at",
            "refresh_token": "",
            "credential_source": "chatgpt_session",
            "email": "user@example.com",
        },
    )

    account = {
        "session_auth_file": session_file,
    }

    assert codex_auth.select_oauth_rt_auth_file(account) == ""
    assert codex_auth.is_uploadable_oauth_rt_file(session_file) is False


def test_select_oauth_rt_auth_file_rejects_auth_file_that_points_to_session(tmp_path):
    session_file = _write_json(
        tmp_path / "codex-user@example.com-team-acc-session.json",
        {
            "access_token": "session-at",
            "refresh_token": "",
            "credential_source": "chatgpt_session",
            "email": "user@example.com",
        },
    )

    account = {
        "auth_file": session_file,
        "session_auth_file": session_file,
    }

    assert codex_auth.select_oauth_rt_auth_file(account) == ""


def test_select_oauth_rt_auth_file_allows_legacy_auth_file_when_it_is_oauth_rt(tmp_path):
    legacy_file = _write_json(
        tmp_path / "codex-user@example.com-team-acc.json",
        {
            "access_token": "at-1",
            "refresh_token": "rt-1",
            "email": "user@example.com",
        },
    )

    account = {
        "auth_file": legacy_file,
    }

    assert codex_auth.select_oauth_rt_auth_file(account) == legacy_file


def test_select_oauth_rt_auth_file_rejects_file_without_refresh_token(tmp_path):
    auth_file = _write_json(
        tmp_path / "codex-user@example.com-team-acc-oauth.json",
        {
            "access_token": "at-1",
            "refresh_token": "",
            "email": "user@example.com",
        },
    )

    assert codex_auth.select_oauth_rt_auth_file({"rt_auth_file": auth_file}) == ""
    assert codex_auth.is_uploadable_oauth_rt_file(auth_file) is False


def test_select_oauth_rt_auth_file_prefers_valid_rt_over_legacy_auth_file(tmp_path):
    legacy_file = _write_json(
        tmp_path / "codex-user@example.com-team-old.json",
        {
            "access_token": "old-at",
            "refresh_token": "old-rt",
            "email": "user@example.com",
        },
    )
    rt_file = _write_json(
        tmp_path / "codex-user@example.com-team-new-oauth.json",
        {
            "access_token": "new-at",
            "refresh_token": "new-rt",
            "email": "user@example.com",
        },
    )

    account = {
        "auth_file": legacy_file,
        "rt_auth_file": rt_file,
    }

    assert codex_auth.select_oauth_rt_auth_file(account) == rt_file


def test_get_existing_session_auth_file_prefers_session_auth_file():
    account = {
        "session_auth_file": "/tmp/session-current.json",
        "auth_file": "/tmp/codex-user@example.com-team-old-session.json",
    }

    assert codex_auth.get_existing_session_auth_file(account) == "/tmp/session-current.json"


def test_get_existing_session_auth_file_reads_legacy_session_auth_file():
    account = {
        "auth_file": "/tmp/codex-user@example.com-team-old-session.json",
    }

    assert codex_auth.get_existing_session_auth_file(account) == account["auth_file"]


def test_get_existing_session_auth_file_ignores_non_session_auth_file():
    account = {
        "auth_file": "/tmp/codex-user@example.com-team-old-oauth.json",
    }

    assert codex_auth.get_existing_session_auth_file(account) == ""
