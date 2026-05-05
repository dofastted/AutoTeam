import json

from autoteam import account_deactivation, accounts


class _FakeMailClient:
    provider_name = "cloudmail"

    def __init__(self, emails=None):
        self.emails = emails or []
        self.login_called = False
        self.deleted = []

    def login(self):
        self.login_called = True
        return "token"

    def search_emails_by_recipient(self, to_email, size=10, account_id=None):
        return list(self.emails)

    def delete_account(self, account_id):
        self.deleted.append(account_id)
        return {"code": 200}


def test_deactivated_mail_candidates_skips_unavailable_sold_and_synced_accounts(tmp_path, monkeypatch):
    accounts_file = tmp_path / "accounts.json"
    monkeypatch.setattr(accounts, "ACCOUNTS_FILE", accounts_file)
    accounts.save_accounts(
        [
            {"email": "active@example.com", "status": accounts.STATUS_ACTIVE},
            {"email": "unavailable@example.com", "status": accounts.STATUS_UNAVAILABLE},
            {"email": "sold@example.com", "status": accounts.STATUS_SOLD},
            {"email": "self@example.com", "status": accounts.STATUS_ACTIVE, "usage_status": accounts.USAGE_SELF_USE},
            {"email": "synced@example.com", "status": accounts.STATUS_ACTIVE, "sync_disabled": True},
        ]
    )

    candidates = account_deactivation.deactivated_mail_candidates()

    assert [item["email"] for item in candidates] == ["active@example.com"]


def test_check_deactivated_mail_matches_keyword_in_body_and_marks_account(tmp_path, monkeypatch):
    accounts_file = tmp_path / "accounts.json"
    monkeypatch.setattr(accounts, "ACCOUNTS_FILE", accounts_file)
    accounts.save_accounts(
        [
            {
                "email": "active@example.com",
                "status": accounts.STATUS_ACTIVE,
                "mail_provider": "cloudmail",
                "mail_account_id": 7,
                "auth_file": str(tmp_path / "codex-active@example.com-team-abc-oauth.json"),
            }
        ]
    )

    fake_client = _FakeMailClient(
        emails=[
            {
                "emailId": "m-1",
                "subject": "notice",
                "text": "",
                "content": "",
                "raw": "",
            }
        ]
    )
    fake_client.emails[0]["content"] = "<html><body>your account is deactivated</body></html>"

    removed = []
    monkeypatch.setattr(account_deactivation, "get_mail_client", lambda _provider: fake_client)

    result = account_deactivation.check_deactivated_mail(
        apply=True,
        team_remover=lambda email, _acc: removed.append(email) or "removed",
        dispose_mailbox=True,
    )

    latest = accounts.find_account(accounts.load_accounts(), "active@example.com")
    assert result["matched"] == 1
    assert result["marked"] == 1
    assert result["seats_released"] == 1
    assert result["mailboxes_disposed"] == 1
    assert removed == ["active@example.com"]
    assert latest["status"] == accounts.STATUS_UNAVAILABLE
    assert latest["sync_disabled"] is True
    assert latest["unavailable_reason"] == "account_deactivated"
    assert latest["mailbox_retired"] is True
    assert latest["seat_release"]["status"] == "removed"
    assert latest["deactivated_mail_evidence"]["matched_fields"] == ["content"]


def test_check_deactivated_mail_dry_run_only_reports_matches(tmp_path, monkeypatch):
    accounts_file = tmp_path / "accounts.json"
    monkeypatch.setattr(accounts, "ACCOUNTS_FILE", accounts_file)
    accounts.save_accounts(
        [
            {
                "email": "active@example.com",
                "status": accounts.STATUS_ACTIVE,
                "mail_provider": "cloudmail",
                "mail_account_id": 7,
            }
        ]
    )

    fake_client = _FakeMailClient(
        emails=[
            {"emailId": "m-1", "subject": "deactivated notice", "text": "", "content": "", "raw": ""}
        ]
    )
    monkeypatch.setattr(account_deactivation, "get_mail_client", lambda _provider: fake_client)

    result = account_deactivation.check_deactivated_mail(apply=False)

    latest = accounts.find_account(accounts.load_accounts(), "active@example.com")
    assert result["dry_run"] is True
    assert result["matched"] == 1
    assert latest["status"] == accounts.STATUS_ACTIVE


