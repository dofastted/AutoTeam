from autoteam import codex_auth


def _jwt(payload):
    import base64
    import json

    def enc(data):
        raw = json.dumps(data, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    return f"{enc({'alg': 'none'})}.{enc(payload)}."


def test_build_chatgpt_session_auth_bundle_from_page():
    access_token = _jwt(
        {
            "email": "user@example.com",
            "exp": 2000000000,
            "https://api.openai.com/auth": {
                "chatgpt_account_id": "acc-1",
                "chatgpt_plan_type": "team",
            },
        }
    )

    class FakeContext:
        def cookies(self):
            return [
                {"name": "__Secure-next-auth.session-token.0", "value": "part-a"},
                {"name": "__Secure-next-auth.session-token.1", "value": "part-b"},
            ]

    class FakePage:
        context = FakeContext()

        def goto(self, *_args, **_kwargs):
            return None

        def wait_for_load_state(self, *_args, **_kwargs):
            return None

        def evaluate(self, *_args, **_kwargs):
            return {
                "ok": True,
                "status": 200,
                "data": {
                    "accessToken": access_token,
                    "user": {"email": "fallback@example.com"},
                },
            }

    bundle = codex_auth.build_chatgpt_session_auth_bundle(FakePage())

    assert bundle["email"] == "user@example.com"
    assert bundle["account_id"] == "acc-1"
    assert bundle["plan_type"] == "team"
    assert bundle["access_token"] == access_token
    assert bundle["id_token"] == access_token
    assert bundle["session_token"] == "part-apart-b"
    assert bundle["credential_source"] == "chatgpt_session"


def test_login_codex_via_session_uses_unified_flow_and_returns_bundle(monkeypatch):
    events = []

    class FakeSessionCodexAuthFlow:
        def __init__(self, **kwargs):
            events.append(("init", kwargs))

        def start(self):
            events.append(("start", None))
            return {"step": "completed", "detail": None}

        def complete(self):
            events.append(("complete", None))
            return {"bundle": {"email": "owner@example.com", "plan_type": "team"}}

        def stop(self):
            events.append(("stop", None))

    monkeypatch.setattr(codex_auth, "SessionCodexAuthFlow", FakeSessionCodexAuthFlow)
    monkeypatch.setattr(codex_auth, "get_admin_email", lambda: "owner@example.com")
    monkeypatch.setattr(codex_auth, "get_admin_session_token", lambda: "session-token")
    monkeypatch.setattr(codex_auth, "get_chatgpt_account_id", lambda: "acc-1")
    monkeypatch.setattr(codex_auth, "get_chatgpt_workspace_name", lambda: "Idapro")

    bundle = codex_auth.login_codex_via_session()

    assert bundle == {"email": "owner@example.com", "plan_type": "team"}
    assert events[0][0] == "init"
    assert events[0][1]["email"] == "owner@example.com"
    assert events[0][1]["session_token"] == "session-token"
    assert events[0][1]["account_id"] == "acc-1"
    assert events[0][1]["workspace_name"] == "Idapro"
    assert callable(events[0][1]["auth_file_callback"])
    assert [name for name, _ in events[1:]] == ["start", "complete", "stop"]


def test_login_codex_via_session_returns_none_when_flow_requires_more_steps(monkeypatch):
    events = []

    class FakeSessionCodexAuthFlow:
        def __init__(self, **kwargs):
            events.append(("init", kwargs))

        def start(self):
            events.append(("start", None))
            return {"step": "email_required", "detail": "https://auth.openai.com/login"}

        def complete(self):
            raise AssertionError("complete should not be called")

        def stop(self):
            events.append(("stop", None))

    monkeypatch.setattr(codex_auth, "SessionCodexAuthFlow", FakeSessionCodexAuthFlow)
    monkeypatch.setattr(codex_auth, "get_admin_email", lambda: "owner@example.com")
    monkeypatch.setattr(codex_auth, "get_admin_session_token", lambda: "session-token")
    monkeypatch.setattr(codex_auth, "get_chatgpt_account_id", lambda: "acc-1")
    monkeypatch.setattr(codex_auth, "get_chatgpt_workspace_name", lambda: "Idapro")

    bundle = codex_auth.login_codex_via_session()

    assert bundle is None
    assert [name for name, _ in events[1:]] == ["start", "stop"]


def test_refresh_main_auth_file_saves_bundle_from_session_login(monkeypatch):
    monkeypatch.setattr(
        codex_auth,
        "login_codex_via_session",
        lambda: {"email": "owner@example.com", "account_id": "acc-1", "plan_type": "team"},
    )
    monkeypatch.setattr(codex_auth, "save_main_auth_file", lambda bundle: f"/tmp/{bundle['account_id']}.json")

    result = codex_auth.refresh_main_auth_file()

    assert result == {
        "email": "owner@example.com",
        "auth_file": "/tmp/acc-1.json",
        "plan_type": "team",
    }
