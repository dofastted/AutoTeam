import random

from autoteam.account_inventory import (
    ALLOCATION_STATUS_IN_USE,
    allocate_account,
    release_account,
    _gen_allocation_id,
)


def _inventory_account(**overrides):
    account = {
        "id": "acct_1",
        "email": "stock@example.com",
        "registration_status": "registered",
        "usage_status": "inventory",
        "health_status": "valid",
        "cpa_status": "success",
    }
    account.update(overrides)
    return account


def test_allocate_account_allocates_inventory_account():
    account = _inventory_account()

    result = allocate_account(
        account,
        project="proj-a",
        allocated_to="worker-1",
        allocation_id="custom-1",
        now=12345,
    )

    assert result == {
        "changed": True,
        "applied": [
            "usage_status",
            "allocation.status",
            "allocation.project",
            "allocation.allocation_id",
            "allocation.allocated_to",
            "allocation.allocated_at",
            "updated_at",
        ],
        "reason": None,
        "allocation_id": "custom-1",
        "account": account,
    }
    assert account["usage_status"] == "in_use"
    assert account["updated_at"] == 12345
    assert account["allocation"] == {
        "status": "in_use",
        "project": "proj-a",
        "allocation_id": "custom-1",
        "allocated_to": "worker-1",
        "allocated_at": 12345,
    }


def test_allocate_account_rejects_main_account():
    account = _inventory_account(role="main")

    result = allocate_account(account, now=12345)

    assert result["changed"] is False
    assert result["reason"] == "main_account"
    assert result["allocation_id"] is None
    assert "allocation" not in account


def test_allocate_account_rejects_sold_account():
    account = _inventory_account(usage_status="sold")

    result = allocate_account(account, now=12345)

    assert result["changed"] is False
    assert result["reason"] == "sold"
    assert account["usage_status"] == "sold"


def test_allocate_account_rejects_already_in_use_account():
    account = _inventory_account(
        usage_status="in_use",
        allocation={"status": "in_use", "project": "old", "allocation_id": "alloc-old"},
    )

    result = allocate_account(account, project="proj-b", now=12345)

    assert result["changed"] is False
    assert result["reason"] == "already_in_use"
    assert account["allocation"]["project"] == "old"


def test_allocate_account_force_reallocates_existing_in_use_account():
    account = _inventory_account(
        usage_status="in_use",
        updated_at=1,
        allocation={
            "status": "in_use",
            "project": "old-project",
            "allocation_id": "alloc-old",
            "allocated_to": "old-user",
            "allocated_at": 1,
        },
    )

    result = allocate_account(
        account,
        project="proj-new",
        allocated_to="worker-2",
        allocation_id="custom-2",
        force=True,
        now=20000,
    )

    assert result["changed"] is True
    assert result["reason"] is None
    assert result["allocation_id"] == "custom-2"
    assert result["applied"] == [
        "allocation.project",
        "allocation.allocation_id",
        "allocation.allocated_to",
        "allocation.allocated_at",
        "updated_at",
    ]
    assert account["usage_status"] == ALLOCATION_STATUS_IN_USE
    assert account["allocation"] == {
        "status": "in_use",
        "project": "proj-new",
        "allocation_id": "custom-2",
        "allocated_to": "worker-2",
        "allocated_at": 20000,
    }
    assert account["updated_at"] == 20000


def test_allocate_account_rejects_non_inventory_account():
    account = _inventory_account(
        registration_status="planned",
        usage_status="normal",
    )

    result = allocate_account(account, now=12345)

    assert result["changed"] is False
    assert result["reason"] == "not_in_inventory"


def test_allocate_account_rejects_invalid_health_status():
    account = _inventory_account(health_status="invalid")

    result = allocate_account(account, now=12345)

    assert result["changed"] is False
    assert result["reason"] == "not_valid"


def test_gen_allocation_id_is_reproducible_with_seed():
    allocation_id = _gen_allocation_id(now=1700000000, rng=random.Random(7))

    assert allocation_id == "alloc_1700000000_a4c123"


def test_allocate_account_generates_allocation_id_when_missing(monkeypatch):
    account = _inventory_account()

    monkeypatch.setattr(
        "autoteam.account_inventory._gen_allocation_id",
        lambda now=None, rng=None: "alloc_12345_a4c123",
    )

    result = allocate_account(account, project="proj-a", allocated_to="worker-1", now=12345)

    assert result["changed"] is True
    assert result["allocation_id"] == "alloc_12345_a4c123"
    assert account["allocation"]["allocation_id"] == "alloc_12345_a4c123"


