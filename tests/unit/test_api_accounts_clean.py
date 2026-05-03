from pathlib import Path

import pytest
from fastapi import HTTPException

from autoteam import api


def test_post_accounts_clean_dry_run_returns_report_and_csv(monkeypatch):
    report = {
        "summary": {"duplicate_emails": 1},
        "issues": {"duplicate_emails": [{"email": "dup@example.com", "detail": "duplicate"}]},
    }
    calls = []

    def fake_scan_accounts(*, accounts=None):
        calls.append(("scan", accounts))
        return report

    def fake_format_scan_report_csv(value):
        calls.append(("csv", value))
        return "issue,email,detail\nduplicate_emails,dup@example.com,duplicate\n"

    monkeypatch.setattr("autoteam.account_cleaner.scan_accounts", fake_scan_accounts)
    monkeypatch.setattr("autoteam.account_cleaner.format_scan_report_csv", fake_format_scan_report_csv)

    result = api.post_accounts_clean_dry_run()

    assert result == {
        "report": report,
        "csv": "issue,email,detail\nduplicate_emails,dup@example.com,duplicate\n",
    }
    assert calls == [("scan", None), ("csv", report)]


def test_post_accounts_clean_dry_run_raises_500_when_scan_fails(monkeypatch):
    def fake_scan_accounts(*, accounts=None):
        raise RuntimeError("scan exploded")

    monkeypatch.setattr("autoteam.account_cleaner.scan_accounts", fake_scan_accounts)

    with pytest.raises(HTTPException) as exc_info:
        api.post_accounts_clean_dry_run()

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "账号清理 dry-run 失败: scan exploded"


def test_post_accounts_clean_apply_backs_up_cleans_saves_and_rescans(monkeypatch):
    backup_path = Path("/tmp/accounts.json.bak-account-clean-20260503-123456")
    accounts_data = [{"email": "user@example.com", "category": "legacy"}]
    cleanup_result = {
        "migrated_count": 1,
        "dedupe_summary": {"merged": 0},
        "reclassified": {"inventory": 1},
    }
    report_after = {"summary": {"duplicate_emails": 0}}
    calls = []

    def fake_backup_accounts_file():
        calls.append(("backup", None))
        return backup_path

    def fake_load_accounts():
        calls.append(("load", None))
        return accounts_data

    def fake_cleanup_accounts(*, accounts=None):
        calls.append(("cleanup", accounts))
        assert accounts is accounts_data
        accounts[0]["category"] = "inventory"
        return cleanup_result

    def fake_save_accounts(accounts):
        calls.append(("save", accounts))
        assert accounts is accounts_data

    def fake_scan_accounts(*, accounts=None):
        calls.append(("scan", accounts))
        assert accounts is accounts_data
        return report_after

    monkeypatch.setattr("autoteam.account_cleaner.backup_accounts_file", fake_backup_accounts_file)
    monkeypatch.setattr("autoteam.accounts.load_accounts", fake_load_accounts)
    monkeypatch.setattr("autoteam.account_cleaner.cleanup_accounts", fake_cleanup_accounts)
    monkeypatch.setattr("autoteam.accounts.save_accounts", fake_save_accounts)
    monkeypatch.setattr("autoteam.account_cleaner.scan_accounts", fake_scan_accounts)

    result = api.post_accounts_clean_apply()

    assert result == {
        "backup_path": str(backup_path),
        "result": cleanup_result,
        "report_after": report_after,
    }
    assert calls == [
        ("backup", None),
        ("load", None),
        ("cleanup", accounts_data),
        ("save", accounts_data),
        ("scan", accounts_data),
    ]
    assert accounts_data[0]["category"] == "inventory"


def test_post_accounts_clean_apply_allows_missing_backup(monkeypatch):
    accounts_data = [{"email": "user@example.com"}]
    cleanup_result = {"migrated_count": 0, "dedupe_summary": {}, "reclassified": {}}
    report_after = {"summary": {"duplicate_emails": 0}}

    monkeypatch.setattr("autoteam.account_cleaner.backup_accounts_file", lambda: None)
    monkeypatch.setattr("autoteam.accounts.load_accounts", lambda: accounts_data)
    monkeypatch.setattr("autoteam.account_cleaner.cleanup_accounts", lambda *, accounts=None: cleanup_result)
    monkeypatch.setattr("autoteam.accounts.save_accounts", lambda accounts: None)
    monkeypatch.setattr("autoteam.account_cleaner.scan_accounts", lambda *, accounts=None: report_after)

    result = api.post_accounts_clean_apply()

    assert result["backup_path"] is None
    assert result["result"] == cleanup_result
    assert result["report_after"] == report_after


@pytest.mark.parametrize(
    ("step", "target", "message", "expected_detail"),
    [
        ("backup", "autoteam.account_cleaner.backup_accounts_file", RuntimeError("backup exploded"), "账号清理备份失败: backup exploded"),
        ("load", "autoteam.accounts.load_accounts", RuntimeError("load exploded"), "账号清理加载账号失败: load exploded"),
        ("cleanup", "autoteam.account_cleaner.cleanup_accounts", RuntimeError("cleanup exploded"), "账号清理执行失败: cleanup exploded"),
        ("save", "autoteam.accounts.save_accounts", RuntimeError("save exploded"), "账号清理保存失败: save exploded"),
        ("scan", "autoteam.account_cleaner.scan_accounts", RuntimeError("scan exploded"), "账号清理重扫失败: scan exploded"),
    ],
)
def test_post_accounts_clean_apply_raises_500_with_step_detail(monkeypatch, step, target, message, expected_detail):
    accounts_data = [{"email": "user@example.com"}]
    cleanup_result = {"migrated_count": 0, "dedupe_summary": {}, "reclassified": {}}

    monkeypatch.setattr("autoteam.account_cleaner.backup_accounts_file", lambda: "/tmp/backup.json")
    monkeypatch.setattr("autoteam.accounts.load_accounts", lambda: accounts_data)
    monkeypatch.setattr("autoteam.account_cleaner.cleanup_accounts", lambda *, accounts=None: cleanup_result)
    monkeypatch.setattr("autoteam.accounts.save_accounts", lambda accounts: None)
    monkeypatch.setattr("autoteam.account_cleaner.scan_accounts", lambda *, accounts=None: {"summary": {}})

    if step == "backup":
        monkeypatch.setattr(target, lambda: (_ for _ in ()).throw(message))
    elif step == "load":
        monkeypatch.setattr(target, lambda: (_ for _ in ()).throw(message))
    elif step == "cleanup":
        monkeypatch.setattr(target, lambda *, accounts=None: (_ for _ in ()).throw(message))
    elif step == "save":
        monkeypatch.setattr(target, lambda accounts: (_ for _ in ()).throw(message))
    elif step == "scan":
        monkeypatch.setattr(target, lambda *, accounts=None: (_ for _ in ()).throw(message))

    with pytest.raises(HTTPException) as exc_info:
        api.post_accounts_clean_apply()

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == expected_detail
