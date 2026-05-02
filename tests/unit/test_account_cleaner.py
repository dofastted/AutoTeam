import re
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
