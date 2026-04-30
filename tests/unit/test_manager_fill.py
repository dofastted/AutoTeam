from autoteam import manager


class _FakeChatGPT:
    def __init__(self):
        self.browser = True
        self.started = 0
        self.stopped = 0

    def start(self):
        self.browser = True
        self.started += 1

    def stop(self):
        self.browser = False
        self.stopped += 1


class _FakeMailClient:
    def login(self):
        return None


def test_cmd_fill_tries_other_reusable_accounts_before_creating_new(monkeypatch):
    chatgpt = _FakeChatGPT()
    count_values = iter([4, 5])
    events = []

    monkeypatch.setattr(manager, "ChatGPTTeamAPI", lambda: chatgpt)
    monkeypatch.setattr(manager, "CloudMailClient", lambda: _FakeMailClient())
    monkeypatch.setattr(manager, "get_team_member_count", lambda _chatgpt: next(count_values))
    monkeypatch.setattr(
        manager,
        "get_standby_accounts",
        lambda: [
            {"email": "old-1@example.com", "_quota_recovered": True},
            {"email": "old-2@example.com", "_quota_recovered": True},
        ],
    )

    def fake_reinvite(_chatgpt, _mail, acc):
        events.append(("reinvite", acc["email"]))
        return acc["email"] == "old-2@example.com"

    monkeypatch.setattr(manager, "reinvite_account", fake_reinvite)
    monkeypatch.setattr(
        manager,
        "create_new_account",
        lambda _chatgpt, _mail: events.append(("create", None)) or True,
    )
    monkeypatch.setattr(manager, "sync_to_cpa", lambda: events.append(("sync", None)))
    monkeypatch.setattr(manager, "cmd_status", lambda: events.append(("status", None)))

    manager.cmd_fill(target=5)

    assert events == [
        ("reinvite", "old-1@example.com"),
        ("reinvite", "old-2@example.com"),
        ("sync", None),
        ("status", None),
    ]
    assert chatgpt.stopped == 1


def test_cmd_fill_skips_google_accounts_during_auto_reuse(monkeypatch):
    chatgpt = _FakeChatGPT()
    count_values = iter([4, 5])
    events = []

    monkeypatch.setattr(manager, "ChatGPTTeamAPI", lambda: chatgpt)
    monkeypatch.setattr(manager, "CloudMailClient", lambda: _FakeMailClient())
    monkeypatch.setattr(manager, "get_team_member_count", lambda _chatgpt: next(count_values))
    monkeypatch.setattr(
        manager,
        "get_standby_accounts",
        lambda: [
            {"email": "bubblehuntr@gmail.com", "_quota_recovered": True},
            {"email": "old-2@example.com", "_quota_recovered": True},
        ],
    )

    def fake_reinvite(_chatgpt, _mail, acc):
        events.append(("reinvite", acc["email"]))
        return True

    monkeypatch.setattr(manager, "reinvite_account", fake_reinvite)
    monkeypatch.setattr(
        manager,
        "create_new_account",
        lambda _chatgpt, _mail: events.append(("create", None)) or True,
    )
    monkeypatch.setattr(manager, "sync_to_cpa", lambda: events.append(("sync", None)))
    monkeypatch.setattr(manager, "cmd_status", lambda: events.append(("status", None)))

    manager.cmd_fill(target=5)

    assert events == [
        ("reinvite", "old-2@example.com"),
        ("sync", None),
        ("status", None),
    ]
    assert chatgpt.stopped == 1


def test_cmd_fill_stops_early_when_refreshed_team_count_hits_target(monkeypatch):
    chatgpt = _FakeChatGPT()
    count_values = iter([3, 5])
    events = []

    monkeypatch.setattr(manager, "ChatGPTTeamAPI", lambda: chatgpt)
    monkeypatch.setattr(manager, "CloudMailClient", lambda: _FakeMailClient())
    monkeypatch.setattr(manager, "get_team_member_count", lambda _chatgpt: next(count_values))
    monkeypatch.setattr(manager, "get_standby_accounts", lambda: [])
    monkeypatch.setattr(
        manager,
        "create_new_account",
        lambda _chatgpt, _mail: events.append(("create", None)) or False,
    )
    monkeypatch.setattr(manager, "sync_to_cpa", lambda: events.append(("sync", None)))
    monkeypatch.setattr(manager, "cmd_status", lambda: events.append(("status", None)))

    manager.cmd_fill(target=5)

    assert events == [
        ("create", None),
        ("sync", None),
        ("status", None),
    ]
    assert chatgpt.stopped == 1


