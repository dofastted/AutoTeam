import time

import pytest

from autoteam import accounts, cpa_batch, flow_runs


class _FakeMailClient:
    provider_name = "mo_email"

    def login(self):
        return None

    def create_temp_email(self):
        return "mail-1", "new@example.com"

    def delete_account(self, _account_id):
        return None


def _fake_cpa_result(email):
    return {
        "email": email,
        "plan_type": "team",
        "auth_file": f"/tmp/codex-{email}-team.json",
        "auth_name": f"codex-{email}-team.json",
    }


def _use_tmp_flow_file(tmp_path, monkeypatch):
    monkeypatch.setattr(flow_runs, "FLOW_RUNS_FILE", tmp_path / "flow_runs.json")
    monkeypatch.setattr(accounts, "ACCOUNTS_FILE", tmp_path / "accounts.json")


def test_run_cpa_batch_groups_accounts_by_configured_batch_size(tmp_path, monkeypatch):
    _use_tmp_flow_file(tmp_path, monkeypatch)
    emails = iter(["a1@example.com", "a2@example.com", "a3@example.com"])

    monkeypatch.setattr(cpa_batch, "get_mail_client", lambda: _FakeMailClient())
    monkeypatch.setattr(cpa_batch, "update_account", lambda *args, **kwargs: None)
    monkeypatch.setattr(cpa_batch, "_create_direct_account", lambda _mail, **_kwargs: next(emails))
    monkeypatch.setattr(cpa_batch, "_verify_and_upload_cpa", lambda email, _cache, **_kwargs: _fake_cpa_result(email))

    result = cpa_batch.run_cpa_batch("run-1", target=3, batch_size=2, join_mode="direct")
    run = flow_runs.get_flow_run("run-1")

    assert result["status"] == "completed"
    assert result["attempted"] == 3
    assert result["succeeded"] == 3
    assert [item["batch_index"] for item in run["accounts"]] == [1, 1, 2]
    assert all(item["status"] == "success" for item in run["accounts"])


def test_run_cpa_batch_continues_after_account_error_until_target_is_met(tmp_path, monkeypatch):
    _use_tmp_flow_file(tmp_path, monkeypatch)
    emails = iter(["a1@example.com", "bad@example.com", "a2@example.com", "a3@example.com"])

    monkeypatch.setattr(cpa_batch, "get_mail_client", lambda: _FakeMailClient())
    monkeypatch.setattr(cpa_batch, "update_account", lambda *args, **kwargs: None)
    monkeypatch.setattr(cpa_batch, "_create_direct_account", lambda _mail, **_kwargs: next(emails))

    def fake_verify(email, _cache, **_kwargs):
        if email == "bad@example.com":
            raise RuntimeError("Codex plan=free，不是 team")
        return _fake_cpa_result(email)

    monkeypatch.setattr(cpa_batch, "_verify_and_upload_cpa", fake_verify)

    result = cpa_batch.run_cpa_batch("run-2", target=3, batch_size=2, join_mode="direct")
    run = flow_runs.get_flow_run("run-2")

    assert result["status"] == "completed"
    assert result["attempted"] == 4
    assert result["succeeded"] == 3
    assert run["failed_count"] == 1
    failed = [item for item in run["accounts"] if item["status"] == "failed"]
    assert failed[0]["email"] == "bad@example.com"
    assert failed[0]["error_level"] == "error"


def test_run_cpa_batch_retries_cpa_failure_for_same_account_before_skipping(tmp_path, monkeypatch):
    _use_tmp_flow_file(tmp_path, monkeypatch)
    attempts = {"count": 0}

    monkeypatch.setattr(cpa_batch, "get_mail_client", lambda: _FakeMailClient())
    monkeypatch.setattr(cpa_batch, "update_account", lambda *args, **kwargs: None)
    monkeypatch.setattr(cpa_batch, "_create_direct_account", lambda _mail, **_kwargs: "retry@example.com")

    def fake_verify(email, _cache, **_kwargs):
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise RuntimeError("temporary cpa error")
        return _fake_cpa_result(email)

    monkeypatch.setattr(cpa_batch, "_verify_and_upload_cpa", fake_verify)

    result = cpa_batch.run_cpa_batch("run-retry-cpa", target=1, batch_size=1, join_mode="direct")
    run = flow_runs.get_flow_run("run-retry-cpa")
    account = run["accounts"][0]

    assert result["status"] == "completed"
    assert result["attempted"] == 1
    assert result["succeeded"] == 1
    assert attempts["count"] == 3
    assert account["status"] == "success"
    assert [event["stage"] for event in account["events"]].count("cpa_retry") == 2
    assert account["events"][-1]["stage"] == "completed"


def test_run_cpa_batch_waits_before_retrying_rate_limited_cpa_auth(tmp_path, monkeypatch):
    _use_tmp_flow_file(tmp_path, monkeypatch)
    attempts = {"count": 0}
    sleeps = []

    monkeypatch.setattr(cpa_batch, "get_mail_client", lambda: _FakeMailClient())
    monkeypatch.setattr(cpa_batch, "update_account", lambda *args, **kwargs: None)
    monkeypatch.setattr(cpa_batch, "_create_direct_account", lambda _mail, **_kwargs: "rate@example.com")
    monkeypatch.setattr(cpa_batch, "RATE_LIMIT_RETRY_SECONDS", 7)
    monkeypatch.setattr(cpa_batch.time, "sleep", lambda seconds: sleeps.append(seconds))

    def fake_verify(email, _cache, **_kwargs):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("Codex 协议认证失败: HTTP 429 Rate limit exceeded")
        return _fake_cpa_result(email)

    monkeypatch.setattr(cpa_batch, "_verify_and_upload_cpa", fake_verify)

    result = cpa_batch.run_cpa_batch("run-rate-limited-cpa", target=1, batch_size=1, join_mode="direct")
    run = flow_runs.get_flow_run("run-rate-limited-cpa")
    account = run["accounts"][0]

    assert result["status"] == "completed"
    assert attempts["count"] == 2
    assert 7 in sleeps
    assert account["status"] == "success"
    retry_events = [event for event in account["events"] if event["stage"] == "cpa_retry"]
    assert "临时限流" in retry_events[0]["message"]


