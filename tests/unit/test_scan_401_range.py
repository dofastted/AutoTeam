import importlib.util
import json
from pathlib import Path


def _load_scan_401_range_module():
    script = Path(__file__).resolve().parents[2] / "scripts" / "scan_401_range.py"
    spec = importlib.util.spec_from_file_location("scan_401_range", script)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_build_reauth_email_list_filters_non_active_accounts():
    scan = _load_scan_401_range_module()
    results = [
        scan.cq.CheckResult(
            file="auths/codex-aqw-700@example.com-team-x-oauth.json",
            provider="openai",
            email="aqw-700@example.com",
            account_id="",
            status_code=401,
            classification="401",
            auth_ok=False,
            unauthorized_401=True,
            quota_exceeded=False,
            refresh_attempted=True,
            refresh_succeeded=False,
            refresh_error="401",
            quota_resets_at=None,
            error="",
            response_preview="",
            final_status_code=401,
        ),
        scan.cq.CheckResult(
            file="auths/codex-aqw-701@example.com-team-x-oauth.json",
            provider="openai",
            email="aqw-701@example.com",
            account_id="",
            status_code=401,
            classification="401",
            auth_ok=False,
            unauthorized_401=True,
            quota_exceeded=False,
            refresh_attempted=True,
            refresh_succeeded=False,
            refresh_error="401",
            quota_resets_at=None,
            error="",
            response_preview="",
            final_status_code=401,
        ),
        scan.cq.CheckResult(
            file="auths/codex-aqw-702@example.com-team-x-oauth.json",
            provider="openai",
            email="aqw-702@example.com",
            account_id="",
            status_code=401,
            classification="401",
            auth_ok=False,
            unauthorized_401=True,
            quota_exceeded=False,
            refresh_attempted=True,
            refresh_succeeded=False,
            refresh_error="401",
            quota_resets_at=None,
            error="",
            response_preview="",
            final_status_code=401,
        ),
    ]

    emails, filters = scan._build_reauth_email_list(
        results,
        account_statuses={
            "aqw-700@example.com": "active",
            "aqw-701@example.com": "standby",
        },
    )

    assert emails == ["aqw-700@example.com"]
    assert filters["written"] == 1
    assert filters["filtered_non_active"] == [
        {
            "email": "aqw-701@example.com",
            "status": "standby",
            "file": "auths/codex-aqw-701@example.com-team-x-oauth.json",
        }
    ]
    assert filters["filtered_missing_account"] == [
        {
            "email": "aqw-702@example.com",
            "file": "auths/codex-aqw-702@example.com-team-x-oauth.json",
        }
    ]


def test_load_account_statuses_normalizes_email_and_status(tmp_path):
    scan = _load_scan_401_range_module()
    accounts_file = tmp_path / "accounts.json"
    accounts_file.write_text(
        json.dumps(
            [
                {"email": " User@Example.com ", "status": " Active "},
                {"email": "sold@example.com", "status": "sold"},
            ]
        ),
        encoding="utf-8",
    )

    assert scan._load_account_statuses(accounts_file) == {
        "user@example.com": "active",
        "sold@example.com": "sold",
    }
