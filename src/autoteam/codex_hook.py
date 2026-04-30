"""Helpers for the local Codex monitoring hook."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import time
from pathlib import Path

import requests

from autoteam import outbound_proxy
from autoteam.accounts import find_account, load_accounts
from autoteam.flow_runs import load_flow_runs
from autoteam.textio import read_text, write_text

PROJECT_ROOT = Path(__file__).parent.parent.parent
HOOK_DIR = PROJECT_ROOT / ".autoteam-hook"
RUNTIME_DIR = HOOK_DIR / "runtime"
LOG_DIR = HOOK_DIR / "logs"
CONFIG_FILE = RUNTIME_DIR / "campaign.json"
PROMPT_FILE = RUNTIME_DIR / "codex-monitor-prompt.txt"
CHECKER_LOG = LOG_DIR / "checker.log"
INSTALL_LOG = LOG_DIR / "install.log"
API_LOG = LOG_DIR / "api.stdout.log"
CRON_MARKER = "# AUTOTEAM_CODEX_MONITOR"
DEFAULT_TARGET_SUCCESS = 100
DEFAULT_INTERVAL_MINUTES = 10


def ensure_hook_dirs() -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def _now() -> float:
    return time.time()


def _default_config() -> dict:
    return {
        "enabled": True,
        "target_success": DEFAULT_TARGET_SUCCESS,
        "interval_minutes": DEFAULT_INTERVAL_MINUTES,
        "api_base_url": "http://127.0.0.1:8787",
        "api_key": os.environ.get("API_KEY", ""),
        "join_mode": "direct",
        "batch_size": 6,
        "parallel_workers": 3,
        "managed_run_ids": [],
        "last_check_at": None,
        "last_success_count": 0,
        "last_running_run_id": "",
        "last_codex_exit_code": None,
        "last_codex_started_at": None,
        "last_codex_finished_at": None,
        "last_codex_output_file": "",
        "cron_installed": False,
        "completed_at": None,
    }


def load_campaign_config() -> dict:
    ensure_hook_dirs()
    if not CONFIG_FILE.exists():
        config = _default_config()
        save_campaign_config(config)
        return config
    text = read_text(CONFIG_FILE).strip()
    if not text:
        config = _default_config()
        save_campaign_config(config)
        return config
    data = json.loads(text)
    config = _default_config()
    config.update(data if isinstance(data, dict) else {})
    return config


def save_campaign_config(config: dict) -> None:
    ensure_hook_dirs()
    write_text(CONFIG_FILE, json.dumps(config, indent=2, ensure_ascii=False))


def update_campaign_config(**fields) -> dict:
    config = load_campaign_config()
    config.update(fields)
    save_campaign_config(config)
    return config


def log_line(path: Path, message: str) -> None:
    ensure_hook_dirs()
    stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    previous = read_text(path) if path.exists() else ""
    write_text(path, f"{previous}[{stamp}] {message}\n")


def summarize_campaign(config: dict | None = None) -> dict:
    config = config or load_campaign_config()
    managed = set(config.get("managed_run_ids") or [])
    runs = load_flow_runs()
    matched = [run for run in runs if run.get("run_id") in managed] if managed else []
    if not matched and runs:
        latest = runs[0]
        managed = {latest.get("run_id")}
        matched = [latest]

    total_success = sum(int(run.get("success_count") or 0) for run in matched)
    total_failed = sum(int(run.get("failed_count") or 0) for run in matched)
    total_attempted = sum(int(run.get("attempted_count") or 0) for run in matched)
    running_runs = [run for run in matched if run.get("status") == "running"]
    paused_runs = [run for run in matched if run.get("status") == "paused"]
    failed_runs = [run for run in matched if run.get("status") == "failed"]
    completed_runs = [run for run in matched if run.get("status") == "completed"]

    latest_run = matched[0] if matched else None
    latest_accounts = latest_run.get("accounts", []) if latest_run else []
    recent_accounts = latest_accounts[-5:] if latest_accounts else []

    return {
        "managed_run_ids": [run.get("run_id") for run in matched],
        "run_count": len(matched),
        "total_success": total_success,
        "total_failed": total_failed,
        "total_attempted": total_attempted,
        "running_run_ids": [run.get("run_id") for run in running_runs],
        "paused_run_ids": [run.get("run_id") for run in paused_runs],
        "failed_run_ids": [run.get("run_id") for run in failed_runs],
        "completed_run_ids": [run.get("run_id") for run in completed_runs],
        "latest_run_id": latest_run.get("run_id") if latest_run else "",
        "latest_run_status": latest_run.get("status") if latest_run else "",
        "latest_run_success_count": int(latest_run.get("success_count") or 0) if latest_run else 0,
        "latest_run_target": int(latest_run.get("target") or 0) if latest_run else 0,
        "recent_accounts": recent_accounts,
        "target_success": int(config.get("target_success") or DEFAULT_TARGET_SUCCESS),
    }


def campaign_reached_target(config: dict | None = None) -> bool:
    summary = summarize_campaign(config)
    return summary["total_success"] >= summary["target_success"]


def build_api_headers(config: dict | None = None) -> dict[str, str]:
    config = config or load_campaign_config()
    api_key = (config.get("api_key") or "").strip()
    if not api_key:
        return {}
    return {"Authorization": f"Bearer {api_key}"}


def is_port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect((host, port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def api_service_available(config: dict | None = None, timeout: float = 5.0) -> bool:
    config = config or load_campaign_config()
    api_base = (config.get("api_base_url") or "http://127.0.0.1:8787").rstrip("/")
    try:
        resp = outbound_proxy.request("GET", f"{api_base}/api/auth/check", headers=build_api_headers(config), timeout=timeout)
    except requests.RequestException:
        return False
    return resp.status_code in {200, 401}


def start_local_api_service() -> None:
    ensure_hook_dirs()
    command = f"cd {PROJECT_ROOT} && nohup uv run autoteam api >> {API_LOG} 2>&1 &"
    subprocess.Popen(["/bin/bash", "-lc", command], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def ensure_api_service(config: dict | None = None, timeout_seconds: float = 20.0) -> bool:
    config = config or load_campaign_config()
    if api_service_available(config):
        return True

    log_line(CHECKER_LOG, "api unavailable, trying to start local service")
    start_local_api_service()
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if api_service_available(config):
            log_line(CHECKER_LOG, "api service ready")
            return True
        time.sleep(1)
    log_line(CHECKER_LOG, "api service still unavailable after restart attempt")
    return False


def find_resumable_run(config: dict | None = None) -> dict | None:
    config = config or load_campaign_config()
    managed_ids = set(config.get("managed_run_ids") or [])
    runs = load_flow_runs()
    candidates = []
    for run in runs:
        run_id = run.get("run_id")
        if managed_ids and run_id not in managed_ids:
            continue
        if int(run.get("success_count") or 0) >= int(run.get("target") or 0):
            continue
        if run.get("status") == "running":
            continue
        candidates.append(run)
    return candidates[0] if candidates else None


def append_managed_run_id(run_id: str, config: dict | None = None) -> dict:
    config = config or load_campaign_config()
    run_id = (run_id or "").strip()
    run_ids = [item for item in (config.get("managed_run_ids") or []) if item]
    if run_id and run_id not in run_ids:
        run_ids.append(run_id)
    return update_campaign_config(managed_run_ids=run_ids)


def resume_run_via_api(run_id: str, config: dict | None = None) -> dict:
    config = config or load_campaign_config()
    api_base = (config.get("api_base_url") or "http://127.0.0.1:8787").rstrip("/")
    resp = outbound_proxy.request(
        "POST",
        f"{api_base}/api/cpa-batch/runs/{run_id}/resume",
        headers=build_api_headers(config),
        timeout=30,
    )
    resp.raise_for_status()
    append_managed_run_id(run_id, config)
    return resp.json()


def start_cpa_batch_via_api(
    *,
    target: int,
    batch_size: int,
    parallel_workers: int,
    join_mode: str,
    config: dict | None = None,
) -> dict:
    config = config or load_campaign_config()
    api_base = (config.get("api_base_url") or "http://127.0.0.1:8787").rstrip("/")
    payload = {
        "target": int(target),
        "batch_size": int(batch_size),
        "parallel_workers": int(parallel_workers),
        "join_mode": join_mode,
    }
    resp = outbound_proxy.request(
        "POST",
        f"{api_base}/api/tasks/cpa-batch",
        headers={**build_api_headers(config), "Content-Type": "application/json"},
        json=payload,
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    run_id = ((data.get("params") or {}).get("run_id") or "").strip()
    if run_id:
        append_managed_run_id(run_id, config)
    return data


def fetch_tasks_via_api(config: dict | None = None) -> list[dict]:
    config = config or load_campaign_config()
    api_base = (config.get("api_base_url") or "http://127.0.0.1:8787").rstrip("/")
    resp = outbound_proxy.request(
        "GET",
        f"{api_base}/api/tasks",
        headers=build_api_headers(config),
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    return data if isinstance(data, list) else []


def fetch_accounts_via_api(config: dict | None = None) -> list[dict]:
    config = config or load_campaign_config()
    api_base = (config.get("api_base_url") or "http://127.0.0.1:8787").rstrip("/")
    resp = outbound_proxy.request(
        "GET",
        f"{api_base}/api/accounts",
        headers=build_api_headers(config),
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    return data if isinstance(data, list) else []


def fetch_cpa_files_via_api(config: dict | None = None) -> list[dict]:
    config = config or load_campaign_config()
    api_base = (config.get("api_base_url") or "http://127.0.0.1:8787").rstrip("/")
    resp = outbound_proxy.request(
        "GET",
        f"{api_base}/api/cpa/files",
        headers=build_api_headers(config),
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    return data if isinstance(data, list) else []


def verify_managed_success_accounts(config: dict | None = None) -> list[dict]:
    config = config or load_campaign_config()
    managed_ids = set(config.get("managed_run_ids") or [])
    accounts = load_accounts()
    issues: list[dict] = []
    for run in load_flow_runs():
        if managed_ids and run.get("run_id") not in managed_ids:
            continue
        for item in run.get("accounts", []):
            if item.get("status") != "success":
                continue
            email = item.get("email") or ""
            account = find_account(accounts, email)
            if not account:
                issues.append({"email": email, "issue": "account_missing"})
                continue
            missing = []
            if not account.get("plan_type"):
                missing.append("plan_type")
            if not account.get("auth_file"):
                missing.append("auth_file")
            if not account.get("cpa_uploaded_at"):
                missing.append("cpa_uploaded_at")
            if missing:
                issues.append({"email": email, "issue": ",".join(missing)})
    return issues


def verify_managed_cpa_records(config: dict | None = None) -> list[dict]:
    config = config or load_campaign_config()
    managed_ids = set(config.get("managed_run_ids") or [])
    remote_files = fetch_cpa_files_via_api(config)
    remote_names = {str(item.get("name") or "").strip() for item in remote_files if item.get("name")}
    accounts_by_email = {
        str(item.get("email") or "").strip().lower(): item
        for item in fetch_accounts_via_api(config)
        if item.get("email")
    }
    issues: list[dict] = []

    for run in load_flow_runs():
        if managed_ids and run.get("run_id") not in managed_ids:
            continue
        for item in run.get("accounts", []):
            if item.get("status") != "success":
                continue

            email = str(item.get("email") or "").strip().lower()
            account = accounts_by_email.get(email)
            if not account:
                issues.append({"email": email, "issue": "account_missing_in_api"})
                continue

            missing = []
            auth_file = str(account.get("auth_file") or "").strip()
            auth_name = Path(auth_file).name if auth_file else ""
            if not account.get("qualified_at"):
                missing.append("qualified_at")
            if auth_name and auth_name not in remote_names:
                missing.append("cpa_remote_missing")
            if missing:
                issues.append({"email": email, "issue": ",".join(missing)})

    return issues


def build_codex_prompt(config: dict | None = None) -> str:
    config = config or load_campaign_config()
    summary = summarize_campaign(config)
    latest_run_id = summary["latest_run_id"] or "(none)"
    managed_run_ids = ", ".join(summary["managed_run_ids"]) or "(none)"
    running_run_ids = ", ".join(summary["running_run_ids"]) or "(none)"
    paused_run_ids = ", ".join(summary["paused_run_ids"]) or "(none)"
    recent_lines = []
    for item in summary["recent_accounts"]:
        recent_lines.append(
            f"- {item.get('email')} | worker={item.get('worker_index')} | status={item.get('status')} | stage={item.get('stage')} | error={item.get('error_message') or '-'}"
        )
    recent_block = "\n".join(recent_lines) if recent_lines else "- 无"

    prompt = f"""你在 `/mnt/x/project/AutoTeam` 工作。

