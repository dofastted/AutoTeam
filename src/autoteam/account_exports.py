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

SOLD_CSV_HEADER = [
    "email",
    "sold_at",
    "sold_to",
    "sale_price",
    "sale_note",
    "sale_batch_id",
    "plan_type",
    "original_inventory_at",
]


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _normalize_timestamp(value: Any) -> str:
    if value in (None, ""):
        return ""
    return str(value)


def _normalize_unix_timestamp(value: Any) -> str:
    if value in (None, ""):
        return ""
    try:
        return str(int(float(value)))
    except (TypeError, ValueError):
        return str(value)


def _mapping_value(mapping: Mapping[str, Any] | None, *keys: str) -> str:
    if not isinstance(mapping, Mapping):
        return ""
    for key in keys:
        value = mapping.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def _mapping_raw_value(mapping: Mapping[str, Any] | None, *keys: str) -> Any:
    if not isinstance(mapping, Mapping):
        return None
    for key in keys:
        value = mapping.get(key)
        if value not in (None, ""):
            return value
    return None


def _credential_path(account: Mapping[str, Any], credential_key: str) -> str:
    credentials = account.get("credentials")
    if not isinstance(credentials, Mapping):
        return ""
    credential = credentials.get(credential_key)
    return _mapping_value(credential if isinstance(credential, Mapping) else None, "path", "file")


def _is_inventory_account(account: Mapping[str, Any]) -> bool:
    return account.get("category") == "inventory" and account.get("is_main_account") is not True


def _is_sold_account(account: Mapping[str, Any]) -> bool:
    if str(account.get("usage_status") or "").strip().lower() == "sold":
        return True
    if str(account.get("status") or "").strip().lower() == "sold":
        return True

    sale = account.get("sale")
    return _mapping_raw_value(sale if isinstance(sale, Mapping) else None, "sold_at") is not None


def _sale_mapping(account: Mapping[str, Any]) -> Mapping[str, Any] | None:
    sale = account.get("sale")
    if isinstance(sale, Mapping):
        return sale
    return None


def _original_inventory_at(account: Mapping[str, Any]) -> str:
    inventory_at = account.get("inventory_at")
    if inventory_at not in (None, ""):
        return _normalize_unix_timestamp(inventory_at)

    allocation = account.get("allocation")
    allocated_at = _mapping_raw_value(allocation if isinstance(allocation, Mapping) else None, "allocated_at")
    return _normalize_unix_timestamp(allocated_at)


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


def export_sold_csv(accounts: list[dict], *, encoding: str = "utf-8-sig") -> str:
    """导出 sold 账号为 CSV 文本。"""

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(SOLD_CSV_HEADER)

    for account in accounts:
        if not isinstance(account, Mapping) or not _is_sold_account(account):
            continue

        sale = _sale_mapping(account)
        sold_at = _mapping_raw_value(sale, "sold_at")
        sold_to = _mapping_raw_value(sale, "sold_to", "buyer")
        sale_price = _mapping_raw_value(sale, "price")
        sale_note = _mapping_raw_value(sale, "note")
        sale_batch_id = _mapping_raw_value(sale, "batch_id", "sale_batch_id")

        writer.writerow(
            [
                _normalize_text(account.get("email")),
                _normalize_unix_timestamp(sold_at if sold_at not in (None, "") else account.get("sold_at")),
                _normalize_text(sold_to if sold_to not in (None, "") else account.get("sold_to")),
                _normalize_text(sale_price if sale_price not in (None, "") else account.get("sale_price")),
                _normalize_text(sale_note if sale_note not in (None, "") else account.get("sale_note")),
                _normalize_text(
                    sale_batch_id if sale_batch_id not in (None, "") else account.get("sale_batch_id")
                ),
                _normalize_text(account.get("plan_type")),
                _original_inventory_at(account),
            ]
        )

    csv_text = buffer.getvalue()
    if encoding.lower() == "utf-8-sig":
        return f"\ufeff{csv_text}"
    return csv_text


__all__ = ["export_inventory_csv", "export_sold_csv"]
