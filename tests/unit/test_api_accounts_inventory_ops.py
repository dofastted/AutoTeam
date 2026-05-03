import copy

import pytest
from fastapi import HTTPException

from autoteam import api
from autoteam.account_health import INVALID_REASON_AUTH_ERROR
from autoteam.account_models import (
    HEALTH_INVALID,
    HEALTH_VALID,
    USAGE_IN_USE,
    USAGE_INVENTORY,
    USAGE_NORMAL,
    USAGE_SOLD,
)


def _make_account(**overrides):
    account = {
        "email": "user@example.com",
        "registration_status": "registered",
        "health_status": HEALTH_VALID,
        "usage_status": USAGE_INVENTORY,
        "cpa_status": "success",
        "updated_at": 100,
    }
    account.update(overrides)
    return account


def _patch_account_store(monkeypatch, records):
    store = [copy.deepcopy(item) for item in records]
    saved_snapshots = []

    def fake_load_accounts():
        return store

    def fake_save_accounts(accounts_data):
        assert accounts_data is store
        saved_snapshots.append(copy.deepcopy(accounts_data))

    monkeypatch.setattr("autoteam.accounts.load_accounts", fake_load_accounts)
    monkeypatch.setattr("autoteam.accounts.save_accounts", fake_save_accounts)
    return store, saved_snapshots


def test_post_allocate_account_success(monkeypatch):
    store, saved = _patch_account_store(monkeypatch, [_make_account()])

    data = api.post_allocate_account(
        "user@example.com",
        api.AllocateAccountParams(project="proj-a", allocated_to="worker-1", force=False),
    )

    assert data["changed"] is True
    assert data["reason"] is None
    assert data["warning"] is None
    assert data["account"]["usage_status"] == USAGE_IN_USE
    assert data["account"]["allocation"]["status"] == "in_use"
    assert data["account"]["allocation"]["allocation_id"].startswith("alloc_")
    assert saved
    assert store[0]["allocation"]["allocation_id"] == data["account"]["allocation"]["allocation_id"]


def test_post_allocate_account_main_account_returns_reason(monkeypatch):
    _patch_account_store(monkeypatch, [_make_account(email="main@example.com", role="main")])

    data = api.post_allocate_account("main@example.com", api.AllocateAccountParams())

    assert data["changed"] is False
    assert data["reason"] == "main_account"
    assert data["warning"] is None


def test_post_allocate_account_non_inventory_returns_reason(monkeypatch):
    _patch_account_store(monkeypatch, [_make_account(usage_status=USAGE_NORMAL)])

    data = api.post_allocate_account("user@example.com", api.AllocateAccountParams())

    assert data["changed"] is False
    assert data["reason"] == "not_in_inventory"
    assert data["warning"] is None


def test_post_allocate_account_sold_returns_reason(monkeypatch):
    store, saved = _patch_account_store(monkeypatch, [_make_account(usage_status=USAGE_SOLD)])

    data = api.post_allocate_account("user@example.com", api.AllocateAccountParams())

    assert data["changed"] is False
    assert data["reason"] == "sold"
    assert data["warning"] is None
    assert data["account"]["usage_status"] == USAGE_SOLD
    assert saved
    assert store[0]["usage_status"] == USAGE_SOLD


def test_post_allocate_account_invalid_returns_reason(monkeypatch):
    _patch_account_store(monkeypatch, [_make_account(health_status=HEALTH_INVALID)])

    data = api.post_allocate_account("user@example.com", api.AllocateAccountParams())

    assert data["changed"] is False
    assert data["reason"] == "not_valid"
    assert data["warning"] is None


def test_post_release_account_success(monkeypatch):
    store, saved = _patch_account_store(
        monkeypatch,
        [
            _make_account(
                usage_status=USAGE_IN_USE,
                allocation={
                    "status": "in_use",
                    "allocation_id": "alloc_1",
                    "project": "proj-a",
                    "allocated_to": "worker-1",
                    "allocated_at": 123,
                },
            )
        ],
    )

    data = api.post_release_account("user@example.com", api.ReleaseAccountParams(reason="task_done"))

    assert data["changed"] is True
    assert data["reason"] is None
    assert data["account"]["usage_status"] == USAGE_INVENTORY
    assert data["account"]["allocation"]["status"] == "released"
    assert data["account"]["allocation"]["release_reason"] == "task_done"
    assert saved
    assert store[0]["allocation"]["status"] == "released"


def test_post_release_account_not_in_use_returns_reason(monkeypatch):
    _patch_account_store(monkeypatch, [_make_account(usage_status=USAGE_INVENTORY)])

    data = api.post_release_account("user@example.com", api.ReleaseAccountParams())

    assert data["changed"] is False
    assert data["reason"] == "not_in_use"
    assert data["warning"] is None


