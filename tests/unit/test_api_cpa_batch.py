import threading

import pytest

from autoteam import accounts, api, cpa_batch, flow_runs


def test_post_cpa_batch_starts_fixed_size_task(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        api,
        "_current_runtime_env",
        lambda: {
            "MAIL_PROVIDER": "mo_email",
            "MO_EMAIL_BASE_URL": "https://mo.example.com",
            "MO_EMAIL_API_KEY": "key",
            "MO_EMAIL_DOMAIN": "example.com",
            "MO_EMAIL_NAME_PREFIX": "abc",
            "MO_EMAIL_START_INDEX": "1",
            "MO_EMAIL_EXPIRY_TIME": "3600000",
            "CPA_URL": "http://127.0.0.1:8317",
            "CPA_KEY": "secret",
        },
    )
    monkeypatch.setattr(api, "_admin_status", lambda: {"configured": True})
    monkeypatch.setattr("uuid.uuid4", lambda: type("FakeUuid", (), {"hex": "runid1234567890"})())

    def fake_start_task(command, func, params, *args, **kwargs):
        captured["command"] = command
        captured["params"] = params
        captured["args"] = args
        captured["kwargs"] = kwargs
        return {"task_id": "task-1", "command": command, "params": params}

    monkeypatch.setattr(api, "_start_task", fake_start_task)

    result = api.post_cpa_batch(api.CpaBatchParams(join_mode="invite"))

    assert result["command"] == "cpa-batch"
    assert captured["params"] == {
        "run_id": "runid1234567",
        "join_mode": "invite",
        "target": 100,
        "batch_size": 20,
    }
    assert captured["kwargs"]["join_mode"] == "invite"


def test_post_cpa_batch_accepts_single_validation_target(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        api,
        "_current_runtime_env",
        lambda: {
            "MAIL_PROVIDER": "mo_email",
            "MO_EMAIL_BASE_URL": "https://mo.example.com",
            "MO_EMAIL_API_KEY": "key",
            "MO_EMAIL_DOMAIN": "example.com",
            "MO_EMAIL_NAME_PREFIX": "abc",
            "MO_EMAIL_START_INDEX": "1",
            "MO_EMAIL_EXPIRY_TIME": "3600000",
            "CPA_URL": "http://127.0.0.1:8317",
            "CPA_KEY": "secret",
        },
    )
    monkeypatch.setattr(api, "_admin_status", lambda: {"configured": True})
    monkeypatch.setattr("uuid.uuid4", lambda: type("FakeUuid", (), {"hex": "runid1234567890"})())

    def fake_start_task(command, func, params, *args, **kwargs):
        captured["params"] = params
        captured["kwargs"] = kwargs
        return {"task_id": "task-1", "command": command, "params": params}

    monkeypatch.setattr(api, "_start_task", fake_start_task)

    result = api.post_cpa_batch(api.CpaBatchParams(join_mode="direct", target=1, batch_size=1))

    assert result["params"]["target"] == 1
    assert captured["params"]["batch_size"] == 1
    assert captured["kwargs"]["target"] == 1


def test_post_cpa_batch_rejects_unknown_join_mode(monkeypatch):
    monkeypatch.setattr(
        api,
        "_current_runtime_env",
        lambda: {
            "MAIL_PROVIDER": "mo_email",
            "MO_EMAIL_BASE_URL": "https://mo.example.com",
            "MO_EMAIL_API_KEY": "key",
            "MO_EMAIL_DOMAIN": "example.com",
            "MO_EMAIL_NAME_PREFIX": "abc",
            "MO_EMAIL_START_INDEX": "1",
            "MO_EMAIL_EXPIRY_TIME": "3600000",
            "CPA_URL": "http://127.0.0.1:8317",
            "CPA_KEY": "secret",
        },
    )
    monkeypatch.setattr(api, "_admin_status", lambda: {"configured": True})

    try:
        api.post_cpa_batch(api.CpaBatchParams(join_mode="bad"))
    except api.HTTPException as exc:
        assert exc.status_code == 400
        assert "未知入席方式" in exc.detail
    else:
        raise AssertionError("expected HTTPException")


def test_pause_cpa_batch_run_sets_pause_flag(tmp_path, monkeypatch):
    monkeypatch.setattr(flow_runs, "FLOW_RUNS_FILE", tmp_path / "flow_runs.json")
    flow_runs.create_flow_run("run-pause", target=100, batch_size=20, join_mode="direct")

    result = api.pause_cpa_batch_run("run-pause")
    run = flow_runs.get_flow_run("run-pause")

    assert result["run"]["pause_requested"] is True
    assert run["pause_requested"] is True


