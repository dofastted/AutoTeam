"""旧账号记录到 V2 四轴结构的兼容迁移。"""

from __future__ import annotations

import shutil
import time
from copy import deepcopy
from pathlib import Path
from typing import Any

from autoteam import accounts
from autoteam.account_models import (
    HEALTH_QUOTA_EXHAUSTED,
    HEALTH_UNKNOWN,
    HEALTH_VALID,
    REGISTRATION_PLANNED,
    REGISTRATION_REGISTERED,
    REGISTRATION_REGISTERING,
    REMOTE_STATUS_DISABLED,
    REMOTE_STATUS_FAILED,
    REMOTE_STATUS_PRESENT,
    REMOTE_STATUS_UNKNOWN,
    SCHEMA_VERSION,
    TEAM_ACTIVE,
    TEAM_UNKNOWN,
    USAGE_NORMAL,
    USAGE_SELF_USE,
    USAGE_SOLD,
    default_v2_account,
    legacy_status_to_axes,
)


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_key(value: Any) -> str:
    return _normalize_text(value).lower()


def _is_complete_v2_record(acc: dict[str, Any]) -> bool:
    return (
        isinstance(acc, dict)
        and int(acc.get("schema_version") or 0) >= SCHEMA_VERSION
        and bool(_normalize_text(acc.get("registration_status")))
        and bool(_normalize_text(acc.get("health_status")))
        and bool(_normalize_text(acc.get("usage_status")))
        and bool(_normalize_text(acc.get("team_status")))
    )


def _looks_like_session_auth_file(path_value: Any) -> bool:
    path_text = _normalize_text(path_value)
    if not path_text:
        return False
    return "-session." in Path(path_text).name.lower() or "session" in Path(path_text).stem.lower()


def _resolve_legacy_auth_paths(acc: dict[str, Any]) -> tuple[str, str]:
    session_file = _normalize_text(acc.get("session_auth_file"))
    rt_file = _normalize_text(acc.get("rt_auth_file"))
    auth_file = _normalize_text(acc.get("auth_file"))

    if not session_file and _looks_like_session_auth_file(auth_file):
        session_file = auth_file
    if not rt_file and auth_file and not _looks_like_session_auth_file(auth_file):
        rt_file = auth_file
    return session_file, rt_file


def _derive_registration_status(acc: dict[str, Any], rt_file: str) -> str:
    existing = _normalize_text(acc.get("registration_status"))
    if existing:
        return existing
    if _normalize_key(acc.get("cpa_status")) == "success":
        return REGISTRATION_REGISTERED
    if _normalize_text(acc.get("auth_file")) or rt_file:
        return REGISTRATION_REGISTERED
    return REGISTRATION_PLANNED


def _derive_usage_status(acc: dict[str, Any], legacy_axes: dict[str, Any]) -> str:
    existing = _normalize_text(acc.get("usage_status"))
    if existing:
        return existing
    if acc.get("self_use_at"):
        return USAGE_SELF_USE
    if legacy_axes.get("usage_status"):
        return str(legacy_axes["usage_status"])
    return USAGE_NORMAL


def _derive_team_status(acc: dict[str, Any], legacy_axes: dict[str, Any]) -> str:
    existing = _normalize_text(acc.get("team_status"))
    if existing:
        return existing
    mapped = _normalize_text(legacy_axes.get("team_status"))
    if mapped:
        return mapped
    return TEAM_UNKNOWN


def _derive_health_status(
    acc: dict[str, Any],
    legacy_status: str,
    legacy_axes: dict[str, Any],
    registration_status: str,
) -> str:
    existing = _normalize_text(acc.get("health_status"))
    if existing:
        return existing
    mapped = _normalize_text(legacy_axes.get("health_status"))
    if mapped:
        return mapped
    if legacy_status == "active":
        return HEALTH_VALID
    if registration_status == REGISTRATION_REGISTERED:
        return HEALTH_VALID
    return HEALTH_UNKNOWN


def _derive_sync_disabled(acc: dict[str, Any], legacy_axes: dict[str, Any]) -> bool:
    if "sync_disabled" in acc:
        return bool(acc.get("sync_disabled"))
    if "sync_disabled" in legacy_axes:
        return bool(legacy_axes["sync_disabled"])
    return False


