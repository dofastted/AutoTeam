"""accounts.json 清理辅助工具。

AT-003 backup; AT-004 scan.
AT-005 dedupe added.
AT-008 reclassify added.
"""

from __future__ import annotations

from copy import deepcopy
import shutil
from datetime import datetime
from pathlib import Path

from autoteam import accounts

BACKUP_TAG = "account-clean"
accounts_module = accounts


def backup_accounts_file(
    *,
    accounts_file: Path | None = None,
    tag: str = BACKUP_TAG,
    now: datetime | None = None,
) -> Path | None:
    """为 accounts.json 生成带时间戳的同目录备份文件。"""

    target_file = accounts_file or accounts.ACCOUNTS_FILE
    if not target_file.exists():
        return None

    backup_time = now or datetime.now()
    timestamp = backup_time.strftime("%Y%m%d-%H%M%S")
    backup_path = target_file.with_name(f"{target_file.name}.bak-{tag}-{timestamp}")
    shutil.copy2(target_file, backup_path)
    return backup_path


__all__ = ["BACKUP_TAG", "backup_accounts_file"]

import csv
import io
import json
from collections import defaultdict
from collections.abc import Iterable, Mapping

from autoteam.account_classifier import classify_account, derive_category
from autoteam.account_credentials import (
    CREDENTIAL_TYPE_MISSING,
    CREDENTIAL_TYPE_SESSION,
    identify_credential_file,
    is_uploadable_oauth_rt,
    migrate_accounts_credentials,
)
from autoteam.account_models import REGISTRATION_REGISTERED, USAGE_INVENTORY, USAGE_SOLD
from autoteam.account_store import migrate_accounts

SCAN_ISSUE_KEYS = (
    "duplicate_emails",
    "missing_password",
    "missing_rt_auth_file",
    "session_used_as_auth_file",
    "sold_sync_enabled",
    "invalid_in_inventory",
    "cpa_success_not_inventory",
    "missing_credential_file",
)

_DEDUP_PREFERRED_USAGE_STATUSES = {"inventory", "in_use", "sold"}
_DEDUP_PROTECTED_FIELDS = {"id", "created_at", "updated_at"}


def _scan_normalize_text(value: object) -> str:
    return str(value or "").strip()


def _scan_normalize_key(value: object) -> str:
    return _scan_normalize_text(value).lower()


def _dedupe_is_missing(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) == 0
    return False


def _dedupe_copy_value(value: object) -> object:
    return deepcopy(value)


def _dedupe_get_credentials_oauth_file(account: Mapping[str, object]) -> str:
    credentials = account.get("credentials")
    if not isinstance(credentials, Mapping):
        return ""
    oauth_rt = credentials.get("oauth_rt")
    if not isinstance(oauth_rt, Mapping):
        return ""
    return _scan_normalize_text(oauth_rt.get("file"))


def _dedupe_has_rt_reference(account: Mapping[str, object]) -> bool:
    return bool(
        _scan_normalize_text(account.get("rt_auth_file")) or _dedupe_get_credentials_oauth_file(account)
    )


def _dedupe_created_sort_key(account: Mapping[str, object]) -> tuple[int, str]:
    created_at = _scan_normalize_text(account.get("created_at"))
    if not created_at:
        return (1, "")
    try:
        parsed = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError:
        return (0, created_at)
    return (0, parsed.isoformat())


def _dedupe_id_sort_key(account: Mapping[str, object]) -> tuple[int, str]:
    account_id = _scan_normalize_text(account.get("id"))
    if not account_id:
        return (1, "")
    return (0, account_id)


def _dedupe_merge_mapping(primary: dict[str, object], alias: Mapping[str, object]) -> bool:
    changed = False
    for key, alias_value in alias.items():
        if key not in primary or _dedupe_is_missing(primary.get(key)):
            primary[key] = _dedupe_copy_value(alias_value)
            changed = True
            continue

        primary_value = primary.get(key)
        if isinstance(primary_value, dict) and isinstance(alias_value, Mapping):
            if _dedupe_merge_mapping(primary_value, alias_value):
                changed = True
    return changed


