import json

from autoteam import account_rt_recovery


def test_rt_recovery_scan_classifies_registered_missing_rt_and_401(tmp_path):
    oauth_file = tmp_path / "codex-ready@example.com-team-a-oauth.json"
    oauth_file.write_text(json.dumps({"refresh_token": "rt-1"}), encoding="utf-8")
    session_file = tmp_path / "codex-missing@example.com-team-a-session.json"
    session_file.write_text(json.dumps({"credential_source": "chatgpt_session"}), encoding="utf-8")

    report = account_rt_recovery.scan_rt_recovery_accounts(
        [
            {
                "email": "missing@example.com",
                "registration_status": "registered",
                "status": "standby",
                "session_auth_file": str(session_file),
            },
            {
                "email": "bad401@example.com",
                "registration_status": "registered",
                "status": "unavailable",
                "sync_disabled": True,
                "unavailable_reason": "http_401",
                "rt_auth_file": str(oauth_file),
            },
            {
                "email": "ready@example.com",
                "registration_status": "registered",
                "status": "active",
                "rt_auth_file": str(oauth_file),
            },
            {
                "email": "new@example.com",
                "registration_status": "planned",
                "status": "pending",
            },
        ]
    )

    by_email = {item["email"]: item for item in report["items"]}
    assert by_email["missing@example.com"]["category"] == "rt_missing_registered"
    assert by_email["missing@example.com"]["recoverable"] is True
    assert by_email["missing@example.com"]["has_session"] is True
    assert by_email["bad401@example.com"]["category"] == "rt_401_reauth_needed"
    assert by_email["bad401@example.com"]["recoverable"] is True
    assert by_email["ready@example.com"]["category"] == "rt_ready"
    assert by_email["new@example.com"]["category"] == "not_registered"
    assert report["recoverable_count"] == 2


def test_rt_recovery_deactivated_is_not_recoverable_and_can_be_marked():
    accounts = [
        {
            "email": "dead@example.com",
            "registration_status": "registered",
            "status": "standby",
            "usage_status": "inventory",
            "last_error": "Deactivated account",
        }
    ]

    scan = account_rt_recovery.scan_rt_recovery_accounts(accounts)
    assert scan["items"][0]["category"] == "deactivated_invalid"
    assert scan["items"][0]["recoverable"] is False

    result = account_rt_recovery.mark_deactivated_invalid_accounts(accounts, now=1770000000)

    assert result["changed"] == 1
    assert accounts[0]["status"] == "unavailable"
    assert accounts[0]["health_status"] == "deactivated"
    assert accounts[0]["unavailable_reason"] == "account_deactivated"
    assert accounts[0]["sync_disabled"] is True
    assert accounts[0]["usage_status"] == "normal"


def test_prepare_401_account_for_rt_recovery_clears_stale_invalid_fields():
    account = {
        "email": "retry@example.com",
        "registration_status": "registered",
        "status": "unavailable",
        "health_status": "invalid",
        "sync_disabled": True,
        "unavailable_reason": "http_401",
        "last_error": "401",
    }

    result = account_rt_recovery.prepare_account_for_rt_recovery(account, force=True, now=1770000001)

    assert result["changed"] is True
    assert result["category"] == "rt_401_reauth_needed"
    assert account["sync_disabled"] is False
    assert account["status"] == "standby"
    assert account["health_status"] == "unknown"
    assert account["unavailable_reason"] == ""
    assert account["last_rt_recovery_attempt_at"] == 1770000001
