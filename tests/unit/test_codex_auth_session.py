import json

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
                {"name": "cf_clearance", "value": "cf-1", "domain": ".chatgpt.com"},
                {"name": "ignored", "value": "x", "domain": ".example.com"},
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
    assert "cf_clearance=cf-1" in bundle["cookie_header"]
    assert "ignored=x" not in bundle["cookie_header"]
    assert bundle["credential_source"] == "chatgpt_session"


def test_save_auth_file_keeps_session_and_oauth_files(tmp_path, monkeypatch):
    monkeypatch.setattr(codex_auth, "AUTH_DIR", tmp_path)
    monkeypatch.setattr(codex_auth, "ensure_auth_dir", lambda: tmp_path.mkdir(exist_ok=True))
    monkeypatch.setattr(codex_auth, "ensure_auth_file_permissions", lambda _path: None)

    session_bundle = {
        "email": "user@example.com",
        "account_id": "acc-1",
        "plan_type": "team",
        "access_token": "session-access",
        "id_token": "session-id",
        "refresh_token": "",
        "expired": 2000000000,
        "cookie_header": "cf_clearance=cf-1",
        "credential_source": "chatgpt_session",
    }
    oauth_bundle = {
        "email": "user@example.com",
        "account_id": "acc-1",
        "plan_type": "team",
        "access_token": "oauth-access",
        "id_token": "oauth-id",
        "refresh_token": "rt-1",
        "expired": 2000000000,
    }

    session_path = codex_auth.save_auth_file(session_bundle, source="session")
    oauth_path = codex_auth.save_auth_file(oauth_bundle, source="oauth")

    assert session_path != oauth_path
    assert session_path.endswith("-session.json")
    assert oauth_path.endswith("-oauth.json")
    assert (tmp_path / session_path.split("/")[-1]).exists()
    assert (tmp_path / oauth_path.split("/")[-1]).exists()
    session_data = json.loads((tmp_path / session_path.split("/")[-1]).read_text(encoding="utf-8"))
    assert session_data["cookie_header"] == "cf_clearance=cf-1"


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


def test_poll_verification_code_by_mail_id_uses_exact_message_id_and_skips_used_ids():
    calls = []

    class FakeMailClient:
        def search_emails_by_recipient(self, email, size=5, account_id=None):
            calls.append(("search", email, size, account_id))
            return [
                {
                    "emailId": "mail-1",
                    "sendEmail": "noreply@tm.openai.com",
                    "subject": "Your code",
                    "content": "placeholder",
                },
                {
                    "emailId": "mail-2",
                    "sendEmail": "noreply@tm.openai.com",
                    "subject": "Your code",
                    "content": "placeholder",
                },
            ]

        def get_email_by_id(self, account_id, email_id, to_email=None):
            calls.append(("get", account_id, email_id, to_email))
            return {
                "emailId": email_id,
                "sendEmail": "noreply@tm.openai.com",
                "subject": "Your code",
                "text": "Your temporary OpenAI login code is 654321" if email_id == "mail-2" else "no code",
            }

        def extract_verification_code(self, email_data):
            return "654321" if email_data.get("emailId") == "mail-2" else None

    otp, email_id = codex_auth._poll_verification_code_by_mail_id(
        FakeMailClient(),
        "tmp-user@example.com",
        mail_account_id="acct-1",
        used_email_ids={"mail-1"},
        timeout_seconds=1,
        poll_interval_seconds=0,
    )

    assert (otp, email_id) == ("654321", "mail-2")
    assert calls == [
        ("search", "tmp-user@example.com", 5, "acct-1"),
        ("get", "acct-1", "mail-2", "tmp-user@example.com"),
    ]


def test_poll_verification_code_by_mail_id_ignores_invite_mail_and_sender_mismatch():
    class FakeMailClient:
        def search_emails_by_recipient(self, email, size=5, account_id=None):
            return [
                {
                    "emailId": "mail-1",
                    "sendEmail": "invite@openai.com",
                    "subject": "You've been invited",
                    "content": "Your code is 111111",
                },
                {
                    "emailId": "mail-2",
                    "sendEmail": "billing@example.com",
                    "subject": "Your code",
                    "content": "Your code is 222222",
                },
            ]

        def extract_verification_code(self, email_data):
            return "999999"

    otp, email_id = codex_auth._poll_verification_code_by_mail_id(
        FakeMailClient(),
        "tmp-user@example.com",
        mail_account_id="acct-1",
        used_email_ids=set(),
        timeout_seconds=0,
        poll_interval_seconds=0,
    )

    assert (otp, email_id) == (None, None)
