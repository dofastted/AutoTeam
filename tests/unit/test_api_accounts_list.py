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
            "usage_status": "normal",
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


def test_get_accounts_filters_inventory_category(monkeypatch):
    _patch_load_accounts(monkeypatch, _sample_accounts())

    result = api.get_accounts(category="inventory")

    assert result["total"] == 1
    assert result["category"] == "inventory"
    assert [item["email"] for item in result["items"]] == ["bob@example.com"]


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