def _dedupe_append_merged_from(primary: dict[str, object], alias: Mapping[str, object]) -> None:
    merged_from = primary.get("merged_from")
    if not isinstance(merged_from, list):
        merged_from = []
        primary["merged_from"] = merged_from

    seen_ids = {str(item) for item in merged_from if str(item).strip()}

    alias_ids: list[str] = []
    alias_id = _scan_normalize_text(alias.get("id"))
    if alias_id:
        alias_ids.append(alias_id)

    alias_merged_from = alias.get("merged_from")
    if isinstance(alias_merged_from, list):
        for item in alias_merged_from:
            item_text = _scan_normalize_text(item)
            if item_text:
                alias_ids.append(item_text)

    for item_text in alias_ids:
        if item_text in seen_ids:
            continue
        merged_from.append(item_text)
        seen_ids.add(item_text)


def _scan_is_sold_account(account: Mapping[str, object]) -> bool:
    sale = account.get("sale")
    sale_sold_at = sale.get("sold_at") if isinstance(sale, Mapping) else None
    return bool(
        sale_sold_at
        or _scan_normalize_key(account.get("usage_status")) == USAGE_SOLD
        or _scan_normalize_key(account.get("status")) == USAGE_SOLD
    )


def _scan_is_registered_account(account: Mapping[str, object]) -> bool:
    if _scan_normalize_key(account.get("registration_status")) == REGISTRATION_REGISTERED:
        return True
    return bool(
        _scan_normalize_text(account.get("auth_file"))
        or _scan_normalize_text(account.get("rt_auth_file"))
        or _scan_normalize_text(account.get("session_auth_file"))
        or _scan_normalize_key(account.get("cpa_status")) == "success"
    )


def _scan_account_summary(account: Mapping[str, object], **extra: object) -> dict[str, object]:
    return {
        "id": account.get("id"),
        "email": _scan_normalize_text(account.get("email")),
        "category": derive_category(dict(account)),
        "status": _scan_normalize_text(account.get("status")) or None,
        "registration_status": _scan_normalize_text(account.get("registration_status")) or None,
        "health_status": _scan_normalize_text(account.get("health_status")) or None,
        "usage_status": _scan_normalize_text(account.get("usage_status")) or None,
        "cpa_status": _scan_normalize_text(account.get("cpa_status")) or None,
        "sync_disabled": account.get("sync_disabled"),
        "has_password": bool(_scan_normalize_text(account.get("password"))),
        "auth_file": _scan_normalize_text(account.get("auth_file")) or None,
        "rt_auth_file": _scan_normalize_text(account.get("rt_auth_file")) or None,
        "session_auth_file": _scan_normalize_text(account.get("session_auth_file")) or None,
        **extra,
    }


def pick_primary_account(group: list[dict]) -> dict:
    """按固定优先级为重复邮箱组挑选主记录。"""

    if not group:
        raise ValueError("group must not be empty")

    def sort_key(account: Mapping[str, object]) -> tuple[object, ...]:
        usage_status = _scan_normalize_key(account.get("usage_status"))
        cpa_status = _scan_normalize_key(account.get("cpa_status"))
        return (
            0 if usage_status in _DEDUP_PREFERRED_USAGE_STATUSES else 1,
            0 if _dedupe_has_rt_reference(account) else 1,
            0 if cpa_status == "success" else 1,
            _dedupe_created_sort_key(account),
            _dedupe_id_sort_key(account),
        )

    return min(group, key=sort_key)


def merge_account_pair(primary: dict, alias: dict) -> list[str]:
    """把 alias 的缺失字段补到 primary，且不覆盖主记录已有值。"""

    fields_filled: list[str] = []
    for field_name, alias_value in alias.items():
        if field_name in _DEDUP_PROTECTED_FIELDS or field_name == "merged_from":
            continue
        if _dedupe_is_missing(alias_value):
            continue

        primary_value = primary.get(field_name)
        if field_name not in primary or _dedupe_is_missing(primary_value):
            primary[field_name] = _dedupe_copy_value(alias_value)
            fields_filled.append(field_name)
            continue

        if isinstance(primary_value, dict) and isinstance(alias_value, Mapping):
            if _dedupe_merge_mapping(primary_value, alias_value):
                fields_filled.append(field_name)

    return fields_filled


