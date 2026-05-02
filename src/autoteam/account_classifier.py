"""账号分类辅助函数。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from autoteam.account_models import (
    HEALTH_DEACTIVATED,
    HEALTH_INVALID,
    HEALTH_RISK_BLOCKED,
    HEALTH_VALID,
    REGISTRATION_REGISTERED,
    USAGE_IN_USE,
    USAGE_INVENTORY,
    USAGE_SOLD,
)

CATEGORY_REGISTERED = "registered"
CATEGORY_INVENTORY = "inventory"
CATEGORY_IN_USE = "in_use"
CATEGORY_INVALID = "invalid"
CATEGORY_SOLD = "sold"
CATEGORY_NOT_REGISTERED = "not_registered"

CPA_STATUS_SUCCESS = "success"
LEGACY_STATUS_SOLD = "sold"
INVALID_HEALTH_STATUSES = frozenset(
    {
        HEALTH_INVALID,
        HEALTH_DEACTIVATED,
        HEALTH_RISK_BLOCKED,
    }
)


def _is_sold_account(acc: Mapping[str, Any]) -> bool:
    sale = acc.get("sale")
    sale_sold_at = sale.get("sold_at") if isinstance(sale, Mapping) else None
    return bool(
        sale_sold_at
        or acc.get("usage_status") == USAGE_SOLD
        or acc.get("status") == LEGACY_STATUS_SOLD
    )


def derive_category(acc: dict[str, Any] | None) -> str:
    data: Mapping[str, Any] = acc or {}

    if _is_sold_account(data):
        return CATEGORY_SOLD
    if data.get("health_status") in INVALID_HEALTH_STATUSES:
        return CATEGORY_INVALID
    if data.get("registration_status") != REGISTRATION_REGISTERED:
        return CATEGORY_NOT_REGISTERED
    if data.get("usage_status") == USAGE_IN_USE:
        return CATEGORY_IN_USE
    if (
        data.get("cpa_status") == CPA_STATUS_SUCCESS
        and data.get("health_status") == HEALTH_VALID
        and data.get("rt_auth_file")
        and not data.get("sync_disabled")
    ):
        return CATEGORY_INVENTORY
    return CATEGORY_REGISTERED


def classify_account(acc: dict[str, Any] | None, *, in_place: bool = True) -> dict[str, Any]:
    target: dict[str, Any]
    if acc is None:
        target = {}
    elif in_place:
        target = acc
    else:
        target = dict(acc)

    category = derive_category(target)
    if category == CATEGORY_SOLD:
        target["usage_status"] = USAGE_SOLD
        target["sync_disabled"] = True
    elif category == CATEGORY_INVENTORY:
        target["usage_status"] = USAGE_INVENTORY
    target["category"] = category
    return target


__all__ = [
    "CATEGORY_IN_USE",
    "CATEGORY_INVENTORY",
    "CATEGORY_INVALID",
    "CATEGORY_NOT_REGISTERED",
    "CATEGORY_REGISTERED",
    "CATEGORY_SOLD",
    "classify_account",
    "derive_category",
]
