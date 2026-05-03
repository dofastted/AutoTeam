"""库存账号分配纯函数。"""

from __future__ import annotations

import random
import time
from copy import deepcopy
from typing import Any

from autoteam import accounts as legacy_accounts
from autoteam.account_models import HEALTH_VALID, USAGE_IN_USE, USAGE_INVENTORY, USAGE_SOLD

ALLOCATION_STATUS_INVENTORY = "inventory"
ALLOCATION_STATUS_IN_USE = "in_use"
ALLOCATION_STATUS_RELEASED = "released"
ALLOCATION_STATUS_SOLD = "sold"

_HEX_DIGITS = "0123456789abcdef"
_NON_ALLOCATABLE_USAGE = frozenset({USAGE_SOLD})


def _normalize_key(value: Any) -> str:
    return str(value or "").strip().lower()


def _copy_account(account: dict[str, Any], *, in_place: bool) -> dict[str, Any]:
    return account if in_place else deepcopy(account)


def _append_field(result: dict[str, Any], field: str) -> None:
    result["applied"].append(field)


def _set_if_changed(target: dict[str, Any], field: str, value: Any, result: dict[str, Any]) -> None:
    if target.get(field) == value:
        return
    target[field] = value
    result["changed"] = True
    _append_field(result, field)


def _set_nested_if_changed(
    target: dict[str, Any],
    field: str,
    value: Any,
    result: dict[str, Any],
    *,
    applied_name: str,
) -> None:
    if target.get(field) == value:
        return
    target[field] = value
    result["changed"] = True
    _append_field(result, applied_name)


def _result_payload(
    target: dict[str, Any],
    *,
    changed: bool = False,
    applied: list[str] | None = None,
    reason: str | None = None,
    allocation_id: str | None = None,
) -> dict[str, Any]:
    return {
        "changed": changed,
        "applied": applied or [],
        "reason": reason,
        "allocation_id": allocation_id,
        "account": target,
    }


def _gen_allocation_id(now: int | None = None, *, rng: random.Random | None = None) -> str:
    unix_ts = int(now if now is not None else time.time())
    rand = rng if rng is not None else random.Random()
    short_hash = "".join(rand.choice(_HEX_DIGITS) for _ in range(6))
    return f"alloc_{unix_ts}_{short_hash}"


def allocate_account(
    account: dict,
    *,
    project: str = "",
    allocated_to: str = "",
    allocation_id: str | None = None,
    force: bool = False,
    now: int | None = None,
    in_place: bool = True,
) -> dict:
    target = _copy_account(account, in_place=in_place)
    usage_status = _normalize_key(target.get("usage_status"))
    role = _normalize_key(target.get("role"))
    health_status = _normalize_key(target.get("health_status"))
    cpa_status = _normalize_key(target.get("cpa_status"))

    if role == "main":
        return _result_payload(target, reason="main_account")

    if usage_status in _NON_ALLOCATABLE_USAGE:
        return _result_payload(target, reason="sold")

    if health_status != HEALTH_VALID:
        return _result_payload(target, reason="not_valid")

    if usage_status == USAGE_IN_USE and not force:
        return _result_payload(target, reason="already_in_use")

    allow_reallocate = force and usage_status == USAGE_IN_USE
    if usage_status != USAGE_INVENTORY and not allow_reallocate:
        return _result_payload(target, reason="not_in_inventory")

    if cpa_status != legacy_accounts.CPA_STATUS_SUCCESS:
        return _result_payload(target, reason="not_in_inventory")

    unix_ts = int(now if now is not None else time.time())
    resolved_allocation_id = allocation_id or _gen_allocation_id(unix_ts)
    result: dict[str, Any] = {
        "changed": False,
        "applied": [],
        "reason": None,
        "allocation_id": resolved_allocation_id,
        "account": target,
    }

    _set_if_changed(target, "usage_status", ALLOCATION_STATUS_IN_USE, result)

    allocation = target.get("allocation")
    if not isinstance(allocation, dict):
        allocation = {}
        target["allocation"] = allocation

    _set_nested_if_changed(
        allocation,
        "status",
        ALLOCATION_STATUS_IN_USE,
        result,
        applied_name="allocation.status",
    )
    _set_nested_if_changed(allocation, "project", project, result, applied_name="allocation.project")
    _set_nested_if_changed(
        allocation,
        "allocation_id",
        resolved_allocation_id,
        result,
        applied_name="allocation.allocation_id",
    )
    _set_nested_if_changed(
        allocation,
        "allocated_to",
        allocated_to,
        result,
        applied_name="allocation.allocated_to",
    )
    _set_nested_if_changed(
        allocation,
        "allocated_at",
        unix_ts,
        result,
        applied_name="allocation.allocated_at",
    )

    _set_if_changed(target, "updated_at", unix_ts, result)
    return result


__all__ = [
    "ALLOCATION_STATUS_INVENTORY",
    "ALLOCATION_STATUS_IN_USE",
    "ALLOCATION_STATUS_RELEASED",
    "ALLOCATION_STATUS_SOLD",
    "allocate_account",
]