def test_run_cpa_batch_pauses_when_completed_success_rate_is_at_risk(tmp_path, monkeypatch):
    _use_tmp_flow_file(tmp_path, monkeypatch)
    created = []

    monkeypatch.setattr(cpa_batch, "get_mail_client", lambda: _FakeMailClient())
    monkeypatch.setattr(cpa_batch, "update_account", lambda *args, **kwargs: None)

    def fake_create_direct(_mail_client, **_kwargs):
        index = len(created) + 1
        if index == 22:
            raise cpa_batch.AccountFlowError("bad@example.com", "连续 3 次直注注册失败")
        email = f"user{index}@example.com"
        created.append(email)
        return email

    monkeypatch.setattr(cpa_batch, "_create_direct_account", fake_create_direct)
    monkeypatch.setattr(cpa_batch, "_verify_and_upload_cpa", lambda email, _cache, **_kwargs: _fake_cpa_result(email))

    result = cpa_batch.run_cpa_batch("run-rate-guard", target=100, batch_size=20, join_mode="direct")
    run = flow_runs.get_flow_run("run-rate-guard")

    assert result["status"] == "paused"
    assert result["succeeded"] == 21
    assert result["failed"] == 1
    assert run["status"] == "paused"
    assert run["fatal_error"].startswith("成功率保护暂停")


def test_run_cpa_batch_does_not_pause_success_rate_guard_on_small_sample(tmp_path, monkeypatch):
    _use_tmp_flow_file(tmp_path, monkeypatch)
    attempts = {"count": 0}

    monkeypatch.setattr(cpa_batch, "get_mail_client", lambda: _FakeMailClient())
    monkeypatch.setattr(cpa_batch, "update_account", lambda *args, **kwargs: None)

    def fake_create_direct(_mail_client, **_kwargs):
        attempts["count"] += 1
        index = attempts["count"]
        if index == 2:
            raise cpa_batch.AccountFlowError("bad2@example.com", "直注注册失败")
        email = f"user{index}@example.com"
        return email

    monkeypatch.setattr(cpa_batch, "_create_direct_account", fake_create_direct)
    monkeypatch.setattr(cpa_batch, "_verify_and_upload_cpa", lambda email, _cache, **_kwargs: _fake_cpa_result(email))

    result = cpa_batch.run_cpa_batch("run-small-sample-guard", target=2, batch_size=20, join_mode="direct")
    run = flow_runs.get_flow_run("run-small-sample-guard")

    assert result["status"] == "completed"
    assert result["succeeded"] == 2
    assert run["status"] == "completed"
    assert run["failed_count"] == 1


def test_run_cpa_batch_pauses_after_two_consecutive_register_failures(tmp_path, monkeypatch):
    _use_tmp_flow_file(tmp_path, monkeypatch)
    failures = {"count": 0}

    monkeypatch.setattr(cpa_batch, "get_mail_client", lambda: _FakeMailClient())
    monkeypatch.setattr(cpa_batch, "update_account", lambda *args, **kwargs: None)

    def fake_create_direct(_mail_client, **_kwargs):
        failures["count"] += 1
        raise cpa_batch.AccountFlowError(
            f"bad{failures['count']}@example.com",
            "连续 3 次直注注册失败",
        )

    monkeypatch.setattr(cpa_batch, "_create_direct_account", fake_create_direct)

    result = cpa_batch.run_cpa_batch("run-register-guard", target=100, batch_size=20, join_mode="direct")
    run = flow_runs.get_flow_run("run-register-guard")

    assert result["status"] == "paused"
    assert result["attempted"] == 2
    assert result["failed"] == 2
    assert failures["count"] == 2
    assert run["status"] == "paused"
    assert run["fatal_error"].startswith("连续 2 个账号注册失败")


def test_run_cpa_batch_continue_on_error_ignores_register_failure_guard(tmp_path, monkeypatch):
    _use_tmp_flow_file(tmp_path, monkeypatch)
    failures = {"count": 0}

    monkeypatch.setattr(cpa_batch, "get_mail_client", lambda: _FakeMailClient())
    monkeypatch.setattr(cpa_batch, "update_account", lambda *args, **kwargs: None)

    def fake_create_direct(_mail_client, **_kwargs):
        failures["count"] += 1
        raise cpa_batch.AccountFlowError(
            f"bad{failures['count']}@example.com",
            "直注注册失败",
        )

    monkeypatch.setattr(cpa_batch, "_create_direct_account", fake_create_direct)

    result = cpa_batch.run_cpa_batch(
        "run-continue-register",
        target=3,
        batch_size=20,
        join_mode="direct",
        continue_on_error=True,
    )
    run = flow_runs.get_flow_run("run-continue-register")

    assert result["status"] == "partial"
    assert result["attempted"] == 6
    assert failures["count"] == 6
    assert run["status"] == "partial"
    assert run["failed_count"] == 6
    assert run["continue_on_error"] is True


def test_run_cpa_batch_skips_phone_verification_and_continues(tmp_path, monkeypatch):
    _use_tmp_flow_file(tmp_path, monkeypatch)
    created = []
    attempts = {"count": 0}

    monkeypatch.setattr(cpa_batch, "get_mail_client", lambda: _FakeMailClient())
    monkeypatch.setattr(cpa_batch, "_verify_and_upload_cpa", lambda email, _cache, **_kwargs: _fake_cpa_result(email))

    def fake_create_direct(mail_client, **kwargs):
        attempts["count"] += 1
        index = attempts["count"]
        if index == 1:
            accounts.add_account(
                "phone@example.com",
                "pw",
                mail_provider=getattr(mail_client, "provider_name", ""),
                mail_account_id="mail-phone",
            )
            accounts.update_account(
                "phone@example.com",
                flow_status="failed",
                flow_stage="register",
                flow_error_level="warn",
                flow_error_message="OpenAI 风控要求手机号验证, 跳过该账号",
            )
            hooks = kwargs.get("hooks")
            if hooks:
                hooks.account_event(
                    "phone@example.com",
                    batch_index=kwargs.get("batch_index"),
                    stage="register",
                    message="OpenAI 风控要求手机号验证, 跳过该账号",
                    error_level="warn",
                    status="failed",
                    finished_at=time.time(),
                )
            raise cpa_batch.AccountPhoneVerificationSkipped(
                "phone@example.com",
                "OpenAI 风控要求手机号验证, 跳过该账号",
            )
        email = f"ok-{index}@example.com"
        created.append(email)
        return email

    monkeypatch.setattr(cpa_batch, "_create_direct_account", fake_create_direct)

    result = cpa_batch.run_cpa_batch(
        "run-phone-skip",
        target=1,
        batch_size=1,
        join_mode="direct",
        continue_on_error=True,
    )
    run = flow_runs.get_flow_run("run-phone-skip")
    phone_record = next(item for item in run["accounts"] if item["email"] == "phone@example.com")

    assert result["status"] == "completed"
    assert result["attempted"] == 2
    assert result["succeeded"] == 1
    assert run["failed_count"] == 1
    assert phone_record["status"] == "failed"
    assert phone_record["stage"] == "register"
    assert phone_record["error_level"] == "warn"
    assert phone_record["error_message"] == "OpenAI 风控要求手机号验证, 跳过该账号"
    assert created == ["ok-2@example.com"]


