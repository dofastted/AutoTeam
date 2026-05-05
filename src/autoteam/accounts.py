"""账号池管理 - 持久化存储所有账号状态"""

import json
import threading
import time
from pathlib import Path

from autoteam.admin_state import get_admin_email
from autoteam.mail_provider import MAIL_PROVIDER_CLOUDMAIL, build_account_mail_fields, get_mail_provider_name
from autoteam.textio import read_text, write_text

PROJECT_ROOT = Path(__file__).parent.parent.parent
ACCOUNTS_FILE = PROJECT_ROOT / "accounts.json"
_ACCOUNTS_LOCK = threading.RLock()

# 账号状态
STATUS_ACTIVE = "active"  # 在 team 中，额度可用
STATUS_EXHAUSTED = "exhausted"  # 在 team 中，额度用完
STATUS_STANDBY = "standby"  # 已移出 team，等待额度恢复
STATUS_PENDING = "pending"  # 已邀请，等待注册完成
STATUS_UNAVAILABLE = "unavailable"  # 账号已不可用，例如 account_deactivated
STATUS_SOLD = "sold"  # 已售出，保留 Team 席位但停止同步和轮转

# 业务属性。不要复用 status，status 仍只表达 Team/生命周期。
USAGE_NORMAL = "normal"  # 普通轮转账号
USAGE_INVENTORY = "inventory"  # CPA 库存账号
USAGE_IN_USE = "in_use"  # 已分配使用
USAGE_SELF_USE = "self_use"  # 自用，本地保留，远端下架
USAGE_SOLD = "sold"  # 已售出，本地保留，远端下架
VALID_USAGE_STATUSES = {USAGE_NORMAL, USAGE_INVENTORY, USAGE_IN_USE, USAGE_SELF_USE, USAGE_SOLD}

# 注册与 CPA 阶段结果
REGISTRATION_STATUS_PENDING = "pending"
REGISTRATION_STATUS_SUCCESS = "success"
REGISTRATION_STATUS_FAILED = "failed"
CPA_STATUS_SUCCESS = "success"
CPA_STATUS_FAILED = "failed"
CPA_STATUS_PENDING = "pending"


def _normalized_email(value):
    return (value or "").strip().lower()


def _is_main_account_email(email):
    return bool(_normalized_email(email)) and _normalized_email(email) == _normalized_email(get_admin_email())


def _normalize_account_record(acc):
    if not isinstance(acc, dict):
        return acc
    usage_status = (acc.get("usage_status") or "").strip().lower()
    if usage_status not in VALID_USAGE_STATUSES:
        if acc.get("status") == STATUS_SOLD:
            usage_status = USAGE_SOLD
        elif acc.get("self_use_at"):
            usage_status = USAGE_SELF_USE
        else:
            usage_status = USAGE_NORMAL
    acc["usage_status"] = usage_status
    return acc


def load_accounts():
    """加载账号列表"""
    with _ACCOUNTS_LOCK:
        if ACCOUNTS_FILE.exists():
            text = read_text(ACCOUNTS_FILE).strip()
            if text:
                data = json.loads(text)
                if isinstance(data, list):
                    return [_normalize_account_record(acc) for acc in data]
                return data
        return []


def save_accounts(accounts):
    """保存账号列表"""
    with _ACCOUNTS_LOCK:
        write_text(ACCOUNTS_FILE, json.dumps(accounts, indent=2, ensure_ascii=False))


def migrate_legacy_auth_file_metadata(*, apply=False):
    """
    将旧账号记录中的 OAuth auth_file 元数据补写到 rt_auth_file。

    该迁移只修改 accounts.json 里的路径字段，不读取或改写 token 文件内容。
    ChatGPT session 备份文件不会被提升为可同步凭证。
    """
    from autoteam.codex_auth import (
        get_existing_session_auth_file,
        is_uploadable_oauth_rt_file,
        load_auth_file_data,
    )

    with _ACCOUNTS_LOCK:
        accounts = load_accounts()
        result = {
            "dry_run": not apply,
            "total": len(accounts),
            "changed": 0,
            "migrated": 0,
            "already_rt_auth_file": 0,
            "missing_auth_file": 0,
            "session_auth_file_not_promoted": 0,
            "invalid_auth_file": 0,
            "no_auth_file": 0,
            "invalid_rt_auth_file": 0,
            "accounts": [],
        }
        changed = False

        for acc in accounts:
            if not isinstance(acc, dict):
                continue
            email = acc.get("email") or ""
            rt_auth_file = str(acc.get("rt_auth_file") or "").strip()
            auth_file = str(acc.get("auth_file") or "").strip()

            if rt_auth_file:
                if is_uploadable_oauth_rt_file(rt_auth_file):
                    result["already_rt_auth_file"] += 1
                    result["accounts"].append(
                        {
                            "email": email,
                            "status": "already_rt_auth_file",
                            "rt_auth_file": rt_auth_file,
                        }
                    )
                    continue
                result["invalid_rt_auth_file"] += 1
                result["accounts"].append(
                    {
                        "email": email,
                        "status": "invalid_rt_auth_file",
                        "rt_auth_file": rt_auth_file,
                    }
                )
                continue

            if not auth_file:
                result["no_auth_file"] += 1
                result["accounts"].append({"email": email, "status": "no_auth_file"})
                continue

            auth_path = Path(auth_file)
            if not auth_path.exists() or not auth_path.is_file():
                result["missing_auth_file"] += 1
                result["accounts"].append(
                    {
                        "email": email,
                        "status": "missing_auth_file",
                        "auth_file": auth_file,
                    }
                )
                continue

            auth_data = load_auth_file_data(auth_path)
            session_auth_file = get_existing_session_auth_file(acc)
            if auth_data.get("credential_source") == "chatgpt_session" or session_auth_file == auth_file:
                result["session_auth_file_not_promoted"] += 1
                result["accounts"].append(
                    {
                        "email": email,
                        "status": "session_auth_file_not_promoted",
                        "auth_file": auth_file,
                    }
                )
                continue

            if not is_uploadable_oauth_rt_file(auth_path):
                result["invalid_auth_file"] += 1
                result["accounts"].append(
                    {
                        "email": email,
                        "status": "invalid_auth_file",
                        "auth_file": auth_file,
                    }
                )
                continue

            result["migrated"] += 1
            result["changed"] += 1
            result["accounts"].append(
                {
                    "email": email,
                    "status": "migrated",
                    "auth_file": auth_file,
                    "rt_auth_file": auth_file,
                }
            )
            if apply:
                acc["rt_auth_file"] = auth_file
                changed = True

        if apply and changed:
            save_accounts(accounts)

        return result


