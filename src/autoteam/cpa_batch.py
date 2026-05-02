"""Batch account registration and CPA auth preparation."""

from __future__ import annotations

import base64
import contextvars
import json
import logging
import os
import queue
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

from autoteam import outbound_proxy
from autoteam.account_lifecycle import registered_kwargs
from autoteam.accounts import (
    CPA_STATUS_FAILED,
    CPA_STATUS_PENDING,
    CPA_STATUS_SUCCESS,
    REGISTRATION_STATUS_FAILED,
    REGISTRATION_STATUS_PENDING,
    REGISTRATION_STATUS_SUCCESS,
    STATUS_ACTIVE,
    STATUS_EXHAUSTED,
    STATUS_UNAVAILABLE,
    USAGE_INVENTORY,
    add_account,
    find_account,
    load_accounts,
    update_account,
)
from autoteam.auth_archive import archive_account_auth_file
from autoteam.browser_runtime import acquire_browser_lease, browser_parallel_limit
from autoteam.chatgpt_api import ChatGPTTeamAPI
from autoteam.codex_auth import (
    check_codex_quota,
    quota_result_quota_info,
    quota_result_resets_at,
    save_auth_file,
)
from autoteam.config import get_playwright_launch_options
from autoteam.cpa_sync import upload_to_cpa
from autoteam.exceptions import OpenAiCreateAccountBlockedError, PhoneVerificationRequiredError
from autoteam.flow_runs import (
    append_flow_event,
    create_flow_run,
    delete_flow_account,
    fail_running_flow_accounts,
    get_flow_run,
    is_flow_pause_requested,
    resume_flow_run,
    update_flow_run,
)
from autoteam.invite import register_with_invite
from autoteam.mail_provider import get_account_mail_provider, get_mail_client, get_mail_client_for_account
from autoteam.manager import invite_to_team
from autoteam.sync_targets import SYNC_TARGET_SUB2API, is_sync_target_enabled
from autoteam.textio import read_text

logger = logging.getLogger(__name__)

DEFAULT_TARGET = 100
DEFAULT_BATCH_SIZE = 20
MAX_ATTEMPT_MULTIPLIER = 2
MAX_ACCOUNT_FAILURES = 3
MAX_CONSECUTIVE_REGISTER_FAILURES = 2
MIN_COMPLETED_SUCCESS_RATE = 95.0
SUCCESS_RATE_SAFETY_MARGIN = 1.0
MIN_COMPLETED_ACCOUNTS_FOR_SUCCESS_RATE_GUARD = DEFAULT_BATCH_SIZE
RATE_LIMIT_RETRY_SECONDS = max(5, int(os.getenv("CPA_BATCH_RATE_LIMIT_RETRY_SECONDS", "600") or 600))
MAX_CONSECUTIVE_CPA_RATE_LIMITS = max(0, int(os.getenv("CPA_BATCH_PAUSE_ON_CONSECUTIVE_RATE_LIMITS", "2") or 2))
JOIN_MODE_DIRECT = "direct"
JOIN_MODE_INVITE = "invite"
VALID_JOIN_MODES = {JOIN_MODE_DIRECT, JOIN_MODE_INVITE}


def _proxy_host_label(proxy_url: str | None) -> str:
    value = str(proxy_url or "").strip()
    if not value or value == "direct":
        return "direct"
    parsed = urlsplit(value)
    if parsed.hostname:
        return f"{parsed.hostname}:{parsed.port}" if parsed.port else parsed.hostname
    return value.split("@")[-1]


def _configured_proxy_pool_size() -> int:
    return max(1, len(outbound_proxy.configured_proxy_pool()))


def _rotate_and_log_current_proxy() -> str:
    proxy_url = outbound_proxy.rotate_task_proxy()
    logger.info("[CPA批量] 当前出口 IP: %s", _proxy_host_label(proxy_url))
    return proxy_url


class AccountDeactivatedError(RuntimeError):
    """Raised when OpenAI reports account_deactivated and the account should be skipped permanently."""

    def __init__(self, email: str, message: str = "account_deactivated"):
        super().__init__(message)
        self.email = _normalized_email(email)


class AccountFlowError(RuntimeError):
    """Raised after an account email is known, so monitors can record that account."""

    def __init__(self, email: str, message: str):
        super().__init__(message)
        self.email = _normalized_email(email)