def test_run_cpa_batch_resume_continues_existing_run(tmp_path, monkeypatch):
    _use_tmp_flow_file(tmp_path, monkeypatch)
    flow_runs.create_flow_run("run-resume", target=2, batch_size=1, join_mode="direct")
    flow_runs.update_flow_run(
        "run-resume",
        status="paused",
        success_count=1,
        failed_count=0,
        attempted_count=1,
        finished_at=1000,
        pause_requested=True,
    )

    monkeypatch.setattr(cpa_batch, "get_mail_client", lambda: _FakeMailClient())
    monkeypatch.setattr(cpa_batch, "update_account", lambda *args, **kwargs: None)
    monkeypatch.setattr(cpa_batch, "_create_direct_account", lambda _mail, **_kwargs: "resume@example.com")
    monkeypatch.setattr(cpa_batch, "_verify_and_upload_cpa", lambda email, _cache, **_kwargs: _fake_cpa_result(email))

    result = cpa_batch.run_cpa_batch("run-resume", resume=True)
    run = flow_runs.get_flow_run("run-resume")

    assert result["status"] == "completed"
    assert result["attempted"] == 2
    assert result["succeeded"] == 2
    assert run["success_count"] == 2


def test_run_cpa_batch_resume_legacy_run_without_parallel_workers(tmp_path, monkeypatch):
    _use_tmp_flow_file(tmp_path, monkeypatch)
    flow_runs.create_flow_run("run-resume-legacy", target=2, batch_size=1, join_mode="direct")
    run = flow_runs.get_flow_run("run-resume-legacy")
    run.pop("parallel_workers", None)
    flow_runs.save_flow_runs([run])
    flow_runs.update_flow_run(
        "run-resume-legacy",
        status="paused",
        success_count=1,
        failed_count=0,
        attempted_count=1,
        finished_at=1000,
        pause_requested=True,
    )

    monkeypatch.setattr(cpa_batch, "get_mail_client", lambda: _FakeMailClient())
    monkeypatch.setattr(cpa_batch, "update_account", lambda *args, **kwargs: None)
    monkeypatch.setattr(cpa_batch, "_create_direct_account", lambda _mail, **_kwargs: "legacy@example.com")
    monkeypatch.setattr(cpa_batch, "_verify_and_upload_cpa", lambda email, _cache, **_kwargs: _fake_cpa_result(email))

    result = cpa_batch.run_cpa_batch("run-resume-legacy", resume=True)
    updated = flow_runs.get_flow_run("run-resume-legacy")

    assert result["status"] == "completed"
    assert result["attempted"] == 2
    assert result["succeeded"] == 2
    assert updated["success_count"] == 2


def test_run_cpa_batch_resume_failed_run_can_continue(tmp_path, monkeypatch):
    _use_tmp_flow_file(tmp_path, monkeypatch)
    flow_runs.create_flow_run("run-resume-failed", target=2, batch_size=1, join_mode="direct")
    flow_runs.update_flow_run(
        "run-resume-failed",
        status="failed",
        success_count=1,
        failed_count=1,
        attempted_count=2,
        finished_at=1000,
        pause_requested=False,
    )

    monkeypatch.setattr(cpa_batch, "get_mail_client", lambda: _FakeMailClient())
    monkeypatch.setattr(cpa_batch, "update_account", lambda *args, **kwargs: None)
    monkeypatch.setattr(cpa_batch, "_create_direct_account", lambda _mail, **_kwargs: "failed-resume@example.com")
    monkeypatch.setattr(cpa_batch, "_verify_and_upload_cpa", lambda email, _cache, **_kwargs: _fake_cpa_result(email))

    result = cpa_batch.run_cpa_batch("run-resume-failed", resume=True)
    updated = flow_runs.get_flow_run("run-resume-failed")

    assert result["status"] == "completed"
    assert result["attempted"] == 3
    assert result["succeeded"] == 2
    assert updated["status"] == "completed"
    assert updated["success_count"] == 2


def test_direct_single_worker_waits_for_cpa_result_before_next_account(tmp_path, monkeypatch):
    _use_tmp_flow_file(tmp_path, monkeypatch)
    emails = iter(["a1@example.com", "a2@example.com"])
    call_order = []

    monkeypatch.setattr(cpa_batch, "get_mail_client", lambda: _FakeMailClient())
    monkeypatch.setattr(cpa_batch, "update_account", lambda *args, **kwargs: None)

    def fake_create_direct(_mail_client, **_kwargs):
        email = next(emails)
        call_order.append(f"create:{email}")
        return email

    def fake_verify(email, _cache, **_kwargs):
        call_order.append(f"cpa:{email}")
        time.sleep(0.02)
        return _fake_cpa_result(email)

    monkeypatch.setattr(cpa_batch, "_create_direct_account", fake_create_direct)
    monkeypatch.setattr(cpa_batch, "_verify_and_upload_cpa", fake_verify)
    monkeypatch.setattr(cpa_batch, "is_sync_target_enabled", lambda target: target == cpa_batch.SYNC_TARGET_SUB2API)
    monkeypatch.setattr(
        "autoteam.sub2api_sync.sync_account_to_sub2api",
        lambda email: call_order.append(f"sub2api:{email}")
        or {
            "created": 0,
            "updated": 1,
            "deleted": 0,
            "remote_duplicates_deleted": 0,
            "existing_email_matches": 0,
            "warnings": [],
        },
    )

    result = cpa_batch.run_cpa_batch(
        "run-direct-sequential",
        target=2,
        batch_size=2,
        join_mode="direct",
        parallel_workers=1,
    )

    assert result["status"] == "completed"
    assert result["succeeded"] == 2
    assert call_order == [
        "create:a1@example.com",
        "cpa:a1@example.com",
        "sub2api:a1@example.com",
        "create:a2@example.com",
        "cpa:a2@example.com",
        "sub2api:a2@example.com",
    ]


