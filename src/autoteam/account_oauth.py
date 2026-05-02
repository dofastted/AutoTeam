"""Shared account OAuth login flow."""

from __future__ import annotations

import time

import autoteam.accounts as accounts
import autoteam.codex_auth as codex_auth
import autoteam.mail_provider as mail_provider
from autoteam import protocol_oauth
from autoteam.auth_archive import archive_account_auth_file
from autoteam.exceptions import PhoneVerificationRequiredError


def run_account_oauth_login(
    email: str,
    *,
    account: dict | None = None,
    mail_client=None,
    mail_account_id=None,
    check_quota_snapshot: bool = True,
) -> dict:
    """Run the same account OAuth login used by the project API."""
    email = (email or "").strip().lower()
    latest = account or accounts.find_account(accounts.load_accounts(), email)
    if not latest:
        raise RuntimeError(f"账号不存在: {email}")

    if mail_client is None:
        mail_client = mail_provider.get_mail_client_for_account(latest)
        mail_client.login()
    if mail_account_id is None:
        mail_account_id = mail_provider.get_account_mail_account_id(latest)

    previous_session_auth_file = codex_auth.get_existing_session_auth_file(latest)
    reusable_session = {}
    if previous_session_auth_file:
        reusable_session = codex_auth.load_auth_file_data(previous_session_auth_file)

    try:
        protocol_result = protocol_oauth.run_protocol_oauth_login(
            email,
            latest.get("password", ""),
            mail_client=mail_client,
            mail_account_id=mail_account_id,
            reusable_session=reusable_session,
        )
    except protocol_oauth.ProtocolOauthAccountDeactivated as exc:
        accounts.update_account(
            email,
            status=accounts.STATUS_UNAVAILABLE,
            sync_disabled=True,
            unavailable_reason="account_deactivated",
            unavailable_at=time.time(),
        )
        raise RuntimeError(f"{email} 已返回 account_deactivated，已标记不可用") from exc
    except protocol_oauth.ProtocolOauthNoValidOrganizations as exc:
        raise RuntimeError(f"Codex 协议认证失败: {email} 未进入有效组织，请检查注册后的组织/workspace 步骤") from exc
    except protocol_oauth.ProtocolOauthAddPhoneRequired as exc:
        raise PhoneVerificationRequiredError(f"OpenAI 风控要求手机号: {email}", email=email) from exc
    except PhoneVerificationRequiredError:
        raise
    except protocol_oauth.ProtocolOauthRateLimited as exc:
        raise RuntimeError(f"Codex 协议认证失败: {email} 临时限流: {exc}") from exc
    except protocol_oauth.ProtocolOauthOtpTimeout as exc:
        raise RuntimeError(f"Codex 协议认证失败: {email} 邮箱 OTP 超时") from exc
    except protocol_oauth.ProtocolOauthTokenExchangeError as exc:
        raise RuntimeError(f"Codex 协议认证失败: {email} token 交换失败: {exc}") from exc
    except protocol_oauth.ProtocolOauthError as exc:
        raise RuntimeError(f"Codex 协议认证失败: {email}: {exc}") from exc

    bundle = protocol_result.bundle

    auth_file = codex_auth.save_auth_file(bundle, source="oauth")
    archive_path = archive_account_auth_file(email, auth_file)
    plan_type = (bundle.get("plan_type") or "unknown").strip().lower()

    update_fields = {
        "auth_file": auth_file,
        "rt_auth_file": auth_file,
        "rt_obtained_at": time.time(),
        "plan_type": plan_type,
        "cpa_archive_file": archive_path,
    }
    if previous_session_auth_file:
        update_fields["session_auth_file"] = previous_session_auth_file
    accounts.update_account(email, **update_fields)

    token = bundle.get("access_token")
    account_id = bundle.get("account_id")
    if plan_type == "team":
        accounts.update_account(email, status=accounts.STATUS_ACTIVE, last_active_at=time.time())
        if check_quota_snapshot and token:
            st, info = codex_auth.check_codex_quota(token, account_id=account_id)
            if st == "ok" and isinstance(info, dict):
                accounts.update_account(email, last_quota=info)
            elif st == "exhausted":
                quota_info = codex_auth.quota_result_quota_info(info)
                if quota_info:
                    accounts.update_account(email, last_quota=quota_info)
                accounts.update_account(
                    email,
                    status=accounts.STATUS_EXHAUSTED,
                    quota_exhausted_at=time.time(),
                    quota_resets_at=codex_auth.quota_result_resets_at(info) or int(time.time() + 18000),
                )
            elif st == "account_deactivated":
                accounts.update_account(
                    email,
                    status=accounts.STATUS_UNAVAILABLE,
                    sync_disabled=True,
                    unavailable_reason="account_deactivated",
                    unavailable_at=time.time(),
                )
                raise RuntimeError(f"{email} 已返回 account_deactivated，已标记不可用")
    elif plan_type not in {"team", "unknown"}:
        accounts.update_account(email, status=accounts.STATUS_STANDBY)

    return {
        "email": email,
        "plan": plan_type,
        "plan_type": plan_type,
        "auth_file": auth_file,
        "rt_auth_file": auth_file,
        "cpa_archive_file": archive_path,
        "bundle": bundle,
    }