def find_account(accounts, email):
    """按邮箱查找账号"""
    for acc in accounts:
        if acc["email"] == email:
            return acc
    return None


def add_account(email, password, cloudmail_account_id=None, *, mail_provider=None, mail_account_id=None):
    """添加新账号"""
    with _ACCOUNTS_LOCK:
        accounts = load_accounts()
        if find_account(accounts, email):
            return  # 已存在

        if mail_account_id is None:
            mail_account_id = cloudmail_account_id
        if mail_provider:
            resolved_mail_provider = mail_provider
        elif cloudmail_account_id is not None:
            resolved_mail_provider = MAIL_PROVIDER_CLOUDMAIL
        elif mail_account_id is not None:
            resolved_mail_provider = get_mail_provider_name()
        else:
            resolved_mail_provider = ""
        mail_fields = (
            build_account_mail_fields(mail_account_id, provider=resolved_mail_provider)
            if mail_account_id is not None
            else {
                "mail_provider": resolved_mail_provider,
                "mail_account_id": None,
                "cloudmail_account_id": cloudmail_account_id,
            }
        )

        accounts.append(
            {
                "email": email,
                "password": password,
                **mail_fields,
                "status": STATUS_PENDING,
                "usage_status": USAGE_NORMAL,
                "auth_file": None,  # CPA 认证文件路径
                "quota_exhausted_at": None,  # 额度用完的时间
                "quota_resets_at": None,  # 额度恢复时间
                "created_at": time.time(),
                "last_active_at": None,
            }
        )
        save_accounts(accounts)


def update_account(email, **kwargs):
    """更新账号字段"""
    with _ACCOUNTS_LOCK:
        accounts = load_accounts()
        acc = find_account(accounts, email)
        if acc:
            acc.update(kwargs)
            save_accounts(accounts)
        return acc


def mark_account_usage_status(email, usage_status, **kwargs):
    """更新账号业务属性。sold/self_use 应走专用函数，因为需要远端下架记录。"""
    usage_status = (usage_status or "").strip().lower()
    if usage_status not in {USAGE_NORMAL, USAGE_INVENTORY, USAGE_IN_USE}:
        raise ValueError(f"不允许直接设置业务属性: {usage_status}")
    return update_account(email, usage_status=usage_status, **kwargs)


def mark_account_sold(email, *, remote_cleanup=None):
    """标记账号已售出，保留本地记录和 Team 席位。"""
    return update_account(
        email,
        status=STATUS_SOLD,
        usage_status=USAGE_SOLD,
        sync_disabled=True,
        sold_at=time.time(),
        sale_remote_cleanup=remote_cleanup or {},
    )


def mark_account_self_use(email, *, remote_cleanup=None):
    """标记账号为自用，保留本地记录和 Team 席位，但停止远端同步。"""
    return update_account(
        email,
        usage_status=USAGE_SELF_USE,
        sync_disabled=True,
        self_use_at=time.time(),
        self_use_remote_cleanup=remote_cleanup or {},
    )


def get_active_accounts():
    """获取所有活跃账号"""
    return [a for a in load_accounts() if a["status"] == STATUS_ACTIVE and not _is_main_account_email(a.get("email"))]


def get_standby_accounts():
    """获取所有待命账号（已移出 team，可能额度已恢复）"""
    accounts = load_accounts()
    now = time.time()
    standby = []
    for a in accounts:
        if _is_main_account_email(a.get("email")):
            continue
        if a["status"] == STATUS_STANDBY:
            resets_at = a.get("quota_resets_at")
            if resets_at is None:
                # 没有恢复时间 = 不是因为额度用完被移出的，随时可复用
                a["_quota_recovered"] = True
            else:
                # 有恢复时间，看是否已过
                a["_quota_recovered"] = now >= resets_at
            standby.append(a)
    # 已恢复的排前面
    standby.sort(key=lambda x: (not x.get("_quota_recovered", False), x.get("quota_exhausted_at") or 0))
    return standby


def get_next_reusable_account():
    """获取下一个可重用的 standby 账号（优先额度已恢复的）"""
    standby = get_standby_accounts()
    if standby:
        return standby[0]
    return None
