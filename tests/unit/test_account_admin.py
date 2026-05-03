from autoteam.account_admin import (
    MAIN_FORBIDDEN_USAGE,
    ROLE_MAIN,
    default_main_account,
    enforce_main_role_invariants,
    is_main_account,
    record_main_codex_auth,
    record_main_session,
    summarize_session_cookie,
    summarize_main_accounts,
)


def test_is_main_account_returns_true_only_for_role_main():
    assert is_main_account({"role": ROLE_MAIN}) is True
    assert is_main_account({"role": "child"}) is False


def test_default_main_account_has_expected_defaults():
    account = default_main_account(email="m@a.com", now=1700000000)

    assert account["role"] == ROLE_MAIN
    assert account["schema_version"] == 2
    assert account["registration_status"] == "registered"
    assert account["usage_status"] == "normal"
    assert account["team_status"] == "active"
    assert account["session_cookie_present"] is False
    assert account["main_codex_auth_file"] == ""
    assert account["team_workspace_id"] == ""
    assert account["team_account_id"] == ""
    assert account["id"].startswith("acct_main_1700000000_")


def test_enforce_main_role_invariants_fixes_forbidden_usage_status():
    account = {
        "role": ROLE_MAIN,
        "usage_status": next(iter(MAIN_FORBIDDEN_USAGE)),
        "team_status": "active",
        "sync_disabled": False,
    }

    result = enforce_main_role_invariants(account)

    assert result["changed"] is True
    assert "usage_status" in result["violations"]
    assert account["usage_status"] == "normal"


def test_enforce_main_role_invariants_removes_inventory_category():
    account = {
        "role": ROLE_MAIN,
        "usage_status": "normal",
        "team_status": "active",
        "category": "inventory",
        "sync_disabled": False,
    }

    result = enforce_main_role_invariants(account)

    assert result["changed"] is True
    assert "category" in result["violations"]
    assert "category" not in account


def test_enforce_main_role_invariants_enables_sync_for_main_account():
    account = {
        "role": ROLE_MAIN,
        "usage_status": "normal",
        "team_status": "active",
        "sync_disabled": True,
    }

    result = enforce_main_role_invariants(account)

    assert result["changed"] is True
    assert "sync_disabled" in result["violations"]
    assert account["sync_disabled"] is False


def test_enforce_main_role_invariants_returns_no_changes_for_compliant_main():
    account = {
        "role": ROLE_MAIN,
        "usage_status": "normal",
        "team_status": "active",
        "sync_disabled": False,
        "category": "invalid",
    }

    result = enforce_main_role_invariants(account)

    assert result == {"changed": False, "violations": [], "fixed": []}


def test_summarize_main_accounts_counts_only_main_role_accounts():
    accounts = [
        {
            "role": ROLE_MAIN,
            "session_cookie_present": True,
            "main_codex_auth_file": "auths/codex-main-a.json",
            "team_status": "active",
        },
        {
            "role": ROLE_MAIN,
            "session_cookie_present": False,
            "main_codex_auth_file": "",
            "team_status": "standby",
        },
        {
            "role": "child",
            "session_cookie_present": True,
            "main_codex_auth_file": "auths/codex-main-ignore.json",
            "team_status": "active",
        },
        {
            "role": "child",
            "session_cookie_present": False,
            "main_codex_auth_file": "",
            "team_status": "standby",
        },
        {
            "team_status": "active",
        },
    ]

    assert summarize_main_accounts(accounts) == {
        "total": 2,
        "with_session_cookie": 1,
        "with_codex_auth": 1,
        "active": 1,
    }


def test_summarize_session_cookie_returns_empty_summary_for_empty_input():
    assert summarize_session_cookie(None) == {"length": 0, "fingerprint": "", "captured_at": 0}
    assert summarize_session_cookie("") == {"length": 0, "fingerprint": "", "captured_at": 0}
    assert summarize_session_cookie(b"") == {"length": 0, "fingerprint": "", "captured_at": 0}


def test_summarize_session_cookie_returns_fingerprint_without_exposing_cookie():
    summary = summarize_session_cookie("xxx")

    assert summary["length"] == 3
    assert len(summary["fingerprint"]) == 16
    assert summary["captured_at"] > 0


def test_record_main_session_skips_child_account():
    account = {"role": "child", "email": "child@example.com"}

    result = record_main_session(account, "secret-cookie", now=1700000000)

    assert result == {"changed": False, "reason": "not_main"}
    assert "session_cookie_present" not in account
    assert "session_cookie_summary" not in account


def test_record_main_session_writes_summary_for_main_account():
    account = default_main_account(email="main@example.com", now=1700000000)

    result = record_main_session(account, "secret-cookie", now=1700000001)

    assert result["changed"] is True
    assert account["session_cookie_present"] is True
    assert account["session_cookie_summary"]["length"] == len("secret-cookie")
    assert account["session_cookie_summary"]["captured_at"] == 1700000001
    assert len(account["session_cookie_summary"]["fingerprint"]) == 16
    assert "secret-cookie" not in str(account["session_cookie_summary"])


def test_record_main_codex_auth_detects_real_refresh_token_file(tmp_path):
    auth_file = tmp_path / "codex-main-test.json"
    auth_file.write_text(
        '{"refresh_token":"rt-main","access_token":"at-main"}',
        encoding="utf-8",
    )
    account = default_main_account(email="main@example.com", now=1700000000)

    result = record_main_codex_auth(account, auth_file, now=1700000002)

    assert result["changed"] is True
    assert account["main_codex_auth_file"] == str(auth_file)
    assert account["main_codex_auth_status"] == {
        "present": True,
        "has_refresh_token": True,
        "checked_at": 1700000002,
    }


def test_record_main_codex_auth_writes_empty_status_for_none_path():
    account = default_main_account(email="main@example.com", now=1700000000)

    result = record_main_codex_auth(account, None, now=1700000003)

    assert result["changed"] is True
    assert account["main_codex_auth_file"] == ""
    assert account["main_codex_auth_status"] == {
        "present": False,
        "has_refresh_token": False,
        "checked_at": 1700000003,
    }


def test_record_main_codex_auth_skips_child_account(tmp_path):
    auth_file = tmp_path / "codex-main-test.json"
    auth_file.write_text('{"refresh_token":"rt-main"}', encoding="utf-8")
    account = {"role": "child", "email": "child@example.com"}

    result = record_main_codex_auth(account, auth_file, now=1700000004)

    assert result == {"changed": False, "reason": "not_main"}
    assert "main_codex_auth_file" not in account
    assert "main_codex_auth_status" not in account
