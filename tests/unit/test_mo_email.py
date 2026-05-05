import pytest

from autoteam import accounts, mo_email


def test_normalize_mo_email_base_url_strips_api_suffix():
    assert mo_email.normalize_mo_email_base_url("https://mo.gymbro.cloud/") == "https://mo.gymbro.cloud"
    assert mo_email.normalize_mo_email_base_url("https://mo.gymbro.cloud/api") == "https://mo.gymbro.cloud"


def test_login_accepts_configured_domain(monkeypatch):
    client = mo_email.MoEmailClient()
    monkeypatch.setattr(client, "domain", "gymbro.cloud")
    monkeypatch.setattr(
        client,
        "_request",
        lambda method, path, **kwargs: {"emailDomains": "gymbro.cloud,fkcodex.com,sub.fkcode.com"},
    )

    assert client.login() == client.api_key


def test_create_temp_email_uses_next_index_from_remote_and_local(monkeypatch):
    client = mo_email.MoEmailClient()
    calls = []

    monkeypatch.setattr(client, "domain", "gymbro.cloud")
    monkeypatch.setattr(client, "name_prefix", "abc")
    monkeypatch.setattr(client, "start_index", 1)
    monkeypatch.setattr(
        client,
        "list_accounts",
        lambda size=1000: [
            {"accountId": "email-1", "email": "abc-1@gymbro.cloud"},
            {"accountId": "email-3", "email": "abc-3@gymbro.cloud"},
        ],
    )
    monkeypatch.setattr(
        accounts,
        "load_accounts",
        lambda: [
            {"mail_account_id": "local-5", "email": "abc-5@gymbro.cloud"},
            {"mail_account_id": "other", "email": "other-9@gymbro.cloud"},
        ],
    )

    def fake_request(method, path, **kwargs):
        calls.append((method, path, kwargs))
        return {"email": {"id": "email-6", "address": "abc-6@gymbro.cloud"}}

    monkeypatch.setattr(client, "_request", fake_request)

    account_id, email = client.create_temp_email()

    assert account_id == "email-6"
    assert email == "abc-6@gymbro.cloud"
    assert calls[0][2]["json"] == {
        "name": "abc-6",
        "expiryTime": client.expiry_time,
        "domain": "gymbro.cloud",
    }


def test_create_temp_email_reserves_names_when_remote_list_lags(monkeypatch):
    client = mo_email.MoEmailClient()
    created = []
    mo_email._RESERVED_EMAIL_NAMES.clear()

    monkeypatch.setattr(client, "domain", "gymbro.cloud")
    monkeypatch.setattr(client, "name_prefix", "abc")
    monkeypatch.setattr(client, "start_index", 1)
    monkeypatch.setattr(client, "list_accounts", lambda size=1000: [])
    monkeypatch.setattr(accounts, "load_accounts", lambda: [])

    def fake_request(method, path, **kwargs):
        name = kwargs["json"]["name"]
        created.append(name)
        return {"email": {"id": name, "address": f"{name}@gymbro.cloud"}}

    monkeypatch.setattr(client, "_request", fake_request)

    assert client.create_temp_email()[1] == "abc-1@gymbro.cloud"
    assert client.create_temp_email()[1] == "abc-2@gymbro.cloud"
    assert created == ["abc-1", "abc-2"]
    mo_email._RESERVED_EMAIL_NAMES.clear()


def test_recreate_permanent_email_uses_same_local_part_with_no_expiry(monkeypatch):
    client = mo_email.MoEmailClient()
    calls = []

    def fake_request(method, path, **kwargs):
        calls.append((method, path, kwargs))
        return {"email": {"id": "mailbox-1", "address": "abc-1@gymbro.cloud"}}

    monkeypatch.setattr(client, "_request", fake_request)

    result = client.recreate_permanent_email("abc-1@gymbro.cloud")

    assert result["email"] == "abc-1@gymbro.cloud"
    assert result["account_id"] == "mailbox-1"
    assert calls == [
        (
            "POST",
            "/api/emails/generate",
            {
                "label": "重建永久邮箱",
                "json": {"name": "abc-1", "expiryTime": 0, "domain": "gymbro.cloud"},
            },
        )
    ]


def test_recreate_permanent_email_reuses_existing_mailbox_on_409(monkeypatch):
    client = mo_email.MoEmailClient()
    calls = []

    def fake_request(method, path, **kwargs):
        calls.append((method, path, kwargs))
        raise mo_email.MoEmailRequestError(
            "Mo Email 重建永久邮箱失败: HTTP 409 该邮箱地址已被使用",
            status_code=409,
            payload={"message": "该邮箱地址已被使用"},
        )

    monkeypatch.setattr(client, "_request", fake_request)
    monkeypatch.setattr(
        client,
        "list_accounts",
        lambda size=1000: [{"id": "mailbox-existing", "address": "abc-1@gymbro.cloud"}],
    )
    monkeypatch.setattr(accounts, "load_accounts", lambda: [])

    result = client.recreate_permanent_email("abc-1@gymbro.cloud")

    assert result["email"] == "abc-1@gymbro.cloud"
    assert result["account_id"] == "mailbox-existing"
    assert result["reused"] is True
    assert calls == [
        (
            "POST",
            "/api/emails/generate",
            {
                "label": "重建永久邮箱",
                "json": {"name": "abc-1", "expiryTime": 0, "domain": "gymbro.cloud"},
            },
        )
    ]