def test_post_release_account_main_account_returns_reason(monkeypatch):
    _patch_account_store(
        monkeypatch,
        [
            _make_account(
                email="main@example.com",
                role="main",
                usage_status=USAGE_IN_USE,
                allocation={"status": "in_use", "allocation_id": "alloc_1"},
            )
        ],
    )

    data = api.post_release_account("main@example.com", api.ReleaseAccountParams())

    assert data["changed"] is False
    assert data["reason"] == "main_account"
    assert data["warning"] is None


def test_post_release_account_sold_returns_reason(monkeypatch):
    _patch_account_store(
        monkeypatch,
        [
            _make_account(
                usage_status=USAGE_SOLD,
                allocation={"status": "sold", "allocation_id": "alloc_sold"},
            )
        ],
    )

    data = api.post_release_account("user@example.com", api.ReleaseAccountParams())

    assert data["changed"] is False
    assert data["reason"] == "sold"
    assert data["warning"] is None


def test_post_mark_invalid_account_success(monkeypatch):
    store, saved = _patch_account_store(monkeypatch, [_make_account()])

    data = api.post_mark_invalid_account(
        "user@example.com",
        api.MarkInvalidParams(reason=INVALID_REASON_AUTH_ERROR, last_error="HTTP 401"),
    )

    assert data["changed"] is True
    assert data["reason"] is None
    assert data["warning"] is None
    assert data["account"]["health_status"] == HEALTH_INVALID
    assert data["account"]["invalid_reason"] == INVALID_REASON_AUTH_ERROR
    assert saved
    assert store[0]["health_status"] == HEALTH_INVALID


def test_post_mark_invalid_account_rejects_bad_reason(monkeypatch):
    _patch_account_store(monkeypatch, [_make_account()])

    with pytest.raises(HTTPException) as exc_info:
        api.post_mark_invalid_account(
            "user@example.com",
            api.MarkInvalidParams(reason="bad_reason", last_error="HTTP 401"),
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "reason 非法"


def test_post_mark_invalid_account_main_account_returns_warning(monkeypatch):
    store, saved = _patch_account_store(
        monkeypatch,
        [_make_account(email="main@example.com", role="main")],
    )

    data = api.post_mark_invalid_account(
        "main@example.com",
        api.MarkInvalidParams(reason=INVALID_REASON_AUTH_ERROR, last_error="HTTP 401"),
    )

    assert data["changed"] is True
    assert data["reason"] is None
    assert data["warning"] == "main_account"
    assert data["account"]["health_status"] == HEALTH_INVALID
    assert saved
    assert store[0]["invalid_reason"] == INVALID_REASON_AUTH_ERROR


def test_post_repair_oauth_account_success(monkeypatch):
    store, saved = _patch_account_store(
        monkeypatch,
        [
            _make_account(
                health_status=HEALTH_INVALID,
                invalid_reason=INVALID_REASON_AUTH_ERROR,
                last_error="HTTP 401",
            )
        ],
    )

    data = api.post_repair_oauth_account("user@example.com", api.RepairOauthParams(note="manual reset"))

    assert data["changed"] is True
    assert data["reason"] is None
    assert data["warning"] is None
    assert data["account"]["health_status"] == HEALTH_VALID
    assert data["account"]["invalid_reason"] is None
    assert data["account"]["last_oauth_repair_note"] == "manual reset"
    assert isinstance(data["account"]["last_oauth_repair_at"], int)
    assert saved
    assert store[0]["health_status"] == HEALTH_VALID


def test_post_sell_account_main_account_raises_400(monkeypatch):
    monkeypatch.setattr(api, "_is_main_account_email", lambda email: email == "main@example.com")

    with pytest.raises(HTTPException) as exc_info:
        api.post_sell_account("main@example.com")

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "主号不允许标记为已售"


@pytest.mark.parametrize(
    "call",
    [
        lambda: api.post_allocate_account("missing@example.com", api.AllocateAccountParams()),
        lambda: api.post_release_account("missing@example.com", api.ReleaseAccountParams()),
        lambda: api.post_mark_invalid_account(
            "missing@example.com",
            api.MarkInvalidParams(reason=INVALID_REASON_AUTH_ERROR, last_error="HTTP 401"),
        ),
        lambda: api.post_repair_oauth_account("missing@example.com", api.RepairOauthParams()),
    ],
)
def test_account_inventory_ops_return_404_when_email_missing(monkeypatch, call):
    _patch_account_store(monkeypatch, [])

    with pytest.raises(HTTPException) as exc_info:
        call()

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "账号不存在"
