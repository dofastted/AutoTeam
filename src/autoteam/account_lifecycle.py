"""账号生命周期状态变迁纯函数。"""

from __future__ import annotations

import time
from copy import deepcopy
from pathlib import Path
from typing import Any

from autoteam import accounts as legacy_accounts
from autoteam.account_models import HEALTH_VALID, REGISTRATION_REGISTERED, TEAM_ACTIVE, USAGE_NORMAL

LIFECYCLE_EVENT_REGISTERED = "registered"

_PRESERVED_USAGE_STATUSES = frozenset({"inventory", "in_use", "sold"})

# 旧模块仍暴露 success 常量；V2 注册成功值需要统一到 registered。
legacy_accounts.REGISTRATION_STATUS_SUCCESS = REGISTRATION_REGISTERED


def _normalize_key(value: Any) -> str:
    return str(value or "").strip().lower()


def _append_field(result: dict[str, Any], bucket: str, field: str) -> None:
    result[bucket].append(field)


def _set_if_changed(target: dict[str, Any], field: str, value: Any, result: dict[str, Any]) -> None:
    if target.get(field) == value:
        _append_field(result, "skipped", field)
        return
    target[field] = value
    result["changed"] = True
    _append_field(result, "applied", field)


def mark_registered(account: dict, *, now: int | None = None, in_place: bool = True) -> dict:
    target = account if in_place else dict(account)
    unix_ts = int(now if now is not None else time.time())
    result: dict[str, Any] = {"changed": False, "applied": [], "skipped": []}

    _set_if_changed(target, "registration_status", REGISTRATION_REGISTERED, result)
    _set_if_changed(target, "team_status", TEAM_ACTIVE, result)

    usage_status = _normalize_key(target.get("usage_status"))
    if usage_status in _PRESERVED_USAGE_STATUSES:
        _append_field(result, "skipped", "usage_status")
    else:
        _set_if_changed(target, "usage_status", USAGE_NORMAL, result)

    _set_if_changed(target, "updated_at", unix_ts, result)
    return result


def registered_kwargs(*, now: int | None = None) -> dict[str, Any]:
    unix_ts = int(now if now is not None else time.time())
    return {
        "registration_status": REGISTRATION_REGISTERED,
        "team_status": TEAM_ACTIVE,
        "usage_status": USAGE_NORMAL,
        "updated_at": unix_ts,
    }


def record_rt_obtained(
    account: dict,
    rt_file_path: str | Path,
    *,
    has_refresh_token: bool | None = None,
    now: int | None = None,
    in_place: bool = True,
) -> dict:
    from autoteam.account_credentials import is_uploadable_oauth_rt

    target = account if in_place else deepcopy(account)
    path_str = str(rt_file_path)
    unix_ts = int(now if now is not None else time.time())
    resolved_has_refresh_token = (
        is_uploadable_oauth_rt(rt_file_path) if has_refresh_token is None else bool(has_refresh_token)
    )
    result: dict[str, Any] = {
        "changed": False,
        "applied": [],
        "skipped": [],
        "has_refresh_token": resolved_has_refresh_token,
    }

    _set_if_changed(target, "rt_auth_file", path_str, result)
    _set_if_changed(target, "rt_obtained_at", unix_ts, result)

    credentials = target.setdefault("credentials", {})
    if not isinstance(credentials, dict):
        credentials = {}
        target["credentials"] = credentials
    oauth_rt = credentials.setdefault("oauth_rt", {})
    if not isinstance(oauth_rt, dict):
        oauth_rt = {}
        credentials["oauth_rt"] = oauth_rt

    _set_if_changed(oauth_rt, "file", path_str, result)
    if result["applied"] and result["applied"][-1] == "file":
        result["applied"][-1] = "credentials.oauth_rt.file"
    _set_if_changed(oauth_rt, "present", True, result)
    if result["applied"] and result["applied"][-1] == "present":
        result["applied"][-1] = "credentials.oauth_rt.present"
    _set_if_changed(oauth_rt, "has_refresh_token", resolved_has_refresh_token, result)
    if result["applied"] and result["applied"][-1] == "has_refresh_token":
        result["applied"][-1] = "credentials.oauth_rt.has_refresh_token"
    _set_if_changed(oauth_rt, "obtained_at", unix_ts, result)
    if result["applied"] and result["applied"][-1] == "obtained_at":
        result["applied"][-1] = "credentials.oauth_rt.obtained_at"

    _set_if_changed(target, "updated_at", unix_ts, result)
    result.pop("skipped", None)
    return result


def rt_obtained_kwargs(
    rt_file_path: str | Path,
    *,
    has_refresh_token: bool | None = None,
    now: int | None = None,
) -> dict[str, Any]:
    if has_refresh_token is None:
        from autoteam.account_credentials import is_uploadable_oauth_rt

        is_uploadable_oauth_rt(rt_file_path)
    unix_ts = int(now if now is not None else time.time())
    return {
        "rt_auth_file": str(rt_file_path),
        "rt_obtained_at": unix_ts,
        "updated_at": unix_ts,
    }


__all__ = [
    "HEALTH_VALID",
    "LIFECYCLE_EVENT_REGISTERED",
    "mark_registered",
    "record_rt_obtained",
    "registered_kwargs",
    "rt_obtained_kwargs",
]
