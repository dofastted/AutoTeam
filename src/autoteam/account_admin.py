"""母号账号模型与守门辅助函数。"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Mapping
from typing import Any

from autoteam.account_models import (
    HEALTH_VALID,
    REGISTRATION_REGISTERED,
    SCHEMA_VERSION,
    TEAM_ACTIVE,
    TEAM_STANDBY,
    USAGE_NORMAL,
    default_v2_account,
)

ROLE_MAIN = "main"
ROLE_CHILD = "child"

MAIN_ALLOWED_USAGE = frozenset({USAGE_NORMAL})
MAIN_FORBIDDEN_USAGE = frozenset({"inventory", "in_use", "sold"})

_MAIN_ALLOWED_TEAM_STATUSES = frozenset({TEAM_ACTIVE, TEAM_STANDBY})
_MAIN_FORBIDDEN_CATEGORIES = frozenset({"inventory", "in_use", "sold"})


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_key(value: Any) -> str:
    return _normalize_text(value).lower()


def _default_main_account_id(email: str, unix_ts: int) -> str:
    digest = hashlib.md5(f"{email}:{unix_ts}".encode("utf-8")).hexdigest()[:8]
    return f"acct_main_{unix_ts}_{digest}"


def _append_issue(result: dict[str, Any], field: str, detail: str) -> None:
    if field not in result["violations"]:
        result["violations"].append(field)
    result["fixed"].append(detail)
    result["changed"] = True


def is_main_account(acc: dict) -> bool:
    return isinstance(acc, Mapping) and acc.get("role") == ROLE_MAIN


def default_main_account(
    *,
    email: str,
    password: str = "",
    id: str | None = None,
    now: int | None = None,
) -> dict[str, Any]:
    unix_ts = int(now if now is not None else time.time())
    account_id = id or _default_main_account_id(email, unix_ts)
    timestamp = float(unix_ts)

    account = default_v2_account(
        schema_version=SCHEMA_VERSION,
        id=account_id,
        email=email,
        password=password,
        role=ROLE_MAIN,
        registration_status=REGISTRATION_REGISTERED,
        health_status=HEALTH_VALID,
        usage_status=USAGE_NORMAL,
        team_status=TEAM_ACTIVE,
        sync_disabled=False,
        created_at=timestamp,
        updated_at=timestamp,
    )
    account["team_workspace_id"] = ""
    account["team_account_id"] = ""
    account["session_cookie_present"] = False
    account["main_codex_auth_file"] = ""
    return account


def enforce_main_role_invariants(acc: dict, *, in_place: bool = True) -> dict[str, Any]:
    result: dict[str, Any] = {"changed": False, "violations": [], "fixed": []}
    if not isinstance(acc, dict):
        return result

    target = acc if in_place else dict(acc)
    role_value = _normalize_key(target.get("role"))
    if role_value != ROLE_MAIN:
        return result

    if target.get("role") != ROLE_MAIN:
        target["role"] = ROLE_MAIN
        _append_issue(result, "role", "role=main")

    usage_status = _normalize_key(target.get("usage_status"))
    if usage_status in MAIN_FORBIDDEN_USAGE:
        target["usage_status"] = USAGE_NORMAL
        _append_issue(result, "usage_status", "usage_status=normal")

    team_status = _normalize_key(target.get("team_status"))
    if team_status not in _MAIN_ALLOWED_TEAM_STATUSES:
        target["team_status"] = TEAM_ACTIVE
        _append_issue(result, "team_status", "team_status=active")

    category = _normalize_key(target.get("category"))
    if category in _MAIN_FORBIDDEN_CATEGORIES and "category" in target:
        del target["category"]
        _append_issue(result, "category", "category removed")

    if target.get("sync_disabled") is not False:
        target["sync_disabled"] = False
        _append_issue(result, "sync_disabled", "sync_disabled=false")

    return result


def summarize_main_accounts(accounts: list[dict]) -> dict[str, int]:
    summary = {
        "total": 0,
        "with_session_cookie": 0,
        "with_codex_auth": 0,
        "active": 0,
    }

    for account in accounts:
        if not is_main_account(account):
            continue
        summary["total"] += 1
        if bool(account.get("session_cookie_present")):
            summary["with_session_cookie"] += 1
        if bool(_normalize_text(account.get("main_codex_auth_file"))):
            summary["with_codex_auth"] += 1
        if _normalize_key(account.get("team_status")) == TEAM_ACTIVE:
            summary["active"] += 1

    return summary


__all__ = [
    "MAIN_ALLOWED_USAGE",
    "MAIN_FORBIDDEN_USAGE",
    "ROLE_CHILD",
    "ROLE_MAIN",
    "default_main_account",
    "enforce_main_role_invariants",
    "is_main_account",
    "record_main_codex_auth",
    "record_main_session",
    "summarize_session_cookie",
    "summarize_main_accounts",
]


def summarize_session_cookie(cookie_value: str | bytes | None) -> dict[str, Any]:
    if cookie_value in (None, "", b""):
        return {"length": 0, "fingerprint": "", "captured_at": 0}

    raw_value = cookie_value if isinstance(cookie_value, bytes) else str(cookie_value).encode("utf-8")
    return {
        "length": len(cookie_value),
        "fingerprint": hashlib.sha256(raw_value).hexdigest()[:16],
        "captured_at": int(time.time()),
    }


def record_main_session(
    account: dict,
    cookie_value: str | bytes | None,
    *,
    in_place: bool = True,
    now: int | None = None,
) -> dict[str, Any]:
    if not is_main_account(account):
        return {"changed": False, "reason": "not_main"}

    target = account if in_place else dict(account)
    summary = summarize_session_cookie(cookie_value)
    if now is not None and summary["length"]:
        summary["captured_at"] = int(now)

    session_cookie_present = bool(summary["length"])
    changed = (
        target.get("session_cookie_present") != session_cookie_present
        or target.get("session_cookie_summary") != summary
    )

    target["session_cookie_present"] = session_cookie_present
    target["session_cookie_summary"] = summary

    return {"changed": changed, "summary": summary}


def record_main_codex_auth(
    account: dict,
    auth_file_path: str | Path | None,
    *,
    in_place: bool = True,
    now: int | None = None,
) -> dict[str, Any]:
    if not is_main_account(account):
        return {"changed": False, "reason": "not_main"}

    from autoteam.account_credentials import identify_credential_file

    checked_at = int(now if now is not None else time.time())
    target = account if in_place else dict(account)
    path_str = str(auth_file_path or "").strip()

    if not path_str:
        status = {
            "present": False,
            "has_refresh_token": False,
            "checked_at": checked_at,
        }
    else:
        identified = identify_credential_file(path_str)
        present = identified["type"] not in {"missing", "invalid_json"}
        has_refresh_token = bool(identified.get("details", {}).get("has_refresh_token"))
        if present and not has_refresh_token:
            import json

            from pathlib import Path as _Path

            try:
                payload = json.loads(_Path(path_str).read_text(encoding="utf-8"))
            except Exception:
                payload = {}

            if isinstance(payload, Mapping):
                direct_refresh_token = str(payload.get("refresh_token") or "").strip()
                nested_tokens = payload.get("tokens")
                nested_refresh_token = (
                    str(nested_tokens.get("refresh_token") or "").strip()
                    if isinstance(nested_tokens, Mapping)
                    else ""
                )
                has_refresh_token = bool(direct_refresh_token or nested_refresh_token)

        status = {
            "present": present,
            "has_refresh_token": has_refresh_token,
            "checked_at": checked_at,
        }

    changed = (
        target.get("main_codex_auth_file") != path_str
        or target.get("main_codex_auth_status") != status
    )

    target["main_codex_auth_file"] = path_str
    target["main_codex_auth_status"] = status

    return {"changed": changed, "status": status}
