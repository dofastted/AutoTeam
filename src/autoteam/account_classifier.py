"""账号分类辅助函数。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from autoteam.account_models import (
    HEALTH_DEACTIVATED,
    HEALTH_INVALID,
    HEALTH_RISK_BLOCKED,
    HEALTH_SYNC_ERROR,
    REGISTRATION_REGISTERED,
    REMOTE_STATUS_DISABLED,
    REMOTE_STATUS_MISSING,
    REMOTE_STATUS_PRESENT,
    REMOTE_STATUS_UPLOADED,
    USAGE_IN_USE,
    USAGE_INVENTORY,
    USAGE_NORMAL,
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
LEGACY_STATUS_PENDING = "pending"
LEGACY_STATUS_UNAVAILABLE = "unavailable"
REGISTERED_STATUSES = frozenset({REGISTRATION_REGISTERED, "success", "completed", "complete", "done"})
INVALID_HEALTH_STATUSES = frozenset(
    {
        HEALTH_INVALID,
        HEALTH_DEACTIVATED,
        HEALTH_RISK_BLOCKED,
        HEALTH_SYNC_ERROR,
        "risk",
        "http401",
        "http_401",
    }
)
INVALID_TEXT_MARKERS = frozenset(
    {
        "401",
        "account_deactivated",
        "auth_error",
        "deactivated",
        "http_401",
        "invalid_username_or_password",
        "passwordless_login_blocked",
        "refresh_token_reused",
        "token_invalid",
        "token_invalidated",
        "token_revoked",
    }
)
USAGE_RECLASSIFIABLE = frozenset({USAGE_IN_USE, USAGE_INVENTORY})
SUB2API_PRESENT_STATUSES = frozenset({REMOTE_STATUS_PRESENT, REMOTE_STATUS_UPLOADED})


def _normalize(value: Any) -> str:
    return str(value or "").strip().lower()


def _is_truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return bool(value)
    return _normalize(value) in {"1", "true", "yes", "on", "enabled"}


def _is_sold_account(acc: Mapping[str, Any]) -> bool:
    sale = acc.get("sale")
    sale_sold_at = sale.get("sold_at") if isinstance(sale, Mapping) else None
    return bool(
        sale_sold_at
        or _normalize(acc.get("usage_status")) == USAGE_SOLD
        or _normalize(acc.get("status")) == LEGACY_STATUS_SOLD
    )


def _has_invalid_failure_marker(acc: Mapping[str, Any]) -> bool:
    if _normalize(acc.get("status")) == LEGACY_STATUS_UNAVAILABLE:
        return True
    if _normalize(acc.get("health_status")) in INVALID_HEALTH_STATUSES:
        return True
    if _contains_401_field(acc):
        return True
    for key in (
        "unavailable_reason",
        "invalid_reason",
        "last_error",
        "cpa_error_message",
        "flow_error_message",
        "sync_error_message",
    ):
        value = str(acc.get(key) or "").strip().lower()
        if value and any(marker in value for marker in INVALID_TEXT_MARKERS):
            return True
    return False


def _contains_401_field(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized_key = str(key or "").strip().lower()
            if "401" in normalized_key and item not in (None, "", False):
                return True
            if normalized_key.endswith("reason") or "error" in normalized_key or "status" in normalized_key:
                text = str(item or "").strip().lower()
                if text and any(marker in text for marker in INVALID_TEXT_MARKERS):
                    return True
            if isinstance(item, Mapping) and _contains_401_field(item):
                return True
        return False
    if isinstance(value, (list, tuple)):
        return any(_contains_401_field(item) for item in value)
    return False


def _registration_complete(acc: Mapping[str, Any]) -> bool:
    return _normalize(acc.get("registration_status")) in REGISTERED_STATUSES


def _has_oauth_rt(acc: Mapping[str, Any]) -> bool:
    if acc.get("rt_auth_file"):
        return True

    auth_file = _normalize(acc.get("auth_file"))
    if auth_file and ("-oauth" in auth_file or "oauth" in auth_file):
        return True

    credentials = acc.get("credentials")
    if not isinstance(credentials, Mapping):
        return False

    oauth_rt = credentials.get("oauth_rt") or credentials.get("rt_auth_file")
    if not isinstance(oauth_rt, Mapping):
        return False
    return bool(
        oauth_rt.get("file")
        and oauth_rt.get("present", True) is not False
        and oauth_rt.get("has_refresh_token", True) is not False
    )


def is_usable_account(acc: Mapping[str, Any]) -> bool:
    """Return whether the account is locally safe to use or sync."""

    return bool(
        not _is_sold_account(acc)
        and _registration_complete(acc)
        and not _is_truthy(acc.get("sync_disabled"))
        and _normalize(acc.get("status")) not in {LEGACY_STATUS_SOLD, LEGACY_STATUS_UNAVAILABLE, LEGACY_STATUS_PENDING}
        and _normalize(acc.get("health_status")) not in INVALID_HEALTH_STATUSES
        and _has_oauth_rt(acc)
        and not _has_invalid_failure_marker(acc)
    )


def has_sub2api_presence(acc: Mapping[str, Any]) -> bool:
    remote = acc.get("remote")
    if not isinstance(remote, Mapping):
        return False
    sub2api = remote.get("sub2api")
    if not isinstance(sub2api, Mapping):
        return False
    return _normalize(sub2api.get("status")) in SUB2API_PRESENT_STATUSES


def _resolve_sub2api_present(acc: Mapping[str, Any], sub2api_present: bool | None) -> bool:
    if sub2api_present is not None:
        return bool(sub2api_present)
    return has_sub2api_presence(acc)


def derive_category(acc: dict[str, Any] | None, *, sub2api_present: bool | None = None) -> str:
    data: Mapping[str, Any] = acc or {}

    if _is_sold_account(data):
        return CATEGORY_SOLD
    if _normalize(data.get("health_status")) in INVALID_HEALTH_STATUSES or _has_invalid_failure_marker(data):
        return CATEGORY_INVALID
    if not _registration_complete(data):
        return CATEGORY_NOT_REGISTERED
    usable = is_usable_account(data)
    if usable and _resolve_sub2api_present(data, sub2api_present):
        return CATEGORY_IN_USE
    if (
        usable
        and _normalize(data.get("cpa_status")) == CPA_STATUS_SUCCESS
    ):
        return CATEGORY_INVENTORY
    return CATEGORY_REGISTERED


def _set_if_changed(target: dict[str, Any], key: str, value: Any, applied: list[str]) -> None:
    if target.get(key) == value:
        return
    target[key] = value
    applied.append(key)


def _ensure_allocation_status(target: dict[str, Any], status: str, applied: list[str]) -> None:
    allocation = target.get("allocation")
    if not isinstance(allocation, dict):
        allocation = {}
        target["allocation"] = allocation
    if allocation.get("status") == status:
        return
    allocation["status"] = status
    applied.append("allocation.status")


def _set_sub2api_remote_status(target: dict[str, Any], present: bool, applied: list[str]) -> None:
    remote = target.get("remote")
    if not isinstance(remote, dict):
        remote = {}
        target["remote"] = remote
    sub2api = remote.get("sub2api")
    if not isinstance(sub2api, dict):
        sub2api = {}
        remote["sub2api"] = sub2api
    desired = REMOTE_STATUS_PRESENT if present else REMOTE_STATUS_MISSING
    if target.get("sync_disabled") is True or _is_sold_account(target):
        desired = REMOTE_STATUS_DISABLED
    if sub2api.get("status") == desired:
        return
    sub2api["status"] = desired
    applied.append("remote.sub2api.status")


def classify_account(
    acc: dict[str, Any] | None,
    *,
    in_place: bool = True,
    sub2api_present: bool | None = None,
) -> dict[str, Any]:
    target: dict[str, Any]
    if acc is None:
        target = {}
    elif in_place:
        target = acc
    else:
        target = dict(acc)

    category = derive_category(target, sub2api_present=sub2api_present)
    if category == CATEGORY_SOLD:
        target["usage_status"] = USAGE_SOLD
        target["sync_disabled"] = True
    elif category == CATEGORY_IN_USE:
        target["usage_status"] = USAGE_IN_USE
    elif category == CATEGORY_INVENTORY:
        target["usage_status"] = USAGE_INVENTORY
    elif _normalize(target.get("usage_status")) in USAGE_RECLASSIFIABLE:
        target["usage_status"] = USAGE_NORMAL
    target["category"] = category
    return target


def reconcile_usage_classification(
    acc: dict[str, Any],
    *,
    sub2api_present: bool | None = None,
    in_place: bool = True,
) -> dict[str, Any]:
    target = acc if in_place else dict(acc or {})
    applied: list[str] = []

    previous_usage = target.get("usage_status")
    previous_category = target.get("category")
    classify_account(target, in_place=True, sub2api_present=sub2api_present)

    if target.get("usage_status") != previous_usage:
        applied.append("usage_status")
    if target.get("category") != previous_category:
        applied.append("category")

    category = target.get("category")
    if category == CATEGORY_SOLD:
        _set_if_changed(target, "status", LEGACY_STATUS_SOLD, applied)
        _set_if_changed(target, "sync_disabled", True, applied)
        _ensure_allocation_status(target, USAGE_SOLD, applied)
    elif category == CATEGORY_IN_USE:
        _ensure_allocation_status(target, USAGE_IN_USE, applied)
    elif category == CATEGORY_INVENTORY:
        _ensure_allocation_status(target, USAGE_INVENTORY, applied)
    elif category == CATEGORY_INVALID:
        _set_if_changed(target, "status", LEGACY_STATUS_UNAVAILABLE, applied)
        allocation = target.get("allocation")
        if isinstance(allocation, dict) and allocation.get("status") in USAGE_RECLASSIFIABLE:
            allocation["status"] = "released"
            applied.append("allocation.status")
    elif category == CATEGORY_NOT_REGISTERED:
        allocation = target.get("allocation")
        if isinstance(allocation, dict) and allocation.get("status") in USAGE_RECLASSIFIABLE:
            allocation["status"] = "released"
            applied.append("allocation.status")

    if sub2api_present is not None:
        _set_sub2api_remote_status(target, bool(sub2api_present), applied)

    return {
        "changed": bool(applied),
        "applied": applied,
        "category": target.get("category"),
        "usage_status": target.get("usage_status"),
        "account": target,
    }


__all__ = [
    "CATEGORY_IN_USE",
    "CATEGORY_INVENTORY",
    "CATEGORY_INVALID",
    "CATEGORY_NOT_REGISTERED",
    "CATEGORY_REGISTERED",
    "CATEGORY_SOLD",
    "classify_account",
    "derive_category",
    "has_sub2api_presence",
    "is_usable_account",
    "reconcile_usage_classification",
]