class AccountPhoneVerificationSkipped(AccountFlowError):
    """Raised when OpenAI requires phone verification and the email should be skipped."""


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
        self.thread: threading.Thread | None = None
        self._started = False
        self._finished = False
        self.failures: dict[str, int] = {}
        self.consecutive_rate_limit_emails: list[str] = []

    def start(self) -> None:
        if not self._started:
            context = contextvars.copy_context()
            self.thread = threading.Thread(
                target=lambda: context.run(self._run),
                name=f"cpa-upload-{self.hooks.run_id}",
                daemon=True,
            )
            self.thread.start()
            self._started = True

    def enqueue(self, email: str, *, batch_index: int | None = None, worker_index: int | None = None) -> None:
        self.jobs.put(
            {
                "email": _normalized_email(email),
                "batch_index": batch_index,
                "worker_index": worker_index,
                "defer_count": 0,
            }
        )

    def finish(self) -> None:
        if self._started and not self._finished:
            self.jobs.put(None)
            self._finished = True

    def join(self, timeout: float | None = None) -> None:
        if self._started and self.thread is not None:
            self.thread.join(timeout=timeout)

    def flush_and_close(self, timeout: float | None = None) -> None:
        if not self._started:
            return
        if not self._finished:
            self.jobs.join()
            self.finish()
        self.join(timeout=timeout)

    def _run(self) -> None:
        account_mail_cache: dict[str, object] = {}
        with outbound_proxy.task_proxy_context():
            while True:
                job = self.jobs.get()
                try:
                    if job is None:
                        return
                    self._run_job(job, account_mail_cache)
                finally:
                    self.jobs.task_done()

    def _run_job(self, job: dict, account_mail_cache: dict[str, object]) -> None:
        email = str(job.get("email") or "")
        batch_index = job.get("batch_index")
        worker_index = job.get("worker_index")
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
                worker_index=worker_index,
                stage="cpa_auth",
                message="开始 Codex 认证、额度检查和 CPA 上传",
                status="running",
            )
            result = _verify_and_upload_cpa(
                email,
                account_mail_cache,
                hooks=self.hooks,
                batch_index=batch_index,
                worker_index=worker_index,
            )
            sub2api_result = _sync_cpa_account_to_sub2api(
                email,
                hooks=self.hooks,
                batch_index=batch_index,
                worker_index=worker_index,
            )
            account_updates = {
                "flow_status": "success",
                "flow_stage": "completed",
                "flow_error_level": "info",
                "flow_error_message": "",
                "plan_type": result["plan_type"],
            }
            if worker_index is not None:
                account_updates["worker_index"] = worker_index
            if sub2api_result:
                account_updates["sub2api_synced_at"] = time.time()
            update_account(email, **account_updates)
            self.hooks.account_event(
                email,
                batch_index=batch_index,
                worker_index=worker_index,
                stage="completed",
                message="CPA JSON 已可用" + ("，Sub2API 已同步" if sub2api_result else ""),
                status="success",
                plan_type=result["plan_type"],
                auth_file=result["auth_file"],
                auth_name=result["auth_name"],
                cpa_uploaded=True,
                sub2api_synced=bool(sub2api_result),
                finished_at=time.time(),
            )
            self.failures.pop(email, None)
            self.consecutive_rate_limit_emails = []
            self.results.put({"ok": True, "email": email, "result": result})
        except Exception as exc:
            if isinstance(exc, AccountDeactivatedError):
                update_account(
                    email,
                    status=STATUS_UNAVAILABLE,
                    sync_disabled=True,
                    flow_status="failed",
                    flow_stage="cpa_auth",
                    flow_error_level="error",
                    flow_error_message=str(exc),
                    unavailable_reason="account_deactivated",
                    unavailable_at=time.time(),
                )
                self.hooks.account_event(
                    email,
                    batch_index=batch_index,
                    worker_index=worker_index,
                    stage="cpa_auth",
                    message="检测到 account_deactivated，已标记不可用并跳过",
                    error_level="error",
                    status="failed",
                    finished_at=time.time(),
                )
            failure_count = self.failures.get(email, 0) + 1
            self.failures[email] = failure_count
            if isinstance(exc, AccountDeactivatedError):
                self.consecutive_rate_limit_emails = []
                self.results.put({"ok": False, "email": email, "error": str(exc), "failure_count": failure_count})
                return
            if failure_count < MAX_ACCOUNT_FAILURES:
                retry_delay = RATE_LIMIT_RETRY_SECONDS if _is_temporary_rate_limit_error(exc) else 0
                if retry_delay:
                    message = (
                        f"CPA 认证命中临时限流，第 {failure_count}/{MAX_ACCOUNT_FAILURES} 次，"
                        f"{retry_delay}s 后重试当前账号: {exc}"
                    )
                else:
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
                    worker_index=worker_index,
                    stage="cpa_retry",
                    message=message,
                    error_level="warn",
                    status="running",
                    failure_count=failure_count,
                )
                if retry_delay:
                    next_proxy = outbound_proxy.rotate_task_proxy()
                    logger.warning(
                        "[CPA批量] 协议认证临时限流，%ss 后切换出口重试当前账号: %s",
                        retry_delay,
                        next_proxy.split("@")[-1] if next_proxy else "direct",
                    )
                    time.sleep(retry_delay)
                self.jobs.put(job)
                return

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
                worker_index=worker_index,
                stage="cpa_auth",
                message=str(exc),
                error_level="error",
                status="failed",
                finished_at=time.time(),
                failure_count=failure_count,
            )
            if _is_temporary_rate_limit_error(exc):
                if email not in self.consecutive_rate_limit_emails:
                    self.consecutive_rate_limit_emails.append(email)
                if (
                    MAX_CONSECUTIVE_CPA_RATE_LIMITS > 0
                    and len(self.consecutive_rate_limit_emails) >= MAX_CONSECUTIVE_CPA_RATE_LIMITS
                ):
                    reason = (
                        f"连续 {len(self.consecutive_rate_limit_emails)} 个账号触发 OpenAI 协议认证限流，"
                        f"已暂停 CPA 批量任务以避免持续失败："
                        f"{', '.join(self.consecutive_rate_limit_emails)}"
                    )
                    logger.warning("[CPA批量] %s", reason)
                    self.hooks.run_update(fatal_error=reason, pause_requested=True)
            else:
                self.consecutive_rate_limit_emails = []
            self.results.put({"ok": False, "email": email, "error": str(exc), "failure_count": failure_count})


def _normalized_email(value: str | None) -> str:
    return (value or "").strip().lower()


