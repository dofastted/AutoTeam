import re
import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path

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


def test_pick_primary_account_prefers_usage_status_then_rt_then_cpa_success():
    group = [
        {
            "id": "acc-rt",
            "email": "pick@example.com",
            "usage_status": "normal",
            "rt_auth_file": "auths/rt.json",
            "created_at": "2026-05-03T10:00:00+00:00",
        },
        {
            "id": "acc-inventory",
            "email": "pick@example.com",
            "usage_status": "inventory",
            "created_at": "2026-05-03T11:00:00+00:00",
        },
        {
            "id": "acc-cpa",
            "email": "pick@example.com",
            "usage_status": "normal",
            "cpa_status": "success",
            "created_at": "2026-05-03T09:00:00+00:00",
        },
    ]

    primary = account_cleaner.pick_primary_account(group)

    assert primary["id"] == "acc-inventory"


def test_pick_primary_account_uses_cpa_success_then_created_at_then_id():
    group = [
        {
            "id": "acc-b",
            "email": "pick2@example.com",
            "usage_status": "normal",
            "created_at": "2026-05-03T10:00:00+00:00",
        },
        {
            "id": "acc-a",
            "email": "pick2@example.com",
            "usage_status": "normal",
            "cpa_status": "success",
            "created_at": "2026-05-03T12:00:00+00:00",
        },
        {
            "id": "acc-c",
            "email": "pick2@example.com",
            "usage_status": "normal",
            "cpa_status": "success",
            "created_at": "2026-05-03T13:00:00+00:00",
        },
    ]

    primary = account_cleaner.pick_primary_account(group)

    assert primary["id"] == "acc-a"


def test_merge_account_pair_fills_missing_plain_fields_without_overwriting_primary():
    primary = {
        "id": "primary-1",
        "email": "merge@example.com",
        "password": "",
        "mo_email": "",
        "notes": "keep-primary",
        "created_at": "2026-05-03T10:00:00+00:00",
    }
    alias = {
        "id": "alias-1",
        "email": "merge@example.com",
        "password": "pw-from-alias",
        "mo_email": "alias@mail.example.com",
        "notes": "alias-notes",
        "updated_at": "2026-05-03T11:00:00+00:00",
    }

    fields_filled = account_cleaner.merge_account_pair(primary, alias)

    assert fields_filled == ["password", "mo_email"]
    assert primary["password"] == "pw-from-alias"
    assert primary["mo_email"] == "alias@mail.example.com"
    assert primary["notes"] == "keep-primary"
    assert primary["id"] == "primary-1"
    assert primary["created_at"] == "2026-05-03T10:00:00+00:00"
    assert "updated_at" not in primary


def test_dedupe_accounts_dry_run_returns_merges_without_mutating_input():
    accounts_fixture = [
        {
            "id": "inv-primary",
            "email": " DUP@example.com ",
            "usage_status": "inventory",
            "password": "",
            "created_at": "2026-05-03T10:00:00+00:00",
        },
        {
            "id": "inv-alias",
            "email": "dup@example.com",
            "usage_status": "normal",
            "password": "pw-dup",
            "rt_auth_file": "auths/dup-oauth.json",
            "notes": "alias-note",
            "created_at": "2026-05-03T11:00:00+00:00",
        },
        {
            "id": "cpa-primary",
            "email": "cpa@example.com",
            "usage_status": "normal",
            "cpa_status": "success",
            "created_at": "2026-05-03T09:00:00+00:00",
        },
        {
            "id": "cpa-alias",
            "email": " CPA@example.com ",
            "usage_status": "normal",
            "password": "pw-cpa",
            "session_auth_file": "auths/cpa-session.json",
            "created_at": "2026-05-03T10:30:00+00:00",
        },
    ]
    original_accounts = deepcopy(accounts_fixture)

    result = account_cleaner.dedupe_accounts(accounts_fixture, in_place=False)

    assert result["changed"] is True
    assert len(result["duplicate_groups"]) == 2
    assert len(result["merges"]) == 2
    assert len(result["result_accounts"]) == 2
    assert accounts_fixture == original_accounts

    merge_by_primary = {item["primary_id"]: item for item in result["merges"]}
    assert merge_by_primary["inv-primary"]["alias_ids"] == ["inv-alias"]
    assert set(merge_by_primary["inv-primary"]["fields_filled"]) == {"password", "rt_auth_file", "notes"}
    assert merge_by_primary["cpa-primary"]["alias_ids"] == ["cpa-alias"]
    assert set(merge_by_primary["cpa-primary"]["fields_filled"]) == {"password", "session_auth_file"}

    result_by_id = {item["id"]: item for item in result["result_accounts"]}
    assert result_by_id["inv-primary"]["password"] == "pw-dup"
    assert result_by_id["inv-primary"]["merged_from"] == ["inv-alias"]
    assert result_by_id["cpa-primary"]["password"] == "pw-cpa"
    assert result_by_id["cpa-primary"]["merged_from"] == ["cpa-alias"]


