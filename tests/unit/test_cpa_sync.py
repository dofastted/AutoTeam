import json

from autoteam import accounts, cpa_sync


def test_maintain_cpa_inventory_uploads_only_inventory_rt_files(tmp_path, monkeypatch):
    accounts_file = tmp_path / "accounts.json"
    monkeypatch.setattr(accounts, "ACCOUNTS_FILE", accounts_file)
    monkeypatch.setattr(cpa_sync, "list_cpa_files", lambda: [])
    uploaded = []
    monkeypatch.setattr(cpa_sync, "upload_to_cpa", lambda path: uploaded.append(path.name) or True)

    rt_file = tmp_path / "codex-stock@example.com-team-acc-oauth.json"
    rt_file.write_text(
        json.dumps({"access_token": "at", "refresh_token": "rt", "email": "stock@example.com"}),
        encoding="utf-8",
    )
    session_file = tmp_path / "codex-session@example.com-team-acc-session.json"
    session_file.write_text(
        json.dumps(
            {
                "access_token": "at",
                "refresh_token": "",
                "email": "session@example.com",
                "credential_source": "chatgpt_session",
            }
        ),
        encoding="utf-8",
    )
    normal_file = tmp_path / "codex-normal@example.com-team-acc-oauth.json"
    normal_file.write_text(
        json.dumps({"access_token": "at", "refresh_token": "rt", "email": "normal@example.com"}),
        encoding="utf-8",
    )
    accounts.save_accounts(
        [
            {
                "email": "stock@example.com",
                "status": accounts.STATUS_ACTIVE,
                "usage_status": accounts.USAGE_INVENTORY,
                "cpa_status": accounts.CPA_STATUS_SUCCESS,
                "rt_auth_file": str(rt_file),
            },
            {
                "email": "session@example.com",
                "status": accounts.STATUS_ACTIVE,
                "usage_status": accounts.USAGE_INVENTORY,
                "cpa_status": accounts.CPA_STATUS_SUCCESS,
                "session_auth_file": str(session_file),
            },
            {
                "email": "normal@example.com",
                "status": accounts.STATUS_ACTIVE,
                "usage_status": accounts.USAGE_NORMAL,
                "cpa_status": accounts.CPA_STATUS_SUCCESS,
                "rt_auth_file": str(normal_file),
            },
        ]
    )

    result = cpa_sync.maintain_cpa_inventory(target=1)

    assert uploaded == [rt_file.name]
    assert result["uploaded_count"] == 1
    latest = accounts.find_account(accounts.load_accounts(), "stock@example.com")
    assert latest["cloud_stocked_at"] > 0


def test_delete_http401_marks_returned_auth_names_unavailable(tmp_path, monkeypatch):
    accounts_file = tmp_path / "accounts.json"
    monkeypatch.setattr(accounts, "ACCOUNTS_FILE", accounts_file)
    accounts.save_accounts(
        [
            {
                "email": "dead@example.com",
                "status": accounts.STATUS_ACTIVE,
                "rt_auth_file": str(tmp_path / "codex-dead@example.com-team-acc-oauth.json"),
            }
        ]
    )

    class Resp:
        status_code = 200
        text = "{}"

        def json(self):
            return {"deleted": ["codex-dead@example.com-team-acc-oauth.json"]}

    monkeypatch.setattr(cpa_sync.outbound_proxy, "request", lambda *_args, **_kwargs: Resp())

    result = cpa_sync.delete_http401_from_cpa()

    assert result["deleted"] == ["codex-dead@example.com-team-acc-oauth.json"]
    latest = accounts.find_account(accounts.load_accounts(), "dead@example.com")
    assert latest["status"] == accounts.STATUS_UNAVAILABLE
    assert latest["sync_disabled"] is True
    assert latest["unavailable_reason"] == "http_401"