def dedupe_accounts(accounts: list[dict], *, in_place: bool = False) -> dict:
    """合并重复邮箱账号，返回分组、合并结果和去重后的账号列表。"""

    target_accounts = accounts if in_place else deepcopy(accounts)
    email_groups: dict[str, list[dict]] = defaultdict(list)

    for account in target_accounts:
        if not isinstance(account, dict):
            continue
        email_key = _scan_normalize_key(account.get("email"))
        if email_key:
            email_groups[email_key].append(account)

    duplicate_groups: list[dict[str, object]] = []
    merges: list[dict[str, object]] = []
    alias_ids_to_remove: set[str] = set()
    alias_object_ids_to_remove: set[int] = set()

    for email_key, group in email_groups.items():
        if len(group) < 2:
            continue

        duplicate_groups.append(
            {
                "email": email_key,
                "count": len(group),
                "ids": [_scan_normalize_text(account.get("id")) or account.get("id") for account in group],
            }
        )

        primary = pick_primary_account(group)
        alias_accounts = [account for account in group if account is not primary]
        fields_filled: list[str] = []

        for alias in alias_accounts:
            for field_name in merge_account_pair(primary, alias):
                if field_name not in fields_filled:
                    fields_filled.append(field_name)
            _dedupe_append_merged_from(primary, alias)

            alias_id = _scan_normalize_text(alias.get("id"))
            if alias_id:
                alias_ids_to_remove.add(alias_id)
            else:
                alias_object_ids_to_remove.add(id(alias))

        merges.append(
            {
                "primary_id": primary.get("id"),
                "primary_email": _scan_normalize_text(primary.get("email")),
                "alias_ids": [_scan_normalize_text(alias.get("id")) or alias.get("id") for alias in alias_accounts],
                "fields_filled": fields_filled,
            }
        )

    if merges:
        result_accounts = []
        for account in target_accounts:
            account_id = _scan_normalize_text(account.get("id")) if isinstance(account, Mapping) else ""
            if account_id and account_id in alias_ids_to_remove:
                continue
            if not account_id and id(account) in alias_object_ids_to_remove:
                continue
            result_accounts.append(account)
    else:
        result_accounts = target_accounts

    if in_place:
        accounts[:] = result_accounts
        result_accounts = accounts

    return {
        "duplicate_groups": duplicate_groups,
        "merges": merges,
        "result_accounts": result_accounts,
        "changed": bool(merges),
    }


def _scan_collect_referenced_files(account: Mapping[str, object]) -> list[tuple[str, str]]:
    fields = ("auth_file", "rt_auth_file", "session_auth_file")
    references: list[tuple[str, str]] = []
    for field_name in fields:
        path_text = _scan_normalize_text(account.get(field_name))
        if path_text:
            references.append((field_name, path_text))
    return references


def _scan_rt_candidates(account: Mapping[str, object]) -> Iterable[tuple[str, str]]:
    seen_paths: set[str] = set()
    for field_name in ("rt_auth_file", "auth_file"):
        path_text = _scan_normalize_text(account.get(field_name))
        if path_text and path_text not in seen_paths:
            seen_paths.add(path_text)
            yield field_name, path_text


def _scan_has_uploadable_rt(account: Mapping[str, object]) -> bool:
    for _, path_text in _scan_rt_candidates(account):
        if is_uploadable_oauth_rt(path_text):
            return True
    return False


