"""账号 V2 状态模型与兼容映射。

本模块不依赖 ``autoteam.accounts``，但状态字符串与其现有取值保持一致，
方便后续模块逐步从旧 ``status`` 字段迁到四轴状态模型。
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, TypedDict

SCHEMA_VERSION = 2

# 注册状态
REGISTRATION_PLANNED = "planned"
REGISTRATION_MAIL_CREATED = "mail_created"
REGISTRATION_REGISTERING = "registering"
REGISTRATION_REGISTERED = "registered"
REGISTRATION_REGISTER_FAILED = "register_failed"
REGISTRATION_ABANDONED = "abandoned"

ALL_REGISTRATION_STATUSES = frozenset(
    {
        REGISTRATION_PLANNED,
        REGISTRATION_MAIL_CREATED,
        REGISTRATION_REGISTERING,
        REGISTRATION_REGISTERED,
        REGISTRATION_REGISTER_FAILED,
        REGISTRATION_ABANDONED,
    }
)

# 健康状态
HEALTH_UNKNOWN = "unknown"
HEALTH_VALID = "valid"
HEALTH_QUOTA_EXHAUSTED = "quota_exhausted"
HEALTH_AUTH_EXPIRED = "auth_expired"
HEALTH_INVALID = "invalid"
HEALTH_DEACTIVATED = "deactivated"
HEALTH_RISK_BLOCKED = "risk_blocked"
HEALTH_SYNC_ERROR = "sync_error"

ALL_HEALTH_STATUSES = frozenset(
    {
        HEALTH_UNKNOWN,
        HEALTH_VALID,
        HEALTH_QUOTA_EXHAUSTED,
        HEALTH_AUTH_EXPIRED,
        HEALTH_INVALID,
        HEALTH_DEACTIVATED,
        HEALTH_RISK_BLOCKED,
        HEALTH_SYNC_ERROR,
    }
)

# 用途状态
USAGE_NORMAL = "normal"
USAGE_INVENTORY = "inventory"
USAGE_IN_USE = "in_use"
USAGE_RESERVED = "reserved"
USAGE_SOLD = "sold"
USAGE_SELF_USE = "self_use"
USAGE_QUARANTINE = "quarantine"

ALL_USAGE_STATUSES = frozenset(
    {
        USAGE_NORMAL,
        USAGE_INVENTORY,
        USAGE_IN_USE,
        USAGE_RESERVED,
        USAGE_SOLD,
        USAGE_SELF_USE,
        USAGE_QUARANTINE,
    }
)

# Team 状态
TEAM_UNKNOWN = "unknown"
TEAM_ACTIVE = "active"
TEAM_STANDBY = "standby"
TEAM_PENDING_INVITE = "pending_invite"
TEAM_REMOVED = "removed"
TEAM_EXTERNAL = "external"
TEAM_OWNER = "owner"

ALL_TEAM_STATUSES = frozenset(
    {
        TEAM_UNKNOWN,
        TEAM_ACTIVE,
        TEAM_STANDBY,
        TEAM_PENDING_INVITE,
        TEAM_REMOVED,
        TEAM_EXTERNAL,
        TEAM_OWNER,
    }
)

# 远端同步状态
REMOTE_STATUS_UNKNOWN = "unknown"
REMOTE_STATUS_PRESENT = "present"
REMOTE_STATUS_MISSING = "missing"
REMOTE_STATUS_UPLOADED = "uploaded"
REMOTE_STATUS_FAILED = "failed"
REMOTE_STATUS_DISABLED = "disabled"
REMOTE_STATUS_SKIPPED_SOLD = "skipped_sold"
REMOTE_STATUS_SKIPPED_INVALID = "skipped_invalid"

ALL_REMOTE_SYNC_STATUSES = frozenset(
    {
        REMOTE_STATUS_UNKNOWN,
        REMOTE_STATUS_PRESENT,
        REMOTE_STATUS_MISSING,
        REMOTE_STATUS_UPLOADED,
        REMOTE_STATUS_FAILED,
        REMOTE_STATUS_DISABLED,
        REMOTE_STATUS_SKIPPED_SOLD,
        REMOTE_STATUS_SKIPPED_INVALID,
    }
)


class MailInfoV2(TypedDict, total=False):
    provider: str | None
    account_id: str | int | None
    domain: str | None
    prefix: str | None
    index: int | None
    group_id: str | None


class SessionCredentialV2(TypedDict, total=False):
    file: str | None
    present: bool


class OAuthRtCredentialV2(TypedDict, total=False):
    file: str | None
    present: bool
    has_refresh_token: bool


class CpaArchiveCredentialV2(TypedDict, total=False):
    file: str | None
    present: bool


class CredentialsV2(TypedDict, total=False):
    session: SessionCredentialV2
    oauth_rt: OAuthRtCredentialV2
    cpa_archive: CpaArchiveCredentialV2


class RemoteTargetV2(TypedDict, total=False):
    status: str
    auth_name: str | None
    group: str | None


class RemoteInfoV2(TypedDict, total=False):
    cpa: RemoteTargetV2
    sub2api: RemoteTargetV2


class AllocationInfoV2(TypedDict, total=False):
    status: str | None
    project: str | None
    allocation_id: str | None


class SaleInfoV2(TypedDict, total=False):
    sold_at: float | None
    sold_to: str | None
    sale_batch_id: str | None
    delivered: bool


class AccountV2(TypedDict, total=False):
    schema_version: int
    id: str | None
    email: str | None
    password: str | None
    role: str | None
    registration_status: str
    health_status: str
    usage_status: str
    team_status: str
    category: str | None
    mail: MailInfoV2
    credentials: CredentialsV2
    cpa_status: str | None
    remote: RemoteInfoV2
    allocation: AllocationInfoV2
    sale: SaleInfoV2
    sync_disabled: bool
    created_at: float | None
    updated_at: float | None


def _deep_merge_dict(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge_dict(merged[key], value)
        else:
            merged[key] = value
    return merged


def _default_remote_target() -> RemoteTargetV2:
    return {"status": REMOTE_STATUS_UNKNOWN, "auth_name": None, "group": None}


def legacy_status_to_axes(
    legacy_status: str,
    *,
    unavailable_reason: str | None = None,
) -> dict[str, Any]:
    normalized_status = (legacy_status or "").strip().lower()
    normalized_reason = (unavailable_reason or "").strip().lower()

    if normalized_status == "active":
        return {"team_status": TEAM_ACTIVE}
    if normalized_status == "standby":
        return {"team_status": TEAM_STANDBY}
    if normalized_status == "exhausted":
        return {"health_status": HEALTH_QUOTA_EXHAUSTED, "team_status": TEAM_ACTIVE}
    if normalized_status == "sold":
        return {"usage_status": USAGE_SOLD, "sync_disabled": True}
    if normalized_status == "pending":
        return {"registration_status": REGISTRATION_REGISTERING}
    if normalized_status == "unavailable":
        health_status = HEALTH_DEACTIVATED if "deactivated" in normalized_reason else HEALTH_INVALID
        return {"health_status": health_status}
    return {}


def default_v2_account(**overrides: Any) -> AccountV2:
    account: AccountV2 = {
        "schema_version": SCHEMA_VERSION,
        "id": None,
        "email": None,
        "password": None,
        "role": None,
        "registration_status": REGISTRATION_PLANNED,
        "health_status": HEALTH_UNKNOWN,
        "usage_status": USAGE_NORMAL,
        "team_status": TEAM_UNKNOWN,
        "category": None,
        "mail": {
            "provider": None,
            "account_id": None,
            "domain": None,
            "prefix": None,
            "index": None,
            "group_id": None,
        },
        "credentials": {
            "session": {"file": None, "present": False},
            "oauth_rt": {"file": None, "present": False, "has_refresh_token": False},
            "cpa_archive": {"file": None, "present": False},
        },
        "cpa_status": None,
        "remote": {
            "cpa": _default_remote_target(),
            "sub2api": _default_remote_target(),
        },
        "allocation": {
            "status": None,
            "project": None,
            "allocation_id": None,
        },
        "sale": {
            "sold_at": None,
            "sold_to": None,
            "sale_batch_id": None,
            "delivered": False,
        },
        "sync_disabled": False,
        "created_at": None,
        "updated_at": None,
    }
    return _deep_merge_dict(account, overrides)


__all__ = [
    "AccountV2",
    "ALL_HEALTH_STATUSES",
    "ALL_REGISTRATION_STATUSES",
    "ALL_REMOTE_SYNC_STATUSES",
    "ALL_TEAM_STATUSES",
    "ALL_USAGE_STATUSES",
    "HEALTH_AUTH_EXPIRED",
    "HEALTH_DEACTIVATED",
    "HEALTH_INVALID",
    "HEALTH_QUOTA_EXHAUSTED",
    "HEALTH_RISK_BLOCKED",
    "HEALTH_SYNC_ERROR",
    "HEALTH_UNKNOWN",
    "HEALTH_VALID",
    "REGISTRATION_ABANDONED",
    "REGISTRATION_MAIL_CREATED",
    "REGISTRATION_PLANNED",
    "REGISTRATION_REGISTERED",
    "REGISTRATION_REGISTERING",
    "REGISTRATION_REGISTER_FAILED",
    "REMOTE_STATUS_DISABLED",
    "REMOTE_STATUS_FAILED",
    "REMOTE_STATUS_MISSING",
    "REMOTE_STATUS_PRESENT",
    "REMOTE_STATUS_SKIPPED_INVALID",
    "REMOTE_STATUS_SKIPPED_SOLD",
    "REMOTE_STATUS_UNKNOWN",
    "REMOTE_STATUS_UPLOADED",
    "SCHEMA_VERSION",
    "TEAM_ACTIVE",
    "TEAM_EXTERNAL",
    "TEAM_OWNER",
    "TEAM_PENDING_INVITE",
    "TEAM_REMOVED",
    "TEAM_STANDBY",
    "TEAM_UNKNOWN",
    "USAGE_IN_USE",
    "USAGE_INVENTORY",
    "USAGE_NORMAL",
    "USAGE_QUARANTINE",
    "USAGE_RESERVED",
    "USAGE_SELF_USE",
    "USAGE_SOLD",
    "default_v2_account",
    "legacy_status_to_axes",
]