def test_dedupe_accounts_in_place_removes_aliases_and_appends_merged_from():
    accounts_fixture = [
        {
            "id": "primary-1",
            "email": "multi@example.com",
            "usage_status": "inventory",
            "merged_from": ["old-alias"],
            "created_at": "2026-05-03T09:00:00+00:00",
        },
        {
            "id": "alias-1",
            "email": "MULTI@example.com",
            "usage_status": "normal",
            "password": "pw-1",
            "created_at": "2026-05-03T10:00:00+00:00",
        },
        {
            "id": "alias-2",
            "email": " multi@example.com ",
            "usage_status": "normal",
            "proxy": "http://127.0.0.1:10808",
            "merged_from": ["legacy-2"],
            "created_at": "2026-05-03T11:00:00+00:00",
        },
    ]

    result = account_cleaner.dedupe_accounts(accounts_fixture, in_place=True)

    assert result["changed"] is True
    assert len(accounts_fixture) == 1
    assert result["result_accounts"] is accounts_fixture
    primary = accounts_fixture[0]
    assert primary["id"] == "primary-1"
    assert primary["password"] == "pw-1"
    assert primary["proxy"] == "http://127.0.0.1:10808"
    assert primary["merged_from"] == ["old-alias", "alias-1", "alias-2", "legacy-2"]
    assert result["merges"] == [
        {
            "primary_id": "primary-1",
            "primary_email": "multi@example.com",
            "alias_ids": ["alias-1", "alias-2"],
            "fields_filled": ["password", "proxy"],
        }
    ]


def test_dedupe_accounts_returns_unchanged_result_when_no_duplicates():
    accounts_fixture = [
        {
            "id": "acc-1",
            "email": "one@example.com",
            "usage_status": "normal",
        },
        {
            "id": "acc-2",
            "email": "two@example.com",
            "usage_status": "normal",
        },
    ]
    original_accounts = deepcopy(accounts_fixture)

    result = account_cleaner.dedupe_accounts(accounts_fixture, in_place=False)

    assert result["changed"] is False
    assert result["merges"] == []
    assert result["duplicate_groups"] == []
    assert len(result["result_accounts"]) == len(accounts_fixture)
    assert result["result_accounts"] == accounts_fixture
    assert accounts_fixture == original_accounts


def test_reclassify_accounts_runs_migration_dedupe_and_classify(tmp_path):
    oauth_file = tmp_path / "codex-inventory@example.com-team-01-oauth.json"
    oauth_file.write_text(json.dumps({"refresh_token": "rt-1"}), encoding="utf-8")
    session_file = tmp_path / "codex-dup@example.com-team-01-session.json"
    session_file.write_text(json.dumps({"credential_source": "chatgpt_session"}), encoding="utf-8")

    accounts_fixture = [
        {
            "id": "acc-active",
            "email": "active@example.com",
            "status": "active",
            "password": "pw-active",
        },
        {
            "id": "acc-sold",
            "email": "sold@example.com",
            "status": "sold",
            "password": "pw-sold",
        },
        {
            "id": "acc-inventory",
            "email": "inventory@example.com",
            "status": "exhausted",
            "password": "pw-inventory",
            "cpa_status": "success",
            "auth_file": str(oauth_file),
        },
        {
            "id": "dup-primary",
            "email": "dup@example.com",
            "status": "pending",
            "password": "",
        },
        {
            "id": "dup-alias",
            "email": " DUP@example.com ",
            "status": "active",
            "password": "pw-dup",
            "auth_file": str(session_file),
        },
    ]

    result = account_cleaner.reclassify_accounts(accounts_fixture, in_place=False)

    assert result["changed"] is True
    assert result["schema_changes"] >= 1
    assert result["credential_changes"] >= 0
    assert result["merge_count"] >= 1
    assert any(key in result["category_counts"] for key in ("inventory", "sold", "registered"))
    assert len(result["result_accounts"]) == 4

    result_by_id = {account["id"]: account for account in result["result_accounts"]}
    assert result_by_id["dup-primary"]["credentials"]["session"]["file"] == str(session_file)

    for account in result["result_accounts"]:
        assert account["schema_version"] == 2
        assert account["registration_status"]
        assert account["health_status"]
        assert account["usage_status"]
        assert account["team_status"]
        assert account["category"]