def _archive_account_auth(email: str, auth_path: str | Path) -> str:
    if not Path(auth_path).exists():
        logger.warning("[CPA批量] 认证文件不存在，跳过归档: %s", auth_path)
        return ""
    archive_path = archive_account_auth_file(email, auth_path)
    if archive_path:
        update_account(email, cpa_archive_file=archive_path)
    return archive_path


def _archive_update(archive_path: str) -> dict[str, str]:
    return {"cpa_archive_file": archive_path} if archive_path else {}


def _is_temporary_rate_limit_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return "http 429" in text or "rate limit" in text or "临时限流" in text


def _delete_temp_mail_account(mail_client, account_id, email: str, *, reason: str = "失败") -> None:
    if account_id is None:
        return
    try:
        mail_client.delete_account(account_id)
    except Exception as exc:
        logger.warning("[直接注册] 删除%s临时邮箱异常: %s", reason, exc)


def _is_non_ip_create_account_block(exc: OpenAiCreateAccountBlockedError) -> bool:
    reason = str(getattr(exc, "reason", "") or "").strip().lower()
    if reason:
        return reason == "about_you_timeout"
    return "about-you 超时" in str(exc)


def _completed_success_rate(success_count: int, failed_count: int) -> float:
    completed = int(success_count) + int(failed_count)
    if completed <= 0:
        return 100.0
    return int(success_count) * 100 / completed


def _should_pause_for_success_rate(success_count: int, failed_count: int) -> bool:
    if success_count + failed_count < MIN_COMPLETED_ACCOUNTS_FOR_SUCCESS_RATE_GUARD:
        return False
    if success_count <= 0 or failed_count <= 0:
        return False
    return _completed_success_rate(success_count, failed_count) < (
        MIN_COMPLETED_SUCCESS_RATE + SUCCESS_RATE_SAFETY_MARGIN
    )


def _split_success_targets(total: int, workers: int) -> list[int]:
    total = max(0, int(total or 0))
    workers = min(max(1, int(workers or 1)), max(1, total or 1))
    base, extra = divmod(total, workers)
    return [base + (1 if index < extra else 0) for index in range(workers) if base + (1 if index < extra else 0) > 0]


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


def _is_oauth_rt_auth_data(auth_data: dict) -> bool:
    if not auth_data:
        return False
    if auth_data.get("credential_source") == "chatgpt_session":
        return False
    return bool(auth_data.get("refresh_token"))


def _resolve_oauth_auth_path(acc: dict) -> str:
    for key in ("rt_auth_file", "auth_file"):
        auth_path = acc.get(key) or ""
        if not auth_path or not Path(auth_path).exists():
            continue
        try:
            auth_data = _load_auth_data(auth_path)
        except Exception:
            continue
        if _is_oauth_rt_auth_data(auth_data):
            return str(auth_path)
    return ""


def _account_for_email(email: str) -> dict | None:
    return find_account(load_accounts(), _normalized_email(email))


def _record_account_runtime(
    email: str,
    *,
    run_id: str | None = None,
    batch_index: int | None = None,
    worker_index: int | None = None,
    flow_status: str = "running",
    flow_stage: str = "",
    flow_error_level: str = "info",
    flow_error_message: str = "",
    **fields,
) -> None:
    payload = {
        "run_id": run_id,
        "batch_index": batch_index,
        "worker_index": worker_index,
        "flow_status": flow_status,
        "flow_stage": flow_stage,
        "flow_error_level": flow_error_level,
        "flow_error_message": flow_error_message,
        **fields,
    }
    update_account(email, **{key: value for key, value in payload.items() if value is not None})


def _skip_email_reason(email: str) -> str | None:
    account = _account_for_email(email)
    if not account:
        return None
    status = (account.get("status") or "").strip().lower()
    if status == STATUS_UNAVAILABLE:
        return account.get("unavailable_reason") or "status=unavailable"
    if account.get("skip_registration"):
        return account.get("skip_reason") or "skip_registration"
    return None


