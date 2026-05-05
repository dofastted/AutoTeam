"""RT recovery classification and resume helpers."""

from __future__ import annotations

import time
from collections import Counter
from collections.abc import Iterable
from copy import deepcopy
from pathlib import Path
from typing import Any

from autoteam import accounts
from autoteam.account_models import (
    HEALTH_DEACTIVATED,
    HEALTH_INVALID,
    HEALTH_UNKNOWN,
    REGISTRATION_REGISTERED,
    USAGE_SOLD,
)
from autoteam.codex_auth import get_existing_session_auth_file, select_oauth_rt_auth_file

RT_CATEGORY_READY = "rt_ready"
RT_CATEGORY_MISSING_REGISTERED = "rt_missing_registered"
RT_CATEGORY_401_REAUTH_NEEDED = "rt_401_reauth_needed"
RT_CATEGORY_DEACTIVATED_INVALID = "deactivated_invalid"
RT_CATEGORY_NOT_REGISTERED = "not_registered"
RT_CATEGORY_SOLD = "sold"
RT_CATEGORY_MAIN = "main"
RT_CATEGORY_SKIPPED = "skipped"

RECOVERABLE_CATEGORIES = frozenset({RT_CATEGORY_MISSING_REGISTERED, RT_CATEGORY_401_REAUTH_NEEDED})
DEACTIVATED_MARKERS = frozenset({"deactivated", "account_deactivated"})
HTTP_401_MARKERS = frozenset(
    {
        "401",
        "http_401",
        "refresh_token_reused",
        "token_invalid",
        "token_invalidated",
        "token_revoked",
        "auth_error",
    }
)
REGISTERED_STATUSES = frozenset({REGISTRATION_REGISTERED, "success", "completed", "complete", "done"})

ERROR_FIELDS = (
    "unavailable_reason",
    "invalid_reason",
    "last_error",
    "cpa_error_message",
    "flow_error_message",
    "sync_error_message",
    "cpa_error",
    "error",
)


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


def _nested_error_text(value: Any) -> str:
    parts: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = _normalize(key)
            if key_text.endswith("reason") or "error" in key_text or "status" in key_text:
                parts.append(str(item or ""))
            if isinstance(item, (dict, list, tuple)):
                parts.append(_nested_error_text(item))
        return " ".join(part for part in parts if part)
    if isinstance(value, (list, tuple)):
        return " ".join(_nested_error_text(item) for item in value)
    return ""


def account_error_text(account: dict[str, Any] | None) -> str:
    account = account or {}
    parts = [str(account.get(field) or "") for field in ERROR_FIELDS]
    parts.append(_nested_error_text(account))
    return " ".join(part for part in parts if part).strip()


def has_deactivated_marker(account: dict[str, Any] | None) -> bool:
    text = account_error_text(account).lower()
    if any(marker in text for marker in DEACTIVATED_MARKERS):
        return True
    return _normalize((account or {}).get("health_status")) == HEALTH_DEACTIVATED


def has_401_marker(account: dict[str, Any] | None) -> bool:
    text = account_error_text(account).lower()
    if any(marker in text for marker in HTTP_401_MARKERS):
        return True
    return _normalize((account or {}).get("health_status")) in {"http401", "http_401"}


def is_registered_account(account: dict[str, Any] | None) -> bool:
    account = account or {}
    if _normalize(account.get("registration_status")) in REGISTERED_STATUSES:
        return True
    if _normalize(account.get("status")) in {"active", "standby", "exhausted", "unavailable"}:
        return True
    return bool(account.get("session_auth_file") or account.get("rt_auth_file") or account.get("auth_file"))


def is_sold_account(account: dict[str, Any] | None) -> bool:
    account = account or {}
    sale = account.get("sale") if isinstance(account.get("sale"), dict) else {}
    return bool(
        _normalize(account.get("usage_status")) == USAGE_SOLD
        or _normalize(account.get("status")) == "sold"
        or account.get("sold_at")
        or sale.get("sold_at")
    )


def classify_rt_recovery_account(account: dict[str, Any] | None, *, is_main: bool = False) -> dict[str, Any]:
    """Classify one account for OAuth RT recovery."""

    data = account or {}
    email = _normalize(data.get("email"))
    has_rt = bool(select_oauth_rt_auth_file(data))
    session_file = get_existing_session_auth_file(data)
    has_session = bool(session_file and Path(session_file).exists())
    registered = is_registered_account(data)
    deactivated = has_deactivated_marker(data)
    http_401 = has_401_marker(data)

    if is_main:
        category = RT_CATEGORY_MAIN
        recoverable = False
        reason = "主号不属于账号池 RT 恢复对象"
    elif is_sold_account(data):
        category = RT_CATEGORY_SOLD
        recoverable = False
        reason = "已售账号不自动恢复"
    elif deactivated:
        category = RT_CATEGORY_DEACTIVATED_INVALID
        recoverable = False
        reason = "错误文本包含 Deactivated，需标记失效"
    elif not registered:
        category = RT_CATEGORY_NOT_REGISTERED
        recoverable = False
        reason = "注册未完成"
    elif http_401:
        category = RT_CATEGORY_401_REAUTH_NEEDED
        recoverable = True
        reason = "检测到 401 或 token 失效，需要重新获取 RT"
    elif has_rt:
        category = RT_CATEGORY_READY
        recoverable = False
        reason = "已有可上传 OAuth RT"
    else:
        category = RT_CATEGORY_MISSING_REGISTERED
        recoverable = True
        reason = "注册完成但缺少 OAuth RT"

    return {
        "email": email,
        "category": category,
        "recoverable": recoverable,
        "reason": reason,
        "registered": registered,
        "has_rt": has_rt,
        "has_session": has_session,
        "session_auth_file": session_file,
        "sync_disabled": _is_truthy(data.get("sync_disabled")),
        "status": data.get("status") or "",
        "registration_status": data.get("registration_status") or "",
        "health_status": data.get("health_status") or "",
        "usage_status": data.get("usage_status") or "",
        "unavailable_reason": data.get("unavailable_reason") or "",
        "last_error": data.get("last_error") or data.get("cpa_error_message") or data.get("flow_error_message") or "",
    }


