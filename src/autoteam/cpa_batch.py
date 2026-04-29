"""Batch account registration and CPA auth preparation."""

from __future__ import annotations

import base64
import json
import logging
import queue
import threading
import time
import uuid
from pathlib import Path

from playwright.sync_api import sync_playwright

from autoteam.accounts import STATUS_ACTIVE, STATUS_EXHAUSTED, add_account, find_account, load_accounts, update_account
from autoteam.browser_runtime import acquire_browser_lease
from autoteam.chatgpt_api import ChatGPTTeamAPI
from autoteam.codex_auth import (
    check_codex_quota,
    login_codex_via_browser,
    quota_result_quota_info,
    quota_result_resets_at,
    save_auth_file,
)
from autoteam.config import get_playwright_launch_options
from autoteam.cpa_sync import upload_to_cpa
from autoteam.flow_runs import (
    append_flow_event,
    create_flow_run,
    delete_flow_account,
    get_flow_run,
    is_flow_pause_requested,
    resume_flow_run,
    update_flow_run,
)
from autoteam.invite import register_with_invite
from autoteam.mail_provider import get_account_mail_provider, get_mail_client, get_mail_client_for_account
from autoteam.manager import invite_to_team
from autoteam.textio import read_text

logger = logging.getLogger(__name__)

DEFAULT_TARGET = 100
DEFAULT_BATCH_SIZE = 20
MAX_ATTEMPT_MULTIPLIER = 2
MAX_ACCOUNT_FAILURES = 3
MIN_COMPLETED_SUCCESS_RATE = 95.0
SUCCESS_RATE_SAFETY_MARGIN = 1.0
JOIN_MODE_DIRECT = "direct"
JOIN_MODE_INVITE = "invite"
VALID_JOIN_MODES = {JOIN_MODE_DIRECT, JOIN_MODE_INVITE}


class AccountFlowError(RuntimeError):
    """Raised after an account email is known, so monitors can record that account."""

    def __init__(self, email: str, message: str):
        super().__init__(message)
        self.email = _normalized_email(email)


class CpaBatchHooks:
    """Event hooks used by the batch runner and Web monitor."""

    def __init__(self, run_id: str):
        self.run_id = run_id

    def run_update(self, **fields) -> None:
        update_flow_run(self.run_id, **fields)

    def account_event(self, email: str, **fields) -> None:
        append_flow_event(self.run_id, email, **fields)

    def remove_account(self, email: str) -> None:
        delete_flow_account(self.run_id, email)

    def pause_requested(self) -> bool:
        return is_flow_pause_requested(self.run_id)

    def pause(self) -> None:
        update_flow_run(self.run_id, status="paused", finished_at=time.time())