def test_create_direct_account_retries_current_account_after_browser_error(tmp_path, monkeypatch):
    monkeypatch.setattr(accounts, "ACCOUNTS_FILE", tmp_path / "accounts.json")
    monkeypatch.setattr(cpa_batch, "time", type("FakeTime", (), {"time": staticmethod(lambda: 1000), "sleep": staticmethod(lambda _s: None)})())
    monkeypatch.setattr("autoteam.manager._is_email_in_team", lambda _email: False)
    monkeypatch.setattr(cpa_batch, "save_auth_file", lambda _bundle: str(tmp_path / "codex-a-team.json"))

    calls = []

    def fake_register(_mail_client, email, _password, **kwargs):
        calls.append(email)
        if len(calls) == 1:
            raise RuntimeError("browser closed")
        kwargs["session_bundle_callback"](
            {
                "access_token": "token",
                "id_token": "token",
                "email": email,
                "plan_type": "team",
                "expired": 2000,
            }
        )
        return True

    monkeypatch.setattr("autoteam.manager._register_direct_once", fake_register)

    class FakeMailClient:
        provider_name = "mo_email"

        def create_temp_email(self):
            return "mail-1", "retry@example.com"

        def delete_account(self, _account_id):
            raise AssertionError("should not delete successful account")

    email = cpa_batch._create_direct_account(FakeMailClient())

    assert email == "retry@example.com"
    assert calls == ["retry@example.com", "retry@example.com"]
    saved = accounts.load_accounts()[0]
    assert saved["status"] == accounts.STATUS_ACTIVE
    assert saved["auth_file"].endswith("codex-a-team.json")


def test_create_direct_account_does_not_accept_team_membership_without_session(tmp_path, monkeypatch):
    monkeypatch.setattr(accounts, "ACCOUNTS_FILE", tmp_path / "accounts.json")
    monkeypatch.setattr(cpa_batch.time, "sleep", lambda _s: None)
    monkeypatch.setattr("autoteam.manager._is_email_in_team", lambda _email: True)

    def fake_register(*_args, **_kwargs):
        raise RuntimeError("ChatGPT session 提取失败: no token")

    monkeypatch.setattr("autoteam.manager._register_direct_once", fake_register)

    class FakeMailClient:
        provider_name = "mo_email"
        deleted = False

        def create_temp_email(self):
            return "mail-1", "nosession@example.com"

        def delete_account(self, _account_id):
            self.deleted = True

    mail_client = FakeMailClient()

    with pytest.raises(cpa_batch.AccountFlowError, match="连续 3 次直注注册失败"):
        cpa_batch._create_direct_account(mail_client)

    assert mail_client.deleted is True


def test_run_cpa_batch_processes_cpa_upload_while_registering_next_account(tmp_path, monkeypatch):
    monkeypatch.setattr(flow_runs, "FLOW_RUNS_FILE", tmp_path / "flow_runs.json")
    monkeypatch.setattr(accounts, "ACCOUNTS_FILE", tmp_path / "accounts.json")

    class FakeMailClient:
        def login(self):
            pass

    monkeypatch.setattr(cpa_batch, "get_mail_client", lambda: FakeMailClient())

    created = []
    first_upload_started = threading.Event()
    release_first_upload = threading.Event()
    second_created_after_upload_started = {"value": False}

    def fake_create_direct(_mail_client, hooks=None, batch_index=None):
        email = f"user{len(created) + 1}@example.com"
        created.append(email)
        accounts.add_account(email, "pw")
        accounts.update_account(email, status=accounts.STATUS_ACTIVE)
        if len(created) == 2:
            second_created_after_upload_started["value"] = first_upload_started.wait(timeout=2)
            release_first_upload.set()
        return email

    def fake_verify(email, _mail_cache, **_kwargs):
        if email == "user1@example.com":
            first_upload_started.set()
            assert release_first_upload.wait(timeout=2)
        return {
            "email": email,
            "plan_type": "team",
            "auth_file": str(tmp_path / f"{email}.json"),
            "auth_name": f"{email}.json",
            "quota": {"primary_pct": 1},
        }

    monkeypatch.setattr(cpa_batch, "_create_direct_account", fake_create_direct)
    monkeypatch.setattr(cpa_batch, "_verify_and_upload_cpa", fake_verify)

    result = cpa_batch.run_cpa_batch("run-async", target=2, batch_size=20)

    assert result["status"] == "completed"
    assert result["succeeded"] == 2
    assert created == ["user1@example.com", "user2@example.com"]
    assert second_created_after_upload_started["value"] is True