def test_direct_single_worker_does_not_create_next_account_while_first_is_pending(tmp_path, monkeypatch):
    _use_tmp_flow_file(tmp_path, monkeypatch)
    emails = iter(["a1@example.com", "a2@example.com"])
    call_order = []
    state = {"count": 0}

    monkeypatch.setattr(cpa_batch, "get_mail_client", lambda: _FakeMailClient())
    monkeypatch.setattr(cpa_batch, "update_account", lambda *args, **kwargs: None)

    def fake_create_direct(_mail_client, **_kwargs):
        email = next(emails)
        call_order.append(f"create:{email}")
        return email

    def fake_verify(email, _cache, **_kwargs):
        state["count"] += 1
        call_order.append(f"cpa:{email}:{state['count']}")
        if state["count"] == 1:
            raise RuntimeError("Codex 协议认证失败: HTTP 429 Rate limit exceeded")
        return _fake_cpa_result(email)

    monkeypatch.setattr(cpa_batch, "_create_direct_account", fake_create_direct)
    monkeypatch.setattr(cpa_batch, "_verify_and_upload_cpa", fake_verify)
    monkeypatch.setattr(cpa_batch, "RATE_LIMIT_RETRY_SECONDS", 0)

    result = cpa_batch.run_cpa_batch(
        "run-direct-pending",
        target=1,
        batch_size=2,
        join_mode="direct",
        parallel_workers=1,
    )

    assert result["status"] == "completed"
    assert result["succeeded"] == 1
    assert call_order[:2] == ["create:a1@example.com", "cpa:a1@example.com:1"]
    assert "create:a2@example.com" not in call_order[:2]


def test_run_cpa_batch_resume_preserves_parallel_workers(tmp_path, monkeypatch):
    _use_tmp_flow_file(tmp_path, monkeypatch)
    flow_runs.create_flow_run("run-resume-parallel", target=3, batch_size=20, join_mode="direct", parallel_workers=3)
    flow_runs.update_flow_run(
        "run-resume-parallel",
        status="paused",
        success_count=0,
        failed_count=0,
        attempted_count=0,
        finished_at=1000,
        pause_requested=True,
    )
    seen = {}

    def fake_create_parallel(total, *, parallel_workers, hooks, batch_index):
        seen["parallel_workers"] = parallel_workers
        return {
            "attempted": 0,
            "succeeded": 0,
            "failed": 0,
            "emails": [],
            "worker_reports": [],
            "parallel_workers": parallel_workers,
        }

    monkeypatch.setattr(cpa_batch, "_create_direct_accounts_parallel", fake_create_parallel)

    result = cpa_batch.run_cpa_batch("run-resume-parallel", resume=True)

    assert result["status"] == "paused"
    assert seen["parallel_workers"] == 3


def test_run_cpa_batch_resume_marks_lingering_running_accounts_failed(tmp_path, monkeypatch):
    _use_tmp_flow_file(tmp_path, monkeypatch)
    flow_runs.create_flow_run("run-resume-clean", target=2, batch_size=1, join_mode="direct")
    flow_runs.append_flow_event(
        "run-resume-clean",
        "stale@example.com",
        batch_index=1,
        worker_index=1,
        stage="register",
        message="旧窗口仍在运行",
        status="running",
    )
    flow_runs.update_flow_run(
        "run-resume-clean",
        status="paused",
        success_count=0,
        failed_count=0,
        attempted_count=1,
        finished_at=1000,
        pause_requested=True,
    )

    monkeypatch.setattr(cpa_batch, "get_mail_client", lambda: _FakeMailClient())
    monkeypatch.setattr(cpa_batch, "update_account", lambda *args, **kwargs: None)
    monkeypatch.setattr(cpa_batch, "_create_direct_account", lambda _mail, **_kwargs: "resume-clean@example.com")
    monkeypatch.setattr(cpa_batch, "_verify_and_upload_cpa", lambda email, _cache, **_kwargs: _fake_cpa_result(email))

    result = cpa_batch.run_cpa_batch("run-resume-clean", resume=True)
    run = flow_runs.get_flow_run("run-resume-clean")
    stale = next(item for item in run["accounts"] if item["email"] == "stale@example.com")

    assert result["status"] == "completed"
    assert result["attempted"] == 3
    assert result["succeeded"] == 2
    assert stale["status"] == "failed"
    assert "恢复前清理遗留运行记录" in stale["events"][-1]["message"]


def test_run_cpa_batch_parallel_direct_uses_cpa_batch_session_first_helper(tmp_path, monkeypatch):
    _use_tmp_flow_file(tmp_path, monkeypatch)

    monkeypatch.setattr(
        cpa_batch,
        "get_mail_client",
        lambda: (_ for _ in ()).throw(AssertionError("parallel direct should create mail clients inside workers")),
    )
    monkeypatch.setattr(
        cpa_batch,
        "ChatGPTTeamAPI",
        lambda: (_ for _ in ()).throw(AssertionError("direct batch should not start main account browser")),
    )
    monkeypatch.setattr(cpa_batch, "update_account", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "autoteam.manager._create_new_accounts_parallel",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("manager parallel helper should not run")),
    )

    def fake_create_parallel(total, *, parallel_workers, hooks, batch_index):
        assert total == 3
        assert parallel_workers == 3
        assert hooks.run_id == "run-parallel-direct"
        assert batch_index == 1
        for index, email in enumerate(["w1@example.com", "w2@example.com", "w3@example.com"], start=1):
            accounts.add_account(email, "pw")
            hooks.account_event(
                email,
                batch_index=batch_index,
                worker_index=index,
                stage="session_auth",
                message="session saved",
                status="running",
            )
        return {
            "attempted": 3,
            "succeeded": 3,
            "failed": 0,
            "emails": [
                {"email": "w1@example.com", "worker_index": 1},
                {"email": "w2@example.com", "worker_index": 2},
                {"email": "w3@example.com", "worker_index": 3},
            ],
            "worker_reports": [],
            "parallel_workers": 3,
        }

    monkeypatch.setattr(cpa_batch, "_create_direct_accounts_parallel", fake_create_parallel)
    monkeypatch.setattr(cpa_batch, "_verify_and_upload_cpa", lambda email, _cache, **_kwargs: _fake_cpa_result(email))

    result = cpa_batch.run_cpa_batch(
        "run-parallel-direct",
        target=3,
        batch_size=20,
        join_mode="direct",
        parallel_workers=3,
    )
    run = flow_runs.get_flow_run("run-parallel-direct")

    assert result["status"] == "completed"
    assert result["attempted"] == 3
    assert result["succeeded"] == 3
    assert sorted(item["worker_index"] for item in run["accounts"]) == [1, 2, 3]
    assert all(item["status"] == "success" for item in run["accounts"])


