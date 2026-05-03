#!/usr/bin/env python3
"""Scan-and-quarantine 401 OAuth RT files within an aqw-{start..end} range.

This wrapper imports the existing scanner module
(``scripts/codex_quota_401_scanner.py``) and applies it to a strict
filename range so we touch only target accounts.

Workflow:

  1. Build the filtered list of ``auths/codex-aqw-<N>@*-oauth.json`` where
     ``start <= N <= end``.
  2. For each file, call ``codex_quota_401_scanner._scan_single_file`` so
     the same probe / refresh logic runs and refreshed tokens are
     persisted **back into the original file** (atomic write).
  3. Print the scanner-style summary table.
  4. Move any file that remains classified as ``401`` (refresh either
     skipped or also failed) into ``auths/invalidated/``.
  5. Emit a JSON list of failed emails to ``--emails-out`` (default
     ``.tmp/session_only_emails.json``) so
     ``scripts/backfill_session_only_oauth.sh`` can re-run full Codex
     OAuth on them.
  6. Emit a structured JSON report to ``--report-out`` (default
     ``.tmp/scan_401_aqw_range_report.json``).

Usage examples:

  python3 scripts/scan_401_range.py
  python3 scripts/scan_401_range.py --start 700 --end 900 --workers 8
  python3 scripts/scan_401_range.py --dry-run
  python3 scripts/scan_401_range.py --no-quarantine
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path

# Import scanner as a sibling module
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import codex_quota_401_scanner as cq  # noqa: E402


_FILE_PATTERN = re.compile(r"^codex-aqw-(\d+)@.*-oauth\.json$")
_ACTIVE_STATUS = "active"


def _build_scanner_args(args: argparse.Namespace) -> argparse.Namespace:
    """Build the namespace ``codex_quota_401_scanner`` expects."""
    return argparse.Namespace(
        auth_dir=args.auth_dir,
        recursive=False,
        base_url=cq.DEFAULT_CODEX_BASE_URL,
        quota_path="/responses",
        model="gpt-5",
        timeout=args.timeout,
        retry_attempts=cq.DEFAULT_RETRY_ATTEMPTS,
        retry_backoff=cq.DEFAULT_RETRY_BACKOFF,
        refresh_url=cq.DEFAULT_REFRESH_URL,
        no_refresh=args.no_refresh,
        dry_run=args.dry_run,
        workers=args.workers,
    )


def _filter_files(auth_dir: Path, start: int, end: int) -> list[Path]:
    files: list[Path] = []
    for f in sorted(auth_dir.glob("codex-aqw-*-oauth.json")):
        m = _FILE_PATTERN.match(f.name)
        if not m:
            continue
        n = int(m.group(1))
        if start <= n <= end:
            files.append(f)
    return files


def _run_scan(
    files: list[Path],
    scanner_args: argparse.Namespace,
    workers: int,
) -> list[cq.CheckResult]:
    """Scan files in parallel and return aggregated CheckResult list."""
    if not files:
        return []

    indexed: list[tuple[int, list[cq.CheckResult]]] = []
    workers = max(1, min(workers, len(files)))

    if workers == 1:
        for index, path in enumerate(files, start=1):
            try:
                res = cq._scan_single_file(path, scanner_args)
            except Exception as exc:  # noqa: BLE001
                res = [_internal_error_result(path, exc)]
            indexed.append((index, res))
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            future_map = {
                pool.submit(cq._scan_single_file, path, scanner_args): (i, path)
                for i, path in enumerate(files, start=1)
            }
            done = 0
            total = len(files)
            for future in as_completed(future_map):
                done += 1
                index, path = future_map[future]
                try:
                    res = future.result()
                except Exception as exc:  # noqa: BLE001
                    res = [_internal_error_result(path, exc)]
                if sys.stdout.isatty():
                    sys.stdout.write(
                        f"\r  scan progress {done}/{total} {path.name[:40]:<40}"
                    )
                    sys.stdout.flush()
                indexed.append((index, res))
            if sys.stdout.isatty():
                sys.stdout.write("\n")
                sys.stdout.flush()

    indexed.sort(key=lambda item: item[0])
    return [r for _, group in indexed for r in group]


def _internal_error_result(path: Path, exc: Exception) -> cq.CheckResult:
    return cq.CheckResult(
        file=str(path),
        provider="unknown",
        email="",
        account_id="",
        status_code=None,
        classification="other",
        auth_ok=False,
        unauthorized_401=False,
        quota_exceeded=False,
        refresh_attempted=False,
        refresh_succeeded=False,
        refresh_error="",
        quota_resets_at=None,
        error=f"internal error: {exc}",
        response_preview="",
        final_status_code=None,
    )


def _email_from_filename(name: str) -> str:
    # codex-aqw-700@gymbro.cloud-team-dbf8c1ed-oauth.json -> aqw-700@gymbro.cloud
    m = re.match(r"^codex-(.+?)-(team|plus|free|unknown|pro)-", name)
    if m:
        return m.group(1)
    # fallback: between codex- and the first '-team-' / '-oauth'
    m = re.match(r"^codex-(.+?)(?:-team|-oauth)", name)
    if m:
        return m.group(1)
    return ""


def _load_account_statuses(accounts_file: Path) -> dict[str, str]:
    """Load account statuses by normalized email from accounts.json."""
    if not accounts_file.exists():
        raise FileNotFoundError(f"accounts file not found: {accounts_file}")
    data = json.loads(accounts_file.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"accounts file must contain a JSON array: {accounts_file}")
    statuses: dict[str, str] = {}
    for item in data:
        if not isinstance(item, dict):
            continue
        email = (item.get("email") or "").strip().lower()
        if not email:
            continue
        statuses[email] = (item.get("status") or "").strip().lower()
    return statuses


def _build_reauth_email_list(
    results: list[cq.CheckResult],
    *,
    account_statuses: dict[str, str],
    include_non_active: bool = False,
) -> tuple[list[str], dict]:
    """Return active re-auth emails plus filtering details."""
    failed_emails: list[str] = []
    seen: set[str] = set()
    filtered_non_active: list[dict] = []
    filtered_missing_account: list[dict] = []
    total_401 = 0

    for r in results:
        if r.classification != "401":
            continue
        total_401 += 1
        email = (r.email or "").strip().lower()
        if not email:
            email = _email_from_filename(Path(r.file).name).lower()
        if not email or email in seen:
            continue
        seen.add(email)

        status = account_statuses.get(email)
        if status is None:
            filtered_missing_account.append({"email": email, "file": r.file})
            continue
        if status != _ACTIVE_STATUS and not include_non_active:
            filtered_non_active.append({"email": email, "status": status, "file": r.file})
            continue
        failed_emails.append(email)

    filters = {
        "total_401": total_401,
        "unique_401_emails": len(seen),
        "include_non_active": include_non_active,
        "written": len(failed_emails),
        "filtered_non_active": filtered_non_active,
        "filtered_missing_account": filtered_missing_account,
    }
    return failed_emails, filters


def _quarantine(
    results: list[cq.CheckResult],
    invalidated_dir: Path,
) -> tuple[list[str], list[dict]]:
    moved: list[str] = []
    errors: list[dict] = []
    for r in results:
        if r.classification != "401":
            continue
        src = Path(r.file)
        if not src.exists():
            continue
        dst, err = cq._move_file_safely(src, invalidated_dir)
        if err:
            errors.append({"file": r.file, "error": err})
        elif dst:
            moved.append(dst)
    return moved, errors


def main() -> int:
    description = (__doc__ or "Scan-and-quarantine 401 OAuth RT files within an aqw range.").split("\n\n", 1)[0]
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--auth-dir", default="auths", help="Auth files directory (default: auths)")
    parser.add_argument("--start", type=int, default=700, help="Range start, inclusive (default: 700)")
    parser.add_argument("--end", type=int, default=900, help="Range end, inclusive (default: 900)")
    parser.add_argument("--workers", type=int, default=8, help="Concurrent probe workers (default: 8)")
    parser.add_argument("--timeout", type=float, default=20.0, help="HTTP timeout seconds (default: 20)")
    parser.add_argument("--no-refresh", action="store_true", help="Do not attempt RT refresh on 401.")
    parser.add_argument("--no-quarantine", action="store_true", help="Do not move 401 files to invalidated/.")
    parser.add_argument("--dry-run", action="store_true", help="Probe + refresh in-memory; no disk writes/moves.")
    parser.add_argument("--invalidated-dir", default=None, help="Override invalidated dir. Default <auth-dir>/invalidated/.")
    parser.add_argument("--accounts-file", default="accounts.json", help="Accounts JSON used to filter re-auth emails.")
    parser.add_argument(
        "--include-non-active",
        action="store_true",
        help="Write non-active 401 accounts to --emails-out. Default writes active accounts only.",
    )
    parser.add_argument("--emails-out", default=".tmp/session_only_emails.json", help="Re-auth email list output path.")
    parser.add_argument("--report-out", default=".tmp/scan_401_aqw_range_report.json", help="Detailed JSON report path.")
    parser.add_argument("--no-color", action="store_true", help="Disable ANSI color output.")
    args = parser.parse_args()

    if args.workers < 1:
        parser.error("--workers must be >= 1")
    if args.start > args.end:
        parser.error("--start must be <= --end")

    auth_dir = Path(args.auth_dir).expanduser().resolve()
    if not auth_dir.is_dir():
        print(f"Error: auth dir not found: {auth_dir}", file=sys.stderr)
        return 2
    invalidated_dir = (
        Path(args.invalidated_dir).expanduser().resolve()
        if args.invalidated_dir
        else auth_dir / "invalidated"
    )
    accounts_file = Path(args.accounts_file).expanduser().resolve()

    files = _filter_files(auth_dir, args.start, args.end)
    print(
        f"[scan_401_range] auth_dir={auth_dir} range=aqw-{args.start}..{args.end} "
        f"matched={len(files)} workers={args.workers}"
    )
    if not files:
        # Still write empty outputs so downstream automation doesn't crash.
        Path(args.emails_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.emails_out).write_text("[]\n", encoding="utf-8")
        Path(args.report_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report_out).write_text(
            json.dumps(
                {
                    "auth_dir": str(auth_dir),
                    "range": [args.start, args.end],
                    "total_scanned": 0,
                    "summary": {},
                    "quarantine": {"enabled": False, "moved": [], "errors": []},
                    "reauth_email_filter": {
                        "accounts_file": str(accounts_file),
                        "total_401": 0,
                        "unique_401_emails": 0,
                        "include_non_active": bool(args.include_non_active),
                        "written": 0,
                        "filtered_non_active": [],
                        "filtered_missing_account": [],
                    },
                    "failed_emails": [],
                    "results": [],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print("No matching files. Wrote empty outputs.")
        return 0

    scanner_args = _build_scanner_args(args)
    results = _run_scan(files, scanner_args, args.workers)

    # Reuse scanner's pretty printer for consistency.
    use_color = cq._supports_color(args.no_color)
    cq._print_table(results, use_color=use_color)

    # Quarantine remaining 401 (only when not dry-run / not --no-quarantine).
    moved: list[str] = []
    move_errors: list[dict] = []
    if not args.no_quarantine and not args.dry_run:
        moved, move_errors = _quarantine(results, invalidated_dir)
        if moved:
            print(
                f"\n[scan_401_range] Quarantined {len(moved)} files → {invalidated_dir}/"
            )
        for err in move_errors:
            print(f"  move-failed: {err['file']} :: {err['error']}", file=sys.stderr)

    # Build the failed email list for backfill_session_only_oauth.sh.  The API
    # endpoint only accepts active accounts, so filter before writing the list.
    try:
        account_statuses = _load_account_statuses(accounts_file)
    except Exception as exc:  # noqa: BLE001
        print(f"Error: cannot load account statuses: {exc}", file=sys.stderr)
        return 2
    failed_emails, email_filter = _build_reauth_email_list(
        results,
        account_statuses=account_statuses,
        include_non_active=bool(args.include_non_active),
    )
    email_filter["accounts_file"] = str(accounts_file)

    emails_out = Path(args.emails_out)
    emails_out.parent.mkdir(parents=True, exist_ok=True)
    emails_out.write_text(
        json.dumps(failed_emails, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"\n[scan_401_range] re-auth emails: {len(failed_emails)} eligible / "
        f"{email_filter['unique_401_emails']} unique 401 → {emails_out}"
    )
    if email_filter["filtered_non_active"] or email_filter["filtered_missing_account"]:
        print(
            "[scan_401_range] filtered: "
            f"non_active={len(email_filter['filtered_non_active'])}, "
            f"missing_account={len(email_filter['filtered_missing_account'])}"
        )

    # Detailed report (raw + summary).
    report = {
        "auth_dir": str(auth_dir),
        "range": [args.start, args.end],
        "total_scanned": len(results),
        "summary": {
            "auth_ok": sum(1 for r in results if r.classification == "auth_ok"),
            "refreshed": sum(1 for r in results if r.classification == "refreshed"),
            "invalidated_401": sum(1 for r in results if r.classification == "401"),
            "quota_lim": sum(1 for r in results if r.classification == "quota_lim"),
            "other": sum(1 for r in results if r.classification == "other"),
            "refresh_attempted": sum(1 for r in results if r.refresh_attempted),
            "refresh_succeeded": sum(
                1 for r in results if r.refresh_attempted and r.refresh_succeeded
            ),
        },
        "quarantine": {
            "enabled": (not args.no_quarantine) and (not args.dry_run),
            "invalidated_dir": str(invalidated_dir),
            "moved": moved,
            "errors": move_errors,
        },
        "reauth_email_filter": email_filter,
        "failed_emails": failed_emails,
        "results": [asdict(r) for r in results],
    }
    report_out = Path(args.report_out)
    report_out.parent.mkdir(parents=True, exist_ok=True)
    report_out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"[scan_401_range] report: {report_out}")

    # Exit code: non-zero if there are still-401 files (after refresh).
    return 1 if failed_emails else 0


if __name__ == "__main__":
    raise SystemExit(main())
