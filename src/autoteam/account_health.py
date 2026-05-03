"""账号健康状态辅助函数。"""

from __future__ import annotations

from copy import deepcopy
import time
from typing import Any

from autoteam.account_models import (
    HEALTH_DEACTIVATED,
    HEALTH_INVALID,
    HEALTH_UNKNOWN,
    USAGE_INVENTORY,
    USAGE_NORMAL,
)

INVALID_REASON_AUTH_ERROR = "auth_error"
INVALID_REASON_DEACTIVATED = "account_deactivated"
INVALID_REASON_TOKEN_REVOKED = "token_revoked"
INVALID_REASON_QUOTA = "quota_exhausted"

ALL_INVALID_REASONS = frozenset(
    {
        INVALID_REASON_AUTH_ERROR,
        INVALID_REASON_DEACTIVATED,
        INVALID_REASON_TOKEN_REVOKED,
        INVALID_REASON_QUOTA,
    }
)

_INVALID_HEALTH_STATUSES = frozenset({HEALTH_INVALID, HEALTH_DEACTIVATED})


def _normalize_key(value: Any) -> str:
    return str(value or "").strip().lower()


def _copy_account(account: dict[str, Any], *, in_place: bool) -> dict[str, Any]:
    return account if in_place else deepcopy(account)


def _append_applied(result: dict[str, Any], field: str) -> None:
    result["applied"].append(field)


def _set_if_changed(target: dict[str, Any], field: str, value: Any, result: dict[str, Any]) -> None:
    if target.get(field) == value:
        return
    target[field] = value
    result["changed"] = True
    _append_applied(result, field)


def mark_invalid(
    account: dict,
    *,
    reason: str,
    last_error: str = "",
    now: int | None = None,
    in_place: bool = True,
) -> dict:
    target = _copy_account(account, in_place=in_place)
    unix_ts = int(now if now is not None else time.time())
    result: dict[str, Any] = {
        "changed": False,
        "applied": [],
        "warning": None,
    }

    if _normalize_key(target.get("role")) == "main":
        result["warning"] = "main_account"

    _set_if_changed(target, "health_status", HEALTH_INVALID, result)
    _set_if_changed(target, "invalid_reason", reason, result)
    _set_if_changed(target, "invalid_at", unix_ts, result)
    _set_if_changed(target, "last_error", last_error, result)

    if _normalize_key(target.get("usage_status")) == USAGE_INVENTORY:
        target["usage_status"] = USAGE_NORMAL
        result["changed"] = True
        _append_applied(result, "usage_status_inventory_to_normal")

    _set_if_changed(target, "updated_at", unix_ts, result)
    return result


def mark_deactivated(
    account: dict,
    *,
    last_error: str = "",
    now: int | None = None,
    in_place: bool = True,
) -> dict:
    target = _copy_account(account, in_place=in_place)
    unix_ts = int(now if now is not None else time.time())
    result: dict[str, Any] = {
        "changed": False,
        "applied": [],
    }

    _set_if_changed(target, "health_status", HEALTH_DEACTIVATED, result)
    _set_if_changed(target, "invalid_reason", INVALID_REASON_DEACTIVATED, result)
    _set_if_changed(target, "invalid_at", unix_ts, result)
    _set_if_changed(target, "last_error", last_error, result)
    _set_if_changed(target, "sync_disabled", True, result)

    if _normalize_key(target.get("usage_status")) == USAGE_INVENTORY:
        target["usage_status"] = USAGE_NORMAL
        result["changed"] = True
        _append_applied(result, "usage_status_inventory_to_normal")

    _set_if_changed(target, "updated_at", unix_ts, result)
    return result


def is_invalid(account: dict) -> bool:
    return _normalize_key(account.get("health_status")) in _INVALID_HEALTH_STATUSES


def summarize_health(accounts: list[dict]) -> dict[str, int]:
    summary: dict[str, int] = {}
    for account in accounts:
        health_status = _normalize_key(account.get("health_status")) or HEALTH_UNKNOWN
        summary[health_status] = summary.get(health_status, 0) + 1
    return summary


__all__ = [
    "ALL_INVALID_REASONS",
    "INVALID_REASON_AUTH_ERROR",
    "INVALID_REASON_DEACTIVATED",
    "INVALID_REASON_QUOTA",
    "INVALID_REASON_TOKEN_REVOKED",
    "is_invalid",
    "mark_deactivated",
    "mark_invalid",
    "summarize_health",
]