def _create_direct_account(
    mail_client,
    hooks: CpaBatchHooks | None = None,
    batch_index: int | None = None,
    worker_index: int | None = None,
) -> str:
    from autoteam.manager import _register_direct_once

    max_ip_rotations = _configured_proxy_pool_size()
    skipped_emails: set[str] = set()
    ip_rotations = 0
    proxy_already_rotated = False

    while True:
        if proxy_already_rotated:
            logger.info("[CPA批量] 当前出口 IP: %s", _proxy_host_label(outbound_proxy.current_proxy_url()))
            proxy_already_rotated = False
        else:
            _rotate_and_log_current_proxy()
        while True:
            account_id, email = mail_client.create_temp_email()
            email = _normalized_email(email)
            skip_reason = _skip_email_reason(email)
            if not skip_reason and email not in skipped_emails:
                break
            skipped_emails.add(email)
            logger.warning("[直接注册] 跳过已标记邮箱 %s: %s", email, skip_reason or "duplicate in same allocation loop")
            if hooks:
                hooks.account_event(
                    email,
                    batch_index=batch_index,
                    worker_index=worker_index,
                    stage="email_skipped",
                    message=f"跳过已标记邮箱，改用新邮箱: {skip_reason or 'duplicate in same allocation loop'}",
                    error_level="warn",
                    status="failed",
                    finished_at=time.time(),
                )
            _delete_temp_mail_account(mail_client, account_id, email, reason="跳过")

        password = f"Tmp_{uuid.uuid4().hex[:12]}!"
        provider_name = getattr(mail_client, "provider_name", "")
        session_bundle: dict[str, object] = {}
        oauth_bundle: dict[str, object] = {}

        def capture_session_bundle(bundle: dict) -> None:
            session_bundle.clear()
            session_bundle.update(bundle or {})

        def capture_oauth_bundle(bundle: dict) -> None:
            oauth_bundle.clear()
            oauth_bundle.update(bundle or {})

        add_account(
            email,
            password,
            cloudmail_account_id=account_id if provider_name == "cloudmail" else None,
            mail_provider=provider_name,
            mail_account_id=account_id,
        )
        update_account(email, registration_status=REGISTRATION_STATUS_PENDING, cpa_status=CPA_STATUS_PENDING)
        _record_account_runtime(
            email,
            run_id=hooks.run_id if hooks else None,
            batch_index=batch_index,
            worker_index=worker_index,
            flow_status="running",
            flow_stage="email_created",
        )
        if hooks:
            hooks.account_event(
                email,
                batch_index=batch_index,
                worker_index=worker_index,
                stage="email_created",
                message="邮箱已创建并写入账号池",
                status="running",
            )

        if hooks:
            hooks.account_event(
                email,
                batch_index=batch_index,
                worker_index=worker_index,
                stage="register",
                message="开始直注注册",
                status="running",
            )
        logger.info("[直接注册] 开始注册: %s", email)

        session_bundle.clear()
        try:
            try:
                success = _register_direct_once(
                    mail_client,
                    email,
                    password,
                    mail_account_id=account_id,
                    session_bundle_callback=capture_session_bundle,
                    oauth_bundle_callback=capture_oauth_bundle,
                    require_session_bundle=True,
                    require_oauth_bundle=True,
                )
            except TypeError as exc:
                if "require_session_bundle" not in str(exc) and "oauth_bundle_callback" not in str(exc):
                    raise
                success = _register_direct_once(
                    mail_client,
                    email,
                    password,
                    mail_account_id=account_id,
                    session_bundle_callback=capture_session_bundle,
                )
        except OpenAiCreateAccountBlockedError as exc:
            if _is_non_ip_create_account_block(exc):
                skipped_emails.add(email)
                message = f"直注注册失败: {exc}"
                update_account(
                    email,
                    registration_status=REGISTRATION_STATUS_FAILED,
                    registration_error_message=message,
                    flow_status="failed",
                    flow_stage="register",
                    flow_error_level="warn",
                    flow_error_message=message,
                )
                _delete_temp_mail_account(mail_client, account_id, email, reason="about-you超时")
                logger.warning("[CPA批量] 跳过 (about-you 超时): %s", email)
                if hooks:
                    hooks.account_event(
                        email,
                        batch_index=batch_index,
                        worker_index=worker_index,
                        stage="register",
                        message=message,
                        error_level="warn",
                        status="failed",
                        finished_at=time.time(),
                    )
                raise AccountFlowError(email, message) from exc
            ip_rotations += 1
            skipped_emails.add(email)
            message = f"OpenAI 创建账号命中 IP 风控: {exc}"
            update_account(
                email,
                registration_status=REGISTRATION_STATUS_FAILED,
                registration_error_message=message,
                flow_status="failed",
                flow_stage="register",
                flow_error_level="warn",
                flow_error_message=message,
            )
            _delete_temp_mail_account(mail_client, account_id, email, reason="IP风控")
            if hooks:
                hooks.account_event(
                    email,
                    batch_index=batch_index,
                    worker_index=worker_index,
                    stage="register",
                    message=message,
                    error_level="warn",
                    status="failed",
                    finished_at=time.time(),
                )
            if ip_rotations >= max_ip_rotations:
                raise AccountFlowError(email, message) from exc
            new_proxy = outbound_proxy.rotate_task_proxy()
            proxy_already_rotated = True
            remain = max(0, max_ip_rotations - ip_rotations)
            logger.warning(
                "[CPA批量] 触发 IP 风控, 切换到 IP %s 重试当前批次 (剩 %d 次)",
                _proxy_host_label(new_proxy),
                remain,
            )
            continue
        except PhoneVerificationRequiredError as exc:
            message = "OpenAI 风控要求手机号验证, 跳过该账号"
            update_account(
                email,
                registration_status=REGISTRATION_STATUS_FAILED,
                registration_error_message=message,
                flow_status="failed",
                flow_stage="register",
                flow_error_level="warn",
                flow_error_message=message,
            )
            _delete_temp_mail_account(mail_client, account_id, email, reason="风控")
            logger.warning("[CPA批量] 跳过 (风控要求手机号): %s", email)
            if hooks:
                hooks.account_event(
                    email,
                    batch_index=batch_index,
                    worker_index=worker_index,
                    stage="register",
                    message=message,
                    error_level="warn",
                    status="failed",
                    finished_at=time.time(),
                )
            raise AccountPhoneVerificationSkipped(email, message) from exc
        except Exception as exc:
            message = f"直注注册失败: {exc}"
            update_account(email, registration_status=REGISTRATION_STATUS_FAILED, registration_error_message=message)
            _delete_temp_mail_account(mail_client, account_id, email)
            logger.warning("[直接注册] %s: %s", message, email)
            if hooks:
                hooks.account_event(
                    email,
                    batch_index=batch_index,
                    worker_index=worker_index,
                    stage="register",
                    message=message,
                    error_level="error",
                    status="failed",
                    finished_at=time.time(),
                )
            raise AccountFlowError(email, message) from exc
        break

    if not success:
        message = "直注注册未完成"
        update_account(email, registration_status=REGISTRATION_STATUS_FAILED, registration_error_message=message)
        _delete_temp_mail_account(mail_client, account_id, email)
        if hooks:
            hooks.account_event(
                email,
                batch_index=batch_index,
                worker_index=worker_index,
                stage="register",
                message=message,
                error_level="error",
                status="failed",
                finished_at=time.time(),
            )
        raise AccountFlowError(email, message)

    if not session_bundle:
        message = "未获取到 ChatGPT session CPA 凭证"
        update_account(email, registration_status=REGISTRATION_STATUS_FAILED, registration_error_message=message)
        _delete_temp_mail_account(mail_client, account_id, email)
        if hooks:
            hooks.account_event(
                email,
                batch_index=batch_index,
                worker_index=worker_index,
                stage="session_auth",
                message=message,
                error_level="error",
                status="failed",
                finished_at=time.time(),
            )
        raise AccountFlowError(email, message)

    plan_type = (session_bundle.get("plan_type") or "unknown").strip().lower()
    auth_path = save_auth_file(session_bundle, source="session")
    archive_path = _archive_account_auth(email, auth_path)
    registration_updates = {
        "session_auth_file": auth_path,
        "registration_status": REGISTRATION_STATUS_SUCCESS,
        "registration_error_message": "",
        "plan_type": plan_type,
        "session_archive_file": archive_path,
        **registered_kwargs(),
    }
    update_account(
        email,
        **registration_updates,
    )
    if hooks:
        hooks.account_event(
            email,
            batch_index=batch_index,
            worker_index=worker_index,
            stage="session_auth",
            message=f"已从 ChatGPT session 保存本地备份凭证，plan={plan_type}",
            status="running",
            plan_type=plan_type,
            auth_file=str(auth_path),
            auth_name=Path(auth_path).name,
            cpa_archive_file=archive_path,
        )

    if oauth_bundle:
        oauth_plan_type = (oauth_bundle.get("plan_type") or plan_type or "unknown").strip().lower()
        oauth_path = save_auth_file(oauth_bundle, source="oauth")
        oauth_archive_path = _archive_account_auth(email, oauth_path)
        update_account(
            email,
            auth_file=oauth_path,
            rt_auth_file=oauth_path,
            rt_obtained_at=time.time(),
            plan_type=oauth_plan_type,
            **_archive_update(oauth_archive_path),
        )
        if hooks:
            hooks.account_event(
                email,
                batch_index=batch_index,
                worker_index=worker_index,
                stage="oauth",
                message=f"已在注册浏览器内保存 Codex OAuth RT，plan={oauth_plan_type}",
                status="running",
                plan_type=oauth_plan_type,
                auth_file=str(oauth_path),
                auth_name=Path(oauth_path).name,
                cpa_archive_file=oauth_archive_path,
            )

    _record_account_runtime(
        email,
        run_id=hooks.run_id if hooks else None,
        batch_index=batch_index,
        worker_index=worker_index,
        flow_status="running",
        flow_stage="team_joined",
        status=STATUS_ACTIVE,
        last_active_at=time.time(),
    )
    return email