def test_parallel_direct_runs_protocol_auth_without_browser_oauth_deferral(tmp_path, monkeypatch):
    _use_tmp_flow_file(tmp_path, monkeypatch)
    accounts.add_account("w1@example.com", "pw")
    accounts.update_account(
        "w1@example.com",
        status=accounts.STATUS_ACTIVE,
        session_auth_file=str(tmp_path / "codex-w1@example.com-team-session.json"),
        plan_type="team",
    )
    accounts.add_account("w2@example.com", "pw")
    accounts.update_account(
        "w2@example.com",
        status=accounts.STATUS_ACTIVE,
        session_auth_file=str(tmp_path / "codex-w2@example.com-team-session.json"),
        plan_type="team",
    )
    verify_calls = []

    def fake_create_parallel(total, *, parallel_workers, hooks, batch_index):
        assert total == 2
        time.sleep(0.05)
        return {
            "attempted": 2,
            "succeeded": 2,
            "failed": 0,
            "emails": [
                {"email": "w1@example.com", "worker_index": 1},
                {"email": "w2@example.com", "worker_index": 2},
            ],
            "worker_reports": [],
            "parallel_workers": parallel_workers,
        }

    def fake_verify(email, _cache, **kwargs):
        verify_calls.append((email, kwargs))
        return _fake_cpa_result(email)

    monkeypatch.setattr(cpa_batch, "time", time)
    monkeypatch.setattr(cpa_batch, "_create_direct_accounts_parallel", fake_create_parallel)
    monkeypatch.setattr(cpa_batch, "_verify_and_upload_cpa", fake_verify)
    monkeypatch.setattr(cpa_batch, "update_account", lambda *args, **kwargs: None)

    result = cpa_batch.run_cpa_batch(
        "run-defer-oauth",
        target=2,
        batch_size=20,
        join_mode="direct",
        parallel_workers=2,
    )

    assert result["status"] == "completed"
    assert [item[0] for item in verify_calls] == ["w1@example.com", "w2@example.com"]
    assert all("allow_browser_oauth" not in item[1] for item in verify_calls)


def test_flow_runs_keep_recent_records_and_account_events(tmp_path, monkeypatch):
    _use_tmp_flow_file(tmp_path, monkeypatch)

    flow_runs.create_flow_run("run-3", target=100, batch_size=20, join_mode="direct")
    flow_runs.append_flow_event(
        "run-3",
        "user@example.com",
        batch_index=1,
        stage="cpa_auth",
        message="CPA JSON 已可用",
        status="success",
        plan_type="team",
        cpa_uploaded=True,
    )

    loaded = flow_runs.get_flow_run("run-3")

    assert loaded["success_count"] == 1
    assert loaded["accounts"][0]["email"] == "user@example.com"
    assert loaded["accounts"][0]["events"][0]["stage"] == "cpa_auth"


def test_run_cpa_batch_stops_when_pause_is_requested(tmp_path, monkeypatch):
    _use_tmp_flow_file(tmp_path, monkeypatch)
    emails = iter(["a1@example.com", "a2@example.com"])
    seen = []

    monkeypatch.setattr(cpa_batch, "get_mail_client", lambda: _FakeMailClient())
    monkeypatch.setattr(cpa_batch, "update_account", lambda *args, **kwargs: None)
    monkeypatch.setattr(cpa_batch, "_create_direct_account", lambda _mail, **_kwargs: next(emails))

    def fake_verify(email, _cache, **_kwargs):
        seen.append(email)
        flow_runs.request_flow_pause("run-4")
        return _fake_cpa_result(email)

    monkeypatch.setattr(cpa_batch, "_verify_and_upload_cpa", fake_verify)

    result = cpa_batch.run_cpa_batch("run-4", target=2, batch_size=2, join_mode="direct")
    run = flow_runs.get_flow_run("run-4")

    assert result["status"] == "paused"
    assert seen == ["a1@example.com"]
    assert run["status"] == "paused"


def test_cpa_upload_success_syncs_sub2api_when_enabled(tmp_path, monkeypatch):
    _use_tmp_flow_file(tmp_path, monkeypatch)
    synced = []

    monkeypatch.setattr(cpa_batch, "get_mail_client", lambda: _FakeMailClient())
    monkeypatch.setattr(cpa_batch, "update_account", lambda *args, **kwargs: None)
    monkeypatch.setattr(cpa_batch, "_create_direct_account", lambda _mail, **_kwargs: "sync@example.com")
    monkeypatch.setattr(cpa_batch, "is_sync_target_enabled", lambda target: target == cpa_batch.SYNC_TARGET_SUB2API)
    monkeypatch.setattr(
        "autoteam.sub2api_sync.sync_account_to_sub2api",
        lambda email: (
            synced.append(email)
            or {
                "created": 0,
                "updated": 1,
                "deleted": 0,
                "remote_duplicates_deleted": 0,
                "existing_email_matches": 0,
                "warnings": [],
            }
        ),
    )
    monkeypatch.setattr(cpa_batch, "_verify_and_upload_cpa", lambda email, _cache, **_kwargs: _fake_cpa_result(email))

    result = cpa_batch.run_cpa_batch("run-sub2api-after-cpa", target=1, batch_size=1, join_mode="direct")
    run = flow_runs.get_flow_run("run-sub2api-after-cpa")

    assert result["status"] == "completed"
    assert synced == ["sync@example.com"]
    assert any(event["stage"] == "sub2api_sync" for event in run["accounts"][0]["events"])
    assert run["accounts"][0]["sub2api_synced"] is True


def test_direct_account_records_email_before_register_failure(tmp_path, monkeypatch):
    _use_tmp_flow_file(tmp_path, monkeypatch)
    flow_runs.create_flow_run("run-direct", target=1, batch_size=20, join_mode="direct")

    monkeypatch.setattr("autoteam.manager._register_direct_once", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        "autoteam.manager._is_email_in_team",
        lambda _email: (_ for _ in ()).throw(AssertionError("team check should not run")),
    )
    monkeypatch.setattr(
        cpa_batch.time,
        "sleep",
        lambda _seconds: (_ for _ in ()).throw(AssertionError("same email retry sleep should not run")),
    )

    hooks = cpa_batch.CpaBatchHooks("run-direct")
    try:
        cpa_batch._create_direct_account(_FakeMailClient(), hooks=hooks, batch_index=1)
    except cpa_batch.AccountFlowError as exc:
        assert exc.email == "new@example.com"
        assert str(exc) == "直注注册未完成"
    else:
        raise AssertionError("expected AccountFlowError")

    run = flow_runs.get_flow_run("run-direct")
    assert run["accounts"][0]["email"] == "new@example.com"
    assert run["accounts"][0]["stage"] == "register"
    assert run["accounts"][0]["status"] == "failed"
    assert accounts.load_accounts()[0]["email"] == "new@example.com"


