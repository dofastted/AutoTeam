import json
import time

from autoteam import accounts


def _write_json(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


def test_add_and_update_account_persists_data(tmp_path, monkeypatch):
    accounts_file = tmp_path / "accounts.json"
    monkeypatch.setattr(accounts, "ACCOUNTS_FILE", accounts_file)
    monkeypatch.setattr(accounts, "get_admin_email", lambda: "")

    accounts.add_account("user@example.com", "secret", cloudmail_account_id=123)
    created = accounts.load_accounts()

    assert len(created) == 1
    assert created[0]["email"] == "user@example.com"
    assert created[0]["cloudmail_account_id"] == 123
    assert created[0]["mail_account_id"] == 123
    assert created[0]["mail_provider"] == "cloudmail"
    assert created[0]["status"] == accounts.STATUS_PENDING
    assert created[0]["usage_status"] == accounts.USAGE_NORMAL

    updated = accounts.update_account("user@example.com", status=accounts.STATUS_ACTIVE, auth_file="auth.json")

    assert updated["status"] == accounts.STATUS_ACTIVE
    assert updated["auth_file"] == "auth.json"
    assert accounts.load_accounts()[0]["auth_file"] == "auth.json"


def test_mark_account_sold_keeps_record_and_disables_sync(tmp_path, monkeypatch):
    accounts_file = tmp_path / "accounts.json"
    monkeypatch.setattr(accounts, "ACCOUNTS_FILE", accounts_file)

    accounts.save_accounts(
        [
            {
                "email": "sold@example.com",
                "status": accounts.STATUS_ACTIVE,
                "auth_file": "auth.json",
            }
        ]
    )

    updated = accounts.mark_account_sold("sold@example.com", remote_cleanup={"cpa": {"count": 1}})

    assert updated["status"] == accounts.STATUS_SOLD
    assert updated["usage_status"] == accounts.USAGE_SOLD
    assert updated["sync_disabled"] is True
    assert updated["sold_at"] > 0
    assert updated["sale_remote_cleanup"] == {"cpa": {"count": 1}}
    assert accounts.load_accounts()[0]["auth_file"] == "auth.json"


def test_mark_account_self_use_keeps_record_and_disables_sync(tmp_path, monkeypatch):
    accounts_file = tmp_path / "accounts.json"
    monkeypatch.setattr(accounts, "ACCOUNTS_FILE", accounts_file)

    accounts.save_accounts(
        [
            {
                "email": "self@example.com",
                "status": accounts.STATUS_ACTIVE,
                "auth_file": "auth.json",
            }
        ]
    )

    updated = accounts.mark_account_self_use("self@example.com", remote_cleanup={"cpa": {"count": 1}})

    assert updated["status"] == accounts.STATUS_ACTIVE
    assert updated["usage_status"] == accounts.USAGE_SELF_USE
    assert updated["sync_disabled"] is True
    assert updated["self_use_at"] > 0
    assert updated["self_use_remote_cleanup"] == {"cpa": {"count": 1}}
    assert accounts.load_accounts()[0]["auth_file"] == "auth.json"


def test_load_accounts_normalizes_missing_usage_status(tmp_path, monkeypatch):
    accounts_file = tmp_path / "accounts.json"
    accounts_file.write_text(
        '[{"email":"a@example.com","status":"active"},{"email":"b@example.com","status":"sold"}]',
        encoding="utf-8",
    )
    monkeypatch.setattr(accounts, "ACCOUNTS_FILE", accounts_file)

    loaded = accounts.load_accounts()

    assert loaded[0]["usage_status"] == accounts.USAGE_NORMAL
    assert loaded[1]["usage_status"] == accounts.USAGE_SOLD


def test_get_active_accounts_excludes_main_account(tmp_path, monkeypatch):
    accounts_file = tmp_path / "accounts.json"
    monkeypatch.setattr(accounts, "ACCOUNTS_FILE", accounts_file)
    monkeypatch.setattr(accounts, "get_admin_email", lambda: "owner@example.com")

    accounts.save_accounts(
        [
            {"email": "owner@example.com", "status": accounts.STATUS_ACTIVE},
            {"email": "member@example.com", "status": accounts.STATUS_ACTIVE},
            {"email": "standby@example.com", "status": accounts.STATUS_STANDBY},
        ]
    )

    active = accounts.get_active_accounts()

    assert [item["email"] for item in active] == ["member@example.com"]


def test_get_standby_accounts_orders_recovered_first_and_skips_main_account(tmp_path, monkeypatch):
    accounts_file = tmp_path / "accounts.json"
    monkeypatch.setattr(accounts, "ACCOUNTS_FILE", accounts_file)
    monkeypatch.setattr(accounts, "get_admin_email", lambda: "owner@example.com")

    now = time.time()
    accounts.save_accounts(
        [
            {
                "email": "owner@example.com",
                "status": accounts.STATUS_STANDBY,
                "quota_resets_at": None,
                "quota_exhausted_at": None,
            },
            {
                "email": "ready@example.com",
                "status": accounts.STATUS_STANDBY,
                "quota_resets_at": now - 60,
                "quota_exhausted_at": now - 120,
            },
            {
                "email": "later@example.com",
                "status": accounts.STATUS_STANDBY,
                "quota_resets_at": now + 600,
                "quota_exhausted_at": now - 30,
            },
            {
                "email": "always@example.com",
                "status": accounts.STATUS_STANDBY,
                "quota_resets_at": None,
                "quota_exhausted_at": None,
            },
        ]
    )

    standby = accounts.get_standby_accounts()

    assert [item["email"] for item in standby] == [
        "always@example.com",
        "ready@example.com",
        "later@example.com",
    ]
    assert standby[0]["_quota_recovered"] is True
    assert standby[1]["_quota_recovered"] is True
    assert standby[2]["_quota_recovered"] is False
    assert accounts.get_next_reusable_account()["email"] == "always@example.com"


def test_migrate_legacy_auth_file_metadata_dry_run_reports_without_writing(tmp_path, monkeypatch):
    accounts_file = tmp_path / "accounts.json"
    monkeypatch.setattr(accounts, "ACCOUNTS_FILE", accounts_file)
    legacy_auth = _write_json(
        tmp_path / "codex-user@example.com-team-old.json",
        {
            "access_token": "at",
            "refresh_token": "rt",
            "email": "user@example.com",
        },
    )
    accounts.save_accounts(
        [
            {
                "email": "user@example.com",
                "status": accounts.STATUS_ACTIVE,
                "auth_file": legacy_auth,
            }
        ]
    )
    before = accounts_file.read_text(encoding="utf-8")

    result = accounts.migrate_legacy_auth_file_metadata()

    assert result["dry_run"] is True
    assert result["migrated"] == 1
    assert result["changed"] == 1
    assert result["accounts"] == [
        {
            "email": "user@example.com",
            "status": "migrated",
            "auth_file": legacy_auth,
            "rt_auth_file": legacy_auth,
        }
    ]
    assert accounts_file.read_text(encoding="utf-8") == before
    assert "rt_auth_file" not in accounts.load_accounts()[0]


def test_migrate_legacy_auth_file_metadata_apply_sets_rt_without_touching_token_file(tmp_path, monkeypatch):
    accounts_file = tmp_path / "accounts.json"
    monkeypatch.setattr(accounts, "ACCOUNTS_FILE", accounts_file)
    legacy_path = tmp_path / "codex-user@example.com-team-old.json"
    legacy_auth = _write_json(
        legacy_path,
        {
            "access_token": "at",
            "refresh_token": "rt",
            "email": "user@example.com",
        },
    )
    before_token_content = legacy_path.read_text(encoding="utf-8")
    accounts.save_accounts(
        [
            {
                "email": "user@example.com",
                "status": accounts.STATUS_ACTIVE,
                "auth_file": legacy_auth,
            }
        ]
    )

    result = accounts.migrate_legacy_auth_file_metadata(apply=True)

    assert result["dry_run"] is False
    assert result["migrated"] == 1
    assert result["changed"] == 1
    loaded = accounts.load_accounts()
    assert loaded[0]["auth_file"] == legacy_auth
    assert loaded[0]["rt_auth_file"] == legacy_auth
    assert legacy_path.read_text(encoding="utf-8") == before_token_content


def test_migrate_legacy_auth_file_metadata_does_not_promote_session_auth_file(tmp_path, monkeypatch):
    accounts_file = tmp_path / "accounts.json"
    monkeypatch.setattr(accounts, "ACCOUNTS_FILE", accounts_file)
    session_auth = _write_json(
        tmp_path / "codex-user@example.com-team-old-session.json",
        {
            "access_token": "session-at",
            "refresh_token": "",
            "credential_source": "chatgpt_session",
            "email": "user@example.com",
        },
    )
    accounts.save_accounts(
        [
            {
                "email": "user@example.com",
                "status": accounts.STATUS_ACTIVE,
                "auth_file": session_auth,
                "session_auth_file": session_auth,
            }
        ]
    )

    result = accounts.migrate_legacy_auth_file_metadata(apply=True)

    assert result["migrated"] == 0
    assert result["changed"] == 0
    assert result["session_auth_file_not_promoted"] == 1
    loaded = accounts.load_accounts()
    assert "rt_auth_file" not in loaded[0]
    assert loaded[0]["auth_file"] == session_auth


def test_migrate_legacy_auth_file_metadata_reports_missing_and_invalid_auth_files(tmp_path, monkeypatch):
    accounts_file = tmp_path / "accounts.json"
    monkeypatch.setattr(accounts, "ACCOUNTS_FILE", accounts_file)
    invalid_auth = _write_json(
        tmp_path / "codex-invalid@example.com-team-old.json",
        {
            "access_token": "at",
            "refresh_token": "",
            "email": "invalid@example.com",
        },
    )
    accounts.save_accounts(
        [
            {
                "email": "missing@example.com",
                "status": accounts.STATUS_ACTIVE,
                "auth_file": str(tmp_path / "missing.json"),
            },
            {
                "email": "invalid@example.com",
                "status": accounts.STATUS_ACTIVE,
                "auth_file": invalid_auth,
            },
        ]
    )

    result = accounts.migrate_legacy_auth_file_metadata(apply=True)

    assert result["migrated"] == 0
    assert result["changed"] == 0
    assert result["missing_auth_file"] == 1
    assert result["invalid_auth_file"] == 1
    assert [item["status"] for item in result["accounts"]] == [
        "missing_auth_file",
        "invalid_auth_file",
    ]
    assert all("rt_auth_file" not in item for item in accounts.load_accounts())


def test_migrate_legacy_auth_file_metadata_keeps_existing_valid_rt_auth_file(tmp_path, monkeypatch):
    accounts_file = tmp_path / "accounts.json"
    monkeypatch.setattr(accounts, "ACCOUNTS_FILE", accounts_file)
    legacy_auth = _write_json(
        tmp_path / "codex-user@example.com-team-old.json",
        {
            "access_token": "old-at",
            "refresh_token": "old-rt",
            "email": "user@example.com",
        },
    )
    rt_auth = _write_json(
        tmp_path / "codex-user@example.com-team-new-oauth.json",
        {
            "access_token": "new-at",
            "refresh_token": "new-rt",
            "email": "user@example.com",
        },
    )
    accounts.save_accounts(
        [
            {
                "email": "user@example.com",
                "status": accounts.STATUS_ACTIVE,
                "auth_file": legacy_auth,
                "rt_auth_file": rt_auth,
            }
        ]
    )

    result = accounts.migrate_legacy_auth_file_metadata(apply=True)

    assert result["migrated"] == 0
    assert result["changed"] == 0
    assert result["already_rt_auth_file"] == 1
    loaded = accounts.load_accounts()
    assert loaded[0]["auth_file"] == legacy_auth
    assert loaded[0]["rt_auth_file"] == rt_auth