def test_allocate_account_returns_copied_account_when_not_in_place():
    original = _inventory_account()

    result = allocate_account(
        original,
        project="proj-copy",
        allocated_to="copy-user",
        allocation_id="copy-1",
        now=888,
        in_place=False,
    )

    copied = result["account"]
    assert copied is not original
    assert copied["usage_status"] == "in_use"
    assert copied["allocation"]["allocation_id"] == "copy-1"
    assert original["usage_status"] == "inventory"
    assert "allocation" not in original


def test_release_account_releases_in_use_account_back_to_inventory():
    account = _inventory_account(
        usage_status="in_use",
        updated_at=1,
        allocation={
            "status": "in_use",
            "allocation_id": "alloc_123",
            "project": "proj-a",
            "allocated_to": "worker-1",
            "allocated_at": 100,
        },
    )

    result = release_account(account, now=200)

    assert result == {
        "changed": True,
        "applied": [
            "usage_status",
            "allocation.status",
            "allocation.released_at",
            "allocation.release_reason",
            "updated_at",
        ],
        "reason": None,
        "warning": None,
        "account": account,
    }
    assert account["usage_status"] == "inventory"
    assert account["updated_at"] == 200
    assert account["allocation"] == {
        "status": "released",
        "allocation_id": "alloc_123",
        "project": "proj-a",
        "allocated_to": "worker-1",
        "allocated_at": 100,
        "released_at": 200,
        "release_reason": "",
    }


def test_release_account_writes_release_reason():
    account = _inventory_account(
        usage_status="in_use",
        allocation={
            "status": "in_use",
            "allocation_id": "alloc_123",
            "project": "proj-a",
            "allocated_to": "worker-1",
            "allocated_at": 100,
        },
    )

    result = release_account(account, reason="task_done", now=300)

    assert result["changed"] is True
    assert account["allocation"]["release_reason"] == "task_done"


def test_release_account_rejects_account_not_in_use():
    account = _inventory_account(usage_status="inventory")

    result = release_account(account, now=12345)

    assert result == {
        "changed": False,
        "applied": [],
        "reason": "not_in_use",
        "warning": None,
        "account": account,
    }


def test_release_account_rejects_main_account():
    account = _inventory_account(
        role="main",
        usage_status="in_use",
        allocation={
            "status": "in_use",
            "allocation_id": "alloc_123",
            "project": "proj-a",
            "allocated_to": "worker-1",
            "allocated_at": 100,
        },
    )

    result = release_account(account, now=12345)

    assert result == {
        "changed": False,
        "applied": [],
        "reason": "main_account",
        "warning": None,
        "account": account,
    }
    assert account["usage_status"] == "in_use"
    assert account["allocation"]["status"] == "in_use"


def test_release_account_rejects_sold_account():
    account = _inventory_account(usage_status="sold")

    result = release_account(account, now=12345)

    assert result == {
        "changed": False,
        "applied": [],
        "reason": "sold",
        "warning": None,
        "account": account,
    }


def test_release_account_warns_when_health_is_not_valid():
    account = _inventory_account(
        usage_status="in_use",
        health_status="invalid",
        allocation={
            "status": "in_use",
            "allocation_id": "alloc_123",
            "project": "proj-a",
            "allocated_to": "worker-1",
            "allocated_at": 100,
        },
    )

    result = release_account(account, now=12345)

    assert result["changed"] is True
    assert result["reason"] is None
    assert result["warning"] == "not_valid"
    assert account["usage_status"] == "inventory"
    assert account["allocation"]["status"] == "released"


def test_release_account_returns_copied_account_when_not_in_place():
    original = _inventory_account(
        usage_status="in_use",
        allocation={
            "status": "in_use",
            "allocation_id": "alloc_123",
            "project": "proj-a",
            "allocated_to": "worker-1",
            "allocated_at": 100,
        },
    )

    result = release_account(original, reason="task_done", now=555, in_place=False)

    copied = result["account"]
    assert copied is not original
    assert copied["usage_status"] == "inventory"
    assert copied["allocation"]["status"] == "released"
    assert copied["allocation"]["release_reason"] == "task_done"
    assert original["usage_status"] == "in_use"
    assert original["allocation"]["status"] == "in_use"
    assert "released_at" not in original["allocation"]