def test_direct_account_saves_chatgpt_session_auth(tmp_path, monkeypatch):
    _use_tmp_flow_file(tmp_path, monkeypatch)
    flow_runs.create_flow_run("run-session", target=1, batch_size=20, join_mode="direct")
    auth_path = tmp_path / "codex-new@example.com-team-acc.json"

    def fake_register(_mail_client, email, _password, mail_account_id=None, session_bundle_callback=None):
        assert mail_account_id == "mail-1"
        session_bundle_callback(
            {
                "email": email,
                "account_id": "acc-1",
                "plan_type": "team",
                "access_token": "access-token",
                "id_token": "id-token",
                "refresh_token": "",
                "expired": 2000000000,
                "credential_source": "chatgpt_session",
            }
        )
        return True

    monkeypatch.setattr("autoteam.manager._register_direct_once", fake_register)
    monkeypatch.setattr(
        "autoteam.manager._is_email_in_team",
        lambda _email: (_ for _ in ()).throw(AssertionError("team check should not run")),
    )
    monkeypatch.setattr(cpa_batch, "save_auth_file", lambda _bundle, **_kwargs: str(auth_path))

    hooks = cpa_batch.CpaBatchHooks("run-session")
    email = cpa_batch._create_direct_account(_FakeMailClient(), hooks=hooks, batch_index=1)

    assert email == "new@example.com"
    acc = accounts.load_accounts()[0]
    assert acc["session_auth_file"] == str(auth_path)
    assert acc.get("auth_file") is None
    assert acc["registration_status"] == accounts.REGISTRATION_STATUS_SUCCESS
    assert acc["plan_type"] == "team"
    run = flow_runs.get_flow_run("run-session")
    assert any(event["stage"] == "session_auth" for event in run["accounts"][0]["events"])


def test_direct_account_saves_registration_window_oauth_callback(tmp_path, monkeypatch):
    _use_tmp_flow_file(tmp_path, monkeypatch)
    flow_runs.create_flow_run("run-oauth-window", target=1, batch_size=20, join_mode="direct")
    session_path = tmp_path / "codex-new@example.com-team-session.json"
    oauth_path = tmp_path / "codex-new@example.com-team-oauth.json"

    def fake_register(
        _mail_client,
        email,
        _password,
        mail_account_id=None,
        session_bundle_callback=None,
        oauth_bundle_callback=None,
        **_kwargs,
    ):
        assert mail_account_id == "mail-1"
        session_bundle_callback(
            {
                "email": email,
                "account_id": "acc-1",
                "plan_type": "team",
                "access_token": "session-access",
                "id_token": "session-token",
                "refresh_token": "",
                "expired": 2000000000,
                "credential_source": "chatgpt_session",
            }
        )
        oauth_bundle_callback(
            {
                "email": email,
                "account_id": "acc-1",
                "plan_type": "team",
                "access_token": "oauth-access",
                "refresh_token": "oauth-refresh",
                "id_token": "oauth-id",
                "expired": 2000000000,
                "credential_source": "oauth",
            }
        )
        return True

    saved_sources = []

    def fake_save(bundle, source=None):
        saved_sources.append(source)
        if source == "session":
            assert bundle.get("credential_source") == "chatgpt_session"
            return str(session_path)
        if source == "oauth":
            assert bundle.get("refresh_token") == "oauth-refresh"
            return str(oauth_path)
        raise AssertionError(f"unexpected source {source}")

    monkeypatch.setattr("autoteam.manager._register_direct_once", fake_register)
    monkeypatch.setattr(cpa_batch, "save_auth_file", fake_save)

    hooks = cpa_batch.CpaBatchHooks("run-oauth-window")
    email = cpa_batch._create_direct_account(_FakeMailClient(), hooks=hooks, batch_index=1)

    latest = accounts.find_account(accounts.load_accounts(), email)
    assert latest["session_auth_file"] == str(session_path)
    assert latest["auth_file"] == str(oauth_path)
    assert latest["rt_auth_file"] == str(oauth_path)
    assert latest["registration_status"] == accounts.REGISTRATION_STATUS_SUCCESS
    assert saved_sources == ["session", "oauth"]
    run = flow_runs.get_flow_run("run-oauth-window")
    assert any(event["stage"] == "oauth" for event in run["accounts"][0]["events"])


