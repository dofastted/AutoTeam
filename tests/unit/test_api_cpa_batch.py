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
        "parallel_workers": 1,
        "continue_on_error": False,
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


def test_post_cpa_batch_accepts_parallel_workers(monkeypatch):
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

    api.post_cpa_batch(api.CpaBatchParams(join_mode="direct", parallel_workers=3))

    assert captured["params"]["parallel_workers"] == 3
    assert captured["kwargs"]["parallel_workers"] == 3


def test_post_cpa_batch_accepts_continue_on_error(monkeypatch):
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

    api.post_cpa_batch(api.CpaBatchParams(join_mode="direct", continue_on_error=True))

    assert captured["params"]["continue_on_error"] is True
    assert captured["kwargs"]["continue_on_error"] is True


def test_post_fill_accepts_parallel_workers(monkeypatch):
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
            "SYNC_TARGET_CPA": "true",
            "CPA_URL": "http://127.0.0.1:8317",
            "CPA_KEY": "secret",
        },
    )

    def fake_start_task(command, func, params, *args, **kwargs):
        captured["command"] = command
        captured["params"] = params
        captured["args"] = args
        captured["kwargs"] = kwargs
        return {"task_id": "task-fill", "command": command, "params": params}

    monkeypatch.setattr(api, "_start_task", fake_start_task)

    result = api.post_fill(api.TaskParams(parallel_workers=3))

    assert result["command"] == "fill"
    assert captured["params"]["parallel_workers"] == 3
    assert captured["params"]["max_add"] >= 1
    assert captured["args"] == (None,)
    assert captured["kwargs"]["parallel_workers"] == 3


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


def test_resume_cpa_batch_run_starts_resume_task(tmp_path, monkeypatch):
    monkeypatch.setattr(flow_runs, "FLOW_RUNS_FILE", tmp_path / "flow_runs.json")
    flow_runs.create_flow_run("run-resume", target=100, batch_size=20, join_mode="direct")
    flow_runs.update_flow_run("run-resume", status="paused", success_count=20, attempted_count=23)
    from autoteam.cpa_batch import run_cpa_batch

    captured = {}

    def fake_start_task(command, func, params, *args, **kwargs):
        captured["command"] = command
        captured["func"] = func
        captured["params"] = params
        captured["args"] = args
        captured["kwargs"] = kwargs
        return {"task_id": "task-resume", "command": command, "params": params}

    monkeypatch.setattr(api, "_start_task", fake_start_task)

    result = api.resume_cpa_batch_run("run-resume")

    assert result["task_id"] == "task-resume"
    assert captured["command"] == "cpa-batch"
    assert captured["func"] is api._ensure_not_asyncio_loop_thread
    assert captured["params"]["run_id"] == "run-resume"
    assert captured["params"]["resume"] is True
    assert captured["args"] == (run_cpa_batch, "run-resume")
    assert captured["kwargs"] == {"resume": True, "parallel_workers": 1}


def test_resume_cpa_batch_run_reuses_parallel_workers(tmp_path, monkeypatch):
    monkeypatch.setattr(flow_runs, "FLOW_RUNS_FILE", tmp_path / "flow_runs.json")
    flow_runs.create_flow_run("run-resume", target=100, batch_size=20, join_mode="direct", parallel_workers=3)
    flow_runs.update_flow_run("run-resume", status="paused", success_count=20, attempted_count=23)
    captured = {}

    def fake_start_task(command, func, params, *args, **kwargs):
        captured["params"] = params
        captured["kwargs"] = kwargs
        return {"task_id": "task-resume", "command": command, "params": params}

    monkeypatch.setattr(api, "_start_task", fake_start_task)

    api.resume_cpa_batch_run("run-resume")

    assert captured["params"]["parallel_workers"] == 3
    assert captured["kwargs"]["parallel_workers"] == 3


def test_create_direct_account_fails_current_email_after_browser_error(tmp_path, monkeypatch):
    monkeypatch.setattr(accounts, "ACCOUNTS_FILE", tmp_path / "accounts.json")
    monkeypatch.setattr(
        cpa_batch,
        "time",
        type(
            "FakeTime",
            (),
            {
                "time": staticmethod(lambda: 1000),
                "sleep": staticmethod(
                    lambda _s: (_ for _ in ()).throw(AssertionError("same email retry should not sleep"))
                ),
            },
        )(),
    )
    monkeypatch.setattr(
        "autoteam.manager._is_email_in_team",
        lambda _email: (_ for _ in ()).throw(AssertionError("team check should not run")),
    )
    monkeypatch.setattr(cpa_batch, "save_auth_file", lambda _bundle: str(tmp_path / "codex-a-team.json"))

    calls = []

    def fake_register(_mail_client, email, _password, **kwargs):
        calls.append(email)
        raise RuntimeError("browser closed")

    monkeypatch.setattr("autoteam.manager._register_direct_once", fake_register)

    class FakeMailClient:
        provider_name = "mo_email"
        deleted = False

        def create_temp_email(self):
            return "mail-1", "retry@example.com"

        def delete_account(self, _account_id):
            self.deleted = True

    mail_client = FakeMailClient()

    with pytest.raises(cpa_batch.AccountFlowError, match="直注注册失败: browser closed"):
        cpa_batch._create_direct_account(mail_client)

    assert calls == ["retry@example.com"]
    assert mail_client.deleted is True
    saved = accounts.load_accounts()[0]
    assert saved["status"] == accounts.STATUS_PENDING
    assert saved["auth_file"] is None


def test_create_direct_account_does_not_accept_team_membership_without_session(tmp_path, monkeypatch):
    monkeypatch.setattr(accounts, "ACCOUNTS_FILE", tmp_path / "accounts.json")
    monkeypatch.setattr(
        cpa_batch.time,
        "sleep",
        lambda _s: (_ for _ in ()).throw(AssertionError("same email retry should not sleep")),
    )
    monkeypatch.setattr(
        "autoteam.manager._is_email_in_team",
        lambda _email: (_ for _ in ()).throw(AssertionError("team check should not run")),
    )

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

    with pytest.raises(cpa_batch.AccountFlowError, match="直注注册失败: ChatGPT session 提取失败: no token"):
        cpa_batch._create_direct_account(mail_client)

    assert mail_client.deleted is True


def test_run_cpa_batch_single_worker_pipelines_cpa_upload_before_return(tmp_path, monkeypatch):
    monkeypatch.setattr(flow_runs, "FLOW_RUNS_FILE", tmp_path / "flow_runs.json")
    monkeypatch.setattr(accounts, "ACCOUNTS_FILE", tmp_path / "accounts.json")

    class FakeMailClient:
        def login(self):
            pass

    monkeypatch.setattr(cpa_batch, "get_mail_client", lambda: FakeMailClient())

    created = []
    first_upload_finished = threading.Event()
    second_created_before_first_upload_finished = {"value": False}

    def fake_create_direct(_mail_client, hooks=None, batch_index=None):
        email = f"user{len(created) + 1}@example.com"
        created.append(email)
        accounts.add_account(email, "pw")
        accounts.update_account(email, status=accounts.STATUS_ACTIVE)
        if len(created) == 2:
            second_created_before_first_upload_finished["value"] = not first_upload_finished.is_set()
        return email

    def fake_verify(email, _mail_cache, **_kwargs):
        if email == "user1@example.com":
            threading.Event().wait(0.02)
            first_upload_finished.set()
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
    assert second_created_before_first_upload_finished["value"] is True
    assert first_upload_finished.is_set()