def scan_accounts(accounts: list[dict] | None = None) -> dict:
    """扫描账号列表中的重复邮箱、缺失凭证和错误认证类型。"""

    if accounts is None:
        from autoteam import accounts as accounts_mod

        accounts = accounts_mod.load_accounts()

    issues: dict[str, list[dict[str, object]]] = {key: [] for key in SCAN_ISSUE_KEYS}
    email_groups: dict[str, list[Mapping[str, object]]] = defaultdict(list)

    for account in accounts:
        if not isinstance(account, Mapping):
            continue

        email_key = _scan_normalize_key(account.get("email"))
        if email_key:
            email_groups[email_key].append(account)

        if _scan_is_registered_account(account) and not _scan_normalize_text(account.get("password")):
            issues["missing_password"].append(
                _scan_account_summary(account, detail="registered account missing password")
            )

        for field_name, path_text in _scan_collect_referenced_files(account):
            credential_info = identify_credential_file(path_text)
            if credential_info["type"] == CREDENTIAL_TYPE_MISSING:
                issues["missing_credential_file"].append(
                    _scan_account_summary(
                        account,
                        detail=f"{field_name} missing: {path_text}",
                        credential_field=field_name,
                        credential_path=path_text,
                    )
                )

        auth_file = _scan_normalize_text(account.get("auth_file"))
        if auth_file:
            auth_info = identify_credential_file(auth_file)
            if auth_info["type"] == CREDENTIAL_TYPE_SESSION:
                issues["session_used_as_auth_file"].append(
                    _scan_account_summary(
                        account,
                        detail=f"auth_file points to session credential: {auth_file}",
                        credential_field="auth_file",
                        credential_path=auth_file,
                    )
                )

        usage_status = _scan_normalize_key(account.get("usage_status"))
        cpa_status = _scan_normalize_key(account.get("cpa_status"))
        is_sold = _scan_is_sold_account(account)

        if usage_status == USAGE_INVENTORY or cpa_status == "success":
            if not _scan_has_uploadable_rt(account):
                issues["missing_rt_auth_file"].append(
                    _scan_account_summary(
                        account,
                        detail="inventory/cpa-success account missing uploadable OAuth RT file",
                    )
                )

        if is_sold and account.get("sync_disabled") is not True:
            issues["sold_sync_enabled"].append(
                _scan_account_summary(account, detail="sold account still has sync enabled")
            )

        if _scan_normalize_key(account.get("health_status")) == "invalid" and usage_status == USAGE_INVENTORY:
            issues["invalid_in_inventory"].append(
                _scan_account_summary(account, detail="invalid account is still marked as inventory")
            )

        if cpa_status == "success" and usage_status != USAGE_INVENTORY and not is_sold:
            issues["cpa_success_not_inventory"].append(
                _scan_account_summary(account, detail="cpa_status=success but usage_status is not inventory")
            )

    duplicate_groups: list[dict[str, object]] = []
    for email_key, group in email_groups.items():
        if len(group) < 2:
            continue
        duplicate_groups.append(
            {
                "email": email_key,
                "count": len(group),
                "ids": [acc.get("id") for acc in group],
            }
        )
        for account in group:
            issues["duplicate_emails"].append(
                _scan_account_summary(
                    account,
                    detail=f"duplicate email group {email_key} x{len(group)}",
                    duplicate_email=email_key,
                    duplicate_count=len(group),
                )
            )

    summary = {key: len(items) for key, items in issues.items()}
    summary["duplicate_emails"] = len(duplicate_groups)

    return {
        "summary": summary,
        "issues": issues,
        "total_accounts": len(accounts),
        "duplicate_groups": duplicate_groups,
    }


def format_scan_report_csv(report: dict) -> str:
    """把 scan 报告格式化为 `issue,email,detail` CSV。"""

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["issue", "email", "detail"])

    issues = report.get("issues") if isinstance(report, Mapping) else {}
    if not isinstance(issues, Mapping):
        return buffer.getvalue()

    for issue_key in SCAN_ISSUE_KEYS:
        entries = issues.get(issue_key)
        if not isinstance(entries, list):
            continue
        for item in entries:
            if not isinstance(item, Mapping):
                continue
            writer.writerow(
                [
                    issue_key,
                    _scan_normalize_text(item.get("email")),
                    _scan_normalize_text(item.get("detail")),
                ]
            )
    return buffer.getvalue()