def test_check_deactivated_mail_can_filter_specific_emails(tmp_path, monkeypatch):
    accounts_file = tmp_path / "accounts.json"
    monkeypatch.setattr(accounts, "ACCOUNTS_FILE", accounts_file)
    accounts.save_accounts(
        [
            {
                "email": "target@example.com",
                "status": accounts.STATUS_ACTIVE,
                "mail_provider": "cloudmail",
                "mail_account_id": 7,
            },
            {
                "email": "other@example.com",
                "status": accounts.STATUS_ACTIVE,
                "mail_provider": "cloudmail",
                "mail_account_id": 8,
            },
        ]
    )

    checked = []

    class FilterClient(_FakeMailClient):
        def search_emails_by_recipient(self, to_email, size=10, account_id=None):
            checked.append(to_email)
            return super().search_emails_by_recipient(to_email, size=size, account_id=account_id)

    fake_client = FilterClient(emails=[{"emailId": "m-1", "subject": "Account deactivated", "text": ""}])
    monkeypatch.setattr(account_deactivation, "get_mail_client", lambda _provider: fake_client)

    result = account_deactivation.check_deactivated_mail(apply=False, emails=["target@example.com"])

    assert checked == ["target@example.com"]
    assert result["candidate_count"] == 1
    assert result["matched"] == 1


def test_check_deactivated_mail_targeted_mode_includes_unavailable_but_skips_sold(tmp_path, monkeypatch):
    accounts_file = tmp_path / "accounts.json"
    monkeypatch.setattr(accounts, "ACCOUNTS_FILE", accounts_file)
    accounts.save_accounts(
        [
            {
                "email": "retry@example.com",
                "status": accounts.STATUS_UNAVAILABLE,
                "sync_disabled": True,
                "mail_provider": "cloudmail",
                "mail_account_id": 7,
            },
            {
                "email": "sold@example.com",
                "status": accounts.STATUS_SOLD,
                "mail_provider": "cloudmail",
                "mail_account_id": 8,
            },
        ]
    )

    checked = []

    class TargetedClient(_FakeMailClient):
        def search_emails_by_recipient(self, to_email, size=10, account_id=None):
            checked.append(to_email)
            return []

    monkeypatch.setattr(account_deactivation, "get_mail_client", lambda _provider: TargetedClient())

    result = account_deactivation.check_deactivated_mail(
        apply=False,
        emails=["retry@example.com", "sold@example.com"],
        include_targeted_accounts=True,
    )

    assert checked == ["retry@example.com"]
    assert result["candidate_count"] == 1


def test_check_deactivated_mail_can_use_directory_as_source(tmp_path, monkeypatch):
    accounts_file = tmp_path / "accounts.json"
    monkeypatch.setattr(accounts, "ACCOUNTS_FILE", accounts_file)
    unusable_dir = tmp_path / "auths" / "unusable" / "account_deactivated"
    unusable_dir.mkdir(parents=True)
    unusable_file = unusable_dir / "codex-dir@example.com-team-abc.json"
    unusable_file.write_text(json.dumps({"email": "dir@example.com"}), encoding="utf-8")
    accounts.save_accounts(
        [
            {
                "email": "dir@example.com",
                "status": accounts.STATUS_UNAVAILABLE,
                "sync_disabled": True,
                "unavailable_reason": "account_deactivated",
                "mail_provider": "cloudmail",
                "mail_account_id": 7,
            }
        ]
    )

    fake_client = _FakeMailClient(
        emails=[
            {"emailId": "m-1", "subject": "deactivated notice", "text": "", "content": "", "raw": ""}
        ]
    )
    monkeypatch.setattr(account_deactivation, "get_mail_client", lambda _provider: fake_client)

    result = account_deactivation.check_deactivated_mail(directory=str(unusable_dir), apply=False)

    assert result["source_mode"] == "directory"
    assert result["directory_files"] == 1
    assert result["candidate_count"] == 1
    assert result["matched"] == 1
    assert result["matches"][0]["email"] == "dir@example.com"
