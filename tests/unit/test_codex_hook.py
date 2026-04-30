import json

from autoteam import accounts, codex_hook, flow_runs


def test_summarize_campaign_counts_managed_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(flow_runs, "FLOW_RUNS_FILE", tmp_path / "flow_runs.json")
    monkeypatch.setattr(codex_hook, "CONFIG_FILE", tmp_path / "campaign.json")
    monkeypatch.setattr(codex_hook, "PROMPT_FILE", tmp_path / "prompt.txt")
    monkeypatch.setattr(codex_hook, "CHECKER_LOG", tmp_path / "checker.log")
    monkeypatch.setattr(codex_hook, "INSTALL_LOG", tmp_path / "install.log")

    flow_runs.create_flow_run("run-a", target=6, batch_size=6, join_mode="direct", parallel_workers=3)
    flow_runs.update_flow_run("run-a", status="running", success_count=3, failed_count=1, attempted_count=4)

    flow_runs.create_flow_run("run-b", target=6, batch_size=6, join_mode="direct", parallel_workers=3)
    flow_runs.update_flow_run("run-b", status="paused", success_count=5, failed_count=2, attempted_count=7)

    config = codex_hook.load_campaign_config()
    config["managed_run_ids"] = ["run-a", "run-b"]
    config["target_success"] = 10
    codex_hook.save_campaign_config(config)

    summary = codex_hook.summarize_campaign()

    assert summary["total_success"] == 8
    assert summary["total_failed"] == 3
    assert summary["total_attempted"] == 11
    assert summary["running_run_ids"] == ["run-a"]
    assert summary["paused_run_ids"] == ["run-b"]
    assert codex_hook.campaign_reached_target() is False


def test_load_campaign_config_creates_default_file(tmp_path, monkeypatch):
    monkeypatch.setattr(codex_hook, "CONFIG_FILE", tmp_path / "campaign.json")
    monkeypatch.setattr(codex_hook, "RUNTIME_DIR", tmp_path / "runtime")
    monkeypatch.setattr(codex_hook, "LOG_DIR", tmp_path / "logs")

    config = codex_hook.load_campaign_config()

    assert config["target_success"] == 100
    assert config["interval_minutes"] == 10
    stored = json.loads((tmp_path / "campaign.json").read_text(encoding="utf-8"))
    assert stored["enabled"] is True


def test_find_resumable_run_skips_completed_and_running(tmp_path, monkeypatch):
    monkeypatch.setattr(flow_runs, "FLOW_RUNS_FILE", tmp_path / "flow_runs.json")
    monkeypatch.setattr(codex_hook, "CONFIG_FILE", tmp_path / "campaign.json")

    flow_runs.create_flow_run("run-completed", target=6, batch_size=6, join_mode="direct", parallel_workers=3)
    flow_runs.update_flow_run("run-completed", status="completed", success_count=6, attempted_count=6)

    flow_runs.create_flow_run("run-running", target=6, batch_size=6, join_mode="direct", parallel_workers=3)
    flow_runs.update_flow_run("run-running", status="running", success_count=2, attempted_count=3)

    flow_runs.create_flow_run("run-paused", target=6, batch_size=6, join_mode="direct", parallel_workers=3)
    flow_runs.update_flow_run("run-paused", status="paused", success_count=4, attempted_count=5)

    config = codex_hook.load_campaign_config()
    config["managed_run_ids"] = ["run-completed", "run-running", "run-paused"]
    codex_hook.save_campaign_config(config)

    resumable = codex_hook.find_resumable_run()

    assert resumable is not None
    assert resumable["run_id"] == "run-paused"


def test_verify_managed_success_accounts_flags_missing_plan_or_cpa(tmp_path, monkeypatch):
    monkeypatch.setattr(flow_runs, "FLOW_RUNS_FILE", tmp_path / "flow_runs.json")
    monkeypatch.setattr(accounts, "ACCOUNTS_FILE", tmp_path / "accounts.json")
    monkeypatch.setattr(codex_hook, "CONFIG_FILE", tmp_path / "campaign.json")

    accounts.add_account("ok@example.com", "pw")
    accounts.update_account(
        "ok@example.com",
        status=accounts.STATUS_ACTIVE,
        plan_type="team",
        auth_file="/tmp/ok.json",
        cpa_uploaded_at=123,
    )
    accounts.add_account("bad@example.com", "pw")
    accounts.update_account("bad@example.com", status=accounts.STATUS_ACTIVE)

    flow_runs.create_flow_run("run-verify", target=2, batch_size=2, join_mode="direct", parallel_workers=1)
    flow_runs.upsert_flow_account("run-verify", "ok@example.com", status="success")
    flow_runs.upsert_flow_account("run-verify", "bad@example.com", status="success")

    config = codex_hook.load_campaign_config()
    config["managed_run_ids"] = ["run-verify"]
    codex_hook.save_campaign_config(config)

    issues = codex_hook.verify_managed_success_accounts()

    assert {"email": "bad@example.com", "issue": "plan_type,auth_file,cpa_uploaded_at"} in issues


def test_verify_managed_cpa_records_flags_missing_remote_file_and_qualified_at(tmp_path, monkeypatch):
    monkeypatch.setattr(flow_runs, "FLOW_RUNS_FILE", tmp_path / "flow_runs.json")
    monkeypatch.setattr(codex_hook, "CONFIG_FILE", tmp_path / "campaign.json")

    flow_runs.create_flow_run("run-cpa", target=1, batch_size=1, join_mode="direct", parallel_workers=1)
    flow_runs.upsert_flow_account("run-cpa", "ok@example.com", status="success")

    config = codex_hook.load_campaign_config()
    config["managed_run_ids"] = ["run-cpa"]
    codex_hook.save_campaign_config(config)

    monkeypatch.setattr(
        codex_hook,
        "fetch_accounts_via_api",
        lambda config=None: [
            {
                "email": "ok@example.com",
                "auth_file": "/tmp/codex-ok@example.com-team-abc.json",
                "plan_type": "team",
                "cpa_uploaded_at": 123,
            }
        ],
    )
    monkeypatch.setattr(codex_hook, "fetch_cpa_files_via_api", lambda config=None: [])

    issues = codex_hook.verify_managed_cpa_records()

    assert {"email": "ok@example.com", "issue": "qualified_at,cpa_remote_missing"} in issues
