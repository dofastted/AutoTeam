"""账号远端同步状态辅助函数。"""

from __future__ import annotations

from copy import deepcopy
import time
from typing import Any

REMOTE_KIND_CPA = "cpa"
REMOTE_KIND_SUB2API = "sub2api"

REMOTE_STATUS_PRESENT = "present"
REMOTE_STATUS_MISSING = "missing"
REMOTE_STATUS_FAILED = "failed"
REMOTE_STATUS_DISABLED = "disabled"
REMOTE_STATUS_UNKNOWN = "unknown"

ALL_REMOTE_STATUSES = frozenset(
    {
        REMOTE_STATUS_PRESENT,
        REMOTE_STATUS_MISSING,
        REMOTE_STATUS_FAILED,
        REMOTE_STATUS_DISABLED,
        REMOTE_STATUS_UNKNOWN,
    }
)

_ALL_REMOTE_KINDS = frozenset({REMOTE_KIND_CPA, REMOTE_KIND_SUB2API})


def _validate_kind(kind: str) -> str:
    normalized = str(kind or "").strip().lower()
    if normalized not in _ALL_REMOTE_KINDS:
        raise ValueError(f"unsupported remote kind: {kind}")
    return normalized


def _validate_status(status: str) -> str:
    normalized = str(status or "").strip().lower()
    if normalized not in ALL_REMOTE_STATUSES:
        raise ValueError(f"unsupported remote status: {status}")
    return normalized


def _copy_account(account: dict[str, Any], *, in_place: bool) -> dict[str, Any]:
    return account if in_place else deepcopy(account)


def _build_remote_entry(
    *,
    status: str,
    checked_at: int,
    group: str | None = None,
    auth_name: str | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "status": status,
        "checked_at": checked_at,
    }
    if group is not None:
        entry["group"] = group
    if auth_name is not None:
        entry["auth_name"] = auth_name
    if error is not None:
        entry["error"] = error
    return entry


def default_remote_block() -> dict[str, dict[str, str]]:
    return {
        REMOTE_KIND_CPA: {"status": REMOTE_STATUS_UNKNOWN},
        REMOTE_KIND_SUB2API: {"status": REMOTE_STATUS_UNKNOWN},
    }


def set_remote_status(
    account: dict[str, Any],
    *,
    kind: str,
    status: str,
    group: str | None = None,
    auth_name: str | None = None,
    error: str | None = None,
    now: int | None = None,
    in_place: bool = True,
) -> dict[str, Any]:
    normalized_kind = _validate_kind(kind)
    normalized_status = _validate_status(status)
    checked_at = int(now if now is not None else time.time())

    target = _copy_account(account, in_place=in_place)
    remote_block = target.setdefault("remote", default_remote_block())
    next_block = _build_remote_entry(
        status=normalized_status,
        checked_at=checked_at,
        group=group,
        auth_name=auth_name,
        error=error,
    )
    changed = remote_block.get(normalized_kind) != next_block
    remote_block[normalized_kind] = next_block
    return {"changed": changed, "block": next_block}


def get_remote_status(account: dict[str, Any], kind: str) -> str:
    normalized_kind = _validate_kind(kind)
    remote_block = account.get("remote")
    if not isinstance(remote_block, dict):
        return REMOTE_STATUS_UNKNOWN

    item = remote_block.get(normalized_kind)
    if not isinstance(item, dict):
        return REMOTE_STATUS_UNKNOWN

    status = item.get("status")
    if isinstance(status, str) and status.strip():
        return status
    return REMOTE_STATUS_UNKNOWN


def summarize_remote(accounts: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    summary = {
        REMOTE_KIND_CPA: {status: 0 for status in ALL_REMOTE_STATUSES},
        REMOTE_KIND_SUB2API: {status: 0 for status in ALL_REMOTE_STATUSES},
    }

    for account in accounts:
        cpa_status = get_remote_status(account, REMOTE_KIND_CPA)
        sub2api_status = get_remote_status(account, REMOTE_KIND_SUB2API)
        summary[REMOTE_KIND_CPA][cpa_status] += 1
        summary[REMOTE_KIND_SUB2API][sub2api_status] += 1

    return summary


def apply_disabled_status(account: dict[str, Any], *, in_place: bool = True) -> dict[str, Any]:
    target = _copy_account(account, in_place=in_place)
    if target.get("sync_disabled") is not True:
        return {"changed": False, "block": target.get("remote")}

    checked_at = int(time.time())
    remote_block = target.setdefault("remote", default_remote_block())
    next_cpa = _build_remote_entry(status=REMOTE_STATUS_DISABLED, checked_at=checked_at)
    next_sub2api = _build_remote_entry(status=REMOTE_STATUS_DISABLED, checked_at=checked_at)
    changed = (
        remote_block.get(REMOTE_KIND_CPA) != next_cpa
        or remote_block.get(REMOTE_KIND_SUB2API) != next_sub2api
    )
    remote_block[REMOTE_KIND_CPA] = next_cpa
    remote_block[REMOTE_KIND_SUB2API] = next_sub2api
    return {"changed": changed, "block": remote_block}


__all__ = [
    "REMOTE_KIND_CPA",
    "REMOTE_KIND_SUB2API",
    "REMOTE_STATUS_PRESENT",
    "REMOTE_STATUS_MISSING",
    "REMOTE_STATUS_FAILED",
    "REMOTE_STATUS_DISABLED",
    "REMOTE_STATUS_UNKNOWN",
    "ALL_REMOTE_STATUSES",
    "default_remote_block",
    "set_remote_status",
    "get_remote_status",
    "summarize_remote",
    "apply_disabled_status",
]