def test_cmd_fill_syncs_cpa_after_each_configured_batch(monkeypatch):
    chatgpt = _FakeChatGPT()
    count_values = iter(range(0, 14))
    events = []

    import autoteam.config as config

    monkeypatch.setattr(config, "FILL_BATCH_SIZE", 10)
    monkeypatch.setattr(config, "TEAM_TARGET_SEATS", 999)
    monkeypatch.setattr(config, "MAX_TEAM_SEATS", 999)
    monkeypatch.setattr(manager, "ChatGPTTeamAPI", lambda: chatgpt)
    monkeypatch.setattr(manager, "CloudMailClient", lambda: _FakeMailClient())
    monkeypatch.setattr(manager, "get_team_member_count", lambda _chatgpt: next(count_values))
    monkeypatch.setattr(manager, "get_standby_accounts", lambda: [])
    monkeypatch.setattr(
        manager,
        "create_new_account",
        lambda _chatgpt, _mail: events.append(("create", None)) or True,
    )
    monkeypatch.setattr(manager, "sync_to_cpa", lambda: events.append(("sync", None)) or {"uploaded": 1})
    monkeypatch.setattr(manager, "cmd_status", lambda: events.append(("status", None)))

    result = manager.cmd_fill(target=13)

    assert [event for event in events if event[0] == "sync"] == [("sync", None), ("sync", None)]
    assert events[-1] == ("status", None)
    assert result["attempted"] == 13
    assert result["succeeded"] == 13
    assert [batch["attempted"] for batch in result["batches"]] == [10, 3]
    assert chatgpt.stopped == 1


def test_cmd_fill_uses_parallel_creator_for_new_accounts(monkeypatch):
    chatgpt = _FakeChatGPT()
    count_values = iter([0, 3])
    events = []

    import autoteam.config as config

    monkeypatch.setattr(config, "FILL_BATCH_SIZE", 10)
    monkeypatch.setattr(config, "TEAM_TARGET_SEATS", 999)
    monkeypatch.setattr(config, "MAX_TEAM_SEATS", 999)
    monkeypatch.setattr(manager, "ChatGPTTeamAPI", lambda: chatgpt)
    monkeypatch.setattr(manager, "CloudMailClient", lambda: _FakeMailClient())
    monkeypatch.setattr(manager, "get_team_member_count", lambda _chatgpt: next(count_values))
    monkeypatch.setattr(manager, "get_standby_accounts", lambda: [])

    def fake_parallel(total, *, parallel_workers=None, stop_after_success=None):
        events.append(("parallel", total, parallel_workers))
        return {
            "attempted": 3,
            "succeeded": 3,
            "failed": 0,
            "emails": ["a@example.com", "b@example.com", "c@example.com"],
            "worker_reports": [
                {"worker_index": 1, "target": 1, "attempted": 1, "succeeded": 1, "failed": 0},
                {"worker_index": 2, "target": 1, "attempted": 1, "succeeded": 1, "failed": 0},
                {"worker_index": 3, "target": 1, "attempted": 1, "succeeded": 1, "failed": 0},
            ],
            "parallel_workers": 3,
        }

    monkeypatch.setattr(manager, "_create_new_accounts_parallel", fake_parallel)
    monkeypatch.setattr(manager, "sync_to_cpa", lambda: events.append(("sync", None)) or {"uploaded": 3})
    monkeypatch.setattr(manager, "cmd_status", lambda: events.append(("status", None)))

    result = manager.cmd_fill(target=3, parallel_workers=3)

    assert events[0] == ("parallel", 3, 3)
    assert result["succeeded"] == 3
    assert result["parallel_workers"] == 3
    assert len(result["worker_reports"]) == 3


def test_auto_reuse_skip_reason_detects_google_provider_and_gmail():
    assert manager._auto_reuse_skip_reason({"email": "bubblehuntr@gmail.com"}) == "Google 登录账号暂不支持自动复用"
    assert (
        manager._auto_reuse_skip_reason({"email": "user@example.com", "login_provider": "google"})
        == "Google 登录账号暂不支持自动复用"
    )
    assert manager._auto_reuse_skip_reason({"email": "user@example.com"}) is None
