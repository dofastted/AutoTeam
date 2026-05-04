import json

import pytest
import requests

from autoteam import accounts, cpa_sync


def test_sync_to_cpa_uploads_only_local_rt_files_and_does_not_delete_remote(tmp_path, monkeypatch):
    accounts_file = tmp_path / "accounts.json"
    monkeypatch.setattr(accounts, "ACCOUNTS_FILE", accounts_file)
    monkeypatch.setattr(cpa_sync, "AUTH_DIR", tmp_path)

    rt_file = tmp_path / "codex-active@example.com-team-acc-oauth.json"
    rt_file.write_text(
        json.dumps({"access_token": "at", "refresh_token": "rt", "email": "active@example.com"}),
        encoding="utf-8",
    )
    session_file = tmp_path / "codex-session@example.com-team-acc-session.json"
    session_file.write_text(
        json.dumps(
            {
                "access_token": "session-at",
                "refresh_token": "",
                "email": "session@example.com",
                "credential_source": "chatgpt_session",
            }
        ),
        encoding="utf-8",
    )
    standby_file = tmp_path / "codex-standby@example.com-team-acc-oauth.json"
    standby_file.write_text(
        json.dumps({"access_token": "at", "refresh_token": "rt", "email": "standby@example.com"}),
        encoding="utf-8",
    )
    accounts.save_accounts(
        [
            {
                "email": "active@example.com",
                "status": accounts.STATUS_ACTIVE,
                "rt_auth_file": str(rt_file),
            },
            {
                "email": "session@example.com",
                "status": accounts.STATUS_ACTIVE,
                "session_auth_file": str(session_file),
            },
            {
                "email": "missing@example.com",
                "status": accounts.STATUS_ACTIVE,
            },
            {
                "email": "standby@example.com",
                "status": accounts.STATUS_STANDBY,
                "rt_auth_file": str(standby_file),
            },
        ]
    )

    monkeypatch.setattr(
        cpa_sync,
        "list_cpa_files",
        lambda: [{"name": "codex-old@example.com-team-acc-oauth.json", "email": "old@example.com"}],
    )
    uploaded = []
    deleted = []
    monkeypatch.setattr(cpa_sync, "upload_to_cpa", lambda path: uploaded.append(path.name) or True)
    monkeypatch.setattr(cpa_sync, "delete_from_cpa", lambda name: deleted.append(name) or True)

    result = cpa_sync.sync_to_cpa()

    assert uploaded == [rt_file.name]
    assert deleted == []
    assert result["uploaded"] == 1
    assert result["deleted"] == 0
    assert result["skipped"] == 2
    assert result["skipped_accounts"] == [
        {"email": "session@example.com", "reason": "session_file_not_uploadable"},
        {"email": "missing@example.com", "reason": "missing_oauth_rt_file"},
    ]
    latest = accounts.find_account(accounts.load_accounts(), "active@example.com")
    assert latest["cpa_uploaded_at"] > 0
    assert latest["cpa_status"] == accounts.CPA_STATUS_SUCCESS
    assert latest["cpa_error_message"] == ""
    assert latest["health_status"] == "valid"
    assert latest["qualified_at"] > 0


def test_sync_to_cpa_skips_remote_existing_by_email_or_name(tmp_path, monkeypatch):
    accounts_file = tmp_path / "accounts.json"
    monkeypatch.setattr(accounts, "ACCOUNTS_FILE", accounts_file)
    monkeypatch.setattr(cpa_sync, "AUTH_DIR", tmp_path)

    name_match_file = tmp_path / "codex-name@example.com-team-acc-oauth.json"
    name_match_file.write_text(
        json.dumps({"access_token": "at", "refresh_token": "rt", "email": "name@example.com"}),
        encoding="utf-8",
    )
    email_match_file = tmp_path / "codex-email@example.com-team-acc-oauth.json"
    email_match_file.write_text(
        json.dumps({"access_token": "at", "refresh_token": "rt", "email": "email@example.com"}),
        encoding="utf-8",
    )
    accounts.save_accounts(
        [
            {
                "email": "name@example.com",
                "status": accounts.STATUS_ACTIVE,
                "rt_auth_file": str(name_match_file),
            },
            {
                "email": "email@example.com",
                "status": accounts.STATUS_ACTIVE,
                "rt_auth_file": str(email_match_file),
            },
        ]
    )

    monkeypatch.setattr(
        cpa_sync,
        "list_cpa_files",
        lambda: [
            {"name": name_match_file.name, "email": "other@example.com"},
            {"name": "codex-old-email@example.com-team-acc-oauth.json", "email": "email@example.com"},
        ],
    )
    uploaded = []
    monkeypatch.setattr(cpa_sync, "upload_to_cpa", lambda path: uploaded.append(path.name) or True)

    result = cpa_sync.sync_to_cpa()

    assert uploaded == []
    assert result["uploaded"] == 0
    assert result["skipped_existing"] == 2


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


