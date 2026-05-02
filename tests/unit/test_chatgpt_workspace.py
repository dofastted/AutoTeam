from autoteam import chatgpt_api


def test_workspace_candidate_kind_filters_page_heading_and_legal_links():
    assert chatgpt_api._workspace_candidate_kind("Choose a workspace") is None
    assert chatgpt_api._workspace_candidate_kind("Terms of Use") is None
    assert chatgpt_api._workspace_candidate_kind("Privacy Policy") is None


def test_workspace_candidate_kind_keeps_real_workspace_and_marks_personal_fallback():
    assert chatgpt_api._workspace_candidate_kind("Idapro") == "preferred"
    assert chatgpt_api._workspace_candidate_kind("Personal account") == "fallback"


def test_wait_for_post_workspace_ready_accepts_chatgpt_page_after_body_appears(monkeypatch):
    class FakePage:
        url = "https://chatgpt.com/"

        def wait_for_load_state(self, *_args, **_kwargs):
            return None

    client = chatgpt_api.ChatGPTTeamAPI()
    client.page = FakePage()

    states = iter(["", "", "Chat history"])
    monkeypatch.setattr(client, "_extract_session_token", lambda: "")
    monkeypatch.setattr(client, "_body_excerpt", lambda limit=120: next(states))
    monkeypatch.setattr(chatgpt_api.time, "sleep", lambda _seconds: None)

    assert client._wait_for_post_workspace_ready(timeout=2) is True


def test_wait_for_post_workspace_ready_accepts_blank_chatgpt_page_after_retries(monkeypatch):
    class FakePage:
        url = "https://chatgpt.com/"

        def wait_for_load_state(self, *_args, **_kwargs):
            return None

    client = chatgpt_api.ChatGPTTeamAPI()
    client.page = FakePage()

    monkeypatch.setattr(client, "_extract_session_token", lambda: "")
    monkeypatch.setattr(client, "_body_excerpt", lambda limit=120: "")
    monkeypatch.setattr(chatgpt_api.time, "sleep", lambda _seconds: None)

    assert client._wait_for_post_workspace_ready(timeout=2) is True


def test_select_workspace_option_shortcuts_completed_when_chatgpt_home_loaded(monkeypatch):
    class FakePage:
        url = "https://chatgpt.com/"

        def wait_for_load_state(self, *_args, **_kwargs):
            return None

    client = chatgpt_api.ChatGPTTeamAPI()
    client.page = FakePage()

    monkeypatch.setattr(client, "_list_workspace_options", lambda: [{"id": "0", "label": "Idapro"}])
    monkeypatch.setattr(client, "_click_workspace_option_by_label", lambda label: True)
    monkeypatch.setattr(client, "_wait_for_workspace_selection_exit", lambda timeout=15: True)
    monkeypatch.setattr(client, "_wait_for_post_workspace_ready", lambda timeout=12: True)
    monkeypatch.setattr(client, "_log_login_state", lambda label: None)
    monkeypatch.setattr(
        client,
        "_detect_login_step",
        lambda: (_ for _ in ()).throw(AssertionError("should not reach _detect_login_step")),
    )

    assert client.select_workspace_option(0) == {"step": "completed", "detail": None}


def test_complete_workspace_selection_uses_preferred_workspace(monkeypatch):
    class FakePage:
        url = "https://chatgpt.com/workspace"

    page = FakePage()
    calls = []

    monkeypatch.setattr(chatgpt_api.ChatGPTTeamAPI, "__init__", lambda self: None)
    monkeypatch.setattr(chatgpt_api.ChatGPTTeamAPI, "_is_workspace_selection_page", lambda self: True)
    monkeypatch.setattr(chatgpt_api.ChatGPTTeamAPI, "_body_excerpt", lambda self, limit=200: "")
    monkeypatch.setattr(
        chatgpt_api.ChatGPTTeamAPI,
        "list_workspace_options",
        lambda self: [
            {"id": "0", "label": "Personal account", "kind": "fallback"},
            {"id": "1", "label": "Idapro", "kind": "preferred"},
        ],
    )

    def fake_select(self, option_id):
        calls.append(option_id)
        return {"step": "completed", "detail": None}

    monkeypatch.setattr(chatgpt_api.ChatGPTTeamAPI, "select_workspace_option", fake_select)

    assert chatgpt_api.complete_workspace_selection(page, workspace_name="Idapro") is True
    assert calls == ["1"]


def test_complete_workspace_selection_falls_back_to_non_personal_option(monkeypatch):
    class FakePage:
        url = "https://chatgpt.com/organization"

    page = FakePage()
    calls = []

    monkeypatch.setattr(chatgpt_api.ChatGPTTeamAPI, "__init__", lambda self: None)
    monkeypatch.setattr(chatgpt_api.ChatGPTTeamAPI, "_is_workspace_selection_page", lambda self: True)
    monkeypatch.setattr(chatgpt_api.ChatGPTTeamAPI, "_body_excerpt", lambda self, limit=200: "")
    monkeypatch.setattr(
        chatgpt_api.ChatGPTTeamAPI,
        "list_workspace_options",
        lambda self: [
            {"id": "0", "label": "Personal account", "kind": "fallback"},
            {"id": "1", "label": "New organization", "kind": "fallback"},
        ],
    )

    def fake_select(self, option_id):
        calls.append(option_id)
        return {"step": "completed", "detail": None}

    monkeypatch.setattr(chatgpt_api.ChatGPTTeamAPI, "select_workspace_option", fake_select)

    assert chatgpt_api.complete_workspace_selection(page) is True
    assert calls == ["1"]
