import pytest
from fastapi import HTTPException

from autoteam import api


def _sample_accounts():
    return [
        {
            "email": "charlie@example.com",
            "password": "secret",
            "registration_status": "registered",
            "health_status": "valid",
            "usage_status": "normal",
            "cpa_status": "pending",
            "created_at": 100,
            "updated_at": 300,
            "notes": "primary account",
        },
        {
            "email": "bob@example.com",
            "password": "secret",
            "registration_status": "registered",
            "health_status": "valid",
            "usage_status": "inventory",
            "cpa_status": "success",
            "rt_auth_file": "auths/bob-oauth.json",
            "sync_disabled": False,
            "created_at": 200,
            "updated_at": 400,
            "notes": "inventory ready",
        },
        {
            "email": "alice@example.com",
            "password": "secret",
            "registration_status": "registered",
            "health_status": "valid",
            "usage_status": "in_use",
            "cpa_status": "success",
            "rt_auth_file": "auths/alice-oauth.json",
            "sync_disabled": False,
            "remote": {"sub2api": {"status": "present"}},
            "created_at": 150,
            "notes": "Alice note",
        },
        {
            "email": "zzz@example.com",
            "password": "secret",
            "registration_status": "planned",
            "health_status": "unknown",
            "usage_status": "normal",
            "created_at": 50,
            "notes": "not registered yet",
        },
    ]


def _patch_load_accounts(monkeypatch, accounts_data):
    monkeypatch.setattr("autoteam.accounts.load_accounts", lambda: [dict(item) for item in accounts_data])
    monkeypatch.setattr(api, "_load_sub2api_presence_emails", lambda: None)


def _reset_sub2api_presence_cache():
    api._SUB2API_PRESENCE_CACHE["emails"] = None
    api._SUB2API_PRESENCE_CACHE["expires_at"] = 0.0


def test_get_accounts_returns_paginated_response_by_default(monkeypatch):
    _patch_load_accounts(monkeypatch, _sample_accounts())

    result = api.get_accounts()

    assert result["total"] == 4
    assert result["page"] == 1
    assert result["page_size"] == 20
    assert result["has_next"] is False
    assert result["category"] is None
    assert result["q"] is None
    assert result["sort"] == "updated_at_desc"
    assert [item["email"] for item in result["items"]] == [
        "bob@example.com",
        "charlie@example.com",
        "alice@example.com",
        "zzz@example.com",
    ]
    assert "password" not in result["items"][0]
    categories_by_email = {item["email"]: item["category"] for item in result["items"]}
    assert categories_by_email["bob@example.com"] == "inventory"
    assert categories_by_email["alice@example.com"] == "in_use"
    assert categories_by_email["zzz@example.com"] == "not_registered"


def test_get_accounts_filters_inventory_category(monkeypatch):
    _patch_load_accounts(monkeypatch, _sample_accounts())

    result = api.get_accounts(category="inventory")

    assert result["total"] == 1
    assert result["category"] == "inventory"
    assert [item["email"] for item in result["items"]] == ["bob@example.com"]


def test_get_accounts_uses_live_sub2api_presence_as_category_source(monkeypatch):
    accounts_data = [
        {
            "email": "remote-present@example.com",
            "registration_status": "registered",
            "health_status": "valid",
            "usage_status": "inventory",
            "cpa_status": "success",
            "rt_auth_file": "auths/remote-present-oauth.json",
            "sync_disabled": False,
            "remote": {"sub2api": {"status": "missing"}},
            "updated_at": 20,
        },
        {
            "email": "stale-present@example.com",
            "registration_status": "registered",
            "health_status": "valid",
            "usage_status": "in_use",
            "cpa_status": "success",
            "rt_auth_file": "auths/stale-present-oauth.json",
            "sync_disabled": False,
            "remote": {"sub2api": {"status": "present"}},
            "updated_at": 10,
        },
        {
            "email": "planned@example.com",
            "registration_status": "planned",
            "health_status": "unknown",
            "usage_status": "in_use",
            "cpa_status": "success",
            "rt_auth_file": "auths/planned-oauth.json",
            "sync_disabled": False,
            "remote": {"sub2api": {"status": "present"}},
            "updated_at": 30,
        },
        {
            "email": "invalid@example.com",
            "registration_status": "registered",
            "health_status": "valid",
            "usage_status": "in_use",
            "cpa_status": "success",
            "rt_auth_file": "auths/invalid-oauth.json",
            "sync_disabled": False,
            "unavailable_reason": "http_401",
            "remote": {"sub2api": {"status": "present"}},
            "updated_at": 40,
        },
    ]
    _patch_load_accounts(monkeypatch, accounts_data)
    monkeypatch.setattr(api, "_load_sub2api_presence_emails", lambda: {"remote-present@example.com"})

    in_use = api.get_accounts(category="in_use", sort="email_asc")
    inventory = api.get_accounts(category="inventory", sort="email_asc")
    not_registered = api.get_accounts(category="not_registered", sort="email_asc")
    invalid = api.get_accounts(category="invalid", sort="email_asc")

    assert [item["email"] for item in in_use["items"]] == ["remote-present@example.com"]
    assert [item["email"] for item in inventory["items"]] == ["stale-present@example.com"]
    assert [item["email"] for item in not_registered["items"]] == ["planned@example.com"]
    assert [item["email"] for item in invalid["items"]] == ["invalid@example.com"]


