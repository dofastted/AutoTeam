#!/usr/bin/env python3
import autoteam.display  # noqa: F401 — 自动设置虚拟显示器

"""
账号轮转管理器

功能:
- 检查所有活跃账号的 Codex 额度
- 额度用完的账号移出 Team，放入 standby
- 从 standby 中选额度恢复的旧账号重新邀请
- 无可用旧账号时才创建新账号
- 自动完成注册并保存 Codex 认证文件

用法:
    python manager.py check     # 检查所有活跃账号额度
    python manager.py rotate    # 执行一次轮转（检查 + 替换）
    python manager.py add       # 手动添加一个新账号
    python manager.py status    # 查看所有账号状态
"""

import getpass
import json
import logging
import os
import queue
import sys
import threading
import time
from pathlib import Path

from autoteam import outbound_proxy
from autoteam import protocol_oauth
from autoteam.about_you import fill_about_you_page
from autoteam.account_ops import delete_managed_account, fetch_team_state
from autoteam.accounts import (
    STATUS_ACTIVE,
    STATUS_EXHAUSTED,
    STATUS_PENDING,
    STATUS_SOLD,
    STATUS_STANDBY,
    STATUS_UNAVAILABLE,
    add_account,
    find_account,
    get_standby_accounts,
    load_accounts,
    save_accounts,
    update_account,
)
from autoteam.admin_state import (
    get_admin_email,
    get_admin_state_summary,
    get_chatgpt_account_id,
)
from autoteam.api import _run_with_chatgpt_session
from autoteam.auth_archive import archive_account_auth_file
from autoteam.browser_runtime import acquire_browser_lease, browser_parallel_limit
from autoteam.chatgpt_api import ChatGPTTeamAPI, complete_workspace_selection
from autoteam.codex_auth import (
    MainCodexSyncFlow,
    _click_primary_auth_button,
    _is_google_redirect,
    build_chatgpt_session_auth_bundle,
    check_codex_quota,
    get_existing_session_auth_file,
    get_quota_exhausted_info,
    get_saved_main_auth_file,
    login_codex_via_browser,
    quota_result_quota_info,
    quota_result_resets_at,
    refresh_access_token,
    save_auth_file,
    select_oauth_rt_auth_file,
)
from autoteam.config import get_playwright_launch_options
from autoteam.cpa_sync import sync_from_cpa
from autoteam.exceptions import OpenAiCreateAccountBlockedError, PhoneVerificationRequiredError, is_openai_add_phone_url
from autoteam.mail_provider import (
    get_account_mail_account_id,
    get_account_mail_provider,
    get_mail_client_for_account,
    get_mail_domain,
    get_mail_provider_name,
)
from autoteam.mail_provider import (
    get_mail_client as CloudMailClient,
)
from autoteam.sync_targets import (
    sync_main_codex_to_configured_targets as sync_main_codex_to_cpa,
)
from autoteam.sync_targets import (
    sync_to_configured_targets as sync_to_cpa,
)
from autoteam.textio import read_text, write_text

logger = logging.getLogger(__name__)

MAIL_TIMEOUT = int(os.environ.get("MAIL_TIMEOUT", "180"))
REUSE_RESET_GRACE_SECONDS = int(os.environ.get("REUSE_RESET_GRACE_SECONDS", "300"))


def _normalized_email(value: str | None) -> str:
    return (value or "").strip().lower()


def _archive_saved_auth(email: str, auth_file: str) -> str:
    if not Path(auth_file).exists():
        logger.warning("[Codex] 认证文件不存在，跳过归档: %s", auth_file)
        return ""
    archive_path = archive_account_auth_file(email, auth_file)
    if archive_path:
        update_account(email, cpa_archive_file=archive_path)
    return archive_path


def _archive_update(archive_path: str) -> dict[str, str]:
    return {"cpa_archive_file": archive_path} if archive_path else {}


def _raise_if_add_phone_url(current_url: object, email: str) -> None:
    if is_openai_add_phone_url(current_url):
        raise PhoneVerificationRequiredError(f"OpenAI 风控要求手机号: {email}", email=email)


def _account_oauth_rt_auth_file(acc: dict) -> str:
    auth_file = select_oauth_rt_auth_file(acc)
    return auth_file if auth_file and Path(auth_file).exists() else ""


def _resolve_parallel_workers(value=None) -> int:
    if value is None:
        value = 1
    return min(3, max(1, int(value or 1)))


def _split_success_targets(total: int, workers: int) -> list[int]:
    total = max(0, int(total or 0))
    workers = min(max(1, int(workers or 1)), max(1, total or 1))
    base, extra = divmod(total, workers)
    return [base + (1 if index < extra else 0) for index in range(workers) if base + (1 if index < extra else 0) > 0]


def _is_main_account_email(email: str | None) -> bool:
    return bool(_normalized_email(email)) and _normalized_email(email) == _normalized_email(get_admin_email())


_GOOGLE_AUTO_REUSE_DOMAINS = {"gmail.com", "googlemail.com"}


def _get_account_login_provider(acc: dict | None) -> str:
    acc = acc or {}
    for key in ("login_provider", "auth_provider", "oauth_provider"):
        provider = (acc.get(key) or "").strip().lower()
        if provider:
            return provider

    email = _normalized_email(acc.get("email"))
    if "@" in email and email.rsplit("@", 1)[-1] in _GOOGLE_AUTO_REUSE_DOMAINS:
        return "google"

    return ""


def _auto_reuse_skip_reason(acc: dict | None) -> str | None:
    provider = _get_account_login_provider(acc)
    if provider == "google":
        return "Google 登录账号暂不支持自动复用"
    return None


def _get_account_mail_client(acc: dict | None):
    acc = acc or {}
    has_explicit_mail_binding = bool(acc.get("mail_provider")) or acc.get("mail_account_id") is not None
    has_legacy_cloudmail_binding = acc.get("cloudmail_account_id") is not None
    if has_explicit_mail_binding or has_legacy_cloudmail_binding:
        return get_mail_client_for_account(acc)
    return CloudMailClient()


def sync_account_states(chatgpt_api=None):
    """根据 Team 实际成员列表同步本地账号状态"""
    account_id = get_chatgpt_account_id()
    if not account_id:
        return
    accounts = load_accounts()
    team_emails = set()

    # 获取 Team 实际成员
    need_stop = False
    if not chatgpt_api or not chatgpt_api.browser:
        try:
            chatgpt_api = ChatGPTTeamAPI()
            chatgpt_api.start()
            need_stop = True
        except Exception:
            # Playwright 不可用（event loop 冲突等），跳过同步
            return

    try:
        path = f"/backend-api/accounts/{account_id}/users"
        result = chatgpt_api._api_fetch("GET", path)
        if result["status"] != 200:
            return

        data = json.loads(result["body"])
        members = data.get("items", data.get("users", data.get("members", [])))
        team_emails = {m.get("email", "").lower() for m in members}
    finally:
        if need_stop:
            chatgpt_api.stop()

    # 对照更新状态
    domain_value = get_mail_domain()
    domain_suffix = domain_value.lstrip("@") if domain_value else ""
    current_mail_provider = get_mail_provider_name()

    changed = False
    local_email_set = {a["email"].lower() for a in accounts}

    for acc in accounts:
        email = acc["email"].lower()
        if acc.get("status") == STATUS_SOLD:
            continue
        in_team = email in team_emails

        if in_team and acc["status"] in (STATUS_STANDBY, STATUS_PENDING):
            acc["status"] = STATUS_ACTIVE
            changed = True
        elif not in_team and acc["status"] == STATUS_ACTIVE:
            acc["status"] = STATUS_STANDBY
            changed = True

    # Team 中有我们域名但本地无记录的成员 → 自动添加
    if domain_suffix:
        for email in team_emails:
            if _is_main_account_email(email):
                continue
            if domain_suffix in email and email not in local_email_set:
                accounts.append(
                    {
                        "email": email,
                        "password": "",
                        "mail_provider": current_mail_provider,
                        "mail_account_id": None,
                        "cloudmail_account_id": None,
                        "status": STATUS_ACTIVE,
                        "auth_file": None,
                        "quota_exhausted_at": None,
                        "quota_resets_at": None,
                        "created_at": time.time(),
                        "last_active_at": None,
                    }
                )
                changed = True
                logger.info("[同步] 发现 Team 中新成员: %s（已添加到本地）", email)

    # auths 目录中有认证文件但本地无记录的 → 自动添加为 standby
    from autoteam.codex_auth import AUTH_DIR

    local_email_set = {a["email"].lower() for a in accounts}  # 刷新一下
    if AUTH_DIR.exists():
        for auth_file in AUTH_DIR.glob("codex-*.json"):
            try:
                auth_data = json.loads(read_text(auth_file))
                email = auth_data.get("email", "").lower()
                if not email or email in local_email_set or _is_main_account_email(email):
                    continue
                # 判断是否在 Team 中
                in_team = email in team_emails
                status = STATUS_ACTIVE if in_team else STATUS_STANDBY
                accounts.append(
                    {
                        "email": email,
                        "password": "",
                        "mail_provider": current_mail_provider,
                        "mail_account_id": None,
                        "cloudmail_account_id": None,
                        "status": status,
                        "auth_file": str(auth_file),
                        "quota_exhausted_at": None,
                        "quota_resets_at": None,
                        "created_at": time.time(),
                        "last_active_at": None,
                    }
                )
                local_email_set.add(email)
                changed = True
                logger.info("[同步] 从 auths 目录恢复账号: %s（%s）", email, status)
            except Exception:
                continue

    if changed:
        save_accounts(accounts)


def _print_status_table(accounts, quota_cache=None):
    """打印账号状态表格（使用 rich）"""
    from rich.console import Console
    from rich.table import Table
    from rich.text import Text

    if quota_cache is None:
        quota_cache = {}

    console = Console(width=120)

    table = Table(
        title="AutoTeam 账号状态",
        show_header=True,
        header_style="bold cyan",
        border_style="dim",
        title_style="bold white",
        padding=(0, 1),
        expand=True,
    )

    table.add_column("#", style="dim", width=3, justify="right")
    table.add_column("邮箱", style="white", no_wrap=True)
    table.add_column("状态", justify="center", width=10)
    table.add_column("5h 剩余", justify="right", width=8)
    table.add_column("周 剩余", justify="right", width=8)
    table.add_column("5h 重置", justify="center", width=12)
    table.add_column("周 重置", justify="center", width=12)

    STATUS_STYLE = {
        STATUS_ACTIVE: ("bold green", "● active"),
        STATUS_EXHAUSTED: ("bold red", "✗ used up"),
        STATUS_STANDBY: ("yellow", "○ standby"),
        STATUS_PENDING: ("dim", "… pending"),
        STATUS_UNAVAILABLE: ("red", "! unavailable"),
        STATUS_SOLD: ("cyan", "◆ sold"),
    }

    for idx, acc in enumerate(accounts, 1):
        email = acc["email"]
        qi = quota_cache.get(email) or acc.get("last_quota")
        status = acc["status"]

        style, status_label = STATUS_STYLE.get(status, ("dim", status))
        status_text = Text(status_label, style=style)

        if qi:
            p_val = 100 - qi.get("primary_pct", 0)
            w_val = 100 - qi.get("weekly_pct", 0)
            p_pct = Text(f"{p_val}%", style="green" if p_val > 30 else "yellow" if p_val > 0 else "red")
            w_pct = Text(f"{w_val}%", style="green" if w_val > 30 else "yellow" if w_val > 0 else "red")
            p_reset = (
                time.strftime("%m-%d %H:%M", time.localtime(qi["primary_resets_at"]))
                if qi.get("primary_resets_at")
                else "-"
            )
            w_reset = (
                time.strftime("%m-%d %H:%M", time.localtime(qi["weekly_resets_at"]))
                if qi.get("weekly_resets_at")
                else "-"
            )
        else:
            p_pct = Text("-", style="dim")
            w_pct = Text("-", style="dim")
            p_reset = "-"
            w_reset = "-"

        table.add_row(
            str(idx),
            email,
            status_text,
            p_pct,
            w_pct,
            Text(p_reset, style="dim"),
            Text(w_reset, style="dim"),
        )

    console.print()
    console.print(table)

    # 统计摘要
    active = sum(1 for a in accounts if a["status"] == STATUS_ACTIVE)
    standby = sum(1 for a in accounts if a["status"] == STATUS_STANDBY)
    exhausted = sum(1 for a in accounts if a["status"] == STATUS_EXHAUSTED)
    sold = sum(1 for a in accounts if a["status"] == STATUS_SOLD)
    unavailable = sum(1 for a in accounts if a["status"] == STATUS_UNAVAILABLE)
    console.print(
        f"  [green]● 活跃 {active}[/]  "
        f"[yellow]○ 待命 {standby}[/]  "
        f"[red]✗ 用完 {exhausted}[/]  "
        f"[red]! 不可用 {unavailable}[/]  "
        f"[cyan]◆ 已售 {sold}[/]  "
        f"[dim]总计 {len(accounts)}[/]",
    )


def cmd_status():
    """显示所有账号状态（先同步 Team 实际状态，active 账号实时查询额度）"""
    logger.info("[状态] 同步 Team 实际状态...")
    sync_account_states()

    accounts = load_accounts()
    if not accounts:
        logger.info("[状态] 暂无账号")
        return

    # active 账号实时查询额度
    quota_cache = {}
    active_count = sum(
        1
        for a in accounts
        if a["status"] == STATUS_ACTIVE
        and not a.get("sync_disabled")
        and _account_oauth_rt_auth_file(a)
    )
    if active_count:
        logger.info("[状态] 查询 %d 个 active 账号额度...", active_count)
    for acc in accounts:
        if (
            acc["status"] == STATUS_ACTIVE
            and not acc.get("sync_disabled")
            and _account_oauth_rt_auth_file(acc)
        ):
            auth_data = json.loads(read_text(Path(_account_oauth_rt_auth_file(acc))))
            access_token = auth_data.get("access_token")
            if access_token:
                status, info = check_codex_quota(access_token)
                if status == "ok" and isinstance(info, dict):
                    quota_cache[acc["email"]] = info
                elif status == "exhausted":
                    quota_info = quota_result_quota_info(info)
                    if quota_info:
                        quota_cache[acc["email"]] = quota_info

    _print_status_table(accounts, quota_cache)


