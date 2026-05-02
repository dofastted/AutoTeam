"""Check mailbox deactivation notices and retire affected accounts."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from autoteam import accounts as accounts_store
from autoteam.accounts import (
    CPA_STATUS_FAILED,
    STATUS_ACTIVE,
    STATUS_EXHAUSTED,
    STATUS_PENDING,
    STATUS_SOLD,
    STATUS_STANDBY,
    STATUS_UNAVAILABLE,
    USAGE_SELF_USE,
    USAGE_SOLD,
    find_account,
    load_accounts,
    save_accounts,
)
from autoteam.mail_provider import (
    get_account_mail_account_id,
    get_account_mail_provider,
    get_mail_client,
    get_mail_provider_name,
)

logger = logging.getLogger(__name__)

DEFAULT_DEACTIVATED_KEYWORD = "deactivated"
DEFAULT_CANDIDATE_STATUSES = (
    STATUS_ACTIVE,
    STATUS_EXHAUSTED,
    STATUS_STANDBY,
    STATUS_PENDING,
)
TEAM_SEAT_STATUSES = {STATUS_ACTIVE, STATUS_EXHAUSTED}


TeamRemover = Callable[[str, dict[str, Any]], str | bool]


def _normalized_email(value: object | None) -> str:
    return str(value or "").strip().lower()


def _truthy_text(value: object | None) -> str:
    return str(value or "").strip()


def _email_from_auth_filename(name: str) -> str:
    body = Path(name).name
    if not body.startswith("codex-"):
        return ""
    body = body[len("codex-") :]
    for marker in ("-team-", "-plus-", "-free-", "-unknown-"):
        if marker in body:
            return body.split(marker, 1)[0].strip().lower()
    return ""


def _backup_accounts_file() -> str:
    accounts_file = accounts_store.ACCOUNTS_FILE
    if not accounts_file.exists():
        return ""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup_path = accounts_file.with_name(f"{accounts_file.name}.bak-deactivated-mail-{stamp}")
    backup_path.write_text(accounts_file.read_text(encoding="utf-8"), encoding="utf-8")
    return str(backup_path)


def _email_text_sources(email_item: dict[str, Any]) -> dict[str, str]:
    return {
        "subject": _truthy_text(email_item.get("subject")),
        "text": _truthy_text(email_item.get("text")),
        "content": _truthy_text(email_item.get("content")),
        "raw": _truthy_text(email_item.get("raw")),
        "metadata": _truthy_text(email_item.get("metadata")),
    }


def _email_matches_keyword(email_item: dict[str, Any], keyword: str) -> tuple[bool, list[str]]:
    keyword_l = keyword.lower()
    fields = []
    for field, value in _email_text_sources(email_item).items():
        if keyword_l in value.lower():
            fields.append(field)
    return bool(fields), fields


def _message_id(email_item: dict[str, Any]) -> object | None:
    return email_item.get("messageId") or email_item.get("emailId") or email_item.get("id")


def _safe_mail_evidence(
    email_item: dict[str, Any],
    *,
    provider: str,
    account_id: object | None,
    matched_fields: list[str],
) -> dict[str, Any]:
    return {
        "provider": provider,
        "mail_account_id": account_id,
        "message_id": _message_id(email_item),
        "subject": _truthy_text(email_item.get("subject"))[:200],
        "sender": _truthy_text(email_item.get("sendEmail") or email_item.get("from") or email_item.get("sender"))[:200],
        "matched_fields": matched_fields,
    }


def _is_candidate_account(acc: dict[str, Any], statuses: set[str]) -> bool:
    email = _normalized_email(acc.get("email"))
    if not email:
        return False
    status = str(acc.get("status") or "").strip().lower()
    usage_status = str(acc.get("usage_status") or "").strip().lower()
    if status not in statuses:
        return False
    if status in {STATUS_UNAVAILABLE, STATUS_SOLD}:
        return False
    if usage_status in {USAGE_SOLD, USAGE_SELF_USE}:
        return False
    if acc.get("sync_disabled") or acc.get("unavailable_reason"):
        return False
    return True


def deactivated_mail_candidates(
    accounts: list[dict[str, Any]] | None = None,
    *,
    statuses: list[str] | tuple[str, ...] | set[str] | None = None,
) -> list[dict[str, Any]]:
    """Return local accounts that are not already retired or user-reserved."""
    status_set = {str(item).strip().lower() for item in (statuses or DEFAULT_CANDIDATE_STATUSES) if str(item).strip()}
    return [acc for acc in (accounts or load_accounts()) if _is_candidate_account(acc, status_set)]


def load_deactivated_mail_directory_entries(
    directory: str = "auths/unusable/account_deactivated",
    *,
    accounts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    base = Path(directory)
    files = sorted(base.glob("codex-*.json")) if base.exists() else []
    accounts_by_email = {
        _normalized_email(acc.get("email")): acc for acc in (accounts if accounts is not None else load_accounts())
        if _normalized_email(acc.get("email"))
    }
    entries: list[dict[str, Any]] = []
    parse_errors: list[dict[str, Any]] = []

    for path in files:
        email = ""
        account_id = None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                email = _normalized_email(data.get("email"))
                account_id = data.get("account_id") or data.get("mail_account_id") or data.get("cloudmail_account_id")
        except Exception as exc:
            parse_errors.append({"name": path.name, "error": str(exc)})
        if not email:
            email = _email_from_auth_filename(path.name)
        if not email:
            continue

        local_account = accounts_by_email.get(email)
        if local_account:
            provider = get_account_mail_provider(local_account)
            account_id = get_account_mail_account_id(local_account) or account_id
        else:
            provider = get_mail_provider_name()

        entries.append(
            {
                "email": email,
                "source": "directory",
                "directory_file": str(path),
                "mail_provider": provider,
                "mail_account_id": account_id,
                "has_local_account": bool(local_account),
                "local_account": local_account,
            }
        )

    return {
        "directory": str(base),
        "files": len(files),
        "entries": entries,
        "entry_count": len(entries),
        "parse_errors": parse_errors,
    }


def _fetch_email_detail_if_needed(client, email_item, *, account_id, to_email, keyword: str):
    message_id = _message_id(email_item)
    if not message_id:
        return email_item

    sources = _email_text_sources(email_item)
    keyword_l = keyword.lower()
    if any(keyword_l in value.lower() for value in sources.values() if value):
        return email_item

    getter = getattr(client, "get_email_by_id", None)
    if not callable(getter):
        return email_item

    try:
        detail = getter(account_id, message_id, to_email=to_email)
    except TypeError:
        detail = getter(account_id, message_id)
    except Exception:
        return email_item
    return detail if isinstance(detail, dict) else email_item


def _get_logged_in_client(provider: str, cache: dict[str, Any]):
    client = cache.get(provider)
    if client is not None:
        return client
    client = get_mail_client(provider)
    client.login()
    cache[provider] = client
    return client


def _dispose_mailbox(client, account_id) -> dict[str, Any]:
    if account_id is None:
        return {"attempted": False, "success": False, "message": "missing_mail_account_id"}
    deleter = getattr(client, "delete_account", None)
    if not callable(deleter):
        return {"attempted": False, "success": False, "message": "provider_delete_not_supported"}
    try:
        resp = deleter(account_id)
    except Exception as exc:
        return {"attempted": True, "success": False, "message": str(exc)}
    success = bool(isinstance(resp, dict) and (resp.get("code") == 200 or resp.get("success") is True))
    return {"attempted": True, "success": success, "response": resp}


def _apply_account_deactivated(
    acc: dict[str, Any],
    *,
    evidence: dict[str, Any],
    seat_release: dict[str, Any],
    mailbox_disposal: dict[str, Any],
    now: float,
) -> bool:
    before = (
        acc.get("status"),
        acc.get("sync_disabled"),
        acc.get("unavailable_reason"),
        acc.get("cpa_status"),
        acc.get("cpa_error_message"),
    )
    acc["status"] = STATUS_UNAVAILABLE
    acc["sync_disabled"] = True
    acc["unavailable_reason"] = "account_deactivated"
    acc["unavailable_at"] = now
    acc["deactivated_mail_checked_at"] = now
    acc["deactivated_mail_evidence"] = evidence
    acc["mailbox_retired"] = True
    acc["mailbox_retired_at"] = now
    acc["mailbox_retired_reason"] = "account_deactivated"
    acc["seat_release"] = seat_release
    acc["mailbox_disposal"] = mailbox_disposal
    acc["mailbox_disposed_at"] = now if mailbox_disposal.get("success") else None
    acc["cpa_status"] = CPA_STATUS_FAILED
    acc["cpa_error_message"] = "account_deactivated"
    after = (
        acc.get("status"),
        acc.get("sync_disabled"),
        acc.get("unavailable_reason"),
        acc.get("cpa_status"),
        acc.get("cpa_error_message"),
    )
    return before != after


def check_deactivated_mail(
    *,
    keyword: str = DEFAULT_DEACTIVATED_KEYWORD,
    size: int = 30,
    statuses: list[str] | tuple[str, ...] | set[str] | None = None,
    directory: str | None = None,
    apply: bool = False,
    release_team: bool = True,
    dispose_mailbox: bool = True,
    team_remover: TeamRemover | None = None,
) -> dict[str, Any]:
    """Check account mailboxes for deactivation notices.

    When apply is False this only reads mail providers and returns sanitized evidence.
    When apply is True, matched accounts are marked unavailable; active/exhausted
    accounts can also be removed from Team through team_remover.
    """
    keyword = str(keyword or "").strip() or DEFAULT_DEACTIVATED_KEYWORD
    size = max(1, int(size or 30))
    accounts = load_accounts()
    source_mode = "directory" if directory else "accounts"
    if directory:
        directory_payload = load_deactivated_mail_directory_entries(directory, accounts=accounts)
        candidates = list(directory_payload["entries"])
    else:
        directory_payload = None
        candidates = deactivated_mail_candidates(accounts, statuses=statuses)
    clients: dict[str, Any] = {}

    result: dict[str, Any] = {
        "status": "ok",
        "dry_run": not apply,
        "keyword": keyword,
        "source_mode": source_mode,
        "candidate_count": len(candidates),
        "checked": 0,
        "matched": 0,
        "marked": 0,
        "seats_released": 0,
        "mailboxes_disposed": 0,
        "backup": "",
        "directory": directory_payload["directory"] if directory_payload else "",
        "directory_files": directory_payload["files"] if directory_payload else 0,
        "matches": [],
        "missing_local_accounts": [],
        "errors": [],
    }
    if directory_payload:
        result["directory_parse_errors"] = directory_payload["parse_errors"]

    matched_items: list[dict[str, Any]] = []
    for record in candidates:
        if source_mode == "directory":
            acc = record.get("local_account") if isinstance(record, dict) else None
            email = _normalized_email(record.get("email") if isinstance(record, dict) else "")
            provider = (record.get("mail_provider") if isinstance(record, dict) else None) or (
                get_account_mail_provider(acc) if acc else get_mail_provider_name()
            )
            account_id = (record.get("mail_account_id") if isinstance(record, dict) else None) or (
                get_account_mail_account_id(acc) if acc else None
            )
        else:
            acc = record
            email = _normalized_email(acc.get("email"))
            provider = get_account_mail_provider(acc)
            account_id = get_account_mail_account_id(acc)
        try:
            client = _get_logged_in_client(provider, clients)
            emails = client.search_emails_by_recipient(email, size=size, account_id=account_id)
        except Exception as exc:
            result["errors"].append({"email": email, "provider": provider, "error": str(exc)})
            continue

        result["checked"] += 1
        for email_item in emails or []:
            if not isinstance(email_item, dict):
                continue
            email_item = _fetch_email_detail_if_needed(
                client,
                email_item,
                account_id=account_id,
                to_email=email,
                keyword=keyword,
            )
            matched, fields = _email_matches_keyword(email_item, keyword)
            if not matched:
                continue
            evidence = _safe_mail_evidence(email_item, provider=provider, account_id=account_id, matched_fields=fields)
            item = {
                "email": email,
                "status": acc.get("status") if acc else None,
                "provider": provider,
                "mail_account_id": account_id,
                "directory_file": record.get("directory_file") if isinstance(record, dict) else "",
                "has_local_account": bool(acc),
                "evidence": evidence,
            }
            matched_items.append({"account": acc, "client": client, "item": item, "record": record})
            result["matches"].append(item)
            break

    result["matched"] = len(matched_items)
    if not apply or not matched_items:
        if result["errors"]:
            result["status"] = "partial"
        return result

    result["backup"] = _backup_accounts_file()
    now = time.time()
    for matched in matched_items:
        acc = matched["account"]
        client = matched["client"]
        item = matched["item"]
        record = matched["record"]
        email = item["email"]
        account_id = item.get("mail_account_id")
        seat_release = {"attempted": False, "status": "skipped"}
        mailbox_disposal = {"attempted": False, "success": False, "message": "skipped"}

        if release_team and acc and acc.get("status") in TEAM_SEAT_STATUSES:
            seat_release["attempted"] = True
            if team_remover is None:
                seat_release["status"] = "not_configured"
            else:
                try:
                    removal_status = team_remover(email, acc)
                    seat_release["status"] = str(removal_status)
                    if removal_status is True or str(removal_status) in {"removed", "already_absent"}:
                        result["seats_released"] += 1
                except Exception as exc:
                    seat_release["status"] = "failed"
                    seat_release["error"] = str(exc)
                    result["errors"].append({"email": email, "stage": "release_team", "error": str(exc)})

        if dispose_mailbox:
            mailbox_disposal = _dispose_mailbox(client, account_id)
            if mailbox_disposal.get("success"):
                result["mailboxes_disposed"] += 1

        latest = find_account(accounts, email) if email else None
        if latest and _apply_account_deactivated(
            latest,
            evidence=item["evidence"],
            seat_release=seat_release,
            mailbox_disposal=mailbox_disposal,
            now=now,
        ):
            result["marked"] += 1
        elif not latest:
            result["missing_local_accounts"].append(
                {
                    "email": email,
                    "directory_file": record.get("directory_file") if isinstance(record, dict) else "",
                }
            )
        item["seat_release"] = seat_release
        item["mailbox_disposal"] = mailbox_disposal

    save_accounts(accounts)
    if result["errors"]:
        result["status"] = "partial"
    return result
