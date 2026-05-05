"""Local run records for long account-pool workflows."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from autoteam.textio import read_text, write_text

PROJECT_ROOT = Path(__file__).parent.parent.parent
FLOW_RUNS_FILE = PROJECT_ROOT / "flow_runs.json"
MAX_FLOW_RUNS = 50
ACTIVE_FLOW_STATUSES = {"pending", "running"}
_FLOW_RUNS_LOCK = threading.RLock()


def _now() -> float:
    return time.time()


def load_flow_runs() -> list[dict]:
    with _FLOW_RUNS_LOCK:
        if not FLOW_RUNS_FILE.exists():
            return []
        text = read_text(FLOW_RUNS_FILE).strip()
        if not text:
            return []
        data = json.loads(text)
        if isinstance(data, list):
            return data
        return []


def save_flow_runs(runs: list[dict]) -> None:
    with _FLOW_RUNS_LOCK:
        ordered = sorted(runs, key=lambda item: item.get("created_at") or 0, reverse=True)
        write_text(FLOW_RUNS_FILE, json.dumps(ordered[:MAX_FLOW_RUNS], indent=2, ensure_ascii=False))


def get_flow_run(run_id: str) -> dict | None:
    with _FLOW_RUNS_LOCK:
        for run in load_flow_runs():
            if run.get("run_id") == run_id:
                return run
        return None


def create_flow_run(run_id: str, *, target: int, batch_size: int, join_mode: str, parallel_workers: int = 1) -> dict:
    with _FLOW_RUNS_LOCK:
        runs = [run for run in load_flow_runs() if run.get("run_id") != run_id]
        run = {
            "run_id": run_id,
            "target": int(target),
            "batch_size": int(batch_size),
            "join_mode": join_mode,
            "parallel_workers": int(parallel_workers or 1),
            "status": "running",
            "created_at": _now(),
            "started_at": _now(),
            "finished_at": None,
            "success_count": 0,
            "failed_count": 0,
            "attempted_count": 0,
            "current_batch": 1,
            "fatal_error": "",
            "accounts": [],
        }
        runs.insert(0, run)
        save_flow_runs(runs)
        return run


def update_flow_run(run_id: str, **fields) -> dict | None:
    with _FLOW_RUNS_LOCK:
        runs = load_flow_runs()
        updated = None
        for run in runs:
            if run.get("run_id") == run_id:
                run.update(fields)
                updated = run
                break
        if updated is not None:
            save_flow_runs(runs)
        return updated


def mark_interrupted_running_runs(reason: str = "服务重启或任务中断") -> int:
    with _FLOW_RUNS_LOCK:
        runs = load_flow_runs()
        changed = 0
        now = _now()
        for run in runs:
            if run.get("status") not in ACTIVE_FLOW_STATUSES:
                continue
            run["status"] = "failed"
            run["finished_at"] = run.get("finished_at") or now
            run["fatal_error"] = run.get("fatal_error") or reason
            run["pause_requested"] = False
            for account in run.get("accounts", []):
                if account.get("status") not in ACTIVE_FLOW_STATUSES:
                    continue
                account["status"] = "failed"
                account["error_level"] = "fatal"
                account["error_message"] = account.get("error_message") or reason
                account["finished_at"] = account.get("finished_at") or now
                account.setdefault("events", []).append(
                    {
                        "ts": now,
                        "stage": account.get("stage") or "interrupted",
                        "message": reason,
                        "error_level": "fatal",
                    }
                )
            run["success_count"] = sum(1 for item in run.get("accounts", []) if item.get("status") == "success")
            run["failed_count"] = sum(1 for item in run.get("accounts", []) if item.get("status") == "failed")
            run["attempted_count"] = len(run.get("accounts", []))
            changed += 1
        if changed:
            save_flow_runs(runs)
        return changed


def stop_active_flow_runs(reason: str = "用户强制停止", *, skip_run_ids: set[str] | None = None) -> list[dict]:
    """Mark all active flow runs as stopped for the global force-stop action."""
    with _FLOW_RUNS_LOCK:
        skip_run_ids = {str(item) for item in (skip_run_ids or set()) if item}
        runs = load_flow_runs()
        stopped: list[dict] = []
        now = _now()
        for run in runs:
            if run.get("status") not in ACTIVE_FLOW_STATUSES:
                continue
            if str(run.get("run_id") or "") in skip_run_ids:
                stopped.append(
                    {
                        "run_id": run.get("run_id"),
                        "skipped": True,
                        "reason": "任务线程仍在运行，暂不关闭批量流程记录",
                    }
                )
                continue

            run["status"] = "stopped"
            run["finished_at"] = run.get("finished_at") or now
            run["fatal_error"] = reason
            run["pause_requested"] = False
            active_accounts = 0
            for account in run.get("accounts", []):
                if account.get("status") not in ACTIVE_FLOW_STATUSES:
                    continue
                active_accounts += 1
                account["status"] = "failed"
                account["error_level"] = "fatal"
                account["error_message"] = account.get("error_message") or reason
                account["finished_at"] = account.get("finished_at") or now
                account.setdefault("events", []).append(
                    {
                        "ts": now,
                        "stage": account.get("stage") or "interrupted",
                        "message": reason,
                        "error_level": "fatal",
                    }
                )
            run["success_count"] = sum(1 for item in run.get("accounts", []) if item.get("status") == "success")
            run["failed_count"] = sum(1 for item in run.get("accounts", []) if item.get("status") == "failed")
            run["attempted_count"] = len(run.get("accounts", []))
            stopped.append(
                {
                    "run_id": run.get("run_id"),
                    "join_mode": run.get("join_mode"),
                    "target": run.get("target"),
                    "active_accounts": active_accounts,
                }
            )
        if stopped:
            save_flow_runs(runs)
        return stopped


def fail_running_flow_accounts(run_id: str, reason: str = "恢复前清理遗留运行记录") -> int:
    """Mark lingering running account records as failed for one flow run."""
    with _FLOW_RUNS_LOCK:
        runs = load_flow_runs()
        changed = 0
        now = _now()
        for run in runs:
            if run.get("run_id") != run_id:
                continue
            for account in run.get("accounts", []):
                if account.get("status") not in ACTIVE_FLOW_STATUSES:
                    continue
                account["status"] = "failed"
                if account.get("error_level") not in {"warn", "error", "fatal"}:
                    account["error_level"] = "error"
                account["error_message"] = account.get("error_message") or reason
                account["finished_at"] = account.get("finished_at") or now
                account.setdefault("events", []).append(
                    {
                        "ts": now,
                        "stage": account.get("stage") or "interrupted",
                        "message": reason,
                        "error_level": account["error_level"],
                    }
                )
                changed += 1
            if changed:
                run["attempted_count"] = len(run.get("accounts", []))
                run["success_count"] = sum(1 for item in run.get("accounts", []) if item.get("status") == "success")
                run["failed_count"] = sum(1 for item in run.get("accounts", []) if item.get("status") == "failed")
            break
        if changed:
            save_flow_runs(runs)
        return changed


def request_flow_pause(run_id: str) -> dict | None:
    return update_flow_run(run_id, pause_requested=True)


def resume_flow_run(run_id: str) -> dict | None:
    run = get_flow_run(run_id)
    if not run:
        return None
    status = run.get("status") or "running"
    if status != "running":
        status = "running"
    return update_flow_run(run_id, pause_requested=False, status=status, finished_at=None, fatal_error="")


def is_flow_pause_requested(run_id: str) -> bool:
    run = get_flow_run(run_id)
    return bool(run and run.get("pause_requested"))


def _find_account(run: dict, email: str) -> dict | None:
    normalized = (email or "").strip().lower()
    for account in run.setdefault("accounts", []):
        if (account.get("email") or "").strip().lower() == normalized:
            return account
    return None


def upsert_flow_account(run_id: str, email: str, **fields) -> dict | None:
    with _FLOW_RUNS_LOCK:
        runs = load_flow_runs()
        updated = None
        for run in runs:
            if run.get("run_id") != run_id:
                continue
            account = _find_account(run, email)
            if account is None:
                account = {
                    "email": (email or "").strip().lower(),
                    "batch_index": fields.pop("batch_index", None),
                    "worker_index": fields.pop("worker_index", None),
                    "status": "pending",
                    "stage": "",
                    "error_level": "",
                    "error_message": "",
                    "plan_type": "",
                    "auth_file": "",
                    "cpa_uploaded": False,
                    "started_at": _now(),
                    "finished_at": None,
                    "events": [],
                }
                run.setdefault("accounts", []).append(account)
            account.update({key: value for key, value in fields.items() if value is not None})
            run["attempted_count"] = len(run.get("accounts", []))
            run["success_count"] = sum(1 for item in run.get("accounts", []) if item.get("status") == "success")
            run["failed_count"] = sum(1 for item in run.get("accounts", []) if item.get("status") == "failed")
            updated = account
            break
        if updated is not None:
            save_flow_runs(runs)
        return updated


def delete_flow_account(run_id: str, email: str) -> None:
    with _FLOW_RUNS_LOCK:
        runs = load_flow_runs()
        normalized = (email or "").strip().lower()
        changed = False
        for run in runs:
            if run.get("run_id") != run_id:
                continue
            original = run.get("accounts", [])
            run["accounts"] = [item for item in original if (item.get("email") or "").strip().lower() != normalized]
            changed = len(run["accounts"]) != len(original)
            run["attempted_count"] = len(run.get("accounts", []))
            run["success_count"] = sum(1 for item in run.get("accounts", []) if item.get("status") == "success")
            run["failed_count"] = sum(1 for item in run.get("accounts", []) if item.get("status") == "failed")
            break
        if changed:
            save_flow_runs(runs)


def append_flow_event(
    run_id: str,
    email: str,
    *,
    stage: str,
    message: str,
    error_level: str = "info",
    status: str | None = None,
    batch_index: int | None = None,
    **fields,
) -> dict | None:
    with _FLOW_RUNS_LOCK:
        account = upsert_flow_account(
            run_id,
            email,
            batch_index=batch_index,
            stage=stage,
            error_level=error_level,
            error_message=message if error_level in ("warn", "error", "fatal") else "",
            status=status,
            **fields,
        )
        if account is None:
            return None
        event = {
            "ts": _now(),
            "stage": stage,
            "message": message,
            "error_level": error_level,
        }
        account.setdefault("events", []).append(event)
        upsert_flow_account(run_id, email, events=account["events"])
        return account