def test_direct_account_rotates_proxy_and_recreates_email_on_ip_block(tmp_path, monkeypatch):
    _use_tmp_flow_file(tmp_path, monkeypatch)
    flow_runs.create_flow_run("run-ip-block", target=1, batch_size=20, join_mode="direct")
    auth_path = tmp_path / "codex-ok@example.com-team-session.json"
    rotated = []
    deleted = []
    register_calls = []
    proxies = iter(["http://proxy-a:8080", "http://proxy-b:8080"])

    class FakeMailClient(_FakeMailClient):
        def __init__(self):
            self.created = []
            self._emails = iter(
                [
                    ("mail-blocked", "blocked@example.com"),
                    ("mail-ok", "ok@example.com"),
                ]
            )

        def create_temp_email(self):
            account = next(self._emails)
            self.created.append(account[1])
            return account

        def delete_account(self, account_id):
            deleted.append(account_id)

    mail_client = FakeMailClient()

    def fake_rotate_task_proxy():
        value = next(proxies)
        rotated.append(value)
        return value

    def fake_register(_mail_client, email, _password, mail_account_id=None, session_bundle_callback=None, **_kwargs):
        register_calls.append((email, mail_account_id))
        if email == "blocked@example.com":
            raise cpa_batch.OpenAiCreateAccountBlockedError("Failed to create account")
        session_bundle_callback(
            {
                "email": email,
                "account_id": "acc-ok",
                "plan_type": "team",
                "access_token": "access-token",
                "id_token": "id-token",
                "refresh_token": "",
                "expired": 2000000000,
                "credential_source": "chatgpt_session",
            }
        )
        return True

    monkeypatch.setattr(cpa_batch, "_configured_proxy_pool_size", lambda: 2)
    monkeypatch.setattr(cpa_batch.outbound_proxy, "rotate_task_proxy", fake_rotate_task_proxy)
    monkeypatch.setattr(cpa_batch.outbound_proxy, "current_proxy_url", lambda: rotated[-1])
    monkeypatch.setattr("autoteam.manager._register_direct_once", fake_register)
    monkeypatch.setattr(cpa_batch, "save_auth_file", lambda _bundle, **_kwargs: str(auth_path))

    hooks = cpa_batch.CpaBatchHooks("run-ip-block")
    email = cpa_batch._create_direct_account(mail_client, hooks=hooks, batch_index=1, worker_index=1)

    assert email == "ok@example.com"
    assert mail_client.created == ["blocked@example.com", "ok@example.com"]
    assert register_calls == [("blocked@example.com", "mail-blocked"), ("ok@example.com", "mail-ok")]
    assert deleted == ["mail-blocked"]
    assert rotated == ["http://proxy-a:8080", "http://proxy-b:8080"]
    run = flow_runs.get_flow_run("run-ip-block")
    blocked = next(item for item in run["accounts"] if item["email"] == "blocked@example.com")
    ok = next(item for item in run["accounts"] if item["email"] == "ok@example.com")
    assert blocked["status"] == "failed"
    assert blocked["error_level"] == "warn"
    assert blocked["stage"] == "register"
    assert ok["status"] == "running"
    assert ok["stage"] == "session_auth"
    latest = accounts.find_account(accounts.load_accounts(), "ok@example.com")
    assert latest["status"] == accounts.STATUS_ACTIVE
    assert latest["flow_stage"] == "team_joined"


def test_direct_account_about_you_timeout_skips_without_ip_rotation(tmp_path, monkeypatch):
    _use_tmp_flow_file(tmp_path, monkeypatch)
    flow_runs.create_flow_run("run-about-timeout", target=1, batch_size=20, join_mode="direct")
    deleted = []
    rotated = []
    register_calls = []

    class FakeMailClient(_FakeMailClient):
        def delete_account(self, account_id):
            deleted.append(account_id)

    def fake_rotate_task_proxy():
        value = f"http://proxy-{len(rotated) + 1}:8080"
        rotated.append(value)
        return value

    def fake_register(_mail_client, email, _password, **_kwargs):
        register_calls.append(email)
        raise cpa_batch.OpenAiCreateAccountBlockedError(
            "about-you 超时 / 风控页加载失败",
            email=email,
            reason="about_you_timeout",
        )

    monkeypatch.setattr(cpa_batch, "_configured_proxy_pool_size", lambda: 4)
    monkeypatch.setattr(cpa_batch.outbound_proxy, "rotate_task_proxy", fake_rotate_task_proxy)
    monkeypatch.setattr(cpa_batch.outbound_proxy, "current_proxy_url", lambda: rotated[-1] if rotated else "direct")
    monkeypatch.setattr("autoteam.manager._register_direct_once", fake_register)

    hooks = cpa_batch.CpaBatchHooks("run-about-timeout")
    with pytest.raises(cpa_batch.AccountFlowError) as exc_info:
        cpa_batch._create_direct_account(FakeMailClient(), hooks=hooks, batch_index=1, worker_index=1)

    assert exc_info.value.email == "new@example.com"
    assert "about-you 超时" in str(exc_info.value)
    assert register_calls == ["new@example.com"]
    assert deleted == ["mail-1"]
    assert rotated == ["http://proxy-1:8080"]
    run = flow_runs.get_flow_run("run-about-timeout")
    account = run["accounts"][0]
    assert account["status"] == "failed"
    assert account["stage"] == "register"
    assert account["error_level"] == "warn"