def test_cleanup_invalid_cpa_refresh_tokens_writes_rotated_rt_to_local_auths(tmp_path, monkeypatch):
    name = "codex-ok@example.com-team-acc-oauth.json"
    local_auth_path = tmp_path / name
    local_auth_path.write_text(
        json.dumps({"email": "ok@example.com", "access_token": "local-old-at", "refresh_token": "old-rt"}),
        encoding="utf-8",
    )

    monkeypatch.setattr(cpa_sync, "AUTH_DIR", tmp_path)
    monkeypatch.setattr(cpa_sync, "list_cpa_files", lambda: [{"name": name, "email": "ok@example.com"}])
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

    monkeypatch.setattr(cpa_sync, "_refresh_token_response", lambda _rt: Resp())
    monkeypatch.setattr(cpa_sync, "upload_to_cpa", lambda _path: True)

    result = cpa_sync.cleanup_invalid_cpa_refresh_tokens()

    local_payload = json.loads(local_auth_path.read_text(encoding="utf-8"))
    assert result["checked"] == 1
    assert result["refreshed"] == 1
    assert result["failed"] == []
    assert local_payload["access_token"] == "new-at"
    assert local_payload["refresh_token"] == "new-rt"
    assert local_payload["id_token"] == "new-id"


def test_upload_to_cpa_treats_timeout_as_success_when_remote_file_exists(tmp_path, monkeypatch):
    auth_path = tmp_path / "codex-ok@example.com-team-acc-oauth.json"
    auth_path.write_text(json.dumps({"email": "ok@example.com", "refresh_token": "rt"}), encoding="utf-8")

    def raise_timeout(*_args, **_kwargs):
        raise requests.exceptions.ReadTimeout("timed out")

    monkeypatch.setattr(cpa_sync.outbound_proxy, "request", raise_timeout)
    monkeypatch.setattr(cpa_sync, "list_cpa_files", lambda: [{"name": auth_path.name}])
    monkeypatch.setattr(cpa_sync, "_download_cpa_file_state", lambda _name: cpa_sync.REMOTE_FILE_EXISTS)

    assert cpa_sync.upload_to_cpa(auth_path) is True


def test_upload_to_cpa_does_not_confirm_remote_file_after_non_timeout_error(tmp_path, monkeypatch):
    auth_path = tmp_path / "codex-stale@example.com-team-acc-oauth.json"
    auth_path.write_text(json.dumps({"email": "stale@example.com", "refresh_token": "new-rt"}), encoding="utf-8")
    confirm_calls = []

    def raise_connection_error(*_args, **_kwargs):
        raise requests.exceptions.ConnectionError("connection failed before upload")

    def confirm_should_not_run(_name):
        confirm_calls.append(_name)
        return cpa_sync.REMOTE_FILE_EXISTS

    monkeypatch.setattr(cpa_sync.outbound_proxy, "request", raise_connection_error)
    monkeypatch.setattr(cpa_sync, "confirm_remote_file_state", confirm_should_not_run)

    with pytest.raises(requests.exceptions.ConnectionError):
        cpa_sync.upload_to_cpa(auth_path)

    assert confirm_calls == []


def test_upload_to_cpa_reraises_timeout_when_remote_file_missing(tmp_path, monkeypatch):
    auth_path = tmp_path / "codex-missing@example.com-team-acc-oauth.json"
    auth_path.write_text(json.dumps({"email": "missing@example.com", "refresh_token": "rt"}), encoding="utf-8")

    def raise_timeout(*_args, **_kwargs):
        raise requests.exceptions.ReadTimeout("timed out")

    monkeypatch.setattr(cpa_sync.outbound_proxy, "request", raise_timeout)
    monkeypatch.setattr(cpa_sync, "list_cpa_files", lambda: [])
    monkeypatch.setattr(cpa_sync, "_download_cpa_file_state", lambda _name: cpa_sync.REMOTE_FILE_MISSING)

    try:
        cpa_sync.upload_to_cpa(auth_path)
    except requests.exceptions.ReadTimeout:
        pass
    else:
        raise AssertionError("expected ReadTimeout")


def test_upload_to_cpa_raises_uncertain_when_timeout_confirmation_is_temporarily_unavailable(tmp_path, monkeypatch):
    auth_path = tmp_path / "codex-unknown@example.com-team-acc-oauth.json"
    auth_path.write_text(json.dumps({"email": "unknown@example.com", "refresh_token": "rt"}), encoding="utf-8")

    def raise_timeout(*_args, **_kwargs):
        raise requests.exceptions.ReadTimeout("timed out")

    attempts = {"count": 0}

    def flaky_list():
        attempts["count"] += 1
        raise RuntimeError("cpa list temporary error")

    monkeypatch.setattr(cpa_sync.outbound_proxy, "request", raise_timeout)
    monkeypatch.setattr(cpa_sync, "list_cpa_files", flaky_list)
    monkeypatch.setattr(cpa_sync, "_download_cpa_file_state", lambda _name: (_ for _ in ()).throw(RuntimeError("download failed")))

    with pytest.raises(cpa_sync.CpaUploadConfirmationUncertain):
        cpa_sync.upload_to_cpa(auth_path)

    assert attempts["count"] == cpa_sync.CPA_UPLOAD_CONFIRM_ATTEMPTS


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
