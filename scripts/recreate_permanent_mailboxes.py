#!/usr/bin/env python3
"""Re-create permanent MoEmail mailboxes for accounts whose prior temp boxes expired.

Reads .tmp/session_only_emails.json (JSON array of emails), POSTs
/api/emails/generate with expiryTime=0 for each prefix, and writes the new
mail_account_id back into accounts.json. Outputs a summary file.

Usage:
    python3 scripts/recreate_permanent_mailboxes.py [emails_file]

Defaults:
    emails_file = .tmp/session_only_emails.json
    accounts    = accounts.json
    output      = .tmp/recreate_permanent_mailboxes.json
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from autoteam import accounts as accounts_mod
from autoteam.mo_email import PERMANENT_EMAIL_EXPIRY, MoEmailClient, parse_email_local_name

PERMANENT_EXPIRY = PERMANENT_EMAIL_EXPIRY


def parse_prefix(email: str) -> str:
    return parse_email_local_name(email)


def recreate_one(client: MoEmailClient, email: str) -> dict:
    prefix = parse_prefix(email)
    if not prefix:
        return {"email": email, "ok": False, "error": "empty prefix"}

    try:
        recreated = client.recreate_permanent_email(email)
    except Exception as exc:
        return {"email": email, "ok": False, "error": f"{type(exc).__name__}: {exc}"}

    return {
        "email": recreated["email"],
        "ok": True,
        "account_id": recreated["account_id"],
        "raw_account": recreated["raw_account"],
    }


def update_local_account(email: str, new_account_id) -> bool:
    new_id = (str(new_account_id) if new_account_id is not None else "").strip()
    if not new_id:
        return False
    accounts_mod.update_account(email, mail_account_id=new_id)
    return True


def main() -> None:
    emails_file = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / ".tmp" / "session_only_emails.json"
    if not emails_file.exists():
        print(f"error: {emails_file} not found", file=sys.stderr)
        sys.exit(1)

    emails = json.loads(emails_file.read_text(encoding="utf-8"))
    if not isinstance(emails, list) or not emails:
        print("error: emails file must be a non-empty JSON array", file=sys.stderr)
        sys.exit(1)

    client = MoEmailClient()
    client.login()

    out_dir = ROOT / ".tmp"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / "recreate_permanent_mailboxes.json"

    results = []
    ok_count = 0
    fail_count = 0
    updated = 0
    for idx, raw_email in enumerate(emails, 1):
        email = (raw_email or "").strip().lower()
        if not email:
            continue
        print(f"[{time.strftime('%H:%M:%S')}] ({idx}/{len(emails)}) {email}", flush=True)
        result = recreate_one(client, email)
        if result.get("ok"):
            ok_count += 1
            new_id = result.get("account_id")
            try:
                if update_local_account(email, new_id):
                    updated += 1
                    print(f"  -> ok account_id={new_id} (accounts.json updated)")
                else:
                    print(f"  -> ok account_id={new_id} (accounts.json NOT updated)")
            except Exception as exc:
                result["ok"] = False
                result["error"] = f"local update failed: {exc}"
                print(f"  -> created but local update failed: {exc}")
                fail_count += 1
                ok_count -= 1
        else:
            fail_count += 1
            print(f"  -> failed: {result.get('error')}")
        results.append(result)
        time.sleep(0.3)

    summary = {
        "total": len(emails),
        "recreated": ok_count,
        "failed": fail_count,
        "accounts_json_updated": updated,
        "results": results,
    }
    out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print(f"summary -> {out_path}")
    print(f"recreated={ok_count} failed={fail_count} accounts_json_updated={updated}")


if __name__ == "__main__":
    main()