def _create_direct_accounts_parallel(
    total: int,
    *,
    parallel_workers: int,
    hooks: CpaBatchHooks,
    batch_index: int | None = None,
    on_success=None,
) -> dict:
    total = max(0, int(total or 0))
    targets = _split_success_targets(total, parallel_workers)
    if not targets:
        return {"attempted": 0, "succeeded": 0, "failed": 0, "emails": [], "worker_reports": [], "parallel_workers": 0}

    results: queue.Queue[dict] = queue.Queue()

    def worker(worker_index: int, worker_target: int) -> None:
        attempted = 0
        succeeded = 0
        failed = 0
        emails: list[dict[str, object]] = []
        try:
            with outbound_proxy.task_proxy_context():
                mail_client = get_mail_client()
                mail_client.login()
                max_attempts = max(worker_target, worker_target * MAX_ATTEMPT_MULTIPLIER)
                while succeeded < worker_target and attempted < max_attempts:
                    if hooks.pause_requested():
                        break
                    attempted += 1
                    logger.info(
                        "[CPA批量] 直注 worker %d 开始第 %d 个账号，目标成功 %d",
                        worker_index,
                        attempted,
                        worker_target,
                    )
                    try:
                        email = _create_direct_account(
                            mail_client,
                            hooks=hooks,
                            batch_index=batch_index,
                            worker_index=worker_index,
                        )
                    except AccountPhoneVerificationSkipped as exc:
                        failed += 1
                        logger.warning("[CPA批量] 跳过 (风控要求手机号): %s", exc.email)
                        continue
                    except AccountFlowError as exc:
                        failed += 1
                        logger.warning("[CPA批量] 直注 worker %d 注册失败: %s", worker_index, exc)
                        continue
                    except Exception as exc:
                        failed += 1
                        logger.warning("[CPA批量] 直注 worker %d 异常: %s", worker_index, exc)
                        continue
                    email = _normalized_email(email)
                    if email:
                        succeeded += 1
                        item = {"email": email, "worker_index": worker_index}
                        emails.append(item)
                        if on_success:
                            on_success(item)
                    else:
                        failed += 1
        except Exception as exc:
            failed += 1
            logger.warning("[CPA批量] 直注 worker %d 初始化异常: %s", worker_index, exc)
        finally:
            results.put(
                {
                    "worker_index": worker_index,
                    "target": worker_target,
                    "attempted": attempted,
                    "succeeded": succeeded,
                    "failed": failed,
                    "emails": emails,
                }
            )

    threads = []
    for index, target in enumerate(targets):
        context = contextvars.copy_context()
        threads.append(
            threading.Thread(
                target=lambda ctx=context, worker_index=index + 1, worker_target=target: ctx.run(
                    worker, worker_index, worker_target
                ),
                daemon=True,
            )
        )
    with browser_parallel_limit(len(targets)):
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

    worker_reports = []
    emails = []
    while not results.empty():
        report = results.get()
        emails.extend(report.pop("emails", []))
        worker_reports.append(report)
    worker_reports.sort(key=lambda item: item["worker_index"])
    emails.sort(key=lambda item: (int(item.get("worker_index") or 0), str(item.get("email") or "")))
    return {
        "attempted": sum(int(item.get("attempted") or 0) for item in worker_reports),
        "succeeded": sum(int(item.get("succeeded") or 0) for item in worker_reports),
        "failed": sum(int(item.get("failed") or 0) for item in worker_reports),
        "emails": emails,
        "worker_reports": worker_reports,
        "parallel_workers": len(targets),
    }


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
    worker_index: int | None = None,
) -> tuple[str, str, dict]:
    acc = _account_for_email(email)
    if not acc:
        raise RuntimeError("本地账号记录不存在")

    auth_path = _resolve_oauth_auth_path(acc)
    plan_type = _auth_plan_from_path(auth_path) if auth_path and Path(auth_path).exists() else ""
    auth_data = _load_auth_data(auth_path) if auth_path and Path(auth_path).exists() else {}

    if not _is_oauth_rt_auth_data(auth_data):
        account_mail = _ensure_mail_client_for_account(acc, mail_client_cache)
        if hooks:
            hooks.account_event(
                email,
                batch_index=batch_index,
                worker_index=worker_index,
                stage="oauth",
                message="开始协议认证获取 Codex RT",
                status="running",
            )
        from autoteam.account_oauth import run_account_oauth_login

        oauth_result = run_account_oauth_login(
            email,
            account=acc,
            mail_client=account_mail,
            check_quota_snapshot=False,
        )
        plan_type = (oauth_result.get("plan_type") or oauth_result.get("plan") or "unknown").strip().lower()
        auth_path = str(oauth_result.get("rt_auth_file") or oauth_result.get("auth_file") or "")
        archive_path = str(oauth_result.get("cpa_archive_file") or "")
        auth_data = _load_auth_data(auth_path)
        if hooks:
            hooks.account_event(
                email,
                batch_index=batch_index,
                worker_index=worker_index,
                stage="oauth",
                message=f"协议认证已获取 Codex RT，plan={plan_type}",
                status="running",
                plan_type=plan_type,
                auth_file=str(auth_path),
                auth_name=Path(auth_path).name,
                cpa_archive_file=archive_path,
            )
    elif hooks:
        hooks.account_event(
            email,
            batch_index=batch_index,
            worker_index=worker_index,
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
    worker_index: int | None = None,
) -> dict:
    auth_path, plan_type, auth_data = _ensure_team_auth(
        email,
        mail_client_cache,
        hooks=hooks,
        batch_index=batch_index,
        worker_index=worker_index,
    )
    token = auth_data.get("access_token")
    if not token:
        update_account(email, cpa_status=CPA_STATUS_FAILED, cpa_error_message="认证文件缺少 access_token")
        raise RuntimeError("认证文件缺少 access_token")

    if hooks:
        hooks.account_event(
            email,
            batch_index=batch_index,
            worker_index=worker_index,
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
        update_account(email, cpa_status=CPA_STATUS_FAILED, cpa_error_message="Codex 额度已用完")
        update_account(
            email,
            status=STATUS_EXHAUSTED,
            last_quota=quota_result_quota_info(quota_info),
            quota_exhausted_at=time.time(),
            quota_resets_at=quota_result_resets_at(quota_info) or int(time.time() + 18000),
        )
        raise RuntimeError("Codex 额度已用完")
    elif quota_status == "account_deactivated":
        update_account(email, cpa_status=CPA_STATUS_FAILED, cpa_error_message="account_deactivated")
        update_account(
            email,
            status=STATUS_UNAVAILABLE,
            sync_disabled=True,
            unavailable_reason="account_deactivated",
            unavailable_at=time.time(),
        )
        raise AccountDeactivatedError(email, "account_deactivated")
    else:
        update_account(email, cpa_status=CPA_STATUS_FAILED, cpa_error_message=f"Codex 额度检查失败: {quota_status}")
        raise RuntimeError(f"Codex 额度检查失败: {quota_status}")

    if hooks:
        hooks.account_event(
            email,
            batch_index=batch_index,
            worker_index=worker_index,
            stage="cpa_upload",
            message="额度可用，开始上传 CPA JSON",
            status="running",
            plan_type=plan_type,
            auth_file=str(auth_path),
            auth_name=Path(auth_path).name,
        )
    if not upload_to_cpa(auth_path):
        update_account(email, cpa_status=CPA_STATUS_FAILED, cpa_error_message=f"CPA 上传失败: {Path(auth_path).name}")
        raise RuntimeError(f"CPA 上传失败: {Path(auth_path).name}")

    archive_path = _archive_account_auth(email, auth_path)
    now = time.time()
    update_account(
        email,
        cpa_status=CPA_STATUS_SUCCESS,
        cpa_error_message="",
        usage_status=USAGE_INVENTORY,
        cpa_uploaded_at=now,
        qualified_at=now,
        cloud_stocked_at=now,
        **_archive_update(archive_path),
    )
    return {
        "email": email,
        "plan_type": plan_type,
        "auth_file": str(auth_path),
        "auth_name": Path(auth_path).name,
        "cpa_archive_file": archive_path,
        "quota": quota_info,
    }


def _sync_cpa_account_to_sub2api(
    email: str,
    *,
    hooks: CpaBatchHooks | None = None,
    batch_index: int | None = None,
    worker_index: int | None = None,
) -> dict | None:
    if not is_sync_target_enabled(SYNC_TARGET_SUB2API):
        return None

    try:
        from autoteam.sub2api_sync import sync_account_to_sub2api

        result = sync_account_to_sub2api(email)
    except Exception as exc:
        message = f"Sub2API 同步失败: {exc}"
        logger.warning("[CPA批量] %s: %s", email, message)
        if hooks:
            hooks.account_event(
                email,
                batch_index=batch_index,
                worker_index=worker_index,
                stage="sub2api_sync",
                message=message,
                error_level="warn",
                status="running",
            )
        return None

    if hooks:
        warnings = result.get("warnings") or []
        message = (
            "Sub2API 已同步" if not warnings else f"Sub2API 已同步，警告: {'; '.join(str(item) for item in warnings)}"
        )
        hooks.account_event(
            email,
            batch_index=batch_index,
            worker_index=worker_index,
            stage="sub2api_sync",
            message=message,
            error_level="warn" if warnings else "info",
            status="running",
            sub2api_synced=True,
        )
    return result


def run_cpa_batch(
    run_id: str,
    *,
    join_mode: str = JOIN_MODE_DIRECT,
    target: int = DEFAULT_TARGET,
    batch_size: int = DEFAULT_BATCH_SIZE,
    parallel_workers: int = 1,
    continue_on_error: bool = False,
    resume: bool = False,
) -> dict:
    existing_run = get_flow_run(run_id) if resume else None
    if resume and not existing_run:
        raise ValueError(f"任务记录不存在: {run_id}")
    if resume:
        fail_running_flow_accounts(run_id)
        existing_run = get_flow_run(run_id)

    join_mode = (existing_run.get("join_mode") if existing_run else join_mode or JOIN_MODE_DIRECT).strip().lower()
    if join_mode not in VALID_JOIN_MODES:
        raise ValueError(f"未知入席方式: {join_mode}")

    target = max(1, int(existing_run.get("target") if existing_run else target))
    batch_size = max(1, int(existing_run.get("batch_size") if existing_run else batch_size))
    saved_parallel_workers = parallel_workers
    if existing_run:
        saved_parallel_workers = existing_run.get("parallel_workers")
        if saved_parallel_workers is None:
            saved_parallel_workers = parallel_workers
    parallel_workers = min(3, max(1, int(saved_parallel_workers or 1)))
    if join_mode == JOIN_MODE_INVITE:
        parallel_workers = 1
    if existing_run and "continue_on_error" in existing_run:
        continue_on_error = bool(existing_run.get("continue_on_error"))
    max_attempts = max(target, target * MAX_ATTEMPT_MULTIPLIER)
    if resume:
        resume_flow_run(run_id)
        update_flow_run(run_id, continue_on_error=bool(continue_on_error))
    else:
        create_flow_run(
            run_id, target=target, batch_size=batch_size, join_mode=join_mode, parallel_workers=parallel_workers
        )
        update_flow_run(run_id, continue_on_error=bool(continue_on_error))
    hooks = CpaBatchHooks(run_id)

    chatgpt = None
    mail_client = None
    success_count = int(existing_run.get("success_count") or 0) if existing_run else 0
    account_failures = int(existing_run.get("failed_count") or 0) if existing_run else 0
    attempts = int(existing_run.get("attempted_count") or 0) if existing_run else 0
    pending_cpa = 0
    pending_lock = threading.Lock()
    consecutive_register_failures = 0
    cpa_worker = _CpaUploadWorker(hooks)

    def get_pending_cpa() -> int:
        with pending_lock:
            return pending_cpa

    def add_pending_cpa() -> None:
        nonlocal pending_cpa
        with pending_lock:
            pending_cpa += 1

    def mark_cpa_result_finished() -> None:
        nonlocal pending_cpa
        with pending_lock:
            pending_cpa = max(0, pending_cpa - 1)

    def enqueue_cpa_account(email: str, *, batch_index: int | None = None, worker_index: int | None = None) -> None:
        update_account(
            email,
            run_id=run_id,
            batch_index=batch_index,
            worker_index=worker_index,
            flow_status="running",
            flow_stage="team_joined",
            flow_error_level="info",
            flow_error_message="",
        )
        hooks.account_event(
            email,
            batch_index=batch_index,
            worker_index=worker_index,
            stage="team_joined",
            message="账号已注册并进入 Team",
            status="running",
        )
        hooks.account_event(
            email,
            batch_index=batch_index,
            worker_index=worker_index,
            stage="cpa_queued",
            message="已提交协议认证、CPA JSON 检查和上传，继续处理后续账号",
            status="running",
        )
        cpa_worker.enqueue(email, batch_index=batch_index, worker_index=worker_index)
        add_pending_cpa()

    def consume_cpa_result(*, block: bool = False, timeout: float = 1) -> bool:
        nonlocal success_count
        try:
            result = cpa_worker.results.get(timeout=timeout if block else 0)
        except queue.Empty:
            return False

        mark_cpa_result_finished()
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

    def wait_for_current_cpa_result() -> None:
        while get_pending_cpa() > 0:
            consume_cpa_result(block=True)

    def registered_success_count() -> int:
        return success_count + get_pending_cpa()

    def should_pause_for_register_success_rate() -> bool:
        return _should_pause_for_success_rate(registered_success_count(), account_failures)

    def register_success_rate_message() -> str:
        return (
            f"成功率保护暂停: 成功 {registered_success_count()}, 失败 {account_failures}, "
            f"已完成成功率 {_completed_success_rate(registered_success_count(), account_failures):.2f}%"
        )

    def close_cpa_worker() -> None:
        cpa_worker.flush_and_close()
        drain_cpa_results()

    def pause_for_consecutive_register_failures(last_error: str) -> dict:
        reason = f"连续 {consecutive_register_failures} 个账号注册失败，已暂停: {last_error}"
        hooks.run_update(fatal_error=reason, pause_requested=True)
        close_cpa_worker()
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

    try:
        cpa_worker.start()
        if join_mode == JOIN_MODE_INVITE:
            mail_client = get_mail_client()
            mail_client.login()
            chatgpt = ChatGPTTeamAPI()
            chatgpt.start()
        elif parallel_workers <= 1:
            mail_client = get_mail_client()
            mail_client.login()

        while success_count < target and (attempts < max_attempts or get_pending_cpa() > 0):
            drain_cpa_results()
            if hooks.pause_requested():
                close_cpa_worker()
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

            current_pending_cpa = get_pending_cpa()
            if current_pending_cpa and (attempts >= max_attempts or success_count + current_pending_cpa >= target):
                consume_cpa_result(block=True)
                continue

            if attempts >= max_attempts:
                continue

            if join_mode == JOIN_MODE_DIRECT and parallel_workers > 1:
                current_pending_cpa = get_pending_cpa()
                remaining_success = target - success_count - current_pending_cpa
                remaining_attempts = max_attempts - attempts
                create_target = min(remaining_success, batch_size, remaining_attempts)
                if create_target <= 0:
                    continue
                batch_index = (attempts // batch_size) + 1
                hooks.run_update(current_batch=batch_index)
                created_accounts: list[dict[str, object]] = []

                def enqueue_parallel_success(item: dict[str, object]) -> None:
                    email = _normalized_email(item.get("email"))
                    if not email:
                        return
                    worker_index = item.get("worker_index")
                    created_accounts.append({"email": email, "worker_index": worker_index})
                    enqueue_cpa_account(email, batch_index=batch_index, worker_index=worker_index)

                create_result = _create_direct_accounts_parallel(
                    create_target,
                    parallel_workers=parallel_workers,
                    hooks=hooks,
                    batch_index=batch_index,
                    on_success=enqueue_parallel_success,
                )
                attempts += int(create_result.get("attempted") or 0)
                account_failures += int(create_result.get("failed") or 0)
                hooks.run_update(attempted_count=attempts)
                if not created_accounts:
                    consecutive_register_failures += 1
                    if not continue_on_error and consecutive_register_failures >= MAX_CONSECUTIVE_REGISTER_FAILURES:
                        return pause_for_consecutive_register_failures("并行直注注册未产生成功账号")
                    if not continue_on_error and should_pause_for_register_success_rate():
                        reason = register_success_rate_message()
                        hooks.run_update(fatal_error=reason, pause_requested=True)
                        close_cpa_worker()
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
                consecutive_register_failures = 0
                drain_cpa_results()
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
                consecutive_register_failures = 0
            except AccountPhoneVerificationSkipped as exc:
                failed_email = exc.email or placeholder
                if failed_email != placeholder:
                    hooks.remove_account(placeholder)
                logger.warning("[CPA批量] 跳过 (风控要求手机号): %s", failed_email)
                account_failures += 1
                hooks.run_update(attempted_count=attempts)
                continue
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
                consecutive_register_failures += 1
                if not continue_on_error and consecutive_register_failures >= MAX_CONSECUTIVE_REGISTER_FAILURES:
                    return pause_for_consecutive_register_failures(str(exc))
                if not continue_on_error and should_pause_for_register_success_rate():
                    reason = register_success_rate_message()
                    hooks.run_update(fatal_error=reason, pause_requested=True)
                    close_cpa_worker()
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
                account_failures += 1
                consecutive_register_failures += 1
                if not continue_on_error and consecutive_register_failures >= MAX_CONSECUTIVE_REGISTER_FAILURES:
                    return pause_for_consecutive_register_failures(str(exc))
                continue

            enqueue_cpa_account(email, batch_index=batch_index)

            if hooks.pause_requested():
                close_cpa_worker()
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

            drain_cpa_results()

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
        close_cpa_worker()
        try:
            fail_running_flow_accounts(run_id, "任务结束时清理遗留运行记录")
        except Exception as exc:
            logger.warning("[CPA批量] 清理遗留运行账号记录失败: %s", exc)
        if chatgpt and chatgpt.browser:
            chatgpt.stop()