class _CpaUploadWorker:
    def __init__(self, hooks: CpaBatchHooks):
        self.hooks = hooks
        self.jobs: queue.Queue[dict | None] = queue.Queue()
        self.results: queue.Queue[dict] = queue.Queue()
        self.thread = threading.Thread(target=self._run, name=f"cpa-upload-{hooks.run_id}", daemon=True)
        self._started = False
        self._finished = False
        self.failures: dict[str, int] = {}

    def start(self) -> None:
        if not self._started:
            self.thread.start()
            self._started = True

    def enqueue(self, email: str, *, batch_index: int | None = None) -> None:
        self.jobs.put({"email": _normalized_email(email), "batch_index": batch_index})

    def finish(self) -> None:
        if self._started and not self._finished:
            self.jobs.put(None)
            self._finished = True

    def join(self, timeout: float | None = None) -> None:
        if self._started:
            self.thread.join(timeout=timeout)

    def _run(self) -> None:
        account_mail_cache: dict[str, object] = {}
        while True:
            job = self.jobs.get()
            try:
                if job is None:
                    return
                email = str(job.get("email") or "")
                batch_index = job.get("batch_index")
                try:
                    update_account(
                        email,
                        flow_status="running",
                        flow_stage="cpa_auth",
                        flow_error_level="info",
                        flow_error_message="",
                    )
                    self.hooks.account_event(
                        email,
                        batch_index=batch_index,
                        stage="cpa_auth",
                        message="开始 Codex 认证、额度检查和 CPA 上传",
                        status="running",
                    )
                    result = _verify_and_upload_cpa(
                        email,
                        account_mail_cache,
                        hooks=self.hooks,
                        batch_index=batch_index,
                    )
                    update_account(
                        email,
                        flow_status="success",
                        flow_stage="completed",
                        flow_error_level="info",
                        flow_error_message="",
                        plan_type=result["plan_type"],
                    )
                    self.hooks.account_event(
                        email,
                        batch_index=batch_index,
                        stage="completed",
                        message="CPA JSON 已可用",
                        status="success",
                        plan_type=result["plan_type"],
                        auth_file=result["auth_file"],
                        auth_name=result["auth_name"],
                        cpa_uploaded=True,
                        finished_at=time.time(),
                    )
                    self.failures.pop(email, None)
                    self.results.put({"ok": True, "email": email, "result": result})
                except Exception as exc:
                    failure_count = self.failures.get(email, 0) + 1
                    self.failures[email] = failure_count
                    if failure_count < MAX_ACCOUNT_FAILURES:
                        message = f"CPA 认证失败第 {failure_count}/{MAX_ACCOUNT_FAILURES} 次，继续重试当前账号: {exc}"
                        update_account(
                            email,
                            flow_status="running",
                            flow_stage="cpa_retry",
                            flow_error_level="warn",
                            flow_error_message=message,
                            flow_failure_count=failure_count,
                        )
                        self.hooks.account_event(
                            email,
                            batch_index=batch_index,
                            stage="cpa_retry",
                            message=message,
                            error_level="warn",
                            status="running",
                            failure_count=failure_count,
                        )
                        self.jobs.put(job)
                        continue

                    update_account(
                        email,
                        flow_status="failed",
                        flow_stage="cpa_auth",
                        flow_error_level="error",
                        flow_error_message=str(exc),
                        flow_failure_count=failure_count,
                    )
                    self.hooks.account_event(
                        email,
                        batch_index=batch_index,
                        stage="cpa_auth",
                        message=str(exc),
                        error_level="error",
                        status="failed",
                        finished_at=time.time(),
                        failure_count=failure_count,
                    )
                    self.results.put({"ok": False, "email": email, "error": str(exc), "failure_count": failure_count})
            finally:
                self.jobs.task_done()


def _normalized_email(value: str | None) -> str:
    return (value or "").strip().lower()


def _completed_success_rate(success_count: int, failed_count: int) -> float:
    completed = int(success_count) + int(failed_count)
    if completed <= 0:
        return 100.0
    return int(success_count) * 100 / completed


def _should_pause_for_success_rate(success_count: int, failed_count: int) -> bool:
    if failed_count <= 0:
        return False
    return _completed_success_rate(success_count, failed_count) < (
        MIN_COMPLETED_SUCCESS_RATE + SUCCESS_RATE_SAFETY_MARGIN
    )


def _parse_jwt_payload(token: str) -> dict:
    parts = (token or "").split(".")
    if len(parts) < 2:
        return {}
    payload = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        return json.loads(base64.urlsafe_b64decode(payload))
    except Exception:
        return {}


def _auth_plan_from_path(auth_path: str | Path) -> str:
    path = Path(auth_path)
    try:
        auth_data = json.loads(read_text(path))
    except Exception:
        auth_data = {}

    id_token = auth_data.get("id_token") or ""
    claims = _parse_jwt_payload(id_token)
    auth_claims = claims.get("https://api.openai.com/auth", {}) if isinstance(claims, dict) else {}
    plan_type = (auth_claims.get("chatgpt_plan_type") or "").strip().lower()
    if plan_type:
        return plan_type

    name = path.name.lower()
    if "-team-" in name or "-team-" in name.replace("_", "-"):
        return "team"
    if "-plus-" in name:
        return "plus"
    if "-free-" in name:
        return "free"
    return "unknown"


def _load_auth_data(auth_path: str | Path) -> dict:
    return json.loads(read_text(Path(auth_path)))


def _account_for_email(email: str) -> dict | None:
    return find_account(load_accounts(), _normalized_email(email))