def _build_mail_info(target: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    existing = target.get("mail") if isinstance(target.get("mail"), dict) else {}
    email = _normalize_text(source.get("email"))
    domain = existing.get("domain")
    if domain is None and "@" in email:
        domain = email.split("@", 1)[1]
    account_id = existing.get("account_id")
    if account_id is None:
        account_id = source.get("mail_account_id")
    if account_id is None:
        account_id = source.get("cloudmail_account_id")
    return {
        "provider": existing.get("provider", source.get("mail_provider")),
        "account_id": account_id,
        "domain": domain,
        "prefix": existing.get("prefix"),
        "index": existing.get("index"),
        "group_id": existing.get("group_id"),
    }


def _build_credentials_info(target: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    existing = target.get("credentials") if isinstance(target.get("credentials"), dict) else {}
    existing_session = existing.get("session") if isinstance(existing.get("session"), dict) else {}
    existing_oauth = existing.get("oauth_rt") if isinstance(existing.get("oauth_rt"), dict) else {}
    existing_archive = existing.get("cpa_archive") if isinstance(existing.get("cpa_archive"), dict) else {}

    session_file, rt_file = _resolve_legacy_auth_paths(source)
    archive_file = _normalize_text(source.get("cpa_archive_file"))

    session_file = _normalize_text(existing_session.get("file")) or session_file
    rt_file = _normalize_text(existing_oauth.get("file")) or rt_file
    archive_file = _normalize_text(existing_archive.get("file")) or archive_file

    existing_refresh_token_flag = existing_oauth.get("has_refresh_token")
    if isinstance(existing_refresh_token_flag, bool):
        has_refresh_token = existing_refresh_token_flag
    else:
        has_refresh_token = bool(rt_file)

    return {
        "session": {
            "file": session_file or None,
            "present": bool(session_file),
        },
        "oauth_rt": {
            "file": rt_file or None,
            "present": bool(rt_file),
            "has_refresh_token": has_refresh_token,
        },
        "cpa_archive": {
            "file": archive_file or None,
            "present": bool(archive_file),
        },
    }


def _build_remote_info(
    target: dict[str, Any],
    source: dict[str, Any],
    *,
    sync_disabled: bool,
) -> dict[str, Any]:
    existing = target.get("remote") if isinstance(target.get("remote"), dict) else {}
    existing_cpa = existing.get("cpa") if isinstance(existing.get("cpa"), dict) else {}
    existing_sub2api = existing.get("sub2api") if isinstance(existing.get("sub2api"), dict) else {}

    cpa_archive_file = _normalize_text(source.get("cpa_archive_file"))
    cpa_status = _normalize_key(source.get("cpa_status"))

    cpa_remote_status = _normalize_text(existing_cpa.get("status"))
    if not cpa_remote_status:
        if sync_disabled:
            cpa_remote_status = REMOTE_STATUS_DISABLED
        elif cpa_status == "success" or cpa_archive_file:
            cpa_remote_status = REMOTE_STATUS_PRESENT
        elif cpa_status == "failed":
            cpa_remote_status = REMOTE_STATUS_FAILED
        else:
            cpa_remote_status = REMOTE_STATUS_UNKNOWN

    sub2api_remote_status = _normalize_text(existing_sub2api.get("status"))
    if not sub2api_remote_status:
        sub2api_remote_status = REMOTE_STATUS_DISABLED if sync_disabled else REMOTE_STATUS_UNKNOWN

    return {
        "cpa": {
            "status": cpa_remote_status,
            "auth_name": existing_cpa.get("auth_name") or (Path(cpa_archive_file).name if cpa_archive_file else None),
            "group": existing_cpa.get("group"),
        },
        "sub2api": {
            "status": sub2api_remote_status,
            "auth_name": existing_sub2api.get("auth_name"),
            "group": existing_sub2api.get("group"),
        },
    }


def _build_allocation_info(target: dict[str, Any]) -> dict[str, Any]:
    existing = target.get("allocation") if isinstance(target.get("allocation"), dict) else {}
    return {
        "status": existing.get("status"),
        "project": existing.get("project"),
        "allocation_id": existing.get("allocation_id"),
    }


def _build_sale_info(target: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    existing = target.get("sale") if isinstance(target.get("sale"), dict) else {}
    return {
        "sold_at": existing.get("sold_at", source.get("sold_at")),
        "sold_to": existing.get("sold_to"),
        "sale_batch_id": existing.get("sale_batch_id"),
        "delivered": bool(existing.get("delivered", False)),
    }


def _migrate_account_record(acc: dict[str, Any], *, in_place: bool) -> tuple[dict[str, Any], bool]:
    if not isinstance(acc, dict):
        raise TypeError("account record must be a dict")

    if _is_complete_v2_record(acc):
        return (acc if in_place else deepcopy(acc)), False

    record = acc if in_place else deepcopy(acc)
    original_schema_version = int(record.get("schema_version") or 0)
    legacy_status = _normalize_key(record.get("status"))
    legacy_axes = legacy_status_to_axes(
        legacy_status,
        unavailable_reason=_normalize_text(record.get("unavailable_reason")),
    )

    if (
        legacy_status == "pending"
        and _normalize_text(record.get("registration_status")) == REGISTRATION_REGISTERED
    ):
        legacy_axes = dict(legacy_axes)
        legacy_axes.pop("registration_status", None)

    session_file, rt_file = _resolve_legacy_auth_paths(record)
    registration_status = _derive_registration_status(record, rt_file)
    if legacy_status == "pending" and registration_status != REGISTRATION_REGISTERED:
        registration_status = REGISTRATION_REGISTERING
    usage_status = _derive_usage_status(record, legacy_axes)
    sync_disabled = _derive_sync_disabled(record, legacy_axes)
    team_status = _derive_team_status(record, legacy_axes)
    health_status = _derive_health_status(record, legacy_status, legacy_axes, registration_status)

    now = time.time()
    base = default_v2_account()
    target = deepcopy(record)
    target["schema_version"] = max(original_schema_version, SCHEMA_VERSION)
    target["registration_status"] = registration_status
    target["health_status"] = health_status
    target["usage_status"] = usage_status
    target["team_status"] = team_status
    target["mail"] = _build_mail_info(target, record)
    target["credentials"] = _build_credentials_info(target, record)
    target["remote"] = _build_remote_info(target, record, sync_disabled=sync_disabled)
    target["allocation"] = _build_allocation_info(target)
    target["sale"] = _build_sale_info(target, record)
    target["sync_disabled"] = sync_disabled
    target["created_at"] = record.get("created_at") if record.get("created_at") is not None else now
    target["updated_at"] = now

    for key, value in base.items():
        target.setdefault(key, deepcopy(value))

    if in_place:
        record.clear()
        record.update(target)
        return record, True
    return target, True


def migrate_account_record(acc: dict, *, in_place: bool = True) -> dict:
    """把单条账号记录补齐到 V2 四轴结构。"""

    migrated, _ = _migrate_account_record(acc, in_place=in_place)
    return migrated


def migrate_accounts(accounts_list: list[dict], *, in_place: bool = True) -> list[dict]:
    """批量迁移账号记录。"""

    if in_place:
        for index, acc in enumerate(accounts_list):
            accounts_list[index], _ = _migrate_account_record(acc, in_place=True)
        return accounts_list
    return [migrate_account_record(acc, in_place=False) for acc in accounts_list]


def migrate_accounts_file(*, dry_run: bool = True) -> dict:
    """迁移 accounts.json 到 V2 结构，可选择只做 dry-run。"""

    accounts_file = accounts.ACCOUNTS_FILE
    if not accounts_file.exists():
        return {"total": 0, "skipped": "file_not_found"}

    report = {
        "total": 0,
        "migrated": 0,
        "unchanged": 0,
        "backup_path": None,
        "errors": [],
    }

    try:
        loaded = accounts.load_accounts()
    except Exception as exc:  # pragma: no cover - 防御性分支
        report["errors"].append(str(exc))
        return report

    if not isinstance(loaded, list):
        report["errors"].append("accounts.json root must be a list")
        return report

    report["total"] = len(loaded)
    migrated_accounts: list[dict[str, Any]] = []

    for index, acc in enumerate(loaded):
        try:
            migrated, changed = _migrate_account_record(acc, in_place=False)
        except Exception as exc:
            email = _normalize_text(acc.get("email")) if isinstance(acc, dict) else ""
            label = email or f"index={index}"
            report["errors"].append(f"{label}: {exc}")
            migrated_accounts.append(deepcopy(acc))
            continue
        migrated_accounts.append(migrated)
        if changed:
            report["migrated"] += 1
        else:
            report["unchanged"] += 1

    if dry_run:
        return report

    timestamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(time.time()))
    backup_path = accounts_file.with_name(f"{accounts_file.name}.bak-account-store-{timestamp}")
    shutil.copy2(accounts_file, backup_path)
    accounts.save_accounts(migrated_accounts)
    report["backup_path"] = str(backup_path)
    return report


__all__ = [
    "migrate_account_record",
    "migrate_accounts",
    "migrate_accounts_file",
]
