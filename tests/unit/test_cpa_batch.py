from autoteam import accounts, cpa_batch, flow_runs


class _FakeMailClient:
    provider_name = "mo_email"

    def login(self):
        return None

    def create_temp_email(self):
        return "mail-1", "new@example.com"

    def delete_account(self, _account_id):
        return None


def _use_tmp_flow_file(tmp_path, monkeypatch):
    monkeypatch.setattr(flow_runs, "FLOW_RUNS_FILE", tmp_path / "flow_runs.json")
    monkeypatch.setattr(accounts, "ACCOUNTS_FILE", tmp_path / "accounts.json")


def test_run_cpa_batch_groups_accounts_by_configured_batch_size(tmp_path, monkeypatch):
    _use_tmp_flow_file(tmp_path, monkeypatch)
    emails = iter(["a1@example.com", "a2@example.com", "a3@example.com"])

    monkeypatch.setattr(cpa_batch, "get_mail_client", lambda: _FakeMailClient())
    monkeypatch.setattr(cpa_batch, "update_account", lambda *args, **kwargs: None)
    monkeypatch.setattr(cpa_batch, "_create_direct_account", lambda _mail, **_kwargs: next(emails))
    monkeypatch.setattr(
        cpa_batch,
        "_verify_and_upload_cpa",
        lambda email, _cache, **_kwargs: {
            "email": email,
            "plan_type": "team",
            "auth_file": f"/tmp/codex-{email}-team.json",
            "auth_name": f"codex-{email}-team.json",
        },
    )

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
        return {
            "email": email,
            "plan_type": "team",
            "auth_file": f"/tmp/codex-{email}-team.json",
            "auth_name": f"codex-{email}-team.json",
        }

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
        return {
            "email": email,
            "plan_type": "team",
            "auth_file": f"/tmp/codex-{email}-team.json",
            "auth_name": f"codex-{email}-team.json",
        }

    monkeypatch.setattr(cpa_batch, "_verify_and_upload_cpa", fake_verify)

    result = cpa_batch.run_cpa_batch("run-4", target=2, batch_size=2, join_mode="direct")
    run = flow_runs.get_flow_run("run-4")

    assert result["status"] == "paused"
    assert seen == ["a1@example.com"]
    assert run["status"] == "paused"


def test_direct_account_records_email_before_register_failure(tmp_path, monkeypatch):
    _use_tmp_flow_file(tmp_path, monkeypatch)
    flow_runs.create_flow_run("run-direct", target=1, batch_size=20, join_mode="direct")

    monkeypatch.setattr("autoteam.manager._register_direct_once", lambda *_args, **_kwargs: False)
    monkeypatch.setattr("autoteam.manager._is_email_in_team", lambda _email: False)
    monkeypatch.setattr(cpa_batch.time, "sleep", lambda _seconds: None)

    hooks = cpa_batch.CpaBatchHooks("run-direct")
    try:
        cpa_batch._create_direct_account(_FakeMailClient(), hooks=hooks, batch_index=1)
    except cpa_batch.AccountFlowError as exc:
        assert exc.email == "new@example.com"
    else:
        raise AssertionError("expected AccountFlowError")

    run = flow_runs.get_flow_run("run-direct")
    assert run["accounts"][0]["email"] == "new@example.com"
    assert run["accounts"][0]["stage"] in {"register_retry", "register"}
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
    monkeypatch.setattr("autoteam.manager._is_email_in_team", lambda _email: False)
    monkeypatch.setattr(cpa_batch, "save_auth_file", lambda _bundle: str(auth_path))

    hooks = cpa_batch.CpaBatchHooks("run-session")
    email = cpa_batch._create_direct_account(_FakeMailClient(), hooks=hooks, batch_index=1)

    assert email == "new@example.com"
    acc = accounts.load_accounts()[0]
    assert acc["auth_file"] == str(auth_path)
    assert acc["plan_type"] == "team"
    run = flow_runs.get_flow_run("run-session")
    assert any(event["stage"] == "session_auth" for event in run["accounts"][0]["events"])


def test_cpa_verify_skips_browser_oauth_when_session_auth_missing(tmp_path, monkeypatch):
    _use_tmp_flow_file(tmp_path, monkeypatch)
    accounts.add_account("new@example.com", "pw")
    accounts.update_account("new@example.com", status=accounts.STATUS_ACTIVE)
    monkeypatch.setattr(
        cpa_batch,
        "login_codex_via_browser",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("browser OAuth should not run")),
    )

    try:
        cpa_batch._verify_and_upload_cpa("new@example.com", {})
    except RuntimeError as exc:
        assert "已跳过浏览器 OAuth" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")
