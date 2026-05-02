#!/usr/bin/env python3
"""Analyze a Sub2API account export against local AutoTeam accounts."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_CLOUD_EXPORT = Path("docs/sub2api-account-20260502031448.json")
DEFAULT_LOCAL_ACCOUNTS = Path("accounts.json")
DEFAULT_OUT_DIR = Path(".tmp/sub2api_analysis")
EXCLUDED_EMAILS = {"aqw-2@gymbro.cloud", "aqw-10@gymbro.cloud"}
LOCAL_ACTION_STATUSES = {"active", "standby", "exhausted"}
RECENT_USAGE_SECONDS = 7 * 24 * 60 * 60
EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")


def fail(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    sys.exit(1)


def load_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        fail(f"file not found: {path}")
    except json.JSONDecodeError as exc:
        fail(f"invalid JSON in {path}: {exc}")
    except OSError as exc:
        fail(f"failed to read {path}: {exc}")


def write_json(path: Path, data: Any) -> None:
    try:
        with path.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
    except OSError as exc:
        fail(f"failed to write {path}: {exc}")


def normalize_email(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    text = value.strip().lower()
    if not text:
        return ""
    match = EMAIL_RE.search(text)
    return match.group(0) if match else text


def account_email(account: dict[str, Any]) -> str:
    credentials = account.get("credentials") if isinstance(account.get("credentials"), dict) else {}
    extra = account.get("extra") if isinstance(account.get("extra"), dict) else {}
    for value in (credentials.get("email"), extra.get("email"), account.get("name")):
        email = normalize_email(value)
        if email:
            return email
    return ""


def local_email(account: dict[str, Any]) -> str:
    return normalize_email(account.get("email"))


def is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def parse_time(value: Any) -> datetime | None:
    if is_int(value) or isinstance(value, float):
        timestamp = float(value)
        if abs(timestamp) > 10_000_000_000:
            timestamp /= 1000
        try:
            return datetime.fromtimestamp(timestamp, timezone.utc)
        except (OSError, OverflowError, ValueError):
            return None
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.isdigit():
        return parse_time(int(text))
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def iso_from_epoch(value: Any) -> str:
    if not is_int(value):
        return ""
    parsed = parse_time(value)
    if parsed is None:
        return ""
    return parsed.isoformat().replace("+00:00", "Z")


def value_present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def cloud_health(account: dict[str, Any], now_epoch: int) -> tuple[bool, list[str]]:
    credentials = account.get("credentials") if isinstance(account.get("credentials"), dict) else {}
    extra = account.get("extra") if isinstance(account.get("extra"), dict) else {}
    reasons: list[str] = []

    if not value_present(credentials.get("refresh_token")):
        reasons.append("missing_refresh_token")

    expires_at = credentials.get("expires_at")
    usage_updated_at = parse_time(extra.get("codex_usage_updated_at"))
    usage_is_recent = False
    if usage_updated_at is not None:
        usage_age = datetime.fromtimestamp(now_epoch, timezone.utc) - usage_updated_at
        usage_is_recent = usage_age.total_seconds() <= RECENT_USAGE_SECONDS

    if not is_int(expires_at):
        reasons.append("expires_at_not_int")
    elif expires_at < now_epoch and not usage_is_recent:
        reasons.append("expired_and_usage_not_recent")

    if "codex_7d_used_percent" not in extra or extra.get("codex_7d_used_percent") is None:
        reasons.append("missing_codex_7d_used_percent")

    if not value_present(account.get("proxy_key")):
        reasons.append("missing_proxy_key")

    return not reasons, reasons


def cloud_healthy_row(email: str, account: dict[str, Any]) -> dict[str, Any]:
    credentials = account.get("credentials") if isinstance(account.get("credentials"), dict) else {}
    extra = account.get("extra") if isinstance(account.get("extra"), dict) else {}
    return {
        "email": email,
        "plan_type": credentials.get("plan_type", ""),
        "proxy_key": account.get("proxy_key", ""),
        "codex_7d_used_percent": extra.get("codex_7d_used_percent", ""),
        "expires_at_iso": iso_from_epoch(credentials.get("expires_at")),
        "codex_usage_updated_at": extra.get("codex_usage_updated_at", ""),
    }


def local_details(account: dict[str, Any] | None) -> dict[str, Any]:
    if not account:
        return {
            "local_status": "",
            "has_rt_auth_file": "",
            "has_session_auth_file": "",
            "mail_provider": "",
            "mail_account_id": "",
            "password_present": "",
        }
    return {
        "local_status": account.get("status", ""),
        "has_rt_auth_file": bool(account.get("rt_auth_file")),
        "has_session_auth_file": bool(account.get("session_auth_file")),
        "mail_provider": account.get("mail_provider", ""),
        "mail_account_id": account.get("mail_account_id", ""),
        "password_present": bool(account.get("password")),
    }


def local_is_actionable(account: dict[str, Any]) -> bool:
    status = str(account.get("status", "")).strip().lower()
    usage_status = str(account.get("usage_status", "")).strip().lower()
    return (
        status in LOCAL_ACTION_STATUSES
        and status not in {"sold", "unavailable"}
        and usage_status != "sold"
        and not account.get("sync_disabled")
        and not account.get("sold_at")
    )


def accounts_list(data: Any, label: str) -> list[dict[str, Any]]:
    if isinstance(data, dict):
        data = data.get("accounts", [])
    if not isinstance(data, list):
        fail(f"{label} must be a list or an object with an accounts list")
    return [item for item in data if isinstance(item, dict)]


def index_accounts(accounts: list[dict[str, Any]], email_getter: Any) -> dict[str, list[dict[str, Any]]]:
    indexed: dict[str, list[dict[str, Any]]] = {}
    for account in accounts:
        email = email_getter(account)
        if email:
            indexed.setdefault(email, []).append(account)
    return indexed


def choose_healthy_record(records: list[tuple[dict[str, Any], list[str]]]) -> tuple[bool, dict[str, Any], list[str]]:
    for account, reasons in records:
        if not reasons:
            return True, account, []
    account, reasons = records[0]
    return False, account, reasons


def analyze(cloud_data: Any, local_data: Any, now_epoch: int) -> dict[str, Any]:
    cloud_accounts = accounts_list(cloud_data, "cloud export")
    local_accounts = accounts_list(local_data, "local accounts")
    cloud_by_email = index_accounts(cloud_accounts, account_email)
    local_by_email = index_accounts(local_accounts, local_email)

    excluded_hit = sorted((set(cloud_by_email) | set(local_by_email)) & EXCLUDED_EMAILS)
    excluded_set = set(excluded_hit)

    cloud_healthy: list[dict[str, Any]] = []
    cloud_unhealthy: list[dict[str, Any]] = []

    for email in sorted(set(cloud_by_email) - excluded_set):
        evaluated = [(account, cloud_health(account, now_epoch)[1]) for account in cloud_by_email[email]]
        is_healthy, account, reasons = choose_healthy_record(evaluated)
        if is_healthy:
            cloud_healthy.append(cloud_healthy_row(email, account))
        else:
            details = local_details(local_by_email.get(email, [None])[0])
            cloud_unhealthy.append({"email": email, "reason": ";".join(reasons), **details})

    cloud_known = set(cloud_by_email)
    local_only: list[dict[str, Any]] = []
    for email in sorted(set(local_by_email) - cloud_known - excluded_set):
        account = local_by_email[email][0]
        if not local_is_actionable(account):
            continue
        local_only.append({"email": email, "reason": "local_only", **local_details(account)})

    return {
        "cloud_healthy": cloud_healthy,
        "cloud_unhealthy": cloud_unhealthy,
        "local_only": local_only,
        "excluded_hit": excluded_hit,
        "input_counts": {
            "cloud_accounts": len(cloud_accounts),
            "cloud_unique_emails": len(cloud_by_email),
            "local_accounts": len(local_accounts),
            "local_unique_emails": len(local_by_email),
        },
    }


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    try:
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow({field: row.get(field, "") for field in fieldnames})
    except OSError as exc:
        fail(f"failed to write {path}: {exc}")


def sample_emails(rows: list[dict[str, Any]] | list[str], limit: int = 5) -> list[str]:
    values: list[str] = []
    for row in rows[:limit]:
        values.append(row if isinstance(row, str) else str(row.get("email", "")))
    return values


def write_outputs(result: dict[str, Any], out_dir: Path, now_epoch: int) -> list[Path]:
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        fail(f"failed to create output directory {out_dir}: {exc}")

    cloud_healthy_path = out_dir / "cloud_healthy.csv"
    needs_action_path = out_dir / "needs_action.csv"
    summary_path = out_dir / "summary.json"

    cloud_healthy_fields = [
        "email",
        "plan_type",
        "proxy_key",
        "codex_7d_used_percent",
        "expires_at_iso",
        "codex_usage_updated_at",
    ]
    needs_action_fields = [
        "email",
        "reason",
        "local_status",
        "has_rt_auth_file",
        "has_session_auth_file",
        "mail_provider",
        "mail_account_id",
        "password_present",
    ]

    needs_action = result["cloud_unhealthy"] + result["local_only"]
    write_csv(cloud_healthy_path, result["cloud_healthy"], cloud_healthy_fields)
    write_csv(needs_action_path, needs_action, needs_action_fields)

    summary = {
        "generated_at": datetime.fromtimestamp(now_epoch, timezone.utc).isoformat().replace("+00:00", "Z"),
        "counts": {
            "cloud_healthy": len(result["cloud_healthy"]),
            "cloud_unhealthy": len(result["cloud_unhealthy"]),
            "local_only": len(result["local_only"]),
            "excluded_hit": len(result["excluded_hit"]),
            "needs_action": len(needs_action),
            **result["input_counts"],
        },
        "excluded_hit": result["excluded_hit"],
        "samples": {
            "cloud_healthy": sample_emails(result["cloud_healthy"]),
            "cloud_unhealthy": sample_emails(result["cloud_unhealthy"]),
            "local_only": sample_emails(result["local_only"]),
            "excluded_hit": sample_emails(result["excluded_hit"]),
        },
    }
    write_json(summary_path, summary)
    return [cloud_healthy_path, needs_action_path, summary_path]


def print_summary(result: dict[str, Any], written_files: list[Path]) -> None:
    print("summary")
    print(f"cloud_healthy: {len(result['cloud_healthy'])} sample={sample_emails(result['cloud_healthy'])}")
    print(f"cloud_unhealthy: {len(result['cloud_unhealthy'])} sample={sample_emails(result['cloud_unhealthy'])}")
    print(f"local_only: {len(result['local_only'])} sample={sample_emails(result['local_only'])}")
    print(f"excluded_hit: {len(result['excluded_hit'])} sample={sample_emails(result['excluded_hit'])}")
    print("written_files:")
    for path in written_files:
        print(f"- {path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze a Sub2API account export against local AutoTeam accounts.")
    parser.add_argument("cloud_export", nargs="?", type=Path, default=DEFAULT_CLOUD_EXPORT)
    parser.add_argument("local_accounts", nargs="?", type=Path, default=DEFAULT_LOCAL_ACCOUNTS)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    now_epoch = int(time.time())
    result = analyze(load_json(args.cloud_export), load_json(args.local_accounts), now_epoch)
    written_files = write_outputs(result, args.out_dir, now_epoch)
    print_summary(result, written_files)


if __name__ == "__main__":
    main()