def test_cleanup_invalid_cpa_refresh_tokens_deletes_unauthorized_rt(tmp_path, monkeypatch):
    accounts_file = tmp_path / "accounts.json"
    monkeypatch.setattr(accounts, "ACCOUNTS_FILE", accounts_file)
    accounts.save_accounts(
        [
            {
                "email": "dead@example.com",
                "status": accounts.STATUS_ACTIVE,
                "rt_auth_file": str(tmp_path / "codex-dead@example.com-team-acc-oauth.json"),
            }
        ]
    )

    monkeypatch.setattr(cpa_sync, "list_cpa_files", lambda: [{"name": "codex-dead@example.com-team-acc-oauth.json", "email": "dead@example.com"}])
    monkeypatch.setattr(
        cpa_sync,
        "download_from_cpa",
        lambda _name: json.dumps({"email": "dead@example.com", "access_token": "at", "refresh_token": "rt"}),
    )

    class Resp:
        status_code = 401
        text = '{"error":{"code":"refresh_token_reused"}}'

    deleted = []
    monkeypatch.setattr(cpa_sync, "_refresh_token_response", lambda _rt: Resp())
    monkeypatch.setattr(cpa_sync, "delete_from_cpa", lambda name: deleted.append(name) or True)

    result = cpa_sync.cleanup_invalid_cpa_refresh_tokens()

    assert result["checked"] == 1
    assert result["deleted"] == 1
    assert deleted == ["codex-dead@example.com-team-acc-oauth.json"]
    latest = accounts.find_account(accounts.load_accounts(), "dead@example.com")
    assert latest["status"] == accounts.STATUS_UNAVAILABLE
    assert latest["unavailable_reason"] == "http_401"


def test_cleanup_invalid_cpa_refresh_tokens_reuploads_rotated_rt(monkeypatch):
    monkeypatch.setattr(cpa_sync, "list_cpa_files", lambda: [{"name": "codex-ok@example.com-team-acc-oauth.json", "email": "ok@example.com"}])
    monkeypatch.setattr(
        cpa_sync,
        "download_from_cpa",
        lambda _name: json.dumps({"email": "ok@example.com", "access_token": "old-at", "refresh_token": "old-rt"}),
    )

    class Resp:
        status_code = 200
        text = "{}"

        def json(self):
            return {
                "access_token": "new-at",
                "refresh_token": "new-rt",
                "id_token": "new-id",
                "expires_in": 3600,
            }

    uploaded_payloads = []

    def fake_upload(path):
        uploaded_payloads.append(json.loads(path.read_text(encoding="utf-8")))
        return True

    monkeypatch.setattr(cpa_sync, "_refresh_token_response", lambda _rt: Resp())
    monkeypatch.setattr(cpa_sync, "upload_to_cpa", fake_upload)

    result = cpa_sync.cleanup_invalid_cpa_refresh_tokens()

    assert result["checked"] == 1
    assert result["refreshed"] == 1
    assert result["deleted"] == 0
    assert uploaded_payloads[0]["access_token"] == "new-at"
    assert uploaded_payloads[0]["refresh_token"] == "new-rt"


def test_mark_unusable_account_deactivated_from_dir_marks_local_accounts(tmp_path, monkeypatch):
    accounts_file = tmp_path / "accounts.json"
    monkeypatch.setattr(accounts, "ACCOUNTS_FILE", accounts_file)
    unusable_dir = tmp_path / "auths" / "unusable" / "account_deactivated"
    unusable_dir.mkdir(parents=True)
    unusable_file = unusable_dir / "codex-dead@example.com-team-acc.json"
    unusable_file.write_text(json.dumps({"email": "dead@example.com"}), encoding="utf-8")
    accounts.save_accounts(
        [
            {"email": "dead@example.com", "status": accounts.STATUS_ACTIVE},
            {"email": "ok@example.com", "status": accounts.STATUS_ACTIVE},
        ]
    )

    result = cpa_sync.mark_unusable_account_deactivated_from_dir(str(unusable_dir))

    assert result["files"] == 1
    assert result["matched_accounts"] == 1
    assert result["changed_accounts"] == 1
    latest = accounts.find_account(accounts.load_accounts(), "dead@example.com")
    assert latest["status"] == accounts.STATUS_UNAVAILABLE
    assert latest["sync_disabled"] is True
    assert latest["unavailable_reason"] == "account_deactivated"
    assert latest["cpa_status"] == "failed"