def test_direct_account_fails_when_session_bundle_missing(tmp_path, monkeypatch):
    _use_tmp_flow_file(tmp_path, monkeypatch)
    flow_runs.create_flow_run("run-missing-session", target=1, batch_size=20, join_mode="direct")
    deleted = []

    class FakeMailClient(_FakeMailClient):
        def delete_account(self, account_id):
            deleted.append(account_id)

    monkeypatch.setattr("autoteam.manager._register_direct_once", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(cpa_batch, "save_auth_file", lambda _bundle, **_kwargs: (_ for _ in ()).throw(AssertionError()))

    hooks = cpa_batch.CpaBatchHooks("run-missing-session")
    try:
        cpa_batch._create_direct_account(FakeMailClient(), hooks=hooks, batch_index=1, worker_index=2)
    except cpa_batch.AccountFlowError as exc:
        assert exc.email == "new@example.com"
        assert str(exc) == "未获取到 ChatGPT session CPA 凭证"
    else:
        raise AssertionError("expected AccountFlowError")

    run = flow_runs.get_flow_run("run-missing-session")
    account = run["accounts"][0]
    assert account["status"] == "failed"
    assert account["stage"] == "session_auth"
    assert account["worker_index"] == 2
    assert deleted == ["mail-1"]


def test_direct_account_skips_marked_unavailable_email_and_uses_new_email(tmp_path, monkeypatch):
    _use_tmp_flow_file(tmp_path, monkeypatch)
    flow_runs.create_flow_run("run-skip-marked", target=1, batch_size=20, join_mode="direct")

    accounts.add_account("skip@example.com", "pw")
    accounts.update_account(
        "skip@example.com",
        status=accounts.STATUS_UNAVAILABLE,
        unavailable_reason="account_deactivated",
        sync_disabled=True,
    )

    deleted = []
    register_calls = []

    class FakeMailClient(_FakeMailClient):
        def __init__(self):
            self._emails = iter(
                [
                    ("mail-skip", "skip@example.com"),
                    ("mail-new", "fresh@example.com"),
                ]
            )

        def create_temp_email(self):
            return next(self._emails)

        def delete_account(self, account_id):
            deleted.append(account_id)

    def fake_register(_mail_client, email, _password, mail_account_id=None, session_bundle_callback=None):
        register_calls.append((email, mail_account_id))
        session_bundle_callback(
            {
                "email": email,
                "account_id": "acc-2",
                "plan_type": "team",
                "access_token": "access-token",
                "id_token": "id-token",
                "refresh_token": "",
                "expired": 2000000000,
                "credential_source": "chatgpt_session",
            }
        )
        return True

    auth_path = tmp_path / "codex-fresh@example.com-team-acc.json"
    monkeypatch.setattr("autoteam.manager._register_direct_once", fake_register)
    monkeypatch.setattr(cpa_batch, "save_auth_file", lambda _bundle, **_kwargs: str(auth_path))

    hooks = cpa_batch.CpaBatchHooks("run-skip-marked")
    email = cpa_batch._create_direct_account(FakeMailClient(), hooks=hooks, batch_index=1, worker_index=1)

    assert email == "fresh@example.com"
    assert register_calls == [("fresh@example.com", "mail-new")]
    assert deleted == ["mail-skip"]
    latest = accounts.find_account(accounts.load_accounts(), "fresh@example.com")
    assert latest is not None
    assert latest["session_auth_file"] == str(auth_path)
    run = flow_runs.get_flow_run("run-skip-marked")
    skipped = next(item for item in run["accounts"] if item["email"] == "skip@example.com")
    fresh = next(item for item in run["accounts"] if item["email"] == "fresh@example.com")
    assert skipped["stage"] == "email_skipped"
    assert skipped["status"] == "failed"
    assert fresh["worker_index"] == 1


def test_cpa_verify_gets_oauth_rt_when_session_auth_is_not_uploadable(tmp_path, monkeypatch):
    _use_tmp_flow_file(tmp_path, monkeypatch)
    oauth_path = tmp_path / "codex-new@example.com-team-acc-oauth.json"
    accounts.add_account("new@example.com", "pw")
    accounts.update_account("new@example.com", status=accounts.STATUS_ACTIVE, session_auth_file=str(tmp_path / "session.json"))
    oauth_calls = []

    class FakeMailClient:
        def login(self):
            return None

    monkeypatch.setattr(cpa_batch, "_ensure_mail_client_for_account", lambda _acc, _cache: FakeMailClient())
    oauth_path.write_text('{"access_token":"token-ok","refresh_token":"rt-1"}', encoding="utf-8")
    monkeypatch.setattr(
        "autoteam.account_oauth.run_account_oauth_login",
        lambda email, **kwargs: oauth_calls.append((email, kwargs))
        or accounts.update_account(email, auth_file=str(oauth_path), rt_auth_file=str(oauth_path), plan_type="team")
        or {
            "email": email,
            "plan": "team",
            "plan_type": "team",
            "auth_file": str(oauth_path),
            "rt_auth_file": str(oauth_path),
            "cpa_archive_file": "",
        },
    )
    monkeypatch.setattr(cpa_batch, "check_codex_quota", lambda _token: ("ok", {"primary_pct": 0}))
    monkeypatch.setattr(cpa_batch, "upload_to_cpa", lambda _path: True)
    monkeypatch.setattr(cpa_batch, "archive_account_auth_file", lambda _email, _path: "")

    result = cpa_batch._verify_and_upload_cpa("new@example.com", {})

    assert oauth_calls
    assert result["auth_file"] == str(oauth_path)
    latest = accounts.find_account(accounts.load_accounts(), "new@example.com")
    assert latest["rt_auth_file"] == str(oauth_path)
    assert latest["auth_file"] == str(oauth_path)
    assert latest["cpa_status"] == accounts.CPA_STATUS_SUCCESS
    assert latest["usage_status"] == accounts.USAGE_INVENTORY


def test_cpa_verify_uses_account_oauth_login_interface(tmp_path, monkeypatch):
    _use_tmp_flow_file(tmp_path, monkeypatch)
    oauth_path = tmp_path / "codex-new@example.com-team-acc-oauth.json"
    oauth_path.write_text('{"access_token":"token-ok","refresh_token":"rt-1"}', encoding="utf-8")
    accounts.add_account("new@example.com", "pw")
    accounts.update_account("new@example.com", status=accounts.STATUS_ACTIVE, session_auth_file=str(tmp_path / "session.json"))
    calls = []

    class FakeMailClient:
        def login(self):
            return None

    monkeypatch.setattr(cpa_batch, "_ensure_mail_client_for_account", lambda _acc, _cache: FakeMailClient())
    monkeypatch.setattr(
        "autoteam.account_oauth.run_account_oauth_login",
        lambda email, **kwargs: calls.append((email, kwargs))
        or {
            "email": email,
            "plan": "team",
            "plan_type": "team",
            "auth_file": str(oauth_path),
            "rt_auth_file": str(oauth_path),
            "cpa_archive_file": "",
        },
    )
    monkeypatch.setattr(
        cpa_batch,
        "login_codex_via_browser",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("batch should use account_oauth")),
        raising=False,
    )
    monkeypatch.setattr(cpa_batch, "check_codex_quota", lambda _token: ("ok", {"primary_pct": 0}))
    monkeypatch.setattr(cpa_batch, "upload_to_cpa", lambda _path: True)
    monkeypatch.setattr(cpa_batch, "archive_account_auth_file", lambda _email, _path: "")

    result = cpa_batch._verify_and_upload_cpa("new@example.com", {})

    assert result["auth_file"] == str(oauth_path)
    assert calls
    assert calls[0][0] == "new@example.com"
    assert calls[0][1]["check_quota_snapshot"] is False


def test_cpa_verify_marks_account_unavailable_when_quota_reports_account_deactivated(tmp_path, monkeypatch):
    _use_tmp_flow_file(tmp_path, monkeypatch)
    accounts.add_account("new@example.com", "pw")
    accounts.update_account("new@example.com", status=accounts.STATUS_ACTIVE)

    auth_path = tmp_path / "codex-new@example.com-team.json"
    auth_path.write_text('{"access_token":"token-dead"}', encoding="utf-8")

    monkeypatch.setattr(
        cpa_batch,
        "_ensure_team_auth",
        lambda *_args, **_kwargs: (auth_path, "team", {"access_token": "token-dead"}),
    )
    monkeypatch.setattr(
        cpa_batch,
        "check_codex_quota",
        lambda _token: ("account_deactivated", {"status_code": 403, "body": "account_deactivated"}),
    )

    with pytest.raises(cpa_batch.AccountDeactivatedError, match="account_deactivated"):
        cpa_batch._verify_and_upload_cpa("new@example.com", {})

    latest = accounts.find_account(accounts.load_accounts(), "new@example.com")
    assert latest is not None
    assert latest["status"] == accounts.STATUS_UNAVAILABLE
    assert latest["sync_disabled"] is True
    assert latest["unavailable_reason"] == "account_deactivated"
    assert latest["unavailable_at"]
