"""账号库存导出辅助函数。"""

from __future__ import annotations

import csv
import io
from collections.abc import Mapping
from typing import Any

CSV_HEADER = [
    "email",
    "password",
    "cpa_json_path",
    "auth_file_path",
    "plan_type",
    "registered_at",
    "updated_at",
    "note",
]


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _normalize_timestamp(value: Any) -> str:
    if value in (None, ""):
        return ""
    return str(value)


def _mapping_value(mapping: Mapping[str, Any] | None, *keys: str) -> str:
    if not isinstance(mapping, Mapping):
        return ""
    for key in keys:
        value = mapping.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def _credential_path(account: Mapping[str, Any], credential_key: str) -> str:
    credentials = account.get("credentials")
    if not isinstance(credentials, Mapping):
        return ""
    credential = credentials.get(credential_key)
    return _mapping_value(credential if isinstance(credential, Mapping) else None, "path", "file")


def _is_inventory_account(account: Mapping[str, Any]) -> bool:
    return account.get("category") == "inventory" and account.get("is_main_account") is not True


def export_inventory_csv(accounts: list[dict], *, encoding: str = "utf-8-sig") -> str:
    """导出 inventory 账号为 CSV 文本。"""

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(CSV_HEADER)

    for account in accounts:
        if not isinstance(account, Mapping) or not _is_inventory_account(account):
            continue

        cpa_json_path = _credential_path(account, "cpa_archive") or _normalize_text(account.get("cpa_json"))
        auth_file_path = (
            _credential_path(account, "oauth_rt")
            or _normalize_text(account.get("rt_auth_file"))
            or _normalize_text(account.get("auth_file"))
        )

        writer.writerow(
            [
                _normalize_text(account.get("email")),
                _normalize_text(account.get("password")),
                cpa_json_path,
                auth_file_path,
                _normalize_text(account.get("plan_type")),
                _normalize_timestamp(account.get("registered_at")),
                _normalize_timestamp(account.get("updated_at")),
                _normalize_text(account.get("note")),
            ]
        )

    csv_text = buffer.getvalue()
    if encoding.lower() == "utf-8-sig":
        return f"\ufeff{csv_text}"
    return csv_text


__all__ = ["export_inventory_csv"]
