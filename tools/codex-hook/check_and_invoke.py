#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from autoteam.codex_hook import (  # noqa: E402
    CHECKER_LOG,
    build_codex_prompt,
    campaign_reached_target,
    ensure_api_service,
    fetch_tasks_via_api,
    find_resumable_run,
    load_campaign_config,
    log_line,
    remove_monitor_cron,
    resume_run_via_api,
    save_campaign_config,
    start_cpa_batch_via_api,
    summarize_campaign,
    update_campaign_config,
    verify_managed_cpa_records,
    verify_managed_success_accounts,
)


def main() -> int:
    config = load_campaign_config()
    summary = summarize_campaign(config)
    update_campaign_config(
        last_check_at=time.time(),
        last_success_count=summary["total_success"],
        last_running_run_id=summary["running_run_ids"][0] if summary["running_run_ids"] else "",
    )
    config = load_campaign_config()

    if not config.get("enabled", True):
        log_line(CHECKER_LOG, "hook disabled, skip")
        return 0

    if campaign_reached_target(config):
        config["enabled"] = False
        config["completed_at"] = time.time()
        save_campaign_config(config)
        removed = remove_monitor_cron()
        log_line(
            CHECKER_LOG,
            f"target reached: success={summary['total_success']}, cron_removed={removed}",
        )
        return 0

    verification_issues = verify_managed_success_accounts(config)
    if verification_issues:
        log_line(CHECKER_LOG, f"managed success accounts verification issues: {verification_issues}")

    cpa_record_issues = []
    try:
        cpa_record_issues = verify_managed_cpa_records(config)
    except Exception as exc:
        log_line(CHECKER_LOG, f"managed cpa record verification failed: {exc}")
    if cpa_record_issues:
        log_line(CHECKER_LOG, f"managed cpa record issues: {cpa_record_issues}")

    if not ensure_api_service(config):
        log_line(CHECKER_LOG, "api unavailable, skip codex exec")
        return 1

    summary = summarize_campaign(config)
    if not summary["running_run_ids"]:
        resumable = find_resumable_run(config)
        try:
            if resumable:
                resumed = resume_run_via_api(resumable["run_id"], config)
                log_line(CHECKER_LOG, f"resumed run via api: {resumed}")
            else:
                remaining = max(1, summary["target_success"] - summary["total_success"])
                target = min(100, remaining)
                started = start_cpa_batch_via_api(
                    target=target,
                    batch_size=int(config.get("batch_size") or 6),
                    parallel_workers=int(config.get("parallel_workers") or 3),
                    join_mode=(config.get("join_mode") or "direct"),
                    config=config,
                )
                log_line(CHECKER_LOG, f"started new cpa batch via api: {started}")
        except Exception as exc:
            busy_tasks = []
            try:
                busy_tasks = [
                    {
                        "task_id": item.get("task_id"),
                        "command": item.get("command"),
                        "status": item.get("status"),
                    }
                    for item in fetch_tasks_via_api(config)
                    if item.get("status") in {"pending", "running"}
                ]
            except Exception as task_exc:
                log_line(CHECKER_LOG, f"fetch tasks after api failure failed: {task_exc}")
            log_line(CHECKER_LOG, f"api action failed: {exc}; busy_tasks={busy_tasks}")

    prompt = build_codex_prompt(config)
    output_path = PROJECT_ROOT / ".autoteam-hook" / "logs" / f"codex-{int(time.time())}.last.txt"
    cmd = [
        "codex",
        "exec",
        "--skip-git-repo-check",
        "--sandbox",
        "danger-full-access",
        "--full-auto",
        "-C",
        str(PROJECT_ROOT),
        "-o",
        str(output_path),
        "-",
    ]
    log_line(
        CHECKER_LOG,
        f"starting codex exec: success={summary['total_success']}, latest_run={summary['latest_run_id'] or '-'}",
    )
    update_campaign_config(last_codex_started_at=time.time(), last_codex_output_file=str(output_path))
    result = subprocess.run(cmd, input=prompt, text=True, capture_output=True, check=False)
    update_campaign_config(last_codex_finished_at=time.time(), last_codex_exit_code=result.returncode)
    if result.stdout.strip():
        log_line(CHECKER_LOG, f"codex stdout: {result.stdout.strip()[:1500]}")
    if result.stderr.strip():
        log_line(CHECKER_LOG, f"codex stderr: {result.stderr.strip()[:1500]}")
    log_line(CHECKER_LOG, f"codex exit={result.returncode}")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