def _check_and_refresh(acc):
    """检查单个账号额度，401 时自动刷新 token。返回 (status_str, info)
    info: exhausted 时为 exhausted_info，ok 时为 quota_info dict
    """
    email = acc["email"]
    auth_file = _account_oauth_rt_auth_file(acc)

    if not auth_file:
        return "no_auth", None

    auth_data = json.loads(read_text(Path(auth_file)))
    access_token = auth_data.get("access_token")
    rt = auth_data.get("refresh_token")

    if not access_token:
        return "no_auth", None

    status, info = check_codex_quota(access_token)

    # token 过期，尝试刷新
    if status == "auth_error" and rt:
        logger.info("[%s] token 过期，尝试刷新...", email)
        new_tokens = refresh_access_token(rt)
        if new_tokens:
            auth_data["access_token"] = new_tokens["access_token"]
            auth_data["refresh_token"] = new_tokens.get("refresh_token", rt)
            auth_data["last_refresh"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            write_text(Path(auth_file), json.dumps(auth_data, indent=2))
            logger.info("[%s] token 已刷新，重新检查额度...", email)
            status, info = check_codex_quota(new_tokens["access_token"])
        else:
            logger.error("[%s] token 刷新失败", email)

    return status, info


def cmd_check():
    """只检查 active 账号的额度，无认证文件或 auth_error 的自动重新登录 Codex"""
    from autoteam.config import AUTO_CHECK_THRESHOLD

    # API 运行时配置优先（前端可修改）
    try:
        from autoteam.api import _auto_check_config

        threshold = _auto_check_config.get("threshold", AUTO_CHECK_THRESHOLD)
    except ImportError:
        threshold = AUTO_CHECK_THRESHOLD

    accounts = load_accounts()

    pending_accounts = [a for a in accounts if a["status"] == STATUS_PENDING]
    if pending_accounts:
        logger.info("[检查] 对账 %d 个 pending 账号...", len(pending_accounts))
        chatgpt = None
        mail_client = None
        deleted_pending = 0
        try:
            chatgpt = ChatGPTTeamAPI()
            chatgpt.start()
            members, invites = fetch_team_state(chatgpt)
            team_emails = {(m.get("email", "") or "").lower() for m in members}
            invite_emails = {(inv.get("email_address") or inv.get("email") or "").lower() for inv in invites}

            for acc in pending_accounts:
                email = acc["email"]
                email_l = email.lower()

                if email_l in team_emails:
                    logger.info("[检查] pending 账号已在 Team 中，转为 active: %s", email)
                    update_account(email, status=STATUS_ACTIVE)
                    continue

                if email_l in invite_emails:
                    logger.info("[检查] pending 账号仍存在远端邀请，保留: %s", email)
                    continue

                logger.warning("[检查] pending 账号为失败孤儿，删除: %s", email)
                desired_provider = get_account_mail_provider(acc)
                if mail_client is None or getattr(mail_client, "provider_name", "") != desired_provider:
                    mail_client = _get_account_mail_client(acc)
                    mail_client.login()
                delete_managed_account(
                    email,
                    remove_remote=True,
                    remove_cloudmail=True,
                    sync_cpa_after=False,
                    chatgpt_api=chatgpt,
                    mail_client=mail_client,
                    remote_state=(members, invites),
                )
                deleted_pending += 1
        except Exception as exc:
            logger.warning("[检查] pending 对账失败，跳过本轮清理: %s", exc)
        finally:
            if chatgpt and chatgpt.browser:
                chatgpt.stop()

        if deleted_pending:
            logger.info("[检查] 已删除 %d 个失败 pending 账号", deleted_pending)
            sync_to_cpa()

        accounts = load_accounts()

    all_active = [
        a
        for a in accounts
        if a["status"] == STATUS_ACTIVE and not a.get("sync_disabled") and not _is_main_account_email(a.get("email"))
    ]

    # 区分：有认证文件的 vs 无认证文件的
    active_with_auth = []
    no_auth_list = []
    mail_domain = get_mail_domain()
    mail_domain_suffix = mail_domain.lstrip("@") if mail_domain else ""
    for a in all_active:
        if _account_oauth_rt_auth_file(a):
            active_with_auth.append(a)
        else:
            # 只管我们域名的账号
            if mail_domain_suffix and mail_domain_suffix in a["email"]:
                no_auth_list.append(a)

    if not active_with_auth and not no_auth_list:
        logger.info("[检查] 没有可检查的 active 账号")
        return []

    # 检查有认证文件的账号额度
    exhausted_list = []
    auth_error_list = []

    if active_with_auth:
        logger.info("[检查] 检查 %d 个 active 账号的额度...", len(active_with_auth))
        for acc in active_with_auth:
            email = acc["email"]
            status_str, info = _check_and_refresh(acc)

            if status_str == "ok":
                if isinstance(info, dict):
                    p_remain = 100 - info.get("primary_pct", 0)
                    w_remain = 100 - info.get("weekly_pct", 0)
                    p_reset = info.get("primary_resets_at", 0)
                    w_reset = info.get("weekly_resets_at", 0)
                    p_time = time.strftime("%m-%d %H:%M", time.localtime(p_reset)) if p_reset else "?"
                    w_time = time.strftime("%m-%d %H:%M", time.localtime(w_reset)) if w_reset else "?"
                    # 保存最新额度快照，供 status 离线展示
                    update_account(email, last_quota=info)
                    # 低于阈值视为用完
                    if p_remain < threshold:
                        resets_at = p_reset or (time.time() + 18000)
                        logger.warning(
                            "[%s] 5h剩余 %d%% < %d%%，标记为 exhausted (重置 %s)", email, p_remain, threshold, p_time
                        )
                        update_account(
                            email,
                            status=STATUS_EXHAUSTED,
                            quota_exhausted_at=time.time(),
                            quota_resets_at=resets_at,
                        )
                        exhausted_list.append(acc)
                    else:
                        logger.info(
                            "[%s] 额度可用 - 5h剩余: %d%% (重置 %s) | 周剩余: %d%% (重置 %s)",
                            email,
                            p_remain,
                            p_time,
                            w_remain,
                            w_time,
                        )
                else:
                    logger.info("[%s] 额度可用", email)
            elif status_str == "exhausted":
                quota_info = quota_result_quota_info(info) or {}
                resets_at = quota_result_resets_at(info) or int(time.time() + 18000)
                if quota_info:
                    update_account(email, last_quota=quota_info)
                    p_remain = max(0, 100 - quota_info.get("primary_pct", 0))
                    w_remain = max(0, 100 - quota_info.get("weekly_pct", 0))
                    window = info.get("window") if isinstance(info, dict) else ""
                    logger.warning(
                        "[%s] %s额度已用完 - 5h剩余: %d%% | 周剩余: %d%%",
                        email,
                        "周" if window == "weekly" else "5h和周" if window == "combined" else "5h",
                        p_remain,
                        w_remain,
                    )
                else:
                    logger.warning("[%s] 额度已用完", email)
                update_account(
                    email,
                    status=STATUS_EXHAUSTED,
                    quota_exhausted_at=time.time(),
                    quota_resets_at=resets_at,
                )
                exhausted_list.append(acc)
            elif status_str == "auth_error":
                # token 失效，先看历史额度（重置时间已过的不算）
                lq = acc.get("last_quota")
                if lq:
                    exhausted_info = _pending_historical_exhausted_info(lq)
                    if exhausted_info:
                        resets_at = quota_result_resets_at(exhausted_info) or int(time.time() + 18000)
                        window_label = _quota_window_label(exhausted_info.get("window"))
                        logger.warning("[%s] token 失效，但历史%s额度未恢复，直接标记 exhausted", email, window_label)
                        update_account(
                            email,
                            status=STATUS_EXHAUSTED,
                            quota_exhausted_at=time.time(),
                            quota_resets_at=resets_at,
                        )
                        exhausted_list.append(acc)
                        continue
                    p_resets = lq.get("primary_resets_at", 0)
                    if not (p_resets and time.time() >= p_resets):
                        # 重置时间未过，历史数据有效
                        p_remain = 100 - lq.get("primary_pct", 0)
                        if p_remain < threshold:
                            resets_at = p_resets or (time.time() + 18000)
                            logger.warning(
                                "[%s] token 失效，历史额度 %d%% < %d%%，直接标记 exhausted", email, p_remain, threshold
                            )
                            update_account(
                                email,
                                status=STATUS_EXHAUSTED,
                                quota_exhausted_at=time.time(),
                                quota_resets_at=resets_at,
                            )
                            exhausted_list.append(acc)
                            continue
                    else:
                        logger.info("[%s] token 失效但 5h 重置时间已过，需重新登录验证", email)
                logger.warning("[%s] 认证失败，需要重新登录 Codex", email)
                auth_error_list.append(acc)
            elif status_str == "account_deactivated":
                logger.warning("[%s] 账号已停用，标记为不可用并跳过", email)
                update_account(
                    email,
                    status=STATUS_UNAVAILABLE,
                    sync_disabled=True,
                    unavailable_reason="account_deactivated",
                    unavailable_at=time.time(),
                )

    # 无认证文件的 active 账号也需要重新登录
    if no_auth_list:
        logger.info("[检查] 发现 %d 个 active 账号无认证文件，需要登录 Codex:", len(no_auth_list))
        for a in no_auth_list:
            logger.info("[检查]   %s", a["email"])
        auth_error_list.extend(no_auth_list)

    # auth_error + 无认证文件的统一重新登录 Codex
    if auth_error_list:
        logger.info("[检查] 重新登录 %d 个 token 失效的账号...", len(auth_error_list))
        mail_clients = {}
        for acc in auth_error_list:
            email = acc["email"]
            password = acc.get("password", "")
            logger.info("[%s] 重新 Codex 登录...", email)
            provider = get_account_mail_provider(acc)
            mail_client = mail_clients.get(provider)
            if mail_client is None:
                mail_client = _get_account_mail_client(acc)
                mail_client.login()
                mail_clients[provider] = mail_client
            bundle = login_codex_via_browser(
                email,
                password,
                mail_client=mail_client,
                mail_account_id=get_account_mail_account_id(acc),
            )
            if bundle:
                auth_file = save_auth_file(bundle, source="oauth")
                archive_path = _archive_saved_auth(email, auth_file)
                update_fields = {
                    "auth_file": auth_file,
                    "rt_auth_file": auth_file,
                }
                previous_session_auth_file = get_existing_session_auth_file(acc)
                if previous_session_auth_file:
                    update_fields["session_auth_file"] = previous_session_auth_file
                update_account(email, **update_fields, **_archive_update(archive_path))
                logger.info("[%s] token 已更新", email)
                # 重新检查额度
                status_str, info = _check_and_refresh(find_account(load_accounts(), email))
                if status_str == "exhausted":
                    quota_info = quota_result_quota_info(info)
                    if quota_info:
                        update_account(email, last_quota=quota_info)
                    update_account(
                        email,
                        status=STATUS_EXHAUSTED,
                        quota_exhausted_at=time.time(),
                        quota_resets_at=quota_result_resets_at(info) or int(time.time() + 18000),
                    )
                    exhausted_list.append(acc)
                    logger.warning("[%s] 额度已用完", email)
                elif status_str == "ok" and isinstance(info, dict):
                    p_remain = 100 - info.get("primary_pct", 0)
                    update_account(email, last_quota=info)
                    if p_remain < threshold:
                        resets_at = info.get("primary_resets_at") or (time.time() + 18000)
                        logger.warning("[%s] 5h剩余 %d%% < %d%%，标记为 exhausted", email, p_remain, threshold)
                        update_account(
                            email,
                            status=STATUS_EXHAUSTED,
                            quota_exhausted_at=time.time(),
                            quota_resets_at=resets_at,
                        )
                        exhausted_list.append(acc)
                    else:
                        logger.info("[%s] 额度可用 (%d%%)", email, p_remain)
                elif status_str == "ok":
                    logger.info("[%s] 额度可用", email)
                elif status_str == "auth_error":
                    logger.warning("[%s] 重新登录后仍无法查询额度（可能未选中 Team workspace），标记为 standby", email)
                    update_account(email, status=STATUS_STANDBY)
            else:
                logger.error("[%s] Codex 登录失败，标记为 standby", email)
                update_account(email, status=STATUS_STANDBY)

    return exhausted_list


def remove_from_team(chatgpt_api, email, *, return_status=False):
    """将账号从 Team 中移除"""
    if _is_main_account_email(email):
        logger.warning("[Team] 跳过移除主号: %s", email)
        return "failed" if return_status else False

    account_id = get_chatgpt_account_id()
    # 先获取成员列表找到 user_id
    path = f"/backend-api/accounts/{account_id}/users"
    result = chatgpt_api._api_fetch("GET", path)

    if result["status"] != 200:
        logger.error("[Team] 获取成员列表失败: %d", result["status"])
        return "failed" if return_status else False

    try:
        data = json.loads(result["body"])
        members = data.get("items", data.get("users", data.get("members", [])))
    except Exception:
        logger.error("[Team] 解析成员列表失败")
        return "failed" if return_status else False

    # 找到对应邮箱的成员
    target_user_id = None
    for member in members:
        member_email = member.get("email", "")
        if member_email.lower() == email.lower():
            target_user_id = member.get("user_id") or member.get("id")
            break

    if not target_user_id:
        logger.info("[Team] 未在成员列表中找到 %s（可能已移出）", email)
        # 可能已经不在 team 了
        return "already_absent" if return_status else True

    # 删除成员
    delete_path = f"/backend-api/accounts/{account_id}/users/{target_user_id}"
    result = chatgpt_api._api_fetch("DELETE", delete_path)

    if result["status"] in (200, 204):
        logger.info("[Team] 已将 %s 移出 Team", email)
        return "removed" if return_status else True
    else:
        logger.error("[Team] 移除 %s 失败: %d %s", email, result["status"], result["body"][:200])
        return "failed" if return_status else False


def invite_to_team(chatgpt_api, email, seat_type="default"):
    """邀请账号加入 Team。旧账号用 default，新账号用 usage_based。"""
    status, data = chatgpt_api.invite_member(email, seat_type=seat_type)
    if status == 200 and isinstance(data, dict):
        errored = data.get("errored_emails", [])
        if errored:
            err_msg = errored[0].get("error", "unknown")
            logger.warning("[Team] 邀请 %s 被拒绝: %s", email, err_msg)
            # default 失败则尝试 usage_based
            if seat_type == "default":
                logger.info("[Team] 尝试 usage_based 方式...")
                return invite_to_team(chatgpt_api, email, seat_type="usage_based")
            return False
    return status == 200


def _complete_registration(email, password, invite_link, mail_client):
    """完成注册 + Codex 登录（从已有邀请链接继续）"""
    from playwright.sync_api import sync_playwright

    from autoteam.invite import register_with_invite

    logger.info("[注册] 开始注册 %s...", email)
    with acquire_browser_lease("manager._complete_registration", sync_playwright_factory=sync_playwright) as lease:
        browser = lease.launch_chromium(**get_playwright_launch_options())
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
        )
        page = context.new_page()
        result, password = register_with_invite(page, invite_link, email, mail_client, password=password)

    if not result:
        logger.error("[注册] 注册 %s 失败", email)
        return None

    # Codex 登录
    bundle = login_codex_via_browser(email, password, mail_client=mail_client)
    if bundle:
        auth_file = save_auth_file(bundle, source="oauth")
        archive_path = _archive_saved_auth(email, auth_file)
        update_account(
            email,
            status=STATUS_ACTIVE,
            auth_file=auth_file,
            rt_auth_file=auth_file,
            last_active_at=time.time(),
            **_archive_update(archive_path),
        )
        logger.info("[注册] 账号就绪: %s", email)
        return email
    else:
        update_account(email, status=STATUS_ACTIVE)
        logger.warning("[注册] 账号已加入 Team 但 Codex 登录失败: %s", email)
        return email