def _record_account_runtime(
    email: str,
    *,
    run_id: str | None = None,
    batch_index: int | None = None,
    flow_status: str = "running",
    flow_stage: str = "",
    flow_error_level: str = "info",
    flow_error_message: str = "",
    **fields,
) -> None:
    payload = {
        "run_id": run_id,
        "batch_index": batch_index,
        "flow_status": flow_status,
        "flow_stage": flow_stage,
        "flow_error_level": flow_error_level,
        "flow_error_message": flow_error_message,
        **fields,
    }
    update_account(email, **{key: value for key, value in payload.items() if value is not None})


def _create_direct_account(mail_client, hooks: CpaBatchHooks | None = None, batch_index: int | None = None) -> str:
    from autoteam.manager import _is_email_in_team, _register_direct_once

    account_id, email = mail_client.create_temp_email()
    email = _normalized_email(email)
    password = f"Tmp_{uuid.uuid4().hex[:12]}!"
    provider_name = getattr(mail_client, "provider_name", "")
    session_bundle: dict[str, object] = {}

    def capture_session_bundle(bundle: dict) -> None:
        session_bundle.clear()
        session_bundle.update(bundle or {})

    add_account(
        email,
        password,
        cloudmail_account_id=account_id if provider_name == "cloudmail" else None,
        mail_provider=provider_name,
        mail_account_id=account_id,
    )
    _record_account_runtime(
        email,
        run_id=hooks.run_id if hooks else None,
        batch_index=batch_index,
        flow_status="running",
        flow_stage="email_created",
    )
    if hooks:
        hooks.account_event(
            email,
            batch_index=batch_index,
            stage="email_created",
            message="邮箱已创建并写入账号池",
            status="running",
        )

    success = False
    for attempt in range(3):
        if hooks:
            hooks.account_event(
                email,
                batch_index=batch_index,
                stage="register",
                message=f"开始第 {attempt + 1}/3 次直注注册",
                status="running",
            )
        logger.info("[直接注册] 开始第 %d/3 次注册尝试: %s", attempt + 1, email)
        session_bundle.clear()
        try:
            try:
                success = _register_direct_once(
                    mail_client,
                    email,
                    password,
                    mail_account_id=account_id,
                    session_bundle_callback=capture_session_bundle,
                    require_session_bundle=True,
                )
            except TypeError as exc:
                if "require_session_bundle" not in str(exc):
                    raise
                success = _register_direct_once(
                    mail_client,
                    email,
                    password,
                    mail_account_id=account_id,
                    session_bundle_callback=capture_session_bundle,
                )
        except Exception as exc:
            success = False
            message = str(exc)
            if hooks:
                hooks.account_event(
                    email,
                    batch_index=batch_index,
                    stage="browser_restart",
                    message=f"浏览器流程异常，已关闭并准备重试当前账号: {message}",
                    error_level="warn",
                    status="running",
                )
            logger.warning("[直接注册] 浏览器流程异常，重试当前账号 %s: %s", email, exc)
            session_failed = message.startswith("ChatGPT session 提取失败")
        else:
            session_failed = False
        if success and session_bundle:
            break
        if success:
            success = False
            if hooks:
                hooks.account_event(
                    email,
                    batch_index=batch_index,
                    stage="session_auth",
                    message="注册完成但未获取 ChatGPT session CPA 凭证，重试当前账号",
                    error_level="warn",
                    status="running",
                )

        if not session_failed and _is_email_in_team(email):
            logger.info("[直接注册] 远端确认账号已在 Team 中，视为注册成功: %s", email)
            success = True
            if session_bundle:
                break
            success = False
            if hooks:
                hooks.account_event(
                    email,
                    batch_index=batch_index,
                    stage="session_auth",
                    message="远端已入席但缺少 session CPA 凭证，继续重试当前账号",
                    error_level="warn",
                    status="running",
                )

        if attempt < 2:
            if hooks:
                hooks.account_event(
                    email,
                    batch_index=batch_index,
                    stage="register_retry",
                    message="注册失败且账号不在 Team 中，60 秒后重试",
                    error_level="warn",
                    status="running",
                )
            logger.warning("[直接注册] 注册失败且账号不在 Team 中，60 秒后重试: %s", email)
            time.sleep(60)

    if not success:
        try:
            mail_client.delete_account(account_id)
        except Exception as exc:
            logger.warning("[直接注册] 删除失败临时邮箱异常: %s", exc)
        raise AccountFlowError(email, "连续 3 次直注注册失败")

    if session_bundle:
        plan_type = (session_bundle.get("plan_type") or "unknown").strip().lower()
        auth_path = save_auth_file(session_bundle)
        update_account(email, auth_file=auth_path, plan_type=plan_type)
        if hooks:
            hooks.account_event(
                email,
                batch_index=batch_index,
                stage="session_auth",
                message=f"已从 ChatGPT session 保存 CPA 凭证，plan={plan_type}",
                status="running",
                plan_type=plan_type,
                auth_file=str(auth_path),
                auth_name=Path(auth_path).name,
            )
    elif hooks:
        hooks.account_event(
            email,
            batch_index=batch_index,
            stage="session_auth",
            message="注册会话未返回可保存的 CPA 凭证",
            error_level="warn",
            status="running",
        )

    _record_account_runtime(
        email,
        run_id=hooks.run_id if hooks else None,
        batch_index=batch_index,
        flow_status="running",
        flow_stage="team_joined",
        status=STATUS_ACTIVE,
        last_active_at=time.time(),
    )
    return email