目标：
- 每 {int(config.get('interval_minutes') or DEFAULT_INTERVAL_MINUTES)} 分钟巡检一次 AutoTeam 的 CPA 批量任务。
- 总成功数达到 {summary['target_success']} 后停止巡检。

当前已知：
- managed_run_ids: {managed_run_ids}
- latest_run_id: {latest_run_id}
- latest_run_status: {summary['latest_run_status'] or '(none)'}
- running_run_ids: {running_run_ids}
- paused_run_ids: {paused_run_ids}
- total_success: {summary['total_success']}
- total_failed: {summary['total_failed']}
- total_attempted: {summary['total_attempted']}
- join_mode: {config.get('join_mode')}
- batch_size: {config.get('batch_size')}
- parallel_workers: {config.get('parallel_workers')}
- api_base_url: {config.get('api_base_url')}

最近账号记录：
{recent_block}

你需要按顺序执行：
1. 先检查当前本地 JSON 状态，以及 hook 刚才是否已经恢复或新开 run。
2. 如果已有 run 在 running，确认没有卡死，并输出当前进展。
3. 如果 run 已停止，判断最近失败点是否在注册、session、quota 或 CPA 上传。
4. 如果发现 `account_deactivated`，确认该账号已标记 `unavailable` 并跳过。
5. 核对成功账号是否保存了 `plan_type`、`auth_file`、`cpa_uploaded_at`、`qualified_at`，并检查账号登记是否完整。
6. 通过 API 检查 CPA 远端文件列表，确认异步 CPA JSON 已真正入库，不只看本地状态。
7. 如果看到 `email_skipped`，把它视为“已跳过被标记邮箱并改用新邮箱”，不是主链路失败。
8. 最终只做简短状态结论，说明当前总成功数、正在运行的 run、是否需要下次 {int(config.get('interval_minutes') or DEFAULT_INTERVAL_MINUTES)} 分钟继续检查。

限制：
- 不要改巡检为超长间隔。
- 不要停止当前服务，除非服务本身已经挂掉且需要拉起。
- 优先复用已有 run，不要重复新开一堆无关 run。
"""
    ensure_hook_dirs()
    write_text(PROMPT_FILE, prompt)
    return prompt


def remove_monitor_cron() -> bool:
    result = subprocess.run(["crontab", "-l"], capture_output=True, text=True, check=False)
    lines = result.stdout.splitlines() if result.returncode == 0 else []
    kept = [line for line in lines if CRON_MARKER not in line]
    content = "\n".join(kept).rstrip() + ("\n" if kept else "")
    install = subprocess.run(["crontab", "-"], input=content, text=True, capture_output=True, check=False)
    return install.returncode == 0
