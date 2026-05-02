"""accounts.json 清理辅助工具。

AT-003 backup; AT-004 scan; AT-005 dedupe; AT-008 reclassify will follow.
"""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from autoteam import accounts

BACKUP_TAG = "account-clean"


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

from autoteam.account_classifier import derive_category
from autoteam.account_credentials import (
    CREDENTIAL_TYPE_MISSING,
    CREDENTIAL_TYPE_SESSION,
    identify_credential_file,
    is_uploadable_oauth_rt,
)
from autoteam.account_models import REGISTRATION_REGISTERED, USAGE_INVENTORY, USAGE_SOLD

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


def _scan_normalize_text(value: object) -> str:
    return str(value or "").strip()


def _scan_normalize_key(value: object) -> str:
    return _scan_normalize_text(value).lower()


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


__all__ = [
    "BACKUP_TAG",
    "SCAN_ISSUE_KEYS",
    "backup_accounts_file",
    "format_scan_report_csv",
    "scan_accounts",
    "write_scan_reports",
]