def write_scan_reports(report: dict, *, json_path: Path, csv_path: Path) -> None:
    """把 scan 报告写入 JSON 和 CSV 文件。"""

    json_path.write_text(f"{json.dumps(report, indent=2, ensure_ascii=False)}\n", encoding="utf-8")
    csv_path.write_text(format_scan_report_csv(report), encoding="utf-8")


def _load_accounts_json(accounts_file: Path) -> list[dict]:
    if not accounts_file.exists():
        return []

    text = accounts_file.read_text(encoding="utf-8").strip()
    if not text:
        return []

    data = json.loads(text)
    if not isinstance(data, list):
        raise ValueError("accounts.json root must be a list")
    return data


def _write_accounts_json(accounts_file: Path, accounts_list: list[dict]) -> None:
    payload = json.dumps(accounts_list, ensure_ascii=False, indent=2, sort_keys=False)
    accounts_file.write_text(f"{payload}\n", encoding="utf-8")


def _count_changed_records(before: list[dict], after: list[dict]) -> int:
    return sum(1 for original, current in zip(before, after, strict=False) if original != current)


def reclassify_accounts(accounts: list[dict], *, in_place: bool = False) -> dict:
    """迁移账号结构、凭证字段、重复邮箱，并重算分类。"""

    target_accounts = accounts if in_place else deepcopy(accounts)
    changed = False

    before_schema = deepcopy(target_accounts)
    migrate_accounts(target_accounts, in_place=True)
    schema_changes = _count_changed_records(before_schema, target_accounts)
    changed = changed or schema_changes > 0

    credential_result = migrate_accounts_credentials(target_accounts, in_place=True)
    credential_changes = int(credential_result["changed"])
    changed = changed or credential_changes > 0

    dedupe_result = dedupe_accounts(target_accounts, in_place=True)
    merge_count = len(dedupe_result["merges"])
    changed = changed or merge_count > 0

    category_counts: dict[str, int] = {}
    classify_changes = 0
    for account in target_accounts:
        before_classify = deepcopy(account)
        classify_account(account, in_place=True)
        if account != before_classify:
            classify_changes += 1
        category = _scan_normalize_text(account.get("category")) or "unknown"
        category_counts[category] = category_counts.get(category, 0) + 1

    changed = changed or classify_changes > 0

    return {
        "changed": changed,
        "schema_changes": schema_changes,
        "credential_changes": credential_changes,
        "merge_count": merge_count,
        "category_counts": category_counts,
        "result_accounts": target_accounts,
    }


def cleanup_accounts(
    *,
    accounts: list[dict] | None = None,
    accounts_file: Path | None = None,
    apply: bool = False,
) -> dict:
    """执行迁移、去重、分类和最终扫描，可选写回账号文件。"""

    target_file = accounts_file
    if accounts is None:
        target_file = target_file or accounts_module.ACCOUNTS_FILE
        input_accounts = _load_accounts_json(target_file)
    else:
        input_accounts = accounts

    reclassify_result = reclassify_accounts(input_accounts, in_place=False)
    scan_result = scan_accounts(reclassify_result["result_accounts"])

    backup_path: Path | None = None
    if apply:
        target_file = target_file or accounts_module.ACCOUNTS_FILE
        backup_path = backup_accounts_file(accounts_file=target_file)
        _write_accounts_json(target_file, reclassify_result["result_accounts"])

    return {
        "reclassify": reclassify_result,
        "scan": scan_result,
        "backup_path": str(backup_path) if backup_path else None,
        "applied": apply,
        "accounts_file": str(target_file) if target_file else None,
    }


__all__ = [
    "BACKUP_TAG",
    "SCAN_ISSUE_KEYS",
    "backup_accounts_file",
    "dedupe_accounts",
    "format_scan_report_csv",
    "merge_account_pair",
    "pick_primary_account",
    "scan_accounts",
    "write_scan_reports",
]
__all__ += ["cleanup_accounts", "reclassify_accounts"]