def _create_invited_account(
    chatgpt: ChatGPTTeamAPI,
    mail_client,
    hooks: CpaBatchHooks | None = None,
    batch_index: int | None = None,
) -> str:
    account_id, email = mail_client.create_temp_email()
    email = _normalized_email(email)
    password = f"Tmp_{uuid.uuid4().hex[:12]}!"
    provider_name = getattr(mail_client, "provider_name", "")

    add_account(
        email,
        password,
        cloudmail_account_id=account_id if provider_name == "cloudmail" else None,
        mail_provider=provider_name,
        mail_account_id=account_id,
    )
    _record_account_runtime(
        email,
        run_id=hooks.run_id if hooks else None,
        batch_index=batch_index,
        flow_status="running",
        flow_stage="email_created",
    )
    if hooks:
        hooks.account_event(
            email,
            batch_index=batch_index,
            stage="email_created",
            message="邮箱已创建并写入账号池",
            status="running",
        )

    if not chatgpt.browser:
        chatgpt.start()
    if not invite_to_team(chatgpt, email, seat_type="default"):
        raise AccountFlowError(email, "Team 邀请失败")
    if hooks:
        hooks.account_event(
            email,
            batch_index=batch_index,
            stage="invite_sent",
            message="Team 邀请已发送",
            status="running",
        )

    email_data = mail_client.wait_for_email(to_email=email, timeout=None, sender_keyword="openai")
    invite_link = mail_client.extract_invite_link(email_data)
    if not invite_link:
        raise AccountFlowError(email, "未获取到邀请链接")
    if hooks:
        hooks.account_event(
            email,
            batch_index=batch_index,
            stage="register",
            message="收到邀请邮件，开始注册",
            status="running",
        )

    if chatgpt.browser:
        chatgpt.stop()

    with acquire_browser_lease("cpa_batch._create_invited_account", sync_playwright_factory=sync_playwright) as lease:
        browser = lease.launch_chromium(**get_playwright_launch_options())
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
        )
        page = context.new_page()
        success, final_password = register_with_invite(page, invite_link, email, mail_client, password=password)

    if not success:
        raise AccountFlowError(email, "邀请注册未完成")

    _record_account_runtime(
        email,
        run_id=hooks.run_id if hooks else None,
        batch_index=batch_index,
        flow_status="running",
        flow_stage="team_joined",
        status=STATUS_ACTIVE,
        password=final_password,
        last_active_at=time.time(),
    )
    return email


def _ensure_mail_client_for_account(acc: dict, cache: dict[str, object]):
    provider = get_account_mail_provider(acc)
    client = cache.get(provider)
    if client is None:
        client = get_mail_client_for_account(acc)
        client.login()
        cache[provider] = client
    return client


