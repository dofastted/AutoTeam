import re
import json
from copy import deepcopy
from datetime import datetime

from autoteam import account_cleaner


def test_backup_accounts_file_creates_timestamped_copy_without_changing_source(tmp_path):
    accounts_file = tmp_path / "accounts.json"
    original_text = '[{"email":"user@example.com","status":"active"}]\n'
    accounts_file.write_text(original_text, encoding="utf-8")

    backup_path = account_cleaner.backup_accounts_file(accounts_file=accounts_file)

    assert backup_path is not None
    assert backup_path.exists()
    assert re.fullmatch(r"accounts\.json\.bak-account-clean-\d{8}-\d{6}", backup_path.name)
    assert backup_path.read_text(encoding="utf-8") == original_text
    assert accounts_file.read_text(encoding="utf-8") == original_text


def test_backup_accounts_file_returns_none_when_source_is_missing(tmp_path):
    accounts_file = tmp_path / "accounts.json"

    backup_path = account_cleaner.backup_accounts_file(accounts_file=accounts_file)

    assert backup_path is None


def test_backup_accounts_file_uses_injected_local_datetime_suffix(tmp_path):
    accounts_file = tmp_path / "accounts.json"
    accounts_file.write_text("[]", encoding="utf-8")

    backup_path = account_cleaner.backup_accounts_file(
        accounts_file=accounts_file,
        now=datetime(2026, 5, 3, 12, 34, 56),
    )

    assert backup_path == tmp_path / "accounts.json.bak-account-clean-20260503-123456"
    assert backup_path.exists()


def test_backup_accounts_file_uses_default_accounts_constant_when_not_overridden(tmp_path, monkeypatch):
    accounts_file = tmp_path / "accounts.json"
    accounts_file.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(account_cleaner.accounts, "ACCOUNTS_FILE", accounts_file)

    backup_path = account_cleaner.backup_accounts_file(
        now=datetime(2026, 5, 3, 1, 2, 3),
    )

    assert backup_path == tmp_path / "accounts.json.bak-account-clean-20260503-010203"
    assert backup_path.exists()


def test_scan_accounts_reports_duplicates_and_auth_issues_without_mutating_input(tmp_path):
    session_file = tmp_path / "codex-dup@example.com-team-01-session.json"
    session_file.write_text(json.dumps({"credential_source": "chatgpt_session"}), encoding="utf-8")
    oauth_file = tmp_path / "codex-inventory@example.com-team-02-oauth.json"
    oauth_file.write_text(json.dumps({"refresh_token": "rt-1"}), encoding="utf-8")

    accounts_fixture = [
        {
            "id": "acc-1",
            "email": "Dup@example.com",
            "password": "pw-1",
            "registration_status": "registered",
            "health_status": "valid",
            "usage_status": "normal",
            "auth_file": str(oauth_file),
        },
        {
            "id": "acc-2",
            "email": "dup@example.com",
            "password": "pw-2",
            "registration_status": "registered",
            "health_status": "valid",
            "usage_status": "normal",
            "auth_file": str(oauth_file),
        },
        {
            "id": "acc-3",
            "email": "cpa@example.com",
            "password": "pw-3",
            "registration_status": "registered",
            "health_status": "valid",
            "usage_status": "normal",
            "cpa_status": "success",
            "auth_file": str(oauth_file),
        },
        {
            "id": "acc-4",
            "email": "sold@example.com",
            "password": "pw-4",
            "registration_status": "registered",
            "health_status": "valid",
            "usage_status": "sold",
            "sync_disabled": False,
            "auth_file": str(oauth_file),
        },
        {
            "id": "acc-5",
            "email": "session@example.com",
            "password": "pw-5",
            "registration_status": "registered",
            "health_status": "valid",
            "usage_status": "normal",
            "auth_file": str(session_file),
        },
    ]
    original_accounts = deepcopy(accounts_fixture)

    report = account_cleaner.scan_accounts(accounts=accounts_fixture)

    assert report["total_accounts"] == 5
    assert report["summary"]["duplicate_emails"] >= 1
    assert report["summary"]["cpa_success_not_inventory"] == 1
    assert report["summary"]["sold_sync_enabled"] == 1
    assert report["summary"]["session_used_as_auth_file"] == 1
    assert report["duplicate_groups"] == [{"email": "dup@example.com", "count": 2, "ids": ["acc-1", "acc-2"]}]
    assert accounts_fixture == original_accounts


def test_format_scan_report_csv_and_write_scan_reports_round_trip(tmp_path):
    session_file = tmp_path / "codex-report@example.com-team-03-session.json"
    session_file.write_text(json.dumps({"credential_source": "chatgpt_session"}), encoding="utf-8")
    oauth_file = tmp_path / "codex-report@example.com-team-03-oauth.json"
    oauth_file.write_text(json.dumps({"refresh_token": "rt-2"}), encoding="utf-8")

    report = account_cleaner.scan_accounts(
        accounts=[
            {
                "id": "dup-a",
                "email": "report@example.com",
                "password": "pw-a",
                "registration_status": "registered",
                "health_status": "valid",
                "usage_status": "normal",
                "auth_file": str(oauth_file),
            },
            {
                "id": "dup-b",
                "email": "REPORT@example.com",
                "password": "pw-b",
                "registration_status": "registered",
                "health_status": "valid",
                "usage_status": "normal",
                "auth_file": str(session_file),
            },
            {
                "id": "sold-1",
                "email": "sold-report@example.com",
                "password": "pw-c",
                "registration_status": "registered",
                "health_status": "valid",
                "usage_status": "sold",
                "sync_disabled": False,
                "auth_file": str(oauth_file),
            },
            {
                "id": "cpa-1",
                "email": "cpa-report@example.com",
                "password": "pw-d",
                "registration_status": "registered",
                "health_status": "valid",
                "usage_status": "normal",
                "cpa_status": "success",
                "auth_file": str(oauth_file),
            },
            {
                "id": "misc-1",
                "email": "misc@example.com",
                "password": "pw-e",
                "registration_status": "registered",
                "health_status": "valid",
                "usage_status": "normal",
                "auth_file": str(oauth_file),
            },
        ]
    )

    csv_text = account_cleaner.format_scan_report_csv(report)

    assert "duplicate_emails" in csv_text
    assert "cpa_success_not_inventory" in csv_text
    assert "sold_sync_enabled" in csv_text
    assert "session_used_as_auth_file" in csv_text

    json_path = tmp_path / "scan-report.json"
    csv_path = tmp_path / "scan-report.csv"
    account_cleaner.write_scan_reports(report, json_path=json_path, csv_path=csv_path)

    assert json.loads(json_path.read_text(encoding="utf-8")) == report
    assert csv_path.read_text(encoding="utf-8") == csv_text
