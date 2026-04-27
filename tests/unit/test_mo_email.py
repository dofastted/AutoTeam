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
