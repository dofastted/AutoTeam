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


def _normalize_email(value: Any) -> str:
    return _normalize_text(value).strip().lower()


def _normalize_header(value: Any) -> str:
    return _normalize_text(value).strip().lower()


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


def dry_run_import_csv(
    csv_text: str,
    existing_accounts: list[dict],
    *,
    required_columns: tuple[str, ...] = ("email",),
) -> dict:
    """解析 CSV 文本并返回导入预览报告。"""

    normalized_required_columns = tuple(
        column for column in (_normalize_header(name) for name in required_columns) if column
    )
    existing_emails = {
        _normalize_email(account.get("email"))
        for account in existing_accounts
        if isinstance(account, Mapping) and _normalize_email(account.get("email"))
    }
    report = {
        "headers": [],
        "row_count": 0,
        "to_add": [],
        "conflicts": [],
        "missing_fields": [],
        "invalid_rows": [],
        "summary": {
            "total_rows": 0,
            "to_add_count": 0,
            "conflict_count": 0,
            "missing_field_count": 0,
            "invalid_row_count": 0,
        },
    }

    if not csv_text:
        return report

    buffer = io.StringIO(csv_text.removeprefix("\ufeff"))

    try:
        reader = csv.DictReader(buffer)
    except csv.Error as exc:
        report["invalid_rows"].append({"row_index": 0, "reason": str(exc)})
        report["summary"]["invalid_row_count"] = 1
        return report

    raw_headers = list(reader.fieldnames or [])
    normalized_headers = [_normalize_header(header) for header in raw_headers]
    report["headers"] = normalized_headers

    seen_csv_emails: set[str] = set()
    row_index = 0

    try:
        for raw_row in reader:
            row_index += 1
            report["row_count"] = row_index

            if not isinstance(raw_row, dict):
                report["invalid_rows"].append({"row_index": row_index, "reason": "invalid_row_type"})
                continue

            if None in raw_row:
                report["invalid_rows"].append({"row_index": row_index, "reason": "extra_values"})
                continue

            row = {
                normalized_headers[index]: _normalize_text(raw_row.get(header))
                for index, header in enumerate(raw_headers)
                if normalized_headers[index]
            }
            missing = [column for column in normalized_required_columns if not row.get(column, "").strip()]
            if missing:
                report["missing_fields"].append({"row_index": row_index, "missing": missing})
                continue

            email = _normalize_text(row.get("email")).strip()
            normalized_email = email.lower()

            if normalized_email in seen_csv_emails:
                report["conflicts"].append(
                    {"row_index": row_index, "email": email, "reason": "duplicate_in_csv"}
                )
                continue

            seen_csv_emails.add(normalized_email)
            if normalized_email in existing_emails:
                report["conflicts"].append(
                    {"row_index": row_index, "email": email, "reason": "duplicate_email"}
                )
                continue

            report["to_add"].append(row)
    except csv.Error as exc:
        report["invalid_rows"].append({"row_index": row_index + 1, "reason": str(exc)})

    report["summary"] = {
        "total_rows": report["row_count"],
        "to_add_count": len(report["to_add"]),
        "conflict_count": len(report["conflicts"]),
        "missing_field_count": len(report["missing_fields"]),
        "invalid_row_count": len(report["invalid_rows"]),
    }
    return report


__all__ = ["dry_run_import_csv", "export_inventory_csv", "export_sold_csv"]