def test_cleanup_accounts_apply_false_reads_file_without_writing_backup(tmp_path):
    accounts_file = tmp_path / "accounts.json"
    original_data = [
        {
            "id": "acc-1",
            "email": "dry-run@example.com",
            "status": "active",
            "password": "pw-1",
        }
    ]
    original_text = f"{json.dumps(original_data, ensure_ascii=False, indent=2)}\n"
    accounts_file.write_text(original_text, encoding="utf-8")

    report = account_cleaner.cleanup_accounts(accounts_file=accounts_file, apply=False)

    assert report["applied"] is False
    assert report["backup_path"] is None
    assert report["accounts_file"] == str(accounts_file)
    assert report["reclassify"]["result_accounts"][0]["schema_version"] == 2
    assert accounts_file.read_text(encoding="utf-8") == original_text
    assert list(tmp_path.glob("*.bak-account-clean-*")) == []


def test_cleanup_accounts_apply_true_creates_backup_and_rewrites_file(tmp_path):
    oauth_file = tmp_path / "codex-apply@example.com-team-01-oauth.json"
    oauth_file.write_text(json.dumps({"refresh_token": "rt-apply"}), encoding="utf-8")
    accounts_file = tmp_path / "accounts.json"
    original_data = [
        {
            "id": "acc-apply",
            "email": "apply@example.com",
            "status": "exhausted",
            "password": "pw-apply",
            "cpa_status": "success",
            "auth_file": str(oauth_file),
        }
    ]
    accounts_file.write_text(f"{json.dumps(original_data)}\n", encoding="utf-8")

    report = account_cleaner.cleanup_accounts(accounts_file=accounts_file, apply=True)

    assert report["applied"] is True
    assert report["backup_path"] is not None
    backup_path = tmp_path / Path(report["backup_path"]).name
    assert re.fullmatch(r"accounts\.json\.bak-account-clean-\d{8}-\d{6}", backup_path.name)
    assert backup_path.exists()
    assert json.loads(backup_path.read_text(encoding="utf-8")) == original_data

    written = json.loads(accounts_file.read_text(encoding="utf-8"))
    assert isinstance(written, list)
    assert written[0]["schema_version"] == 2
    assert written[0]["category"] == "registered"
    assert written[0]["credentials"]["oauth_rt"]["file"] == str(oauth_file)


def test_reclassify_accounts_accepts_empty_list():
    result = account_cleaner.reclassify_accounts([], in_place=False)

    assert result["changed"] is False
    assert result["schema_changes"] == 0
    assert result["credential_changes"] == 0
    assert result["merge_count"] == 0
    assert result["category_counts"] == {}
    assert result["result_accounts"] == []


def test_cleaner_duplicate_email_merge_and_auth_file_migration_apply(tmp_path):
    oauth_file = tmp_path / "codex-dup@example.com-team-01-oauth.json"
    oauth_file.write_text(json.dumps({"refresh_token": "rt-dup"}), encoding="utf-8")
    accounts_file = tmp_path / "accounts.json"
    accounts_data = [
        {
            "id": "dup-primary",
            "email": "dup@example.com",
            "status": "active",
            "password": "pw-keep",
            "auth_file": str(oauth_file),
            "created_at": "2026-05-03T10:00:00+00:00",
        },
        {
            "id": "dup-legacy",
            "email": "DUP@example.com",
            "status": "pending",
            "password": "",
            "created_at": "2026-05-03T09:00:00+00:00",
        },
    ]
    accounts_file.write_text(f"{json.dumps(accounts_data, ensure_ascii=False, indent=2)}\n", encoding="utf-8")

    report = account_cleaner.cleanup_accounts(accounts_file=accounts_file, apply=True)

    assert report["applied"] is True
    assert report["reclassify"]["merge_count"] == 1
    assert report["backup_path"] is not None

    written = json.loads(accounts_file.read_text(encoding="utf-8"))
    assert len(written) == 1
    merged = written[0]
    assert merged["id"] == "dup-primary"
    assert merged["password"] == "pw-keep"
    assert merged.get("rt_auth_file") in ("", None, str(oauth_file))
    assert merged["auth_file"] == str(oauth_file)
    assert merged["credentials"]["oauth_rt"]["file"] == str(oauth_file)
    assert merged["credentials"]["oauth_rt"]["present"] is True
    assert merged["merged_from"] == ["dup-legacy"]