def test_load_sub2api_presence_emails_uses_short_cache(monkeypatch):
    _reset_sub2api_presence_cache()
    calls = {"count": 0}

    monkeypatch.setattr("autoteam.sync_targets.is_sync_target_enabled", lambda target, env: True)

    def fake_list_emails():
        calls["count"] += 1
        return {"cached@example.com"}

    monkeypatch.setattr("autoteam.sub2api_sync.list_openai_oauth_account_emails", fake_list_emails)

    first = api._load_sub2api_presence_emails()
    second = api._load_sub2api_presence_emails()

    assert first == {"cached@example.com"}
    assert second == {"cached@example.com"}
    assert calls["count"] == 1
    _reset_sub2api_presence_cache()


def test_get_accounts_category_all_matches_default(monkeypatch):
    _patch_load_accounts(monkeypatch, _sample_accounts())

    default_result = api.get_accounts()
    all_result = api.get_accounts(category="all")

    assert all_result == default_result


def test_get_accounts_rejects_invalid_category(monkeypatch):
    _patch_load_accounts(monkeypatch, _sample_accounts())

    with pytest.raises(HTTPException) as exc_info:
        api.get_accounts(category="bad_value")

    assert exc_info.value.status_code == 400


def test_get_accounts_filters_by_email_query(monkeypatch):
    _patch_load_accounts(monkeypatch, _sample_accounts())

    result = api.get_accounts(q="alice")

    assert result["total"] == 1
    assert result["q"] == "alice"
    assert [item["email"] for item in result["items"]] == ["alice@example.com"]


def test_get_accounts_paginates_second_page(monkeypatch):
    _patch_load_accounts(monkeypatch, _sample_accounts())

    result = api.get_accounts(page=2, page_size=2)

    assert result["total"] == 4
    assert result["page"] == 2
    assert result["page_size"] == 2
    assert result["has_next"] is False
    assert [item["email"] for item in result["items"]] == [
        "alice@example.com",
        "zzz@example.com",
    ]


def test_get_accounts_sorts_by_email_ascending(monkeypatch):
    _patch_load_accounts(monkeypatch, _sample_accounts())

    result = api.get_accounts(sort="email_asc")

    assert [item["email"] for item in result["items"]] == [
        "alice@example.com",
        "bob@example.com",
        "charlie@example.com",
        "zzz@example.com",
    ]


def test_get_accounts_rejects_invalid_sort(monkeypatch):
    _patch_load_accounts(monkeypatch, _sample_accounts())

    with pytest.raises(HTTPException) as exc_info:
        api.get_accounts(sort="bad")

    assert exc_info.value.status_code == 400


@pytest.mark.parametrize(
    ("kwargs", "field"),
    [
        ({"page": 0}, "page"),
        ({"page_size": 0}, "page_size"),
        ({"page_size": 300}, "page_size"),
    ],
)
def test_get_accounts_rejects_invalid_pagination(monkeypatch, kwargs, field):
    _patch_load_accounts(monkeypatch, _sample_accounts())

    with pytest.raises(HTTPException) as exc_info:
        api.get_accounts(**kwargs)

    assert exc_info.value.status_code == 400
    assert field in exc_info.value.detail


def test_get_accounts_has_next_is_true_on_partial_page(monkeypatch):
    _patch_load_accounts(monkeypatch, _sample_accounts())

    result = api.get_accounts(page=1, page_size=2)

    assert result["has_next"] is True
    assert [item["email"] for item in result["items"]] == [
        "bob@example.com",
        "charlie@example.com",
    ]


@pytest.mark.parametrize(
    ("page_size", "expected_count", "expected_has_next"),
    [
        (1, 1, True),
        (100, 4, False),
    ],
)
def test_get_accounts_accepts_page_size_boundaries(monkeypatch, page_size, expected_count, expected_has_next):
    _patch_load_accounts(monkeypatch, _sample_accounts())

    result = api.get_accounts(page=1, page_size=page_size)

    assert result["page_size"] == page_size
    assert len(result["items"]) == expected_count
    assert result["has_next"] is expected_has_next


def test_get_accounts_filters_each_supported_category(monkeypatch):
    accounts_data = [
        {
            "email": "registered@example.com",
            "registration_status": "registered",
            "health_status": "valid",
            "usage_status": "normal",
            "cpa_status": "pending",
            "updated_at": 10,
        },
            {
                "email": "inventory@example.com",
                "registration_status": "registered",
                "health_status": "valid",
                "usage_status": "inventory",
                "cpa_status": "success",
            "rt_auth_file": "auths/inventory-oauth.json",
            "sync_disabled": False,
            "updated_at": 20,
        },
        {
            "email": "inuse@example.com",
            "registration_status": "registered",
            "health_status": "valid",
            "usage_status": "in_use",
            "cpa_status": "success",
            "rt_auth_file": "auths/inuse-oauth.json",
            "sync_disabled": False,
            "remote": {"sub2api": {"status": "present"}},
            "updated_at": 30,
        },
        {
            "email": "invalid@example.com",
            "registration_status": "registered",
            "health_status": "invalid",
            "usage_status": "normal",
            "updated_at": 40,
        },
        {
            "email": "sold@example.com",
            "registration_status": "registered",
            "health_status": "valid",
            "usage_status": "sold",
            "sale": {"sold_at": 123},
            "updated_at": 50,
        },
        {
            "email": "planned@example.com",
            "registration_status": "planned",
            "health_status": "unknown",
            "usage_status": "normal",
            "updated_at": 60,
        },
    ]
    _patch_load_accounts(monkeypatch, accounts_data)

    expected = {
        "registered": ["registered@example.com"],
        "inventory": ["inventory@example.com"],
        "in_use": ["inuse@example.com"],
        "invalid": ["invalid@example.com"],
        "sold": ["sold@example.com"],
        "not_registered": ["planned@example.com"],
    }

    for category, emails in expected.items():
        result = api.get_accounts(category=category)
        assert result["category"] == category
        assert [item["email"] for item in result["items"]] == emails
        assert result["total"] == len(emails)
