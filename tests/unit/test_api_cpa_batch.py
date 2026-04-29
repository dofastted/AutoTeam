from autoteam import api, flow_runs


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