def _check_pending_invites(chatgpt_api, mail_client):
    """
    检查 pending invites 中是否有已收到邮件的邀请，有则继续完成注册。
    返回成功完成的邮箱列表。
    """
    import uuid

    account_id = get_chatgpt_account_id()
    result = chatgpt_api._api_fetch("GET", f"/backend-api/accounts/{account_id}/invites")
    if result["status"] != 200:
        return []

    inv_data = json.loads(result["body"])
    invites = inv_data if isinstance(inv_data, list) else inv_data.get("invites", inv_data.get("account_invites", []))

    if not invites:
        return []

    logger.info("[Pending] 发现 %d 个待处理邀请", len(invites))
    completed = []

    for inv in invites:
        inv_email = inv.get("email_address", "")
        logger.info("[Pending] 检查 %s 是否已收到邮件...", inv_email)

        # 从 CloudMail 搜索该邮箱的邀请邮件
        emails = mail_client.search_emails_by_recipient(inv_email, size=5)
        invite_link = None
        for em in emails:
            sender = em.get("sendEmail", "").lower()
            if "openai" in sender:
                invite_link = mail_client.extract_invite_link(em)
                if invite_link:
                    break

        if not invite_link:
            logger.info("[Pending] %s 未收到邮件，跳过", inv_email)
            continue

        logger.info("[Pending] %s 已收到邀请邮件，继续注册流程...", inv_email)

        # 确保本地有账号记录
        acc = find_account(load_accounts(), inv_email)
        if acc:
            password = acc.get("password", f"Tmp_{uuid.uuid4().hex[:12]}!")
        else:
            password = f"Tmp_{uuid.uuid4().hex[:12]}!"
            add_account(inv_email, password)

        # 关闭 ChatGPT 浏览器再注册
        chatgpt_api.stop()

        email = _complete_registration(inv_email, password, invite_link, mail_client)
        if email:
            completed.append(email)

    return completed


def _is_email_in_team(email):
    """检查邮箱是否已实际进入 Team。"""
    chatgpt = None
    try:
        chatgpt = ChatGPTTeamAPI()
        chatgpt.start()
        members, _ = fetch_team_state(chatgpt)
        return any((m.get("email", "") or "").lower() == email.lower() for m in members)
    except Exception as exc:
        logger.warning("[直接注册] 检查 Team 成员失败: %s", exc)
        return False
    finally:
        if chatgpt and chatgpt.browser:
            chatgpt.stop()


_DIRECT_EMAIL_SELECTORS = (
    'input[name="email"], input[type="email"], input[id="email"], '
    'input[autocomplete="email"], input[autocomplete="username"], '
    'input[placeholder*="email" i], input[placeholder*="Email" i]'
)
_DIRECT_PASSWORD_SELECTORS = 'input[name="password"], input[type="password"]'
_DIRECT_CODE_SELECTORS = (
    'input[name="code"], input[placeholder*="验证码"], input[placeholder*="code" i], '
    'input[inputmode="numeric"], input[autocomplete="one-time-code"], input[maxlength="1"], input[type="text"]'
)
_DIRECT_CONTINUE_WITH_PASSWORD_SELECTORS = (
    'button:has-text("Continue with password"), a:has-text("Continue with password"), '
    'button:has-text("Use password"), a:has-text("Use password"), '
    'button:has-text("使用密码"), a:has-text("使用密码"), '
    'button:has-text("继续使用密码"), a:has-text("继续使用密码")'
)
_DIRECT_SIGNUP_START_URL = "https://chatgpt.com/auth/login"
_DIRECT_ABOUT_YOU_TIMEOUT_SECONDS = 90.0


def _safe_invite_screenshot(page, name):
    from autoteam.invite import screenshot

    try:
        screenshot(page, name)
    except Exception as exc:
        logger.debug("[直接注册] 截图失败 %s: %s", name, exc)


def _page_excerpt(page, limit=240):
    try:
        return page.locator("body").inner_text(timeout=1500)[:limit].replace("\n", " ")
    except Exception:
        return ""


def _safe_excerpt(value, limit=300):
    return str(value or "").replace("\n", " ").replace("\r", " ")[:limit]


def _is_session_ended_page(page) -> bool:
    url = (page.url or "").lower()
    if "auth.openai.com" not in url:
        return False
    body = _page_excerpt(page, limit=500).lower()
    return "your session has ended" in body or "session has ended" in body


def _is_cloudflare_verifying(page) -> bool:
    try:
        html = page.content()[:3000].lower()
    except Exception:
        html = ""
    url = (page.url or "").lower()
    return (
        "verify you are human" in html
        or "verifying..." in html
        or "cloudflare" in html
        or "challenge" in url
    )


def _try_solve_cloudflare_checkbox(page) -> bool:
    challenge_frame = next((frame for frame in page.frames if "challenges.cloudflare.com" in (frame.url or "")), None)
    if challenge_frame:
        checkbox_selectors = [
            'label.ctp-checkbox-label',
            'input[type="checkbox"]',
            '[role="checkbox"]',
        ]
        for selector in checkbox_selectors:
            try:
                target = challenge_frame.locator(selector).first
                if target.is_visible(timeout=1200):
                    target.click(force=True, timeout=2500)
                    logger.info("[直接注册] 已尝试在 Cloudflare frame 内点击验证控件")
                    return True
            except Exception:
                continue

    iframe_selectors = [
        'iframe[title*="Cloudflare"]',
        'iframe[src*="cloudflare"]',
        'iframe[src*="challenges.cloudflare"]',
    ]
    for selector in iframe_selectors:
        try:
            iframe = page.locator(selector).first
            box = iframe.bounding_box(timeout=1500)
            if not box:
                continue
            click_x = box["x"] + min(28, max(12, box["width"] * 0.12))
            click_y = box["y"] + (box["height"] / 2)
            page.mouse.click(click_x, click_y)
            logger.info("[直接注册] 已尝试按坐标点击 Cloudflare 验证框")
            return True
        except Exception:
            continue

    frame_locators = [page.frame_locator(selector) for selector in iframe_selectors]
    checkbox_selectors = [
        'label.ctp-checkbox-label',
        'input[type="checkbox"]',
        '[role="checkbox"]',
        'text=Verify you are human',
    ]

    for frame in frame_locators:
        for selector in checkbox_selectors:
            try:
                target = frame.locator(selector).first
                if target.is_visible(timeout=1200):
                    target.click(force=True, timeout=2500)
                    logger.info("[直接注册] 已尝试点击 Cloudflare 验证控件")
                    return True
            except Exception:
                continue

    for selector in checkbox_selectors:
        try:
            target = page.locator(selector).first
            if target.is_visible(timeout=800):
                target.click(force=True, timeout=2000)
                logger.info("[直接注册] 已尝试点击页面内 Cloudflare 验证控件")
                return True
        except Exception:
            continue

    return False


def _wait_for_direct_cloudflare(page, *, label="Cloudflare", timeout=75) -> bool:
    deadline = time.time() + timeout
    tick = 0
    click_attempted = False
    while time.time() < deadline:
        if not _is_cloudflare_verifying(page):
            return True
        if not click_attempted or tick % 3 == 0:
            click_attempted = _try_solve_cloudflare_checkbox(page) or click_attempted
        logger.info("[直接注册] 等待 %s... (%ds)", label, tick * 5)
        time.sleep(5)
        tick += 1
    return not _is_cloudflare_verifying(page)


def _quota_window_label(window: str | None) -> str:
    if window == "weekly":
        return "周"
    if window == "combined":
        return "5h和周"
    if window == "primary":
        return "5h"
    return "额度"


def _pending_historical_exhausted_info(quota_info, now=None):
    """仅当历史额度快照对应的耗尽窗口尚未重置时，才返回耗尽详情。"""
    exhausted_info = get_quota_exhausted_info(quota_info)
    if not exhausted_info:
        return None

    current_ts = time.time() if now is None else now
    resets_at = quota_result_resets_at(exhausted_info)
    if resets_at and current_ts >= resets_at:
        return None

    return exhausted_info


def _standby_reuse_hold_info(acc, now=None, grace_seconds=None):
    """返回 standby 账号在何时之前都不应复用。

    优先使用账号被标记 exhausted 时保存下来的 quota_resets_at，
    避免仅凭 last_quota.primary_resets_at 误判 5h 已恢复。
    """
    current_ts = time.time() if now is None else now
    grace = REUSE_RESET_GRACE_SECONDS if grace_seconds is None else grace_seconds

    saved_resets_at = 0
    try:
        saved_resets_at = int(acc.get("quota_resets_at") or 0)
    except Exception:
        saved_resets_at = 0

    if saved_resets_at:
        hold_until = saved_resets_at + grace
        if current_ts < hold_until:
            window = (acc.get("quota_window") or "").strip()
            if not window:
                exhausted_info = get_quota_exhausted_info(acc.get("last_quota"))
                if exhausted_info:
                    window = exhausted_info.get("window") or ""
            return {
                "resets_at": saved_resets_at,
                "hold_until": hold_until,
                "window": window,
                "source": "saved",
            }

    exhausted_info = get_quota_exhausted_info(acc.get("last_quota"))
    if exhausted_info:
        resets_at = quota_result_resets_at(exhausted_info)
        hold_until = resets_at + grace if resets_at else 0
        if hold_until and current_ts < hold_until:
            return {
                "resets_at": resets_at,
                "hold_until": hold_until,
                "window": exhausted_info.get("window") or "",
                "source": "history",
            }

    return None


def _first_visible_editable_locator(page, selectors, timeout=800):
    try:
        locator = page.locator(selectors).first
        if not locator.is_visible(timeout=timeout):
            return None
        if locator.is_editable(timeout=timeout):
            return locator
    except Exception:
        return None
    return None


def _find_direct_code_inputs(page, timeout=5000):
    try:
        single_inputs = [
            item
            for item in page.locator('input[maxlength="1"], input[inputmode="numeric"]').all()
            if item.is_visible(timeout=200)
        ]
        if len(single_inputs) >= 4:
            return single_inputs
    except Exception:
        pass

    try:
        code_input = page.locator(_DIRECT_CODE_SELECTORS).first
        if code_input.is_visible(timeout=timeout):
            return [code_input]
    except Exception:
        pass

    return []


def _fill_direct_verification_code(page, inputs, code: str) -> bool:
    if not inputs or not code:
        return False
    if len(inputs) >= 4:
        try:
            for index, char in enumerate(code):
                if index >= len(inputs):
                    break
                inputs[index].fill(char)
                time.sleep(0.1)
            return True
        except Exception:
            return False

    try:
        inputs[0].fill(code)
        return True
    except Exception:
        return False


def _mail_subjects_excerpt(emails, *, limit: int = 5) -> str:
    subjects = []
    for item in emails or []:
        if not isinstance(item, dict):
            continue
        subject = str(item.get("subject") or "").strip()
        sender = str(item.get("sendEmail") or item.get("sender") or item.get("from") or "").strip()
        if subject and sender:
            subjects.append(f"{subject} from {sender}")
        elif subject:
            subjects.append(subject)
        elif sender:
            subjects.append(f"(no subject) from {sender}")
    if not subjects:
        return "none"
    return " | ".join(subjects[:limit])


def _detect_direct_register_step(page):
    url = (page.url or "").lower()
    if is_openai_add_phone_url(url):
        return "add_phone"
    if "auth.openai.com/choose-an-account" in url:
        return "chooser"
    if _is_google_redirect(page):
        return "google"
    if "api/auth/error" in url or "auth/error" in url:
        return "auth_error"
    if _is_cloudflare_verifying(page):
        return "cloudflare"

    try:
        if _first_visible_editable_locator(page, _DIRECT_PASSWORD_SELECTORS, timeout=300):
            return "password"
    except Exception:
        pass

    if "email-verification" in url:
        return "code"
    if "about-you" in url:
        return "profile"
    if "workspace" in url or "organization" in url:
        return "workspace"
    if "create-account/password" in url or url.endswith("/password"):
        return "password"
    if "chatgpt.com" in url and "auth" not in url:
        return "completed"

    try:
        if _first_visible_editable_locator(page, _DIRECT_PASSWORD_SELECTORS, timeout=300):
            return "password"
    except Exception:
        pass

    try:
        if _first_visible_editable_locator(page, _DIRECT_CODE_SELECTORS, timeout=300):
            return "code"
    except Exception:
        pass

    try:
        if page.locator('input[name="name"], [role="spinbutton"]').first.is_visible(timeout=300):
            return "profile"
    except Exception:
        pass

    try:
        body = page.locator("body").inner_text(timeout=300).lower()
    except Exception:
        body = ""
    if (
        ("workspace" in body and ("choose" in body or "select" in body or "join" in body or "launch" in body))
        or ("organization" in body and ("create" in body or "new" in body or "choose" in body or "select" in body))
        or "选择工作空间" in body
        or "选择一个工作空间" in body
        or "创建组织" in body
    ):
        return "workspace"

    try:
        if _first_visible_editable_locator(page, _DIRECT_EMAIL_SELECTORS, timeout=300):
            return "email"
    except Exception:
        pass

    if "log-in-or-create-account" in url or url.endswith("/auth/login"):
        return "email"
    if "create-account" in url or "password" in url:
        return "password"
    return "unknown"


def _title_contains_openai_oops(title: str) -> bool:
    lowered = str(title or "").strip().lower()
    return "oops" in lowered or "an error occurred" in lowered


def _direct_register_error_text(page) -> str:
    selector = "[class*=error], [role=alert], h1:has-text('Sorry'), h1:has-text('Error')"
    try:
        target = page.locator(selector).first
        if target.is_visible(timeout=500):
            try:
                return _safe_excerpt(target.inner_text(timeout=500), limit=300)
            except Exception:
                return _safe_excerpt(target.text_content(timeout=500), limit=300)
    except Exception:
        return ""
    return ""


def _direct_register_failure_diagnostics(page, *, reason: str = "") -> str:
    try:
        current_url = str(getattr(page, "url", "") or "")
    except Exception:
        current_url = ""
    try:
        step = _detect_direct_register_step(page)
    except Exception as exc:
        step = f"unknown({exc})"
    try:
        title = _safe_excerpt(page.title(), limit=120)
    except Exception:
        title = ""
    try:
        html_excerpt = _safe_excerpt(page.content(), limit=300)
    except Exception:
        html_excerpt = ""
    error_text = _direct_register_error_text(page)
    if "failed to create account" in error_text.lower():
        reason = "ip_blocked"
    elif step == "profile" and "auth.openai.com/about-you" in current_url.lower() and _title_contains_openai_oops(title):
        reason = "oops_error"
    reason_text = f" reason={_safe_excerpt(reason, limit=120)}" if reason else ""
    return (
        f"step={step} url={current_url} title={title} "
        f"error_text={_safe_excerpt(error_text, limit=80)} html_excerpt={html_excerpt}{reason_text}"
    )


def _raise_direct_register_failure(page, *, reason: str = "", browser=None) -> None:
    diagnostics = _direct_register_failure_diagnostics(page, reason=reason)
    message = f"直注注册未完成: {diagnostics}"
    logger.error("[直接注册] 注册失败: %s", message)
    if browser is not None:
        try:
            browser.close()
        except Exception:
            pass
    if "reason=ip_blocked" in diagnostics:
        raise OpenAiCreateAccountBlockedError(message, reason="ip_blocked")
    if "reason=oops_error" in diagnostics:
        raise OpenAiCreateAccountBlockedError(message, reason="oops_error")
    raise RuntimeError(message)