def scan_rt_recovery_accounts(
    account_items: list[dict[str, Any]] | None = None,
    *,
    main_email: str | None = None,
) -> dict[str, Any]:
    """Return RT recovery categories without mutating accounts."""

    items = account_items if account_items is not None else accounts.load_accounts()
    normalized_main = _normalize(main_email)
    rows = [
        classify_rt_recovery_account(item, is_main=bool(normalized_main and _normalize(item.get("email")) == normalized_main))
        for item in items
        if isinstance(item, dict)
    ]
    summary = Counter(row["category"] for row in rows)
    recoverable = [row for row in rows if row["recoverable"]]
    deactivated = [row for row in rows if row["category"] == RT_CATEGORY_DEACTIVATED_INVALID]
    return {
        "total_accounts": len(rows),
        "summary": {key: summary.get(key, 0) for key in sorted(summary)},
        "recoverable_count": len(recoverable),
        "deactivated_count": len(deactivated),
        "items": rows,
        "recoverable": recoverable,
        "deactivated": deactivated,
    }


def mark_deactivated_invalid_accounts(
    account_items: list[dict[str, Any]],
    *,
    emails: Iterable[str] | None = None,
    now: int | None = None,
) -> dict[str, Any]:
    """Mark Deactivated accounts invalid in-place."""

    email_filter = {_normalize(email) for email in emails or [] if _normalize(email)}
    unix_ts = int(now if now is not None else time.time())
    changed = 0
    rows: list[dict[str, Any]] = []

    for account in account_items:
        if not isinstance(account, dict):
            continue
        email = _normalize(account.get("email"))
        if not email or (email_filter and email not in email_filter):
            continue
        scan = classify_rt_recovery_account(account)
        if scan["category"] != RT_CATEGORY_DEACTIVATED_INVALID:
            continue

        before = deepcopy(account)
        account["status"] = accounts.STATUS_UNAVAILABLE
        account["health_status"] = HEALTH_DEACTIVATED
        account["invalid_reason"] = "account_deactivated"
        account["unavailable_reason"] = "account_deactivated"
        account["sync_disabled"] = True
        account["unavailable_at"] = unix_ts
        account["invalid_at"] = unix_ts
        account["updated_at"] = unix_ts
        if _normalize(account.get("usage_status")) == "inventory":
            account["usage_status"] = "normal"
        if account != before:
            changed += 1
        rows.append({"email": email, "changed": account != before, "reason": scan["reason"]})

    return {"changed": changed, "accounts": rows}


def prepare_account_for_rt_recovery(account: dict[str, Any], *, force: bool = False, now: int | None = None) -> dict[str, Any]:
    """Clear recoverable stale invalid markers before an explicit RT retry."""

    scan = classify_rt_recovery_account(account)
    if not scan["recoverable"]:
        return {"changed": False, "applied": [], "reason": scan["reason"], "category": scan["category"]}
    if scan["sync_disabled"] and not force:
        return {"changed": False, "applied": [], "reason": "账号已停止同步，恢复时需要 force=true", "category": scan["category"]}

    unix_ts = int(now if now is not None else time.time())
    changed = False
    applied: list[str] = []

    def set_if_changed(field: str, value: Any) -> None:
        nonlocal changed
        if account.get(field) == value:
            return
        account[field] = value
        changed = True
        applied.append(field)

    if force and scan["category"] == RT_CATEGORY_401_REAUTH_NEEDED:
        set_if_changed("sync_disabled", False)
        set_if_changed("status", accounts.STATUS_STANDBY)
        set_if_changed("health_status", HEALTH_UNKNOWN)
        set_if_changed("unavailable_reason", "")
        set_if_changed("invalid_reason", "")
        set_if_changed("last_error", "")
        set_if_changed("cpa_error_message", "")
        set_if_changed("flow_error_message", "")
    else:
        if _normalize(account.get("health_status")) in {HEALTH_INVALID, "auth_expired", "sync_error"}:
            set_if_changed("health_status", HEALTH_UNKNOWN)

    set_if_changed("last_rt_recovery_attempt_at", unix_ts)
    return {"changed": changed, "applied": applied, "reason": None, "category": scan["category"]}


__all__ = [
    "RECOVERABLE_CATEGORIES",
    "RT_CATEGORY_401_REAUTH_NEEDED",
    "RT_CATEGORY_DEACTIVATED_INVALID",
    "RT_CATEGORY_MISSING_REGISTERED",
    "classify_rt_recovery_account",
    "mark_deactivated_invalid_accounts",
    "prepare_account_for_rt_recovery",
    "scan_rt_recovery_accounts",
]
