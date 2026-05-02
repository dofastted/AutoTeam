import json

from autoteam import account_store
from autoteam.account_models import (
    HEALTH_DEACTIVATED,
    HEALTH_QUOTA_EXHAUSTED,
    SCHEMA_VERSION,
    TEAM_ACTIVE,
    USAGE_SOLD,
)


def _write_json(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


def test_migrate_account_record_maps_active_status_and_sets_schema_version(monkeypatch):
    monkeypatch.setattr(account_store.time, "time", lambda: 1700000000.0)
    record = {
        "email": "active@example.com",
        "status": "active",
    }

    migrated = account_store.migrate_account_record(record, in_place=False)

    assert migrated["schema_version"] == SCHEMA_VERSION
    assert migrated["team_status"] == TEAM_ACTIVE
    assert migrated["health_status"] == "valid"
    assert migrated["registration_status"] == "planned"
    assert migrated["created_at"] == 1700000000.0
    assert migrated["updated_at"] == 1700000000.0


def test_migrate_account_record_maps_sold_status_and_disables_sync(monkeypatch):
    monkeypatch.setattr(account_store.time, "time", lambda: 1700000001.0)
    record = {
        "email": "sold@example.com",
        "status": "sold",
    }

    migrated = account_store.migrate_account_record(record, in_place=False)

    assert migrated["usage_status"] == USAGE_SOLD
    assert migrated["sync_disabled"] is True


def test_migrate_account_record_maps_exhausted_status(monkeypatch):
    monkeypatch.setattr(account_store.time, "time", lambda: 1700000002.0)
    record = {
        "email": "quota@example.com",
        "status": "exhausted",
    }

    migrated = account_store.migrate_account_record(record, in_place=False)

    assert migrated["health_status"] == HEALTH_QUOTA_EXHAUSTED
    assert migrated["team_status"] == TEAM_ACTIVE


def test_migrate_account_record_maps_deactivated_unavailable_status(monkeypatch):
    monkeypatch.setattr(account_store.time, "time", lambda: 1700000003.0)
    record = {
        "email": "dead@example.com",
        "status": "unavailable",
        "unavailable_reason": "account_deactivated",
    }

    migrated = account_store.migrate_account_record(record, in_place=False)

    assert migrated["health_status"] == HEALTH_DEACTIVATED


def test_migrate_account_record_preserves_existing_v2_without_rewriting_updated_at():
    record = {
        "schema_version": 2,
        "email": "v2@example.com",
        "registration_status": "registered",
        "health_status": "valid",
        "usage_status": "inventory",
        "team_status": "active",
        "updated_at": 123.0,
    }

    migrated = account_store.migrate_account_record(record, in_place=False)

    assert migrated == record
    assert migrated["updated_at"] == 123.0


def test_migrate_account_record_maps_legacy_auth_fields_into_nested_credentials(monkeypatch, tmp_path):
    monkeypatch.setattr(account_store.time, "time", lambda: 1700000004.0)
    oauth_file = _write_json(tmp_path / "codex-user@example.com-team-oauth.json", {"refresh_token": "rt"})
    session_file = _write_json(
        tmp_path / "codex-user@example.com-team-session.json",
        {"credential_source": "chatgpt_session"},
    )
    archive_file = _write_json(tmp_path / "archive.json", {"ok": True})
    record = {
        "email": "user@example.com",
        "status": "standby",
        "mail_provider": "mo_email",
        "mail_account_id": 12,
        "auth_file": oauth_file,
        "session_auth_file": session_file,
        "cpa_archive_file": archive_file,
        "cpa_status": "success",
    }

    migrated = account_store.migrate_account_record(record, in_place=False)

    assert migrated["registration_status"] == "registered"
    assert migrated["mail"]["provider"] == "mo_email"
    assert migrated["mail"]["account_id"] == 12
    assert migrated["mail"]["domain"] == "example.com"
    assert migrated["credentials"]["session"]["file"] == session_file
    assert migrated["credentials"]["oauth_rt"]["file"] == oauth_file
    assert migrated["credentials"]["cpa_archive"]["file"] == archive_file
    assert migrated["remote"]["cpa"]["status"] == "present"


def test_migrate_accounts_file_dry_run_does_not_write_or_create_backup(tmp_path, monkeypatch):
    accounts_file = tmp_path / "accounts.json"
    original_data = [
        {
            "email": "user@example.com",
            "status": "active",
        }
    ]
    accounts_file.write_text(json.dumps(original_data), encoding="utf-8")
    monkeypatch.setattr(account_store.accounts, "ACCOUNTS_FILE", accounts_file)
    monkeypatch.setattr(account_store.time, "time", lambda: 1700000005.0)

    report = account_store.migrate_accounts_file(dry_run=True)

    assert report["total"] == 1
    assert report["migrated"] == 1
    assert report["unchanged"] == 0
    assert report["backup_path"] is None
    assert report["errors"] == []
    assert json.loads(accounts_file.read_text(encoding="utf-8")) == original_data
    assert list(tmp_path.glob("*.bak-account-store-*")) == []


def test_migrate_accounts_file_apply_creates_timestamped_backup_and_writes(tmp_path, monkeypatch):
    accounts_file = tmp_path / "accounts.json"
    original_data = [
        {
            "email": "sold@example.com",
            "status": "sold",
        }
    ]
    accounts_file.write_text(json.dumps(original_data), encoding="utf-8")
    monkeypatch.setattr(account_store.accounts, "ACCOUNTS_FILE", accounts_file)
    monkeypatch.setattr(account_store.time, "time", lambda: 1700000006.0)

    report = account_store.migrate_accounts_file(dry_run=False)

    assert report["total"] == 1
    assert report["migrated"] == 1
    assert report["unchanged"] == 0
    assert report["errors"] == []
    assert report["backup_path"] is not None
    backup_path = tmp_path / "accounts.json.bak-account-store-20231115-061326"
    assert report["backup_path"] == str(backup_path)
    assert backup_path.exists()
    assert json.loads(backup_path.read_text(encoding="utf-8")) == original_data

    written = json.loads(accounts_file.read_text(encoding="utf-8"))
    assert written[0]["usage_status"] == USAGE_SOLD
    assert written[0]["sync_disabled"] is True


def test_migrate_accounts_file_returns_file_not_found(tmp_path, monkeypatch):
    accounts_file = tmp_path / "accounts.json"
    monkeypatch.setattr(account_store.accounts, "ACCOUNTS_FILE", accounts_file)

    report = account_store.migrate_accounts_file(dry_run=False)

    assert report == {"total": 0, "skipped": "file_not_found"}