def test_recreate_permanent_email_does_not_reuse_local_cache_on_409(monkeypatch):
    client = mo_email.MoEmailClient()

    def fake_request(method, path, **kwargs):
        raise mo_email.MoEmailRequestError(
            "Mo Email 重建永久邮箱失败: HTTP 409 该邮箱地址已被使用",
            status_code=409,
            payload={"message": "该邮箱地址已被使用"},
        )

    monkeypatch.setattr(client, "_request", fake_request)
    monkeypatch.setattr(client, "list_accounts", lambda size=1000: [])
    monkeypatch.setattr(
        accounts,
        "load_accounts",
        lambda: [{"mail_account_id": "stale-local", "email": "abc-1@gymbro.cloud"}],
    )

    with pytest.raises(RuntimeError, match="永久邮箱已存在但无法查询 account_id"):
        client.recreate_permanent_email("abc-1@gymbro.cloud")


def test_recreate_permanent_email_non_409_error_does_not_reuse(monkeypatch):
    client = mo_email.MoEmailClient()
    list_calls = []

    def fake_request(method, path, **kwargs):
        raise mo_email.MoEmailRequestError(
            "Mo Email 重建永久邮箱失败: HTTP 500 upstream error",
            status_code=500,
            payload={"message": "upstream error"},
        )

    monkeypatch.setattr(client, "_request", fake_request)
    monkeypatch.setattr(client, "list_accounts", lambda size=1000: list_calls.append(size) or [])

    with pytest.raises(mo_email.MoEmailRequestError, match="HTTP 500"):
        client.recreate_permanent_email("abc-1@gymbro.cloud")

    assert list_calls == []


def test_search_emails_by_recipient_normalizes_messages(monkeypatch):
    client = mo_email.MoEmailClient()
    monkeypatch.setattr(client, "_resolve_account_id_for_email", lambda email: "mailbox-1")

    def fake_request(method, path, **kwargs):
        if path == "/api/emails/mailbox-1":
            return {
                "messages": [
                    {
                        "id": "msg-1",
                        "from_address": "OpenAI <noreply@tm.openai.com>",
                        "to_address": "abc-1@gymbro.cloud",
                        "subject": "Your ChatGPT code is 654321",
                        "content": "Your temporary OpenAI login code is 654321",
                    }
                ],
                "nextCursor": None,
                "total": 1,
            }
        raise AssertionError(f"unexpected path: {path}")

    monkeypatch.setattr(client, "_request", fake_request)

    emails = client.search_emails_by_recipient("abc-1@gymbro.cloud", size=5)

    assert len(emails) == 1
    assert emails[0]["emailId"] == "msg-1"
    assert emails[0]["sendEmail"] == "OpenAI <noreply@tm.openai.com>"
    assert emails[0]["toEmail"] == "abc-1@gymbro.cloud"
    assert client.extract_verification_code(emails[0]) == "654321"


def test_search_emails_by_recipient_fetches_detail_when_list_has_no_content(monkeypatch):
    client = mo_email.MoEmailClient()
    monkeypatch.setattr(client, "_resolve_account_id_for_email", lambda email: "mailbox-1")

    def fake_request(method, path, **kwargs):
        if path == "/api/emails/mailbox-1":
            return {"messages": [{"id": "msg-1", "subject": "Code"}]}
        if path == "/api/emails/mailbox-1/msg-1":
            return {
                "message": {
                    "id": "msg-1",
                    "from_address": "noreply@tm.openai.com",
                    "to_address": "abc-1@gymbro.cloud",
                    "subject": "Code",
                    "html": "<p>Your temporary OpenAI login code is 123456</p>",
                }
            }
        raise AssertionError(f"unexpected path: {path}")

    monkeypatch.setattr(client, "_request", fake_request)

    emails = client.search_emails_by_recipient("abc-1@gymbro.cloud", size=5)

    assert client.extract_verification_code(emails[0]) == "123456"


def test_search_emails_by_recipient_uses_user_id_account_identifier(monkeypatch):
    client = mo_email.MoEmailClient()
    monkeypatch.setattr(client, "_resolve_account_id_for_email", lambda email: "user-1")

    def fake_request(method, path, **kwargs):
        if path == "/api/emails/user-1":
            return {
                "messages": [
                    {
                        "id": "msg-1",
                        "from_address": "OpenAI <noreply@tm.openai.com>",
                        "to_address": "abc-1@gymbro.cloud",
                        "subject": "Account deactivated",
                        "content": "your account is deactivated",
                    }
                ]
            }
        raise AssertionError(f"unexpected path: {path}")

    monkeypatch.setattr(client, "_request", fake_request)

    emails = client.search_emails_by_recipient("abc-1@gymbro.cloud", size=5, account_id="user-1")

    assert emails[0]["emailId"] == "msg-1"
    assert emails[0]["accountId"] == "user-1"


def test_get_email_by_id_returns_normalized_detail(monkeypatch):
    client = mo_email.MoEmailClient()

    monkeypatch.setattr(
        client,
        "_get_message_detail",
        lambda account_id, message_id: {
            "id": message_id,
            "from_address": "noreply@tm.openai.com",
            "to_address": "abc-1@gymbro.cloud",
            "subject": "Code",
            "html": "<p>Your temporary OpenAI login code is 123456</p>",
        },
    )

    email = client.get_email_by_id("mailbox-1", "msg-1", to_email="abc-1@gymbro.cloud")

    assert email["emailId"] == "msg-1"
    assert email["accountId"] == "mailbox-1"
    assert email["toEmail"] == "abc-1@gymbro.cloud"
    assert client.extract_verification_code(email) == "123456"


def test_extract_invite_link_reads_html_link():
    client = mo_email.MoEmailClient()
    email_data = {
        "content": '<a href="https://chatgpt.com/auth/login?invite=abc">Join</a>',
        "text": "",
    }

    assert client.extract_invite_link(email_data) == "https://chatgpt.com/auth/login?invite=abc"


def test_delete_account_reports_unsupported():
    client = mo_email.MoEmailClient()

    assert client.delete_account("mailbox-1")["code"] == 501