def _ensure_team_auth(
    email: str,
    mail_client_cache: dict[str, object],
    *,
    hooks: CpaBatchHooks | None = None,
    batch_index: int | None = None,
    allow_browser_oauth: bool = True,
) -> tuple[str, str, dict]:
    acc = _account_for_email(email)
    if not acc:
        raise RuntimeError("本地账号记录不存在")

    auth_path = acc.get("auth_file") or ""
    plan_type = _auth_plan_from_path(auth_path) if auth_path and Path(auth_path).exists() else ""
    auth_data = _load_auth_data(auth_path) if auth_path and Path(auth_path).exists() else {}

    if not auth_data:
        if not allow_browser_oauth:
            raise RuntimeError("未获取到 ChatGPT session CPA 凭证，已跳过浏览器 OAuth")
        account_mail = _ensure_mail_client_for_account(acc, mail_client_cache)
        if hooks:
            hooks.account_event(
                email,
                batch_index=batch_index,
                stage="oauth",
                message="开始 Codex OAuth 登录",
                status="running",
            )
        bundle = login_codex_via_browser(email, acc.get("password", ""), mail_client=account_mail)
        if not bundle:
            raise RuntimeError("Codex 登录失败")
        plan_type = (bundle.get("plan_type") or "unknown").strip().lower()
        auth_path = save_auth_file(bundle)
        update_account(email, auth_file=auth_path, plan_type=plan_type)
        auth_data = _load_auth_data(auth_path)
        if hooks:
            hooks.account_event(
                email,
                batch_index=batch_index,
                stage="oauth",
                message=f"Codex OAuth 完成，plan={plan_type}",
                status="running",
                plan_type=plan_type,
                auth_file=str(auth_path),
                auth_name=Path(auth_path).name,
            )
    elif hooks:
        hooks.account_event(
            email,
            batch_index=batch_index,
            stage="oauth",
            message="使用本地已有 Codex 认证文件",
            status="running",
            plan_type=plan_type or "unknown",
            auth_file=str(auth_path),
            auth_name=Path(auth_path).name,
        )

    if plan_type != "team":
        update_account(email, plan_type=plan_type or "unknown")
        raise RuntimeError(f"Codex plan={plan_type or 'unknown'}，不是 team")

    update_account(email, status=STATUS_ACTIVE, plan_type=plan_type, last_active_at=time.time())
    return str(auth_path), plan_type, auth_data


def _verify_and_upload_cpa(
    email: str,
    mail_client_cache: dict[str, object],
    *,
    hooks: CpaBatchHooks | None = None,
    batch_index: int | None = None,
) -> dict:
    auth_path, plan_type, auth_data = _ensure_team_auth(
        email, mail_client_cache, hooks=hooks, batch_index=batch_index, allow_browser_oauth=False
    )
    token = auth_data.get("access_token")
    if not token:
        raise RuntimeError("认证文件缺少 access_token")

    if hooks:
        hooks.account_event(
            email,
            batch_index=batch_index,
            stage="quota_check",
            message="开始检查 Codex 额度",
            status="running",
            plan_type=plan_type,
            auth_file=str(auth_path),
            auth_name=Path(auth_path).name,
        )
    quota_status, quota_info = check_codex_quota(token)
    if quota_status == "ok" and isinstance(quota_info, dict):
        update_account(email, last_quota=quota_info)
    elif quota_status == "exhausted":
        update_account(
            email,
            status=STATUS_EXHAUSTED,
            last_quota=quota_result_quota_info(quota_info),
            quota_exhausted_at=time.time(),
            quota_resets_at=quota_result_resets_at(quota_info) or int(time.time() + 18000),
        )
        raise RuntimeError("Codex 额度已用完")
    else:
        raise RuntimeError(f"Codex 额度检查失败: {quota_status}")

    if hooks:
        hooks.account_event(
            email,
            batch_index=batch_index,
            stage="cpa_upload",
            message="额度可用，开始上传 CPA JSON",
            status="running",
            plan_type=plan_type,
            auth_file=str(auth_path),
            auth_name=Path(auth_path).name,
        )
    if not upload_to_cpa(auth_path):
        raise RuntimeError(f"CPA 上传失败: {Path(auth_path).name}")

    update_account(email, cpa_uploaded_at=time.time())
    return {
        "email": email,
        "plan_type": plan_type,
        "auth_file": str(auth_path),
        "auth_name": Path(auth_path).name,
        "quota": quota_info,
    }