def _wait_for_direct_register_step(page, allowed_steps, timeout=15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        step = _detect_direct_register_step(page)
        if step in allowed_steps:
            return step
        time.sleep(0.5)
    return _detect_direct_register_step(page)


def _wait_for_direct_step_change(page, current_step, timeout=15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        step = _detect_direct_register_step(page)
        if step != current_step:
            return step
        time.sleep(0.5)
    return _detect_direct_register_step(page)


def _click_direct_continue_with_password(page) -> bool:
    """OTP-first signup variants expose an explicit switch to password signup."""
    try:
        target = page.locator(_DIRECT_CONTINUE_WITH_PASSWORD_SELECTORS).first
        if not target.is_visible(timeout=800):
            return False
        logger.info("[直接注册] 验证码页检测到密码注册入口，切换到密码步骤")
        target.click(timeout=3000)
        time.sleep(2)
        return True
    except Exception as exc:
        logger.debug("[直接注册] 切换密码注册入口失败: %s", exc)
        return False


def _goto_direct_signup_start(page) -> None:
    page.goto(_DIRECT_SIGNUP_START_URL, wait_until="domcontentloaded", timeout=60000)
    time.sleep(2)


def _href_from_locator(locator) -> str:
    for expression in [
        "el => el.href || ''",
        "el => el.closest('a')?.href || ''",
        "el => el.getAttribute('href') || ''",
    ]:
        try:
            href = locator.evaluate(expression)
            if href:
                return str(href)
        except Exception:
            continue
    return ""


def _try_activate_direct_signup_locator(page, locator, desc: str) -> bool:
    href = _href_from_locator(locator)
    if href:
        logger.info("[直接注册] 跳转注册入口: %s -> %s", desc, href)
        page.goto(href, wait_until="domcontentloaded", timeout=60000)
        time.sleep(2)
        return True

    click_attempts = [
        lambda: locator.click(timeout=3000),
        lambda: locator.click(force=True, timeout=3000),
        lambda: locator.evaluate("el => el.click()"),
    ]
    for index, click in enumerate(click_attempts, start=1):
        try:
            logger.info("[直接注册] 点击注册入口: %s (attempt %d)", desc, index)
            click()
            time.sleep(2)
            return True
        except Exception as exc:
            logger.debug("[直接注册] 点击注册入口失败: %s attempt=%d error=%s", desc, index, exc)

    try:
        box = locator.bounding_box(timeout=1500)
        if box:
            page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            logger.info("[直接注册] 坐标点击注册入口: %s", desc)
            time.sleep(2)
            return True
    except Exception as exc:
        logger.debug("[直接注册] 坐标点击注册入口失败: %s error=%s", desc, exc)
    return False


def _click_direct_signup_entry(page) -> bool:
    """Click or navigate through a visible entry point that opens the email signup form."""
    selectors = [
        ('button:has-text("More options")', "More options"),
        ('button:has-text("更多选项")', "更多选项"),
        ('a:has-text("Sign up for free")', "Sign up for free"),
        ('button:has-text("Sign up for free")', "Sign up for free"),
        ('a:has-text("Get started")', "Get started"),
        ('button:has-text("Get started")', "Get started"),
        ('a:has-text("Sign up")', "Sign up"),
        ('button:has-text("Sign up")', "Sign up"),
        ('a:has-text("注册")', "注册"),
        ('button:has-text("注册")', "注册"),
    ]
    for _round in range(2):
        for sel, desc in selectors:
            try:
                btn = page.locator(sel).first
                if not btn.is_visible(timeout=1000):
                    continue
                if not _try_activate_direct_signup_locator(page, btn, desc):
                    continue
                if desc in {"More options", "更多选项"}:
                    continue
                return True
            except Exception:
                continue
    return False


def _complete_direct_about_you(page, *, email: str | None = None, timeout: float = _DIRECT_ABOUT_YOU_TIMEOUT_SECONDS):
    """尽量完成 about-you 页面，兼容不同生日字段顺序。"""
    if "about-you" not in str(getattr(page, "url", "") or "").lower():
        return True

    try:
        title = page.title()
    except Exception:
        title = ""
    if _title_contains_openai_oops(title):
        message = f"about-you Oops 风控: url={getattr(page, 'url', '')} title={_safe_excerpt(title, limit=120)}"
        logger.warning("[直接注册] %s", message)
        raise OpenAiCreateAccountBlockedError(message, email=email or "", reason="about_you_oops")

    effective_timeout = max(1.0, float(timeout or _DIRECT_ABOUT_YOU_TIMEOUT_SECONDS))
    started_at = time.monotonic()
    deadline = started_at + effective_timeout
    result = fill_about_you_page(
        page,
        email=email,
        logger=logger,
        log_prefix="[直接注册]",
        submit_timeout=12,
        deadline=deadline,
    )
    elapsed = time.monotonic() - started_at
    if elapsed >= effective_timeout or (not result and "about-you" in str(getattr(page, "url", "") or "").lower()):
        message = f"about-you 超时 / 风控页加载失败: elapsed={elapsed:.1f}s url={getattr(page, 'url', '')}"
        logger.warning("[直接注册] %s | body=%s", message, _page_excerpt(page))
        raise OpenAiCreateAccountBlockedError(message, email=email or "", reason="about_you_timeout")
    if not result and "about-you" in (page.url or "").lower():
        logger.warning("[直接注册] about-you 页面仍未完成 | URL: %s | body=%s", page.url, _page_excerpt(page))
    return result


def _wait_for_direct_admin_members_access(page, *, email: str = "", timeout=90) -> bool:
    """确认注册账号的 workspace 已可访问，再允许保存凭证或关闭窗口。"""
    deadline = time.time() + timeout
    last_error = ""

    while time.time() < deadline:
        try:
            page.goto("https://chatgpt.com/admin/members", wait_until="domcontentloaded", timeout=30000)
            try:
                page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass
            complete_workspace_selection(page, logger=logger, log_prefix="[直接注册]")
            url = (page.url or "").lower()
            _raise_if_add_phone_url(url, email)
            body = _page_excerpt(page, limit=500).lower()
            if "api/auth/error" in url or "auth/error" in url:
                last_error = body or url
            elif "no_valid_organizations" in body or "organization not found" in body:
                last_error = body
            elif "chatgpt.com/admin/members" in url and "auth" not in url:
                logger.info("[直接注册] 已确认 workspace 成员管理页可访问")
                return True
            else:
                last_error = f"url={page.url} body={body[:180]}"
        except Exception as exc:
            last_error = str(exc)

        logger.info("[直接注册] 等待 workspace 创建完成并可访问 admin/members: %s", last_error[:180])
        time.sleep(5)

    logger.warning("[直接注册] workspace 创建确认超时，admin/members 不可访问: %s", last_error[:240])
    return False


def _register_direct_once(
    mail_client,
    email,
    password,
    mail_account_id=None,
    session_bundle_callback=None,
    oauth_bundle_callback=None,
    require_session_bundle=False,
    require_oauth_bundle=False,
):
    """执行一次直接注册，返回是否完成注册并进入 Team。"""
    from playwright.sync_api import sync_playwright

    logger.info("[直接注册] %s", email)
    signup_url = _DIRECT_SIGNUP_START_URL

    with acquire_browser_lease("manager._register_direct_once", sync_playwright_factory=sync_playwright) as lease:
        launch_kwargs = get_playwright_launch_options()
        if sys.platform.startswith("win"):
            launch_kwargs["slow_mo"] = 100
        browser = lease.launch_chromium(**launch_kwargs)
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
        )
        page = context.new_page()
        last_register_issue = ""

        def fail(reason: str) -> None:
            _raise_direct_register_failure(page, reason=reason, browser=browser)

        page.goto(signup_url, wait_until="domcontentloaded", timeout=60000)
        _raise_if_add_phone_url(page.url, email)
        time.sleep(5)

        _wait_for_direct_cloudflare(page, label="初始验证", timeout=75)
        _raise_if_add_phone_url(page.url, email)
        if _is_session_ended_page(page):
            logger.warning("[直接注册] 注册入口返回 session ended，回到 ChatGPT 登录入口重试")
            _goto_direct_signup_start(page)
            _raise_if_add_phone_url(page.url, email)
            _wait_for_direct_cloudflare(page, label="初始验证", timeout=75)
            _raise_if_add_phone_url(page.url, email)

        _safe_invite_screenshot(page, "direct_01_login_page.png")

        # OpenAI 首页有多种 A/B 测试变体，需要逐步找到邮箱输入框
        try:
            email_visible = page.locator(_DIRECT_EMAIL_SELECTORS).first.is_visible(timeout=3000)
            if not email_visible:
                # 尝试按优先级点击各种按钮来展开/跳转到邮箱输入
                if _click_direct_signup_entry(page):
                    _wait_for_direct_cloudflare(page, label="注册入口验证", timeout=75)
                    _raise_if_add_phone_url(page.url, email)
                    if _is_session_ended_page(page):
                        logger.warning("[直接注册] 注册入口跳到 session ended，回到 ChatGPT 登录入口重试")
                        _goto_direct_signup_start(page)
                        _raise_if_add_phone_url(page.url, email)
                        _wait_for_direct_cloudflare(page, label="初始验证", timeout=75)
                        _raise_if_add_phone_url(page.url, email)
        except PhoneVerificationRequiredError:
            raise
        except Exception:
            pass

        _safe_invite_screenshot(page, "direct_02_signup.png")

        logger.info("[直接注册] 准备输入邮箱: %s", email)
        email_step = _wait_for_direct_register_step(
            page,
            {"email", "password", "code", "profile", "completed", "google", "auth_error"},
            timeout=30,
        )
        logger.info("[直接注册] 邮箱步骤初始状态: %s | URL: %s", email_step, page.url)
        _raise_if_add_phone_url(page.url, email)
        if email_step == "email" and not _first_visible_editable_locator(page, _DIRECT_EMAIL_SELECTORS, timeout=500):
            if _click_direct_signup_entry(page):
                _wait_for_direct_cloudflare(page, label="注册入口验证", timeout=75)
                email_step = _wait_for_direct_register_step(
                    page,
                    {"email", "password", "code", "profile", "completed", "google", "auth_error"},
                    timeout=20,
                )
                logger.info("[直接注册] 点击入口后邮箱步骤状态: %s | URL: %s", email_step, page.url)
                _raise_if_add_phone_url(page.url, email)

        if email_step == "auth_error":
            _safe_invite_screenshot(page, "direct_02_auth_error.png")
            logger.warning("[直接注册] 认证错误页，当前邮箱失败 | URL: %s | body=%s", page.url, _page_excerpt(page))
            fail("邮箱步骤进入认证错误页")
        if email_step == "cloudflare":
            _safe_invite_screenshot(page, "direct_02_cloudflare_timeout.png")
            logger.warning("[直接注册] Cloudflare 验证未完成 | URL: %s | body=%s", page.url, _page_excerpt(page))
            fail("邮箱步骤 Cloudflare 验证未完成")
        if email_step == "google":
            logger.warning("[直接注册] 邮箱步骤误跳转到 Google 登录页")
            fail("邮箱步骤跳转到 Google 登录页")
        if email_step == "unknown":
            logger.warning("[直接注册] 未识别到邮箱步骤 | URL: %s | body=%s", page.url, _page_excerpt(page))
            fail("未识别到邮箱步骤")

        try:
            for attempt in range(3):
                step = _detect_direct_register_step(page)
                if step != "email":
                    break

                email_input = _first_visible_editable_locator(page, _DIRECT_EMAIL_SELECTORS, timeout=1500)
                if not email_input:
                    logger.info("[直接注册] 邮箱输入框不可编辑，等待页面继续跳转...")
                    next_step = _wait_for_direct_step_change(page, "email", timeout=10)
                    _raise_if_add_phone_url(page.url, email)
                    if next_step != "email":
                        break
                    logger.warning("[直接注册] 邮箱输入框仍不可编辑，继续重试 | URL: %s", page.url)
                    continue

                email_input.fill(email)
                time.sleep(0.5)
                logger.info("[直接注册] 邮箱已填入，点击 Continue... (attempt %d)", attempt + 1)
                _safe_invite_screenshot(page, f"direct_02b_email_filled_{attempt}.png")
                _click_primary_auth_button(page, email_input, ["Continue", "继续"])

                next_step = _wait_for_direct_step_change(page, "email", timeout=15)
                logger.info("[直接注册] 点击 Continue 后状态: %s | URL: %s", next_step, page.url)
                _raise_if_add_phone_url(page.url, email)
                _safe_invite_screenshot(page, f"direct_02c_after_continue_{attempt}.png")

                if next_step == "google":
                    _safe_invite_screenshot(page, f"direct_03_google_redirect_attempt{attempt + 1}.png")
                    logger.warning("[直接注册] 邮箱步骤误跳转到 Google 登录，返回重试... (attempt %d)", attempt + 1)
                    page.go_back(wait_until="domcontentloaded", timeout=30000)
                    _raise_if_add_phone_url(page.url, email)
                    time.sleep(2)
                    continue
                if next_step == "auth_error":
                    _safe_invite_screenshot(page, f"direct_03_auth_error_attempt{attempt + 1}.png")
                    logger.warning("[直接注册] 邮箱提交后进入认证错误页 | URL: %s | body=%s", page.url, _page_excerpt(page))
                    fail("邮箱提交后进入认证错误页")
                if next_step == "cloudflare":
                    _wait_for_direct_cloudflare(page, label="邮箱提交后验证", timeout=75)
                    _raise_if_add_phone_url(page.url, email)
                    next_step = _detect_direct_register_step(page)
                    logger.info("[直接注册] 邮箱提交后验证结束状态: %s | URL: %s", next_step, page.url)
                    _raise_if_add_phone_url(page.url, email)
                    if next_step == "auth_error":
                        _safe_invite_screenshot(page, f"direct_03_auth_error_attempt{attempt + 1}.png")
                        logger.warning("[直接注册] 邮箱提交后进入认证错误页 | URL: %s | body=%s", page.url, _page_excerpt(page))
                        fail("邮箱提交后验证结束进入认证错误页")
                if next_step != "email":
                    break

                email_input = _first_visible_editable_locator(page, _DIRECT_EMAIL_SELECTORS, timeout=600)
                if not email_input:
                    logger.info("[直接注册] 邮箱框已只读/跳转中，额外等待页面推进...")
                    next_step = _wait_for_direct_step_change(page, "email", timeout=10)
                    logger.info("[直接注册] 额外等待后状态: %s | URL: %s", next_step, page.url)
                    _raise_if_add_phone_url(page.url, email)
                    if next_step != "email":
                        break

                logger.warning(
                    "[直接注册] 点击 Continue 后仍停留在邮箱步骤，准备重试... | URL: %s | body=%s",
                    page.url,
                    _page_excerpt(page),
                )
        except PhoneVerificationRequiredError:
            raise
        except Exception as exc:
            logger.warning("[直接注册] 邮箱步骤异常: %s | URL: %s", exc, page.url)

        _safe_invite_screenshot(page, "direct_03_after_email.png")
        current_step = _detect_direct_register_step(page)
        logger.info("[直接注册] 邮箱步骤结束状态: %s | URL: %s", current_step, page.url)
        _raise_if_add_phone_url(page.url, email)
        if current_step == "auth_error":
            logger.warning("[直接注册] 邮箱步骤进入认证错误页 | URL: %s | body=%s", page.url, _page_excerpt(page))
            fail("邮箱步骤结束后进入认证错误页")
        if current_step == "cloudflare":
            logger.warning("[直接注册] 邮箱步骤仍停留在 Cloudflare 验证 | URL: %s | body=%s", page.url, _page_excerpt(page))
            fail("邮箱步骤结束后仍停留在 Cloudflare 验证")
        if current_step == "google":
            logger.warning("[直接注册] 邮箱步骤仍停留在 Google 登录页")
            fail("邮箱步骤结束后仍停留在 Google 登录页")
        if current_step == "email":
            if "chatgpt.com/auth/login" in (page.url or "") or "chatgpt.com" in (page.url or ""):
                fallback_url = "https://auth.openai.com/log-in-or-create-account?signup=true"
                logger.warning(
                    "[直接注册] 邮箱步骤滞留在 ChatGPT 主登录页，强制跳转 %s 重试一次",
                    fallback_url,
                )
                try:
                    page.goto(fallback_url, wait_until="domcontentloaded", timeout=60000)
                    _raise_if_add_phone_url(page.url, email)
                    time.sleep(3)
                    _wait_for_direct_cloudflare(page, label="fallback 注册入口", timeout=75)
                    _safe_invite_screenshot(page, "direct_02d_fallback_signup.png")
                    fallback_step = _wait_for_direct_register_step(
                        page,
                        {"email", "password", "code", "profile", "completed", "google", "auth_error"},
                        timeout=20,
                    )
                    logger.info("[直接注册] fallback 注册入口状态: %s | URL: %s", fallback_step, page.url)
                    _raise_if_add_phone_url(page.url, email)
                    if fallback_step == "email":
                        email_input = _first_visible_editable_locator(page, _DIRECT_EMAIL_SELECTORS, timeout=3000)
                        if email_input:
                            email_input.fill(email)
                            time.sleep(0.5)
                            logger.info("[直接注册] fallback 邮箱已填入，点击 Continue")
                            _click_primary_auth_button(page, email_input, ["Continue", "继续"])
                            fallback_step = _wait_for_direct_step_change(page, "email", timeout=20)
                            logger.info("[直接注册] fallback 提交后状态: %s | URL: %s", fallback_step, page.url)
                            _raise_if_add_phone_url(page.url, email)
                    if fallback_step in {"password", "code", "profile", "workspace", "completed"}:
                        current_step = fallback_step
                    else:
                        current_step = _detect_direct_register_step(page)
                except PhoneVerificationRequiredError:
                    raise
                except Exception as exc:
                    logger.warning("[直接注册] fallback 注册入口失败: %s | URL: %s", exc, page.url)
            if current_step == "email":
                logger.warning("[直接注册] 邮箱步骤未推进 | URL: %s | body=%s", page.url, _page_excerpt(page))
                fail("邮箱步骤未推进")

        # 等待页面跳转完成（可能跳到 create-account/password）
        password_step = _wait_for_direct_register_step(
            page,
            {"password", "code", "profile", "workspace", "completed", "google", "email"},
            timeout=15,
        )
        logger.info("[直接注册] 密码页检测状态: %s | URL: %s", password_step, page.url)
        _raise_if_add_phone_url(page.url, email)
        _safe_invite_screenshot(page, "direct_03b_before_password.png")

        password_submitted = False
        if password_step == "code" and _click_direct_continue_with_password(page):
            password_step = _wait_for_direct_register_step(
                page,
                {"password", "code", "profile", "workspace", "completed", "google", "email", "auth_error"},
                timeout=12,
            )
            logger.info("[直接注册] 切换密码注册入口后状态: %s | URL: %s", password_step, page.url)
            _raise_if_add_phone_url(page.url, email)
            _safe_invite_screenshot(page, "direct_03c_continue_with_password.png")

        try:
            for attempt in range(2):
                if _detect_direct_register_step(page) != "password":
                    logger.info("[直接注册] 未检测到密码输入框，跳过")
                    break

                pwd_input = _first_visible_editable_locator(page, _DIRECT_PASSWORD_SELECTORS, timeout=1500)
                if not pwd_input:
                    logger.info("[直接注册] 密码输入框不可编辑，等待页面继续跳转...")
                    next_step = _wait_for_direct_step_change(page, "password", timeout=10)
                    _raise_if_add_phone_url(page.url, email)
                    if next_step != "password":
                        break
                    logger.warning("[直接注册] 密码输入框仍不可编辑，继续重试 | URL: %s", page.url)
                    continue

                logger.info("[直接注册] 设置密码")
                pwd_input.fill(password)
                time.sleep(0.5)
                _click_primary_auth_button(page, pwd_input, ["Continue", "继续", "Log in"])
                next_step = _wait_for_direct_step_change(page, "password", timeout=15)
                logger.info("[直接注册] 提交密码后状态: %s | URL: %s", next_step, page.url)
                _raise_if_add_phone_url(page.url, email)

                if next_step == "google":
                    _safe_invite_screenshot(page, f"direct_04_google_redirect_attempt{attempt + 1}.png")
                    logger.warning("[直接注册] 密码步骤误跳转到 Google 登录，返回重试... (attempt %d)", attempt + 1)
                    page.go_back(wait_until="domcontentloaded", timeout=30000)
                    _raise_if_add_phone_url(page.url, email)
                    time.sleep(2)
                    continue
                if next_step != "password":
                    password_submitted = True
                if next_step != "password":
                    break

                pwd_input = _first_visible_editable_locator(page, _DIRECT_PASSWORD_SELECTORS, timeout=600)
                if not pwd_input:
                    logger.info("[直接注册] 密码框已只读/跳转中，额外等待页面推进...")
                    next_step = _wait_for_direct_step_change(page, "password", timeout=10)
                    logger.info("[直接注册] 额外等待后状态: %s | URL: %s", next_step, page.url)
                    _raise_if_add_phone_url(page.url, email)
                    if next_step != "password":
                        break
        except PhoneVerificationRequiredError:
            raise
        except Exception as exc:
            logger.warning("[直接注册] 密码步骤异常: %s | URL: %s", exc, page.url)

        _safe_invite_screenshot(page, "direct_04_after_password.png")
        current_step = _detect_direct_register_step(page)
        _raise_if_add_phone_url(page.url, email)
        if current_step == "google":
            logger.warning("[直接注册] 密码步骤仍停留在 Google 登录页")
            fail("密码步骤停留在 Google 登录页")
        if current_step == "email":
            logger.warning("[直接注册] 提交密码前流程回退到邮箱页 | URL: %s | body=%s", page.url, _page_excerpt(page))
            fail("提交密码前流程回退到邮箱页")
        if current_step == "auth_error":
            logger.warning("[直接注册] 密码步骤进入认证错误页 | URL: %s | body=%s", page.url, _page_excerpt(page))
            fail("密码步骤进入认证错误页")
        if not password_submitted and current_step != "code":
            if current_step == "code" and _click_direct_continue_with_password(page):
                password_step = _wait_for_direct_register_step(
                    page,
                    {"password", "code", "profile", "workspace", "completed", "google", "email", "auth_error"},
                    timeout=12,
                )
                logger.info("[直接注册] 二次切换密码注册入口后状态: %s | URL: %s", password_step, page.url)
                _raise_if_add_phone_url(page.url, email)
                if password_step == "password":
                    try:
                        pwd_input = _first_visible_editable_locator(page, _DIRECT_PASSWORD_SELECTORS, timeout=2500)
                        if pwd_input:
                            logger.info("[直接注册] 二次设置密码")
                            pwd_input.fill(password)
                            time.sleep(0.5)
                            _click_primary_auth_button(page, pwd_input, ["Continue", "继续", "Log in"])
                            next_step = _wait_for_direct_step_change(page, "password", timeout=15)
                            logger.info("[直接注册] 二次提交密码后状态: %s | URL: %s", next_step, page.url)
                            _raise_if_add_phone_url(page.url, email)
                            password_submitted = next_step != "password"
                            current_step = _detect_direct_register_step(page)
                            _raise_if_add_phone_url(page.url, email)
                    except PhoneVerificationRequiredError:
                        raise
                    except Exception as exc:
                        logger.warning("[直接注册] 二次密码步骤异常: %s | URL: %s", exc, page.url)
            if not password_submitted:
                logger.warning(
                    "[直接注册] 未完成真实密码注册，当前邮箱不能用于后续协议 OAuth | URL: %s | body=%s",
                    page.url,
                    _page_excerpt(page),
                )
                fail("未完成真实密码注册")

        code_inputs = _find_direct_code_inputs(page, timeout=12000) if current_step == "code" else []

        if current_step == "code":
            logger.info("[直接注册] 等待验证码...")
            verification_code = None
            last_emails = []
            start_t = time.time()
            mail_timeout = max(MAIL_TIMEOUT, int(os.environ.get("EMAIL_POLL_TIMEOUT", "300") or 300))
            while time.time() - start_t < mail_timeout:
                if not code_inputs:
                    code_inputs = _find_direct_code_inputs(page, timeout=2000)
                emails = mail_client.search_emails_by_recipient(email, size=10, account_id=mail_account_id)
                last_emails = emails or []
                for em in emails:
                    verification_code = mail_client.extract_verification_code(em)
                    if verification_code:
                        break
                if verification_code and code_inputs:
                    break
                elapsed = int(time.time() - start_t)
                print(f"\r  等待验证码... ({elapsed}s)", end="", flush=True)
                time.sleep(3)

            if verification_code and code_inputs:
                logger.info("[直接注册] 输入验证码: %s", verification_code)
                if not _fill_direct_verification_code(page, code_inputs, verification_code):
                    logger.error("[直接注册] 验证码输入失败，code=%s inputs=%d", verification_code, len(code_inputs))
                    fail(f"验证码输入失败: code={verification_code} inputs={len(code_inputs)}")
                time.sleep(0.5)
                _click_primary_auth_button(page, code_inputs[0], ["Continue", "继续"])
                time.sleep(8)
                _raise_if_add_phone_url(page.url, email)
            elif verification_code:
                logger.error("[直接注册] 收到验证码但未找到验证码输入框 | URL: %s | body=%s", page.url, _page_excerpt(page))
                fail("收到验证码但未找到验证码输入框")
            else:
                subjects = _mail_subjects_excerpt(last_emails)
                logger.error("[直接注册] 未收到验证码或邮件没有验证码 | 已看到邮件: %s", subjects)
                fail(f"未收到验证码或邮件没有验证码: seen_subjects={subjects}")

        _safe_invite_screenshot(page, "direct_05_after_code.png")
        logger.info("[直接注册] 当前 URL: %s", page.url)
        _raise_if_add_phone_url(page.url, email)

        try:
            _complete_direct_about_you(page, email=email)
            _raise_if_add_phone_url(page.url, email)
        except Exception as exc:
            if isinstance(exc, PhoneVerificationRequiredError):
                raise
            if isinstance(exc, OpenAiCreateAccountBlockedError):
                raise
            last_register_issue = f"about-you 步骤异常: {exc}"
            logger.warning("[直接注册] about-you 步骤异常: %s | URL: %s", exc, page.url)

        _safe_invite_screenshot(page, "direct_06_after_profile.png")
        logger.info("[直接注册] 当前 URL: %s", page.url)
        _raise_if_add_phone_url(page.url, email)

        try:
            workspace_done = complete_workspace_selection(
                page,
                logger=logger,
                log_prefix="[直接注册]",
            )
            _raise_if_add_phone_url(page.url, email)
            if workspace_done:
                logger.info("[直接注册] workspace / organization 步骤已完成或不需要处理")
            else:
                last_register_issue = "workspace / organization 步骤仍未完成"
                logger.warning("[直接注册] workspace / organization 步骤仍未完成 | URL: %s | body=%s", page.url, _page_excerpt(page))
        except Exception as exc:
            if isinstance(exc, PhoneVerificationRequiredError):
                raise
            last_register_issue = f"workspace / organization 步骤异常: {exc}"
            logger.warning("[直接注册] workspace / organization 步骤异常: %s | URL: %s", exc, page.url)

        try:
            join_btn = page.locator('button:has-text("Accept"), button:has-text("Join"), button:has-text("加入")').first
            if join_btn.is_visible(timeout=5000):
                join_btn.click()
                time.sleep(5)
                _raise_if_add_phone_url(page.url, email)
        except PhoneVerificationRequiredError:
            raise
        except Exception:
            pass

        try:
            complete_workspace_selection(page, logger=logger, log_prefix="[直接注册]")
            _raise_if_add_phone_url(page.url, email)
        except Exception as exc:
            if isinstance(exc, PhoneVerificationRequiredError):
                raise
            last_register_issue = f"二次处理 workspace / organization 异常: {exc}"
            logger.warning("[直接注册] 二次处理 workspace / organization 异常: %s | URL: %s", exc, page.url)

        _safe_invite_screenshot(page, "direct_07_final.png")

        current_url = page.url
        _raise_if_add_phone_url(current_url, email)
        success = "chatgpt.com" in current_url and "auth" not in current_url and not _is_google_redirect(page)
        if success:
            logger.info("[直接注册] 注册流程已进入 ChatGPT，开始确认 workspace 可用...")
            if not _wait_for_direct_admin_members_access(page, email=email):
                _safe_invite_screenshot(page, "direct_08_admin_members_failed.png")
                if require_session_bundle:
                    fail("组织创建失败: admin/members 不可访问")
                success = False
            else:
                _safe_invite_screenshot(page, "direct_08_admin_members_ok.png")
                logger.info("[直接注册] 注册成功并已确认 workspace 可访问")

        if success:
            if session_bundle_callback:
                extracted_session_bundle = {}
                try:
                    extracted_session_bundle = build_chatgpt_session_auth_bundle(page, email=email)
                    session_bundle_callback(extracted_session_bundle)
                except Exception as exc:
                    logger.warning("[直接注册] 注册成功，但提取 ChatGPT session 凭证失败: %s", exc)
                    if require_session_bundle:
                        raise RuntimeError(f"ChatGPT session 提取失败: {exc}") from exc
            else:
                extracted_session_bundle = {}

            if oauth_bundle_callback:
                try:
                    protocol_result = protocol_oauth.run_protocol_oauth_login_with_browser_context(
                        page,
                        email,
                        password=password,
                        mail_client=mail_client,
                        mail_account_id=mail_account_id,
                    )
                    oauth_bundle = protocol_result.bundle
                    if not oauth_bundle:
                        raise RuntimeError("未获取到 OAuth RT 凭证")
                    oauth_bundle_callback(oauth_bundle)
                except Exception as exc:
                    logger.warning("[直接注册] 注册成功，但同窗口 Codex OAuth 失败: %s", exc)
                    if require_oauth_bundle:
                        raise RuntimeError(f"Codex OAuth 提取失败: {exc}") from exc
        else:
            logger.warning("[直接注册] 注册可能未完成，URL: %s", current_url)
            fail(last_register_issue or "最终 URL 未进入 ChatGPT")

        return success


def create_account_direct(mail_client):
    """
    直接注册模式（域名已配置自动加入 workspace，不需要邀请）。
    流程：创建邮箱 → 注册 ChatGPT → 保存 session 备份 → Codex 登录
    """
    import uuid

    for attempt in range(3):
        account_id, email = mail_client.create_temp_email()
        password = f"Tmp_{uuid.uuid4().hex[:12]}!"
        session_bundle = {}
        oauth_bundle = {}

        def capture_session_bundle(bundle: dict, target=session_bundle) -> None:
            target.clear()
            target.update(bundle or {})

        def capture_oauth_bundle(bundle: dict, target=oauth_bundle) -> None:
            target.clear()
            target.update(bundle or {})

        logger.info("[直接注册] 开始第 %d/3 次注册尝试: %s", attempt + 1, email)
        try:
            success = _register_direct_once(
                mail_client,
                email,
                password,
                mail_account_id=account_id,
                session_bundle_callback=capture_session_bundle,
                oauth_bundle_callback=capture_oauth_bundle,
                require_session_bundle=True,
                require_oauth_bundle=False,
            )
        except Exception as exc:
            success = False
            logger.warning("[直接注册] 注册失败: %s", exc)

        if success and session_bundle:
            break

        try:
            mail_client.delete_account(account_id)
        except Exception as exc:
            logger.warning("[直接注册] 删除失败临时邮箱异常: %s", exc)

        if attempt < 2:
            logger.warning("[直接注册] 当前邮箱注册失败，改用新邮箱继续: %s", email)

    if not success or not session_bundle:
        logger.error("[直接注册] 连续 3 次注册失败，删除临时账号: %s", email)
        return None

    add_account(
        email,
        password,
        cloudmail_account_id=account_id if getattr(mail_client, "provider_name", "") == "cloudmail" else None,
        mail_provider=getattr(mail_client, "provider_name", ""),
        mail_account_id=account_id,
    )

    plan_type = (session_bundle.get("plan_type") or "unknown").strip().lower()
    session_auth_file = save_auth_file(session_bundle, source="session")
    archive_path = _archive_saved_auth(email, session_auth_file)
    update_account(
        email,
        status=STATUS_ACTIVE,
        session_auth_file=session_auth_file,
        plan_type=plan_type,
        last_active_at=time.time(),
        **_archive_update(archive_path),
    )

    if oauth_bundle:
        auth_file = save_auth_file(oauth_bundle, source="oauth")
        archive_path = _archive_saved_auth(email, auth_file)
        update_account(
            email,
            status=STATUS_ACTIVE,
            auth_file=auth_file,
            rt_auth_file=auth_file,
            plan_type=(oauth_bundle.get("plan_type") or plan_type or "unknown").strip().lower(),
            last_active_at=time.time(),
            **_archive_update(archive_path),
        )
        logger.info("[直接注册] 账号就绪: %s", email)
        return email
    else:
        update_account(email, status=STATUS_ACTIVE)
        logger.warning("[直接注册] 账号已加入 Team 但 Codex OAuth 文件未生成: %s", email)
        return email


def create_new_account(chatgpt_api, mail_client):
    """
    创建新账号。优先用直接注册模式（域名自动加入 workspace）。
    chatgpt_api 可为 None（直接注册不需要）。
    """
    # 先检查 pending invites
    if chatgpt_api and chatgpt_api.browser:
        logger.info("[创建] 先检查 pending invites...")
        completed = _check_pending_invites(chatgpt_api, mail_client)
        if completed:
            logger.info("[创建] 从 pending invites 完成了 %d 个账号", len(completed))
            return completed[0]

    # 直接注册模式（不需要邀请）
    logger.info("[创建] 使用直接注册模式...")
    if chatgpt_api and chatgpt_api.browser:
        chatgpt_api.stop()
    return create_account_direct(mail_client)


def _create_new_accounts_parallel(total: int, *, parallel_workers=None, stop_after_success=None) -> dict:
    total = max(0, int(total or 0))
    workers = _resolve_parallel_workers(parallel_workers)
    targets = _split_success_targets(total, workers)
    if not targets:
        return {"attempted": 0, "succeeded": 0, "failed": 0, "emails": [], "worker_reports": [], "parallel_workers": 0}

    if len(targets) == 1:
        mail_client = CloudMailClient()
        mail_client.login()
        attempted = 0
        succeeded = 0
        failed = 0
        emails = []
        for _index in range(targets[0]):
            if stop_after_success and stop_after_success(succeeded):
                break
            attempted += 1
            email = create_new_account(None, mail_client)
            if email:
                succeeded += 1
                emails.append({"email": email, "worker_index": 1})
            else:
                failed += 1
        return {
            "attempted": attempted,
            "succeeded": succeeded,
            "failed": failed,
            "emails": emails,
            "worker_reports": [
                {
                    "worker_index": 1,
                    "target": targets[0],
                    "attempted": attempted,
                    "succeeded": succeeded,
                    "failed": failed,
                }
            ],
            "parallel_workers": 1,
        }

    results: queue.Queue[dict] = queue.Queue()
    stop_event = threading.Event()

    def worker(worker_index: int, worker_target: int) -> None:
        attempted = 0
        succeeded = 0
        failed = 0
        emails = []
        try:
            mail_client = CloudMailClient()
            mail_client.login()
            max_attempts = max(worker_target, worker_target * 2)
            while succeeded < worker_target and attempted < max_attempts and not stop_event.is_set():
                attempted += 1
                logger.info(
                    "[并行创建] worker %d 创建第 %d 个，目标成功 %d",
                    worker_index,
                    attempted,
                    worker_target,
                )
                try:
                    email = create_new_account(None, mail_client)
                except Exception as exc:
                    failed += 1
                    logger.warning("[并行创建] worker %d 创建失败: %s", worker_index, exc)
                    continue
                if email:
                    succeeded += 1
                    emails.append({"email": email, "worker_index": worker_index})
                    if stop_after_success and stop_after_success(None):
                        stop_event.set()
                        break
                else:
                    failed += 1
        except Exception as exc:
            failed += 1
            logger.warning("[并行创建] worker %d 异常: %s", worker_index, exc)
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

    threads = [
        threading.Thread(target=worker, args=(index + 1, target), daemon=True) for index, target in enumerate(targets)
    ]
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
    return {
        "attempted": sum(item["attempted"] for item in worker_reports),
        "succeeded": sum(item["succeeded"] for item in worker_reports),
        "failed": sum(item["failed"] for item in worker_reports),
        "emails": emails,
        "worker_reports": worker_reports,
        "parallel_workers": len(targets),
    }


def reinvite_account(chatgpt_api, mail_client, acc):
    """
    恢复 standby 账号 — 复用统一的 Codex OAuth 登录流程。
    只有拿到 team plan 的认证结果，才视为恢复成功。
    """
    email = acc["email"]
    password = acc.get("password", "")

    logger.info("[轮转] 恢复旧账号: %s（统一 OAuth 登录）", email)

    # 关闭 ChatGPT API 浏览器避免冲突
    if chatgpt_api and chatgpt_api.browser:
        chatgpt_api.stop()

    bundle = login_codex_via_browser(
        email,
        password,
        mail_client=mail_client,
        mail_account_id=get_account_mail_account_id(acc),
    )
    if not bundle:
        logger.warning("[轮转] 旧账号 OAuth 登录失败，保持 standby: %s", email)
        update_account(email, status=STATUS_STANDBY)
        return False

    plan_type = (bundle.get("plan_type") or "").lower()
    if plan_type != "team":
        logger.warning("[轮转] 旧账号登录后 plan=%s，不是 team，恢复失败: %s", plan_type or "unknown", email)
        update_account(email, status=STATUS_STANDBY)
        return False

    auth_file = save_auth_file(bundle, source="oauth")
    archive_path = _archive_saved_auth(email, auth_file)
    update_fields = {
        "status": STATUS_ACTIVE,
        "last_active_at": time.time(),
        "auth_file": auth_file,
        "rt_auth_file": auth_file,
    }
    previous_session_auth_file = get_existing_session_auth_file(acc)
    if previous_session_auth_file:
        update_fields["session_auth_file"] = previous_session_auth_file
    update_account(
        email,
        **update_fields,
        **_archive_update(archive_path),
    )
    logger.info("[轮转] 旧账号已恢复: %s", email)
    return True


def cmd_rotate(target_seats=None, parallel_workers=None):
    """
    智能轮转 - 保持 Team 始终有 target_seats 个可用成员，尽量少创建新账号。

    逻辑:
    1. 检查所有账号额度，更新状态
    2. 将额度用完的 active 账号移出 Team → standby
    3. 统计当前 Team 空缺数
    4. 优先从 standby 中选额度已恢复的旧账号填补
    5. 仅当所有旧账号都不可用时，才创建新账号
    """
    if target_seats is None:
        from autoteam.config import TEAM_TARGET_SEATS

        target_seats = TEAM_TARGET_SEATS

    from autoteam.config import MAX_TEAM_SEATS

    TARGET = min(MAX_TEAM_SEATS, max(1, int(target_seats)))

    from autoteam.config import AUTO_CHECK_THRESHOLD

    try:
        from autoteam.api import _auto_check_config

        threshold = _auto_check_config.get("threshold", AUTO_CHECK_THRESHOLD)
    except ImportError:
        threshold = AUTO_CHECK_THRESHOLD

    chatgpt = None
    mail_client = None
    reuse_mail_clients = {}

    def ensure_chatgpt():
        nonlocal chatgpt
        if not chatgpt or not chatgpt.browser:
            chatgpt = ChatGPTTeamAPI()
            chatgpt.start()
        return chatgpt

    def ensure_mail():
        nonlocal mail_client
        if not mail_client:
            mail_client = CloudMailClient()
            mail_client.login()
        return mail_client

    def ensure_account_mail(acc):
        provider = get_account_mail_provider(acc)
        client = reuse_mail_clients.get(provider)
        if client is None:
            client = _get_account_mail_client(acc)
            client.login()
            reuse_mail_clients[provider] = client
        return client

    def refresh_current_count(current_count, stage_label):
        if not chatgpt or not chatgpt.browser:
            ensure_chatgpt()
        latest_count = get_team_member_count(chatgpt)
        if latest_count >= 0:
            logger.info("%s 实时成员数: %d/%d", stage_label, latest_count, TARGET)
            return latest_count
        return current_count

    logger.info("[1/5] 同步 Team 状态...")
    sync_account_states()

    logger.info("[2/5] 检查额度...")
    cmd_check()

    try:
        # 移出所有 exhausted 账号（包括之前已标记的）
        all_accounts = load_accounts()
        all_exhausted = [
            a for a in all_accounts if a["status"] == STATUS_EXHAUSTED and not _is_main_account_email(a.get("email"))
        ]
        initial_api_count = -1
        removed_now = 0
        already_absent_count = 0

        if all_exhausted:
            logger.info("[3/5] 移出 %d 个额度用完的账号...", len(all_exhausted))
            ensure_chatgpt()
            initial_api_count = get_team_member_count(chatgpt)
            for acc in all_exhausted:
                email = acc["email"]
                if not chatgpt.browser:
                    chatgpt.start()
                remove_status = remove_from_team(chatgpt, email, return_status=True)
                if remove_status in ("removed", "already_absent"):
                    update_account(email, status=STATUS_STANDBY)
                    if remove_status == "removed":
                        removed_now += 1
                        logger.info("[3/5] %s → standby（已从 Team 移出）", email)
                    else:
                        already_absent_count += 1
                        logger.info("[3/5] %s → standby（远端已不存在）", email)
        else:
            logger.info("[3/5] 无需移出账号")
        if not chatgpt or not chatgpt.browser:
            ensure_chatgpt()
        api_count = get_team_member_count(chatgpt)
        logger.info(
            "[4/5] API 返回成员数: %d（实际移出: %d，远端已缺席: %d）",
            api_count,
            removed_now,
            already_absent_count,
        )
        if api_count <= 0:
            # API 返回异常，用本地 active 账号数兜底
            local_active = sum(1 for a in load_accounts() if a["status"] == STATUS_ACTIVE)
            logger.warning("[4/5] API 成员数异常 (%d)，使用本地 active 数: %d", api_count, local_active)
            current_count = local_active
        else:
            # 保守估算当前成员数：
            # - api_count 是移除后的最新观察值
            # - initial_api_count - removed_now 是基于移除前人数的理论下界
            # 若远端成员本就不存在（already_absent），不能再从 api_count 里额外扣减，否则会少算人数。
            estimates = [api_count]
            if initial_api_count > 0 and removed_now > 0:
                estimates.append(max(0, initial_api_count - removed_now))
            current_count = min(estimates)
            if len(estimates) > 1 and current_count != api_count:
                logger.info(
                    "[4/5] 成员数保守估算: %d（初始=%d，移出=%d）", current_count, initial_api_count, removed_now
                )
        vacancies = TARGET - current_count

        if vacancies <= 0:
            excess = current_count - TARGET
            if excess > 0:
                logger.info("[4/5] Team 超员 (%d/%d)，清理 %d 个多余成员...", current_count, TARGET, excess)
                # 只移除本地管理的账号，优先移除额度最低的
                all_accs = load_accounts()
                local_active = [
                    a for a in all_accs if a["status"] == STATUS_ACTIVE and not _is_main_account_email(a.get("email"))
                ]
                # 按额度排序，额度低的优先移除
                local_active.sort(key=lambda a: 100 - (a.get("last_quota") or {}).get("primary_pct", 0))
                removed = 0
                for acc in local_active:
                    if removed >= excess:
                        break
                    email = acc["email"]
                    if remove_from_team(chatgpt, email):
                        update_account(email, status=STATUS_STANDBY)
                        logger.info("[4/5] 超员清理: %s → standby", email)
                        removed += 1
                if removed:
                    logger.info("[4/5] 已清理 %d 个多余成员", removed)
            else:
                logger.info("[4/5] Team 已满 (%d/%d)", current_count, TARGET)
            return

        logger.info("[4/5] 填补 %d 个空缺 (当前 %d/%d)...", vacancies, current_count, TARGET)

        # 优先复用旧账号（先验证额度是否真的恢复了）
        filled = 0
        standby_list = [a for a in get_standby_accounts() if not _is_main_account_email(a.get("email"))]
        quota_skipped = []
        auto_reuse_skipped = []

        for acc in standby_list:
            if filled >= vacancies:
                break
            email = acc["email"]
            auth_file = _account_oauth_rt_auth_file(acc)

            skip_reason = _auto_reuse_skip_reason(acc)
            if skip_reason:
                logger.info("[4/5] 跳过 %s（%s）", email, skip_reason)
                auto_reuse_skipped.append(acc)
                continue

            # 验证额度是否真的恢复了
            quota_ok = False
            if auth_file:
                try:
                    auth_data = json.loads(read_text(Path(auth_file)))
                    access_token = auth_data.get("access_token")
                    if access_token:
                        status_str, info = check_codex_quota(access_token)
                        if status_str == "exhausted":
                            quota_info = quota_result_quota_info(info)
                            if quota_info:
                                update_account(email, last_quota=quota_info)
                            logger.info("[4/5] 跳过 %s（额度未恢复）", email)
                            quota_skipped.append(acc)
                            continue
                        if status_str == "ok" and isinstance(info, dict):
                            p_remain = 100 - info.get("primary_pct", 0)
                            if p_remain < threshold:
                                logger.info("[4/5] 跳过 %s（剩余 %d%% < %d%%）", email, p_remain, threshold)
                                quota_skipped.append(acc)
                                continue
                            quota_ok = True
                        if status_str == "auth_error":
                            logger.info("[4/5] %s 的认证已失效，改用保存的额度信息判断是否可复用", email)
                except Exception:
                    pass

            # 没有认证文件或无法查询额度时，用 last_quota / quota_resets_at 兜底
            if not quota_ok:
                hold_info = _standby_reuse_hold_info(acc)
                if hold_info:
                    window_label = _quota_window_label(hold_info.get("window"))
                    mins = max(0, int((hold_info["hold_until"] - time.time()) / 60))
                    logger.info("[4/5] 跳过 %s（保存的%s恢复时间未到，还需约 %d 分钟）", email, window_label, mins)
                    quota_skipped.append(acc)
                    continue

                lq = acc.get("last_quota")
                if lq:
                    p_resets = lq.get("primary_resets_at", 0)
                    if p_resets and time.time() >= p_resets:
                        # 重置时间已过，旧数据作废，视为额度已恢复
                        logger.info("[4/5] %s 的 5h 重置时间已过，视为额度已恢复", email)
                    else:
                        p_remain = 100 - lq.get("primary_pct", 0)
                        if p_remain < threshold:
                            logger.info("[4/5] 跳过 %s（历史额度 %d%% < %d%%）", email, p_remain, threshold)
                            quota_skipped.append(acc)
                            continue
            logger.info("[4/5] 复用: %s", email)
            if not chatgpt or not chatgpt.browser:
                ensure_chatgpt()
            reused = reinvite_account(chatgpt, ensure_account_mail(acc), acc)
            if reused:
                filled += 1
                current_count += 1
            current_count = refresh_current_count(current_count, "[4/5]")
            if current_count >= TARGET:
                logger.info("[4/5] 当前成员数已达到目标，停止继续补位")
                break
            if not reused:
                quota_skipped.append(acc)

        if quota_skipped:
            logger.info("[4/5] 跳过 %d 个额度未恢复或复用失败的旧号", len(quota_skipped))
        if auto_reuse_skipped:
            logger.info("[4/5] 跳过 %d 个暂不支持自动复用的旧号", len(auto_reuse_skipped))

        remaining = TARGET - current_count
        if remaining <= 0:
            logger.info("[4/5] 已用旧账号填满空缺")
        else:
            # 必须创建新号
            logger.info("[5/5] 创建 %d 个新账号...", remaining)
            resolved_parallel_workers = _resolve_parallel_workers(parallel_workers)
            if resolved_parallel_workers <= 1:
                for i in range(remaining):
                    logger.info("[5/5] 创建第 %d/%d 个...", i + 1, remaining)
                    if not chatgpt or not chatgpt.browser:
                        ensure_chatgpt()
                    if create_new_account(chatgpt, ensure_mail()):
                        current_count += 1
                    current_count = refresh_current_count(current_count, "[5/5]")
                    if current_count >= TARGET:
                        logger.info("[5/5] 当前成员数已达到目标，停止继续创建")
                        break
            else:
                if chatgpt and chatgpt.browser:
                    chatgpt.stop()
                create_result = _create_new_accounts_parallel(remaining, parallel_workers=resolved_parallel_workers)
                current_count += int(create_result.get("succeeded") or 0)
                current_count = refresh_current_count(current_count, "[5/5]")
                if current_count >= TARGET:
                    logger.info("[5/5] 当前成员数已达到目标，停止继续创建")

        if not chatgpt or not chatgpt.browser:
            ensure_chatgpt()
        final_count = get_team_member_count(chatgpt)
        logger.info("[轮转] 最终 Team 成员数: %d（目标: %d）", final_count, TARGET)
        if final_count > TARGET:
            logger.warning("[轮转] 最终 Team 成员数超出目标，后续将按清理逻辑修正")
        elif 0 <= final_count < TARGET:
            logger.warning("[轮转] 最终 Team 成员数仍低于目标 (%d/%d)", final_count, TARGET)

    finally:
        if chatgpt and chatgpt.browser:
            chatgpt.stop()
        # 所有操作完成后统一同步远端，避免中途同步导致远端状态不一致
        logger.info("[轮转] 轮转完成，同步已启用远端...")
        sync_to_cpa()
        logger.info("[轮转] 完成，使用 status 命令查看最新状态")


def cmd_add():
    """手动添加一个新账号"""
    chatgpt = ChatGPTTeamAPI()
    chatgpt.start()
    mail_client = CloudMailClient()
    mail_client.login()

    try:
        result = create_new_account(chatgpt, mail_client)  # 内部会 stop chatgpt
        if result:
            logger.info("[添加] 新账号添加成功: %s", result)
            sync_to_cpa()
        else:
            logger.error("[添加] 添加失败")
    finally:
        if chatgpt.browser:
            chatgpt.stop()


def cmd_manual_add():
    """手动添加账号：优先自动接收 localhost 回调，失败时再手动粘贴回调 URL。"""
    from autoteam.manual_account import ManualAccountFlow

    flow = ManualAccountFlow()
    try:
        result = flow.start()
        logger.info("[手动添加] 打开以下链接完成 OAuth 登录：\n%s", result["auth_url"])
        if result.get("auto_callback_available"):
            logger.info("[手动添加] 已启动本地回调服务 http://localhost:1455/auth/callback，可自动完成认证")
        else:
            logger.warning("[手动添加] 本地自动回调不可用：%s", result.get("auto_callback_error") or "未知错误")

        callback_url = input("登录成功后：若自动完成则直接回车；否则粘贴回调 URL（留空取消）: ").strip()
        if callback_url:
            result = flow.submit_callback(callback_url)
        else:
            result = flow.status()
            if result.get("status") != "completed":
                logger.warning("[手动添加] 未检测到自动回调，已取消")
                return None

        account = result.get("account") or {}
        logger.info(
            "[手动添加] 完成: %s (plan=%s, status=%s)",
            account.get("email") or "?",
            account.get("plan_type") or "?",
            account.get("status") or "?",
        )
        return result
    finally:
        flow.stop()


def cmd_admin_login(email=None):
    """交互式完成管理员登录并保存到 state.json。"""
    email = (email or "").strip()
    if not email:
        email = input("管理员邮箱: ").strip()

    if not email:
        logger.error("[管理员登录] 邮箱不能为空")
        return None

    chatgpt = ChatGPTTeamAPI()

    try:
        logger.info("[管理员登录] 开始: %s", email)
        result = chatgpt.begin_admin_login(email)
        step = result.get("step")

        while True:
            if step == "completed":
                info = chatgpt.complete_admin_login()
                chatgpt.stop()
                logger.info("[管理员登录] 登录完成: %s", info.get("email") or email)
                if info.get("account_id"):
                    logger.info("[管理员登录] Workspace ID: %s", info["account_id"])
                if info.get("workspace_name"):
                    logger.info("[管理员登录] Workspace 名称: %s", info["workspace_name"])
                return info

            if step == "password_required":
                password = getpass.getpass("管理员密码（留空取消）: ")
                if not password:
                    logger.warning("[管理员登录] 已取消")
                    return None
                result = chatgpt.submit_admin_password(password)
                step = result.get("step")
                continue

            if step == "code_required":
                code = input("邮箱验证码（留空取消）: ").strip()
                if not code:
                    logger.warning("[管理员登录] 已取消")
                    return None
                result = chatgpt.submit_admin_code(code)
                step = result.get("step")
                continue

            if step == "workspace_required":
                options = chatgpt.list_workspace_options()
                if not options:
                    raise RuntimeError("当前需要选择组织，但未获取到可选项")

                logger.info("[管理员登录] 请选择要进入的 workspace:")
                for idx, option in enumerate(options, 1):
                    suffix = " [推荐]" if option.get("kind") == "preferred" else ""
                    logger.info("[管理员登录]   %d. %s%s", idx, option["label"], suffix)

                choice = input("选择序号（留空取消）: ").strip()
                if not choice:
                    logger.warning("[管理员登录] 已取消")
                    return None
                if not choice.isdigit():
                    raise RuntimeError(f"无效的序号: {choice}")

                selected_index = int(choice) - 1
                if selected_index < 0 or selected_index >= len(options):
                    raise RuntimeError(f"序号超出范围: {choice}")

                result = chatgpt.select_workspace_option(options[selected_index]["id"])
                step = result.get("step")
                continue

            detail = result.get("detail") or "无法识别管理员登录步骤"
            raise RuntimeError(detail)

    except KeyboardInterrupt:
        logger.warning("[管理员登录] 已中断")
        return None
    finally:
        chatgpt.stop()


def cmd_admin_session(email=None):
    """手动导入管理员 session_token 并保存到 state.json。"""
    email = (email or "").strip()
    if not email:
        email = input("管理员邮箱: ").strip()

    if not email:
        logger.error("[管理员登录] 邮箱不能为空")
        return None

    session_token = getpass.getpass("session_token（留空取消）: ").strip()
    if not session_token:
        logger.warning("[管理员登录] 已取消")
        return None

    chatgpt = ChatGPTTeamAPI()
    try:
        logger.info("[管理员登录] 开始导入 session_token: %s", email)
        info = chatgpt.import_admin_session(email, session_token)
        chatgpt.stop()
        logger.info("[管理员登录] session_token 导入完成: %s", info.get("email") or email)
        if info.get("account_id"):
            logger.info("[管理员登录] Workspace ID: %s", info["account_id"])
        if info.get("workspace_name"):
            logger.info("[管理员登录] Workspace 名称: %s", info["workspace_name"])
        return info
    finally:
        chatgpt.stop()


def cmd_main_codex_sync():
    """交互式同步主号 Codex 认证到已启用远端。"""
    state = get_admin_state_summary()
    if not state.get("session_present") or not state.get("email"):
        logger.error("[主号 Codex] 缺少管理员登录态，请先执行 admin-login")
        return None

    saved_auth_file = get_saved_main_auth_file()
    if saved_auth_file:
        sync_main_codex_to_cpa(saved_auth_file)
        logger.info("[主号 Codex] 已直接同步现有认证文件: %s", saved_auth_file)
        return {"auth_file": saved_auth_file}

    flow = MainCodexSyncFlow()
    try:
        logger.info("[主号 Codex] 开始同步: %s", state.get("email"))
        result = flow.start()
        step = result.get("step")

        while True:
            if step == "completed":
                info = flow.complete()
                logger.info("[主号 Codex] 同步完成: %s", info.get("email") or state.get("email"))
                if info.get("plan_type"):
                    logger.info("[主号 Codex] Plan: %s", info["plan_type"])
                if info.get("auth_file"):
                    logger.info("[主号 Codex] Auth 文件: %s", info["auth_file"])
                return info

            if step == "password_required":
                password = getpass.getpass("主号密码（留空取消）: ")
                if not password:
                    logger.warning("[主号 Codex] 已取消")
                    return None
                result = flow.submit_password(password)
                step = result.get("step")
                continue

            if step == "code_required":
                code = input("主号验证码（留空取消）: ").strip()
                if not code:
                    logger.warning("[主号 Codex] 已取消")
                    return None
                result = flow.submit_code(code)
                step = result.get("step")
                continue

            detail = result.get("detail") or "无法识别主号 Codex 登录步骤"
            raise RuntimeError(detail)
    except KeyboardInterrupt:
        logger.warning("[主号 Codex] 已中断")
        return None
    finally:
        flow.stop()


def get_team_member_count(chatgpt_api):
    """获取当前 Team 成员数"""
    account_id = get_chatgpt_account_id()
    if not account_id:
        logger.error("[Team] account_id 为空，无法查询成员数")
        return -1
    path = f"/backend-api/accounts/{account_id}/users"
    result = chatgpt_api._api_fetch("GET", path)
    if result["status"] != 200:
        logger.error("[Team] 获取成员列表失败: %d %s", result["status"], result["body"][:200])
        return -1
    data = json.loads(result["body"])
    members = data.get("items", data.get("users", data.get("members", [])))
    return len(members)


def cmd_fill(target=None, parallel_workers=None):
    """检测 Team 成员数，不足 target 则自动添加新账号补满"""
    from autoteam.config import FILL_BATCH_SIZE, MAX_TEAM_SEATS, TEAM_TARGET_SEATS

    configured_target = min(MAX_TEAM_SEATS, max(1, int(TEAM_TARGET_SEATS)))
    configured_batch = max(1, int(FILL_BATCH_SIZE))
    chatgpt = ChatGPTTeamAPI()
    chatgpt.start()
    mail_client = CloudMailClient()
    mail_client.login()
    reuse_mail_clients = {}

    def ensure_account_mail(acc):
        provider = get_account_mail_provider(acc)
        client = reuse_mail_clients.get(provider)
        if client is None:
            client = _get_account_mail_client(acc)
            client.login()
            reuse_mail_clients[provider] = client
        return client

    try:
        current = get_team_member_count(chatgpt)
        if current < 0:
            logger.error("[填充] 获取成员列表失败")
            return

        if target is None:
            target = min(configured_target, current + configured_batch)
            logger.info(
                "[填充] 当前 Team 成员数: %d，总目标: %d，本次最多新增: %d，本次目标: %d",
                current,
                configured_target,
                configured_batch,
                target,
            )
        else:
            target = min(configured_target, max(1, int(target)))
            logger.info("[填充] 当前 Team 成员数: %d，目标: %d", current, target)

        need = target - current
        if need <= 0:
            logger.info("[填充] 成员数已满足（%d >= %d），无需添加", current, target)
            return

        logger.info("[填充] 需要添加 %d 个账号，按每批最多 %d 个执行", need, configured_batch)
        standby_list = [
            a
            for a in get_standby_accounts()
            if a.get("_quota_recovered") and not _is_main_account_email(a.get("email"))
        ]
        standby_index = 0
        attempted = 0
        succeeded = 0
        failed = 0
        batch_index = 1
        batch_attempted = 0
        batch_succeeded = 0
        batch_failed = 0
        batch_reports = []
        worker_reports = []
        resolved_parallel_workers = _resolve_parallel_workers(parallel_workers)

        i = 0
        while i < need:
            logger.info("[填充] 添加第 %d/%d 个账号...", i + 1, need)
            before_count = current
            attempted += 1
            batch_attempted += 1

            # 优先复用 standby 中额度已恢复的旧账号
            added = False
            while standby_index < len(standby_list):
                reusable = standby_list[standby_index]
                standby_index += 1
                email = reusable["email"]
                skip_reason = _auto_reuse_skip_reason(reusable)
                if skip_reason:
                    logger.info("[填充] 跳过旧账号: %s（%s）", email, skip_reason)
                    continue
                logger.info("[填充] 复用旧账号: %s", email)
                # 确保 chatgpt 浏览器可用
                if not chatgpt.browser:
                    chatgpt.start()
                added = reinvite_account(chatgpt, ensure_account_mail(reusable), reusable)
                if added:
                    break
                logger.warning("[填充] 复用旧账号失败，尝试下一个旧账号: %s", email)

            if added:
                if not chatgpt.browser:
                    chatgpt.start()
                new_count = get_team_member_count(chatgpt)
                counted_success = True
                if new_count >= 0:
                    logger.info("[填充] 当前成员数: %d/%d", new_count, target)
                    counted_success = counted_success or new_count > before_count
                    current = new_count
                if counted_success:
                    succeeded += 1
                    batch_succeeded += 1
                    i += 1
                else:
                    failed += 1
                    batch_failed += 1

            if not added and i < need:
                # 创建新账号
                if resolved_parallel_workers <= 1:
                    logger.info("[填充] 创建新账号...")
                    if not chatgpt.browser:
                        chatgpt.start()
                    added = create_new_account(chatgpt, mail_client)
                    if not added:
                        logger.warning("[填充] 本轮补位失败，第 %d/%d 个空缺仍未填上", i + 1, need)
                    if not chatgpt.browser:
                        chatgpt.start()
                    new_count = get_team_member_count(chatgpt)
                    counted_success = bool(added)
                    if new_count >= 0:
                        logger.info("[填充] 当前成员数: %d/%d", new_count, target)
                        counted_success = counted_success or new_count > before_count
                        current = new_count
                    if counted_success:
                        succeeded += 1
                        batch_succeeded += 1
                    else:
                        failed += 1
                        batch_failed += 1
                    i += 1
                else:
                    remaining_new = need - i
                    batch_capacity = max(1, configured_batch - batch_attempted + 1)
                    create_target = min(remaining_new, batch_capacity)
                    logger.info("[填充] 并行创建新账号: 目标成功 %d", create_target)
                    if chatgpt and chatgpt.browser:
                        chatgpt.stop()
                    create_result = _create_new_accounts_parallel(
                        create_target, parallel_workers=resolved_parallel_workers
                    )
                    new_attempted = int(create_result.get("attempted") or 0)
                    new_succeeded = int(create_result.get("succeeded") or 0)
                    new_failed = int(create_result.get("failed") or 0)
                    attempted += max(0, new_attempted - 1)
                    batch_attempted += max(0, new_attempted - 1)
                    succeeded += new_succeeded
                    batch_succeeded += new_succeeded
                    failed += new_failed
                    batch_failed += new_failed
                    for report in create_result.get("worker_reports") or []:
                        worker_reports.append({"batch": batch_index, **report})
                    added = new_succeeded > 0
                    i += new_succeeded
                    if not chatgpt.browser:
                        chatgpt.start()
                    new_count = get_team_member_count(chatgpt)
                    if new_count >= 0:
                        logger.info("[填充] 当前成员数: %d/%d", new_count, target)
                        current = new_count
                    else:
                        current += new_succeeded
                    if not added:
                        logger.warning("[填充] 本批新账号创建未成功，停止继续补位")
                        break

            reached_target = current >= target
            reached_batch_end = batch_attempted >= configured_batch
            reached_plan_end = i >= need

            if reached_batch_end or reached_target or reached_plan_end:
                success_rate = (batch_succeeded / batch_attempted * 100) if batch_attempted else 0.0
                logger.info(
                    "[填充] 第 %d 批完成: 尝试 %d, 成功 %d, 失败 %d, 成功率 %.1f%%",
                    batch_index,
                    batch_attempted,
                    batch_succeeded,
                    batch_failed,
                    success_rate,
                )
                logger.info("[填充] 第 %d 批开始上传 CPA 认证文件...", batch_index)
                cpa_result = sync_to_cpa()
                logger.info("[填充] 第 %d 批 CPA 上传完成: %s", batch_index, cpa_result or {})
                batch_reports.append(
                    {
                        "batch": batch_index,
                        "attempted": batch_attempted,
                        "succeeded": batch_succeeded,
                        "failed": batch_failed,
                        "success_rate": round(success_rate, 2),
                        "cpa": cpa_result or {},
                    }
                )
                batch_index += 1
                batch_attempted = 0
                batch_succeeded = 0
                batch_failed = 0

            if reached_target:
                logger.info("[填充] 当前成员数已达到目标，停止继续添加")
                break

        total_rate = (succeeded / attempted * 100) if attempted else 0.0
        logger.info(
            "[填充] 填充完成: 尝试 %d, 成功 %d, 失败 %d, 成功率 %.1f%%",
            attempted,
            succeeded,
            failed,
            total_rate,
        )
        cmd_status()
        return {
            "target": target,
            "current": current,
            "attempted": attempted,
            "succeeded": succeeded,
            "failed": failed,
            "success_rate": round(total_rate, 2),
            "batches": batch_reports,
            "parallel_workers": resolved_parallel_workers,
            "worker_reports": worker_reports,
        }

    finally:
        if chatgpt.browser:
            chatgpt.stop()


def cmd_cleanup(max_seats=None):
    """清理多余的 Team 成员，只移除本地 accounts.json 中管理的账号"""
    account_id = get_chatgpt_account_id()
    accounts = load_accounts()
    local_emails = {a["email"].lower() for a in accounts if not _is_main_account_email(a.get("email"))}

    if not local_emails:
        logger.info("[清理] 本地无管理的账号，无需清理")
        return

    chatgpt = ChatGPTTeamAPI()
    chatgpt.start()

    try:
        # 获取当前成员列表
        path = f"/backend-api/accounts/{account_id}/users"
        result = chatgpt._api_fetch("GET", path)

        if result["status"] != 200:
            logger.error("[清理] 获取成员列表失败: %d", result["status"])
            return

        data = json.loads(result["body"])
        members = data.get("items", data.get("users", data.get("members", [])))

        total = len(members)
        logger.info("[清理] 当前 Team 成员数: %d", total)

        # 区分：本地管理的 vs 手动添加的
        local_members = []
        external_members = []
        for m in members:
            email = m.get("email", "").lower()
            if email in local_emails:
                local_members.append(m)
            else:
                external_members.append(m)

        logger.info("[清理] 手动添加的成员: %d", len(external_members))
        for m in external_members:
            logger.info("[清理]   %s (%s)", m.get("email"), m.get("role"))
        logger.info("[清理] 本地管理的成员: %d", len(local_members))
        for m in local_members:
            logger.info("[清理]   %s (%s)", m.get("email"), m.get("role"))

        # 确定要移除的数量
        if max_seats is None:
            from autoteam.config import MAX_TEAM_SEATS, TEAM_TARGET_SEATS

            max_seats = min(MAX_TEAM_SEATS, max(1, int(TEAM_TARGET_SEATS)))
            logger.info("[清理] 未指定上限，使用默认总人数: %d", max_seats)
        else:
            from autoteam.config import MAX_TEAM_SEATS

            max_seats = min(MAX_TEAM_SEATS, max(1, int(max_seats)))
        to_remove_count = total - max_seats
        if to_remove_count <= 0:
            logger.info("[清理] 成员数 %d 未超过上限 %d，无需清理", total, max_seats)
            return

        # 从本地管理的账号中选择要移除的（优先移除额度已用完的）
        removable = sorted(
            local_members,
            key=lambda m: (
                # 额度用完的优先移除
                0
                if find_account(accounts, m.get("email", ""))
                and find_account(accounts, m.get("email", "")).get("status") == STATUS_EXHAUSTED
                else 1,
                # 其次按创建时间，旧的优先
                find_account(accounts, m.get("email", "")).get("created_at", 0)
                if find_account(accounts, m.get("email", ""))
                else 0,
            ),
        )

        to_remove = removable[:to_remove_count]
        logger.info("[清理] 需要移除 %d 个本地账号:", len(to_remove))
        for m in to_remove:
            logger.info("[清理]   %s", m.get("email"))

        # 执行移除
        for m in to_remove:
            email = m.get("email", "")
            user_id = m.get("user_id") or m.get("id")

            delete_path = f"/backend-api/accounts/{account_id}/users/{user_id}"
            result = chatgpt._api_fetch("DELETE", delete_path)

            if result["status"] in (200, 204):
                logger.info("[清理] 已移除 %s", email)
                update_account(email, status=STATUS_STANDBY)
            else:
                logger.error("[清理] 移除 %s 失败: %d", email, result["status"])

        # 取消 pending invites 中本地管理的
        inv_result = chatgpt._api_fetch("GET", f"/backend-api/accounts/{account_id}/invites")
        if inv_result["status"] == 200:
            inv_data = json.loads(inv_result["body"])
            invites = (
                inv_data if isinstance(inv_data, list) else inv_data.get("invites", inv_data.get("account_invites", []))
            )
            for inv in invites:
                inv_email = inv.get("email_address", "").lower()
                inv_id = inv.get("id")
                if inv_email in local_emails and inv_id:
                    del_result = chatgpt._api_fetch("DELETE", f"/backend-api/accounts/{account_id}/invites/{inv_id}")
                    if del_result["status"] in (200, 204):
                        logger.info("[清理] 已取消邀请 %s", inv_email)

        logger.info("[清理] 清理完成")
        sync_to_cpa()

    finally:
        chatgpt.stop()


def cmd_pull_cpa():
    """从 CPA 反向同步认证文件到本地。"""
    result = sync_from_cpa()
    logger.info(
        "[CPA] 拉取完成: 新增文件 %d, 更新文件 %d, 新增账号 %d, 更新账号 %d, 跳过 %d",
        result.get("downloaded", 0),
        result.get("updated", 0),
        result.get("accounts_added", 0),
        result.get("accounts_updated", 0),
        result.get("skipped", 0),
    )
    return result


def cmd_check_deactivated_mail(
    keyword="deactivated",
    size=30,
    directory=None,
    apply=False,
    release_team=True,
    dispose_mailbox=True,
):
    """检查邮箱是否收到 deactivated 邮件。"""
    from autoteam.account_deactivation import check_deactivated_mail

    def _team_remover(email, _acc):
        return _run_with_chatgpt_session(lambda chatgpt: remove_from_team(chatgpt, email, return_status=True))

    if not apply:
        return check_deactivated_mail(
            keyword=keyword,
            size=size,
            directory=directory,
            apply=False,
            release_team=release_team,
            dispose_mailbox=dispose_mailbox,
        )

    return check_deactivated_mail(
        keyword=keyword,
        size=size,
        directory=directory,
        apply=True,
        release_team=release_team,
        dispose_mailbox=dispose_mailbox,
        team_remover=_team_remover if release_team else None,
    )


def main():
    import argparse

    parser = argparse.ArgumentParser(
        prog="manager.py",
        description="ChatGPT Team 账号轮转管理器",
    )
    sub = parser.add_subparsers(dest="command", help="可用命令")

    sub.add_parser("status", help="查看所有账号状态")
    sub.add_parser("check", help="检查活跃账号 Codex 额度")
    rotate_p = sub.add_parser("rotate", help="智能轮转（检查额度 → 移出 → 复用旧号 → 万不得已才创建新号）")
    rotate_p.add_argument("target", type=int, nargs="?", default=None, help="目标成员数（默认读取 TEAM_TARGET_SEATS）")
    sub.add_parser("add", help="手动添加一个新账号")
    sub.add_parser("manual-add", help="手动 OAuth 添加账号（打开链接登录后粘贴回调 URL）")
    admin_login_p = sub.add_parser("admin-login", help="交互式完成管理员主号登录")
    admin_login_p.add_argument("--email", help="管理员邮箱；不传则运行时交互输入")
    admin_session_p = sub.add_parser("admin-session", help="手动输入 session_token 导入管理员登录态")
    admin_session_p.add_argument("--email", help="管理员邮箱；不传则运行时交互输入")
    sub.add_parser("main-codex-sync", help="交互式同步主号 Codex 到已启用远端")

    fill_p = sub.add_parser("fill", help="补满 Team 成员到指定数量")
    fill_p.add_argument(
        "target",
        type=int,
        nargs="?",
        default=None,
        help="目标成员数（默认按 FILL_BATCH_SIZE 分批补到 TEAM_TARGET_SEATS）",
    )

    cleanup_p = sub.add_parser("cleanup", help="清理多余成员（只移除本地管理的）")
    cleanup_p.add_argument("max_seats", type=int, nargs="?", default=None, help="最大席位数")

    sub.add_parser("sync", help="手动同步认证文件到已启用远端")
    sub.add_parser("pull-cpa", help="从 CPA 反向同步认证文件到本地")
    mail_check_p = sub.add_parser("check-deactivated-mail", help="检查 deactivated 邮件并释放命中席位")
    mail_check_p.add_argument("--keyword", default="deactivated", help="邮件关键字")
    mail_check_p.add_argument("--size", type=int, default=30, help="每个邮箱检查的邮件数量")
    mail_check_p.add_argument("--directory", help="从失效 auth 目录读取邮箱列表")
    mail_check_p.add_argument("--apply", action="store_true", help="真正标记并释放席位")
    mail_check_p.add_argument("--no-release-team", action="store_true", help="只标记，不移出 Team")
    mail_check_p.add_argument("--no-dispose-mailbox", action="store_true", help="不处理邮箱提供者账号")

    api_p = sub.add_parser("api", help="启动 HTTP API 服务器")
    api_p.add_argument("--host", default="0.0.0.0", help="监听地址（默认 0.0.0.0）")
    api_p.add_argument("--port", type=int, default=8787, help="监听端口（默认 8787）")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    # 首次启动检查必填配置（api 命令在 start_server 里单独处理）
    if args.command not in ("api",):
        from autoteam.setup_wizard import check_and_setup

        check_and_setup(interactive=True)

    try:
        from autoteam.auth_storage import ensure_auth_file_permissions

        ensure_auth_file_permissions()
    except Exception:
        pass

    if args.command == "api":
        from autoteam.api import start_server

        start_server(host=args.host, port=args.port)
        return

    with outbound_proxy.task_proxy_context() as proxy_url:
        logger.info("[代理] 本次命令使用出口代理: %s", proxy_url or "direct")
        if args.command == "status":
            cmd_status()
        elif args.command == "check":
            cmd_check()
        elif args.command == "rotate":
            cmd_rotate(args.target)
        elif args.command == "add":
            cmd_add()
        elif args.command == "manual-add":
            cmd_manual_add()
        elif args.command == "admin-login":
            cmd_admin_login(args.email)
        elif args.command == "admin-session":
            cmd_admin_session(args.email)
        elif args.command == "main-codex-sync":
            cmd_main_codex_sync()
        elif args.command == "fill":
            cmd_fill(args.target)
        elif args.command == "cleanup":
            cmd_cleanup(args.max_seats)
        elif args.command == "sync":
            sync_to_cpa()
        elif args.command == "pull-cpa":
            cmd_pull_cpa()
        elif args.command == "check-deactivated-mail":
            cmd_check_deactivated_mail(
                keyword=args.keyword,
                size=args.size,
                directory=args.directory,
                apply=args.apply,
                release_team=not args.no_release_team,
                dispose_mailbox=not args.no_dispose_mailbox,
            )


if __name__ == "__main__":
    main()
