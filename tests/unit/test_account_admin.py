from autoteam.account_admin import (
    MAIN_FORBIDDEN_USAGE,
    ROLE_MAIN,
    default_main_account,
    enforce_main_role_invariants,
    is_main_account,
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