def run_cpa_batch(
    run_id: str,
    *,
    join_mode: str = JOIN_MODE_DIRECT,
    target: int = DEFAULT_TARGET,
    batch_size: int = DEFAULT_BATCH_SIZE,
    resume: bool = False,
) -> dict:
    existing_run = get_flow_run(run_id) if resume else None
    if resume and not existing_run:
        raise ValueError(f"任务记录不存在: {run_id}")

    join_mode = (existing_run.get("join_mode") if existing_run else join_mode or JOIN_MODE_DIRECT).strip().lower()
    if join_mode not in VALID_JOIN_MODES:
        raise ValueError(f"未知入席方式: {join_mode}")

    target = max(1, int(existing_run.get("target") if existing_run else target))
    batch_size = max(1, int(existing_run.get("batch_size") if existing_run else batch_size))
    max_attempts = max(target, target * MAX_ATTEMPT_MULTIPLIER)
    if resume:
        resume_flow_run(run_id)
    else:
        create_flow_run(run_id, target=target, batch_size=batch_size, join_mode=join_mode)
    hooks = CpaBatchHooks(run_id)

    chatgpt = None
    mail_client = None
    success_count = int(existing_run.get("success_count") or 0) if existing_run else 0
    account_failures = int(existing_run.get("failed_count") or 0) if existing_run else 0
    attempts = int(existing_run.get("attempted_count") or 0) if existing_run else 0
    pending_cpa = 0
    cpa_worker = _CpaUploadWorker(hooks)

    def consume_cpa_result(*, block: bool = False, timeout: float = 1) -> bool:
        nonlocal pending_cpa, success_count
        try:
            result = cpa_worker.results.get(timeout=timeout if block else 0)
        except queue.Empty:
            return False

        pending_cpa = max(0, pending_cpa - 1)
        email = result.get("email", "")
        if result.get("ok"):
            success_count += 1
            payload = result.get("result") or {}
            hooks.run_update(success_count=success_count)
            logger.info("[CPA批量] 成功 %d/%d: %s", success_count, target, email)
            if payload:
                logger.debug("[CPA批量] CPA 文件已可用: %s", payload.get("auth_name"))
        else:
            logger.warning("[CPA批量] %s 认证失败: %s", email, result.get("error"))
        return True

    def drain_cpa_results() -> None:
        while consume_cpa_result(block=False):
            pass

    try:
        cpa_worker.start()
        mail_client = get_mail_client()
        mail_client.login()
        if join_mode == JOIN_MODE_INVITE:
            chatgpt = ChatGPTTeamAPI()
            chatgpt.start()

        while success_count < target and (attempts < max_attempts or pending_cpa > 0):
            drain_cpa_results()
            if hooks.pause_requested():
                cpa_worker.finish()
                cpa_worker.join()
                drain_cpa_results()
                hooks.pause()
                return {
                    "run_id": run_id,
                    "status": "paused",
                    "target": target,
                    "batch_size": batch_size,
                    "join_mode": join_mode,
                    "attempted": attempts,
                    "succeeded": success_count,
                }

            if success_count >= target:
                break

            if pending_cpa and (attempts >= max_attempts or success_count + pending_cpa >= target):
                consume_cpa_result(block=True)
                continue

            if attempts >= max_attempts:
                continue

            attempts += 1
            batch_index = ((attempts - 1) // batch_size) + 1
            hooks.run_update(current_batch=batch_index)
            placeholder = f"attempt-{attempts}"

            try:
                hooks.account_event(
                    placeholder,
                    batch_index=batch_index,
                    stage="create_email",
                    message="开始创建邮箱并注册账号",
                    status="running",
                )
                if join_mode == JOIN_MODE_INVITE:
                    email = _create_invited_account(chatgpt, mail_client, hooks=hooks, batch_index=batch_index)
                else:
                    email = _create_direct_account(mail_client, hooks=hooks, batch_index=batch_index)
                email = _normalized_email(email)
                hooks.remove_account(placeholder)
                update_account(
                    email,
                    run_id=run_id,
                    batch_index=batch_index,
                    flow_status="running",
                    flow_stage="team_joined",
                    flow_error_level="info",
                    flow_error_message="",
                )
                hooks.account_event(
                    email,
                    batch_index=batch_index,
                    stage="team_joined",
                    message="账号已注册并进入 Team",
                    status="running",
                )
            except AccountFlowError as exc:
                failed_email = exc.email or placeholder
                if failed_email != placeholder:
                    hooks.remove_account(placeholder)
                    update_account(
                        failed_email,
                        run_id=run_id,
                        batch_index=batch_index,
                        flow_status="failed",
                        flow_stage="register",
                        flow_error_level="error",
                        flow_error_message=str(exc),
                    )
                hooks.account_event(
                    failed_email,
                    batch_index=batch_index,
                    stage="register",
                    message=str(exc),
                    error_level="error",
                    status="failed",
                    finished_at=time.time(),
                )
                logger.warning("[CPA批量] 第 %d 个账号注册失败: %s", attempts, exc)
                account_failures += 1
                if _should_pause_for_success_rate(success_count, account_failures):
                    reason = (
                        f"成功率保护暂停: 成功 {success_count}, 失败 {account_failures}, "
                        f"已完成成功率 {_completed_success_rate(success_count, account_failures):.2f}%"
                    )
                    hooks.run_update(fatal_error=reason, pause_requested=True)
                    cpa_worker.finish()
                    cpa_worker.join()
                    drain_cpa_results()
                    hooks.pause()
                    logger.warning("[CPA批量] %s", reason)
                    return {
                        "run_id": run_id,
                        "status": "paused",
                        "target": target,
                        "batch_size": batch_size,
                        "join_mode": join_mode,
                        "attempted": attempts,
                        "succeeded": success_count,
                        "failed": account_failures,
                        "halt_reason": reason,
                    }
                continue
            except Exception as exc:
                hooks.account_event(
                    placeholder,
                    batch_index=batch_index,
                    stage="register",
                    message=str(exc),
                    error_level="error",
                    status="failed",
                    finished_at=time.time(),
                )
                logger.warning("[CPA批量] 第 %d 个账号注册失败: %s", attempts, exc)
                continue

            if hooks.pause_requested():
                cpa_worker.finish()
                cpa_worker.join()
                drain_cpa_results()
                hooks.pause()
                return {
                    "run_id": run_id,
                    "status": "paused",
                    "target": target,
                    "batch_size": batch_size,
                    "join_mode": join_mode,
                    "attempted": attempts,
                    "succeeded": success_count,
                }

            hooks.account_event(
                email,
                batch_index=batch_index,
                stage="cpa_queued",
                message="已提交 CPA JSON 检查和上传，继续处理后续账号",
                status="running",
            )
            cpa_worker.enqueue(email, batch_index=batch_index)
            pending_cpa += 1
            consume_cpa_result(block=True, timeout=0.05)

        status = "completed" if success_count >= target else "partial"
        if status == "partial":
            update_flow_run(
                run_id,
                status=status,
                finished_at=time.time(),
                fatal_error=f"尝试 {attempts} 个账号后只得到 {success_count} 个可用 CPA JSON",
            )
        else:
            update_flow_run(run_id, status=status, finished_at=time.time(), fatal_error="")

        return {
            "run_id": run_id,
            "status": status,
            "target": target,
            "batch_size": batch_size,
            "join_mode": join_mode,
            "attempted": attempts,
            "succeeded": success_count,
        }
    except Exception as exc:
        update_flow_run(run_id, status="failed", finished_at=time.time(), fatal_error=str(exc))
        logger.error("[CPA批量] 任务失败: %s", exc)
        raise
    finally:
        cpa_worker.finish()
        cpa_worker.join()
        drain_cpa_results()
        if chatgpt and chatgpt.browser:
            chatgpt.stop()