def test_cleaner_dry_run_reports_missing_password_missing_rt_and_session_auth_file(tmp_path):
    session_file = tmp_path / "codex-session-only@example.com-team-01-session.json"
    session_file.write_text(json.dumps({"credential_source": "chatgpt_session"}), encoding="utf-8")
    oauth_file = tmp_path / "codex-missing-password@example.com-team-01-oauth.json"
    oauth_file.write_text(json.dumps({"refresh_token": "rt-pw"}), encoding="utf-8")

    report = account_cleaner.cleanup_accounts(
        accounts=[
            {
                "id": "missing-password",
                "email": "missing-password@example.com",
                "registration_status": "registered",
                "health_status": "valid",
                "usage_status": "normal",
                "auth_file": str(oauth_file),
            },
            {
                "id": "session-only",
                "email": "session-only@example.com",
                "registration_status": "registered",
                "health_status": "valid",
                "usage_status": "inventory",
                "password": "pw-session",
                "auth_file": str(session_file),
            },
        ],
        apply=False,
    )

    scan = report["scan"]
    assert scan["summary"]["missing_password"] == 1
    assert scan["summary"]["missing_rt_auth_file"] == 1
    assert scan["summary"]["session_used_as_auth_file"] == 1
    assert scan["issues"]["missing_password"][0]["email"] == "missing-password@example.com"
    assert scan["issues"]["missing_rt_auth_file"][0]["email"] == "session-only@example.com"
    assert scan["issues"]["session_used_as_auth_file"][0]["credential_field"] == "auth_file"


def test_cleaner_sold_sync_enabled_dry_run_and_apply_fix(tmp_path):
    oauth_file = tmp_path / "codex-sold@example.com-team-01-oauth.json"
    oauth_file.write_text(json.dumps({"refresh_token": "rt-sold"}), encoding="utf-8")
    session_file = tmp_path / "codex-session-fix@example.com-team-01-session.json"
    session_file.write_text(json.dumps({"credential_source": "chatgpt_session"}), encoding="utf-8")

    accounts_data = [
        {
            "id": "sold-1",
            "email": "sold@example.com",
            "status": "sold",
            "password": "pw-sold",
            "sync_disabled": False,
            "auth_file": str(oauth_file),
        },
        {
            "id": "session-fix",
            "email": "session-fix@example.com",
            "status": "active",
            "password": "pw-session",
            "auth_file": str(session_file),
        },
    ]
    scan_report = account_cleaner.scan_accounts(deepcopy(accounts_data))

    assert scan_report["summary"]["sold_sync_enabled"] == 1
    assert scan_report["summary"]["session_used_as_auth_file"] == 1

    accounts_file = tmp_path / "accounts.json"
    accounts_file.write_text(f"{json.dumps(accounts_data, ensure_ascii=False, indent=2)}\n", encoding="utf-8")

    apply_report = account_cleaner.cleanup_accounts(accounts_file=accounts_file, apply=True)

    written = json.loads(accounts_file.read_text(encoding="utf-8"))
    written_by_id = {account["id"]: account for account in written}

    assert apply_report["scan"]["summary"]["sold_sync_enabled"] == 0
    assert written_by_id["sold-1"]["usage_status"] == "sold"
    assert written_by_id["sold-1"]["sync_disabled"] is True
    assert written_by_id["session-fix"].get("session_auth_file") in ("", None, str(session_file))
    assert written_by_id["session-fix"]["auth_file"] == str(session_file)
    assert written_by_id["session-fix"]["credentials"]["session"]["file"] == str(session_file)
    assert written_by_id["session-fix"]["credentials"]["session"]["present"] is True


def test_cleaner_idempotent_second_apply_reports_zero_changes(tmp_path):
    oauth_file = tmp_path / "codex-stable@example.com-team-01-oauth.json"
    oauth_file.write_text(json.dumps({"refresh_token": "rt-stable"}), encoding="utf-8")
    accounts_file = tmp_path / "accounts.json"
    accounts_data = [
        {
            "id": "stable-1",
            "email": "stable@example.com",
            "status": "active",
            "password": "pw-stable",
            "auth_file": str(oauth_file),
        }
    ]
    accounts_file.write_text(f"{json.dumps(accounts_data, ensure_ascii=False, indent=2)}\n", encoding="utf-8")

    first_report = account_cleaner.cleanup_accounts(accounts_file=accounts_file, apply=True)
    first_written = accounts_file.read_text(encoding="utf-8")
    second_report = account_cleaner.cleanup_accounts(accounts_file=accounts_file, apply=True)
    second_written = accounts_file.read_text(encoding="utf-8")

    assert first_report["reclassify"]["changed"] is True
    assert second_report["reclassify"]["changed"] is False
    assert second_report["reclassify"]["schema_changes"] == 0
    assert second_report["reclassify"]["credential_changes"] == 0
    assert second_report["reclassify"]["merge_count"] == 0
    assert second_report["scan"]["summary"]["duplicate_emails"] == 0
    assert first_written == second_written
