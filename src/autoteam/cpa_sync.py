"""CPA (CLIProxyAPI) 认证文件同步 - 保持本地 codex 认证文件与 CPA 一致"""

import base64
import json
import logging
import tempfile
import time
from datetime import datetime
from hashlib import md5
from pathlib import Path

from autoteam import outbound_proxy
from autoteam.auth_storage import AUTH_DIR, ensure_auth_dir, ensure_auth_file_permissions
from autoteam.codex_auth import CODEX_CLIENT_ID, CODEX_TOKEN_URL, select_oauth_rt_auth_file
from autoteam.config import CPA_KEY, CPA_URL
from autoteam.textio import read_text, write_text

logger = logging.getLogger(__name__)


def _headers():
    return {"Authorization": f"Bearer {CPA_KEY}"}


def list_cpa_files():
    """获取 CPA 中所有认证文件"""
    resp = outbound_proxy.request("GET", f"{CPA_URL}/v0/management/auth-files", headers=_headers(), timeout=10)
    if resp.status_code != 200:
        logger.error("[CPA] 获取文件列表失败: %d", resp.status_code)
        return []
    data = resp.json()
    return data.get("files", [])


def upload_to_cpa(filepath):
    """上传认证文件到 CPA"""
    filepath = Path(filepath)
    if not filepath.exists():
        logger.warning("[CPA] 文件不存在: %s", filepath)
        return False

    with open(filepath, "rb") as f:
        resp = outbound_proxy.request(
            "POST",
            f"{CPA_URL}/v0/management/auth-files",
            headers=_headers(),
            files={"file": (filepath.name, f, "application/json")},
            timeout=10,
        )

    if resp.status_code == 200:
        logger.info("[CPA] 已上传: %s", filepath.name)
        return True
    else:
        logger.error("[CPA] 上传失败: %d %s", resp.status_code, resp.text[:200])
        return False


def delete_from_cpa(name):
    """从 CPA 删除认证文件"""
    resp = outbound_proxy.request(
        "DELETE",
        f"{CPA_URL}/v0/management/auth-files",
        headers=_headers(),
        params={"name": name},
        timeout=10,
    )
    if resp.status_code == 200:
        logger.info("[CPA] 已删除: %s", name)
        return True
    else:
        logger.error("[CPA] 删除失败: %d %s", resp.status_code, resp.text[:200])
        return False


def refresh_cpa_auth_file(name):
    """让 CPA 刷新单个 Codex auth 文件。"""
    resp = outbound_proxy.request(
        "POST",
        f"{CPA_URL}/v0/management/auth-files/codex/refresh",
        headers={**_headers(), "Content-Type": "application/json"},
        json={"name": name},
        timeout=30,
    )
    if resp.status_code == 200:
        return resp.json()
    logger.error("[CPA] 刷新失败: %s -> %d %s", name, resp.status_code, resp.text[:200])
    raise RuntimeError(f"CPA 刷新失败: {resp.status_code} {resp.text[:200]}")


def delete_http401_from_cpa():
    """删除 CPA 中已记录为 HTTP 401 的认证文件。"""
    resp = outbound_proxy.request(
        "DELETE",
        f"{CPA_URL}/v0/management/auth-files/401",
        headers=_headers(),
        timeout=30,
    )
    if resp.status_code != 200:
        logger.error("[CPA] 清理 401 失败: %d %s", resp.status_code, resp.text[:200])
        raise RuntimeError(f"CPA 清理 401 失败: {resp.status_code} {resp.text[:200]}")
    result = resp.json()
    _mark_http401_accounts_unavailable(result)
    return result


def _refresh_token_response(refresh_token):
    return outbound_proxy.request(
        "POST",
        CODEX_TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "client_id": CODEX_CLIENT_ID,
            "refresh_token": refresh_token,
            "scope": "openid email profile offline_access",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )


def _is_refresh_token_unauthorized(resp):
    text = (getattr(resp, "text", "") or "").lower()
    if getattr(resp, "status_code", 0) == 401:
        return True
    return "refresh_token_reused" in text or "token_invalidated" in text or "token_revoked" in text


def cleanup_invalid_cpa_refresh_tokens():
    """直接刷新 CPA OAuth RT 文件，删除明确 401/复用失效的远端文件。"""
    files = list_cpa_files()
    checked = 0
    refreshed = 0
    skipped = 0
    deleted = []
    failed = []
    for item in files:
        name = item.get("name") or ""
        if not name:
            skipped += 1
            continue
        content = download_from_cpa(name)
        if not content:
            failed.append({"name": name, "error": "download_failed"})
            continue
        try:
            auth_data = json.loads(content)
        except Exception as exc:
            failed.append({"name": name, "error": f"json_error: {exc}"})
            continue
        refresh_token = (auth_data.get("refresh_token") or "").strip()
        if not refresh_token or auth_data.get("credential_source") == "chatgpt_session":
            skipped += 1
            continue

        checked += 1
        email = item.get("email") or auth_data.get("email") or ""
        try:
            resp = _refresh_token_response(refresh_token)
        except Exception as exc:
            failed.append({"name": name, "email": email, "error": str(exc)})
            continue
        if resp.status_code == 200:
            try:
                token_data = resp.json()
            except Exception as exc:
                failed.append({"name": name, "email": email, "error": f"refresh_json_error: {exc}"})
                continue
            auth_data["access_token"] = token_data.get("access_token") or auth_data.get("access_token") or ""
            auth_data["refresh_token"] = token_data.get("refresh_token") or refresh_token
            auth_data["id_token"] = token_data.get("id_token") or auth_data.get("id_token") or ""
            auth_data["expired"] = time.strftime(
                "%Y-%m-%dT%H:%M:%SZ",
                time.gmtime(time.time() + float(token_data.get("expires_in") or 3600)),
            )
            auth_data["last_refresh"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            with tempfile.TemporaryDirectory(prefix="autoteam-cpa-refresh-") as tmpdir:
                tmp_path = Path(tmpdir) / name
                write_text(tmp_path, json.dumps(auth_data, indent=2))
                if not upload_to_cpa(tmp_path):
                    failed.append({"name": name, "email": email, "error": "upload_refreshed_failed"})
                    continue
            refreshed += 1
            continue
        if _is_refresh_token_unauthorized(resp):
            if delete_from_cpa(name):
                deleted.append({"name": name, "email": email, "status_code": resp.status_code})
            else:
                failed.append({"name": name, "email": email, "error": "delete_failed"})
            continue
        failed.append(
            {
                "name": name,
                "email": email,
                "status_code": resp.status_code,
                "error": (resp.text or "")[:200],
            }
        )

    result = {
        "status": "ok" if not failed else "partial",
        "checked": checked,
        "refreshed": refreshed,
        "skipped": skipped,
        "deleted": len(deleted),
        "files": [item["name"] for item in deleted],
        "accounts": deleted,
        "failed": failed,
        "total": len(files),
    }
    _mark_http401_accounts_unavailable(result)
    return result


def download_from_cpa(name):
    """从 CPA 下载认证文件内容。"""
    resp = outbound_proxy.request(
        "GET",
        f"{CPA_URL}/v0/management/auth-files/download",
        headers=_headers(),
        params={"name": name},
        timeout=10,
    )
    if resp.status_code == 200:
        return resp.text
    logger.error("[CPA] 下载失败: %s -> %d %s", name, resp.status_code, resp.text[:200])
    return None


def _parse_expired_timestamp(value):
    if isinstance(value, (int, float)):
        return float(value)
    if not value:
        return time.time() + 3600
    text = str(value).strip()
    try:
        if text.endswith("Z"):
            return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
        return datetime.fromisoformat(text).timestamp()
    except Exception:
        return time.time() + 3600


def _parse_optional_timestamp(value):
    if isinstance(value, (int, float)):
        return float(value)
    if not value:
        return 0.0
    text = str(value).strip()
    try:
        if text.endswith("Z"):
            return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
        return datetime.fromisoformat(text).timestamp()
    except Exception:
        return 0.0


def _parse_jwt_payload(token):
    parts = token.split(".")
    if len(parts) < 2:
        return {}
    payload = parts[1]
    payload += "=" * (-len(payload) % 4)
    try:
        return json.loads(base64.urlsafe_b64decode(payload))
    except Exception:
        return {}


def _bundle_from_auth_data(auth_data, fallback_name=""):
    id_token = auth_data.get("id_token", "")
    claims = _parse_jwt_payload(id_token) if id_token else {}
    auth_claims = claims.get("https://api.openai.com/auth", {}) if isinstance(claims, dict) else {}

    plan_type = auth_claims.get("chatgpt_plan_type", "")
    if not plan_type and "-team" in fallback_name:
        plan_type = "team"
    if not plan_type and "-plus" in fallback_name:
        plan_type = "plus"
    if not plan_type and "-free" in fallback_name:
        plan_type = "free"
    if not plan_type:
        plan_type = "unknown"

    return {
        "id_token": id_token,
        "access_token": auth_data.get("access_token", ""),
        "refresh_token": auth_data.get("refresh_token", ""),
        "account_id": auth_data.get("account_id", ""),
        "email": auth_data.get("email", ""),
        "plan_type": plan_type,
        "expired": _parse_expired_timestamp(auth_data.get("expired")),
        "last_refresh_ts": _parse_optional_timestamp(auth_data.get("last_refresh")),
        "session_token": auth_data.get("session_token", ""),
        "credential_source": auth_data.get("credential_source", ""),
    }


def _normalized_auth_path(bundle, main=False):
    email = bundle.get("email", "")
    account_id = bundle.get("account_id", "")
    if main:
        suffix = account_id or md5(email.encode()).hexdigest()[:8]
        return AUTH_DIR / f"codex-main-{suffix}.json"
    plan_type = bundle.get("plan_type", "unknown")
    hash_id = md5(account_id.encode()).hexdigest()[:8] if account_id else "unknown"
    source = "session" if bundle.get("credential_source") == "chatgpt_session" else "oauth" if bundle.get("refresh_token") else "auth"
    return AUTH_DIR / f"codex-{email}-{plan_type}-{hash_id}-{source}.json"


def _auth_identity(bundle, main=False):
    if main:
        return ("main", bundle.get("account_id") or bundle.get("email") or "")
    source = bundle.get("credential_source") or ""
    if not source:
        source = "oauth" if bundle.get("refresh_token") else "auth"
    return ("codex", (bundle.get("email") or "").lower(), bundle.get("account_id") or "", source)


def _candidate_score(auth_data, bundle, name, main=False):
    canonical_name = _normalized_auth_path(bundle, main=main).name
    return (
        1 if name == canonical_name else 0,
        bundle.get("last_refresh_ts", _parse_optional_timestamp(auth_data.get("last_refresh"))),
        _parse_expired_timestamp(auth_data.get("expired")),
        len(auth_data.get("refresh_token") or ""),
    )


def _write_auth_file(filepath, bundle):
    ensure_auth_dir()
    auth_data = {
        "type": "codex",
        "id_token": bundle.get("id_token", ""),
        "access_token": bundle.get("access_token", ""),
        "refresh_token": bundle.get("refresh_token", ""),
        "account_id": bundle.get("account_id", ""),
        "email": bundle.get("email", ""),
        "expired": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(bundle.get("expired", 0))),
        "last_refresh": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(bundle.get("last_refresh_ts", time.time()))),
    }
    if bundle.get("session_token"):
        auth_data["session_token"] = bundle.get("session_token", "")
    if bundle.get("credential_source"):
        auth_data["credential_source"] = bundle.get("credential_source", "")
    write_text(filepath, json.dumps(auth_data, indent=2))
    ensure_auth_file_permissions(filepath)
    return filepath


def _save_normalized_auth_file(bundle, main=False):
    filepath = _normalized_auth_path(bundle, main=main)

    if main:
        for old in AUTH_DIR.glob("codex-main-*.json"):
            if old != filepath and old.exists():
                old.unlink()
    else:
        email = bundle.get("email", "")
        for old in AUTH_DIR.glob(f"codex-{email}-*.json"):
            old_source = "session" if old.stem.endswith("-session") else "oauth" if old.stem.endswith("-oauth") else "auth"
            target_source = "session" if filepath.stem.endswith("-session") else "oauth" if filepath.stem.endswith("-oauth") else "auth"
            if old_source == target_source and old != filepath and old.exists():
                old.unlink()

    return _write_auth_file(filepath, bundle)


def _load_local_best_candidate(identity_key):
    """读取本地同 identity 的最佳候选认证文件。"""
    best = None
    for path in AUTH_DIR.glob("codex-*.json"):
        if not path.is_file():
            continue
        try:
            auth_data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if auth_data.get("type") != "codex":
            continue
        main = path.name.startswith("codex-main-")
        bundle = _bundle_from_auth_data(auth_data, fallback_name=path.name)
        if _auth_identity(bundle, main=main) != identity_key:
            continue
        candidate = {
            "path": path,
            "auth_data": auth_data,
            "bundle": bundle,
            "main": main,
        }
        if best is None or _candidate_score(
            candidate["auth_data"], candidate["bundle"], candidate["path"].name, candidate["main"]
        ) > _candidate_score(best["auth_data"], best["bundle"], best["path"].name, best["main"]):
            best = candidate
    return best


def _load_auth_data_from_path(path):
    try:
        return json.loads(read_text(Path(path)))
    except Exception:
        return {}


def _is_cpa_uploadable_auth_path(path):
    auth_data = _load_auth_data_from_path(path)
    if not auth_data:
        return False
    if auth_data.get("credential_source") == "chatgpt_session":
        return False
    return bool(auth_data.get("refresh_token") and auth_data.get("access_token"))


def _account_auth_path_for_cpa(acc):
    auth_path = select_oauth_rt_auth_file(acc)
    if auth_path:
        path = Path(auth_path)
        if path.exists() and _is_cpa_uploadable_auth_path(path):
            return path
    return None


def _cleanup_local_duplicates(accounts=None):
    """清理本地同账号重复认证文件，只保留一个规范文件。"""
    grouped = {}
    for path in AUTH_DIR.glob("codex-*.json"):
        if not path.is_file():
            continue
        try:
            auth_data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if auth_data.get("type") != "codex":
            continue
        main = path.name.startswith("codex-main-")
        bundle = _bundle_from_auth_data(auth_data, fallback_name=path.name)
        key = _auth_identity(bundle, main=main)
        grouped.setdefault(key, []).append(
            {
                "path": path,
                "auth_data": auth_data,
                "bundle": bundle,
                "main": main,
            }
        )

    canonical_map = {}
    removed = 0
    for items in grouped.values():
        if not items:
            continue
        winner = max(
            items, key=lambda item: _candidate_score(item["auth_data"], item["bundle"], item["path"].name, item["main"])
        )
        canonical_path = Path(_save_normalized_auth_file(winner["bundle"], main=winner["main"]))
        canonical_map[_auth_identity(winner["bundle"], main=winner["main"])] = canonical_path
        for item in items:
            if item["path"] != canonical_path and item["path"].exists():
                item["path"].unlink()
                removed += 1

    if accounts is not None:
        changed = False
        for acc in accounts:
            auth_path = acc.get("auth_file")
            if not auth_path:
                continue
            try:
                path = Path(auth_path)
                if not path.exists():
                    continue
                auth_data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            bundle = _bundle_from_auth_data(auth_data, fallback_name=path.name)
            canonical_path = canonical_map.get(_auth_identity(bundle, main=False))
            if canonical_path and acc.get("auth_file") != str(canonical_path.resolve()):
                acc["auth_file"] = str(canonical_path.resolve())
                changed = True
        return removed, changed

    return removed, False


def sync_from_cpa():
    """
    从 CPA 反向同步认证文件到本地。

    规则：
    - 下载 CPA 中所有 codex 认证文件到本地 auths/
    - 非主号文件会导入/修复到 accounts.json，默认状态为 standby（保守导入）
    - 不删除本地账号记录，仅补充/更新 auth_file
    """
    from autoteam.accounts import STATUS_STANDBY, find_account, load_accounts, save_accounts

    AUTH_DIR.mkdir(exist_ok=True)

    accounts = load_accounts()
    changed_accounts = False
    imported_files = 0
    updated_files = 0
    added_accounts = 0
    updated_accounts = 0
    skipped = 0
    cpa_duplicates_deleted = 0
    local_kept_newer = 0

    local_duplicates_deleted, accounts_path_repaired = _cleanup_local_duplicates(accounts)
    if accounts_path_repaired:
        save_accounts(accounts)

    cpa_files = list_cpa_files()
    if not cpa_files:
        logger.info("[CPA] 未发现可反向同步的认证文件")
        return {
            "downloaded": 0,
            "updated": 0,
            "accounts_added": 0,
            "accounts_updated": 0,
            "skipped": 0,
            "cpa_duplicates_deleted": 0,
            "local_duplicates_deleted": local_duplicates_deleted,
            "local_kept_newer": 0,
            "total": 0,
        }

    candidates = []
    for item in cpa_files:
        name = (item.get("name") or "").strip()
        if not name or not name.endswith(".json") or not name.startswith("codex-"):
            skipped += 1
            continue

        content = download_from_cpa(name)
        if not content:
            skipped += 1
            continue

        try:
            auth_data = json.loads(content)
        except Exception:
            logger.warning("[CPA] 跳过无效 JSON: %s", name)
            skipped += 1
            continue

        if auth_data.get("type") != "codex":
            logger.info("[CPA] 跳过非 codex 文件: %s", name)
            skipped += 1
            continue

        bundle = _bundle_from_auth_data(auth_data, fallback_name=name)
        email = (bundle.get("email") or item.get("email") or "").lower().strip()
        bundle["email"] = email

        if not email and not name.startswith("codex-main-"):
            logger.info("[CPA] 跳过缺少邮箱的文件: %s", name)
            continue

        candidates.append(
            {
                "name": name,
                "auth_data": auth_data,
                "bundle": bundle,
                "main": name.startswith("codex-main-"),
            }
        )

    grouped = {}
    for item in candidates:
        grouped.setdefault(_auth_identity(item["bundle"], main=item["main"]), []).append(item)

    for items in grouped.values():
        winner = max(
            items,
            key=lambda item: _candidate_score(item["auth_data"], item["bundle"], item["name"], main=item["main"]),
        )
        for item in items:
            if item is winner:
                continue
            if delete_from_cpa(item["name"]):
                cpa_duplicates_deleted += 1

        name = winner["name"]
        bundle = winner["bundle"]
        email = bundle.get("email", "")
        identity_key = _auth_identity(bundle, main=winner["main"])
        local_best = _load_local_best_candidate(identity_key)
        cpa_score = _candidate_score(winner["auth_data"], bundle, name, main=winner["main"])
        local_score = None
        if local_best:
            local_score = _candidate_score(
                local_best["auth_data"], local_best["bundle"], local_best["path"].name, main=local_best["main"]
            )

        if winner["main"]:
            if local_best and local_score >= cpa_score:
                local_kept_newer += 1
                normalized_path = local_best["path"]
            else:
                normalized_path = _normalized_auth_path(bundle, main=True)
                existed = normalized_path.exists()
                previous = None
                if existed:
                    try:
                        previous = normalized_path.read_text(encoding="utf-8")
                    except Exception:
                        previous = None

                normalized_path = Path(_save_normalized_auth_file(bundle, main=True))
                current = normalized_path.read_text(encoding="utf-8")
                if not existed:
                    imported_files += 1
                elif previous != current:
                    updated_files += 1
            if normalized_path.name != name:
                old_path = AUTH_DIR / name
                if old_path.exists() and old_path != normalized_path:
                    old_path.unlink()
            continue

        if local_best and local_score >= cpa_score:
            local_kept_newer += 1
            normalized_path = local_best["path"]
        else:
            normalized_path = _normalized_auth_path(bundle)
            existed = normalized_path.exists()
            previous = None
            if existed:
                try:
                    previous = normalized_path.read_text(encoding="utf-8")
                except Exception:
                    previous = None

            normalized_path = Path(_save_normalized_auth_file(bundle))
            current = normalized_path.read_text(encoding="utf-8")

            if not existed:
                imported_files += 1
            elif previous != current:
                updated_files += 1

        acc = find_account(accounts, email)
        resolved_path = str(normalized_path.resolve())
        if acc:
            if acc.get("auth_file") != resolved_path:
                acc["auth_file"] = resolved_path
                changed_accounts = True
                updated_accounts += 1
        else:
            accounts.append(
                {
                    "email": email,
                    "password": "",
                    "mail_provider": "",
                    "mail_account_id": None,
                    "cloudmail_account_id": None,
                    "status": STATUS_STANDBY,
                    "auth_file": resolved_path,
                    "quota_exhausted_at": None,
                    "quota_resets_at": None,
                    "created_at": time.time(),
                    "last_active_at": None,
                }
            )
            changed_accounts = True
            added_accounts += 1

    if changed_accounts:
        save_accounts(accounts)

    local_duplicates_deleted_after, accounts_path_repaired = _cleanup_local_duplicates(accounts)
    local_duplicates_deleted += local_duplicates_deleted_after
    if accounts_path_repaired:
        save_accounts(accounts)

    logger.info(
        "[CPA] 反向同步完成: 新增文件 %d, 更新文件 %d, 新增账号 %d, 更新账号 %d, 保留本地较新 %d, CPA去重 %d, 本地去重 %d, 跳过 %d",
        imported_files,
        updated_files,
        added_accounts,
        updated_accounts,
        local_kept_newer,
        cpa_duplicates_deleted,
        local_duplicates_deleted,
        skipped,
    )
    return {
        "downloaded": imported_files,
        "updated": updated_files,
        "accounts_added": added_accounts,
        "accounts_updated": updated_accounts,
        "skipped": skipped,
        "local_kept_newer": local_kept_newer,
        "cpa_duplicates_deleted": cpa_duplicates_deleted,
        "local_duplicates_deleted": local_duplicates_deleted,
        "total": len(cpa_files),
    }


def sync_to_cpa():
    """
    上传本地已完成的 OAuth RT 认证文件到 CPA。

    普通同步不启动浏览器、不补 OAuth、不上传 ChatGPT session 备份，也不删除远端文件。
    """
    from autoteam.accounts import STATUS_ACTIVE, load_accounts, save_accounts

    accounts = load_accounts()
    local_emails = {a["email"].lower() for a in accounts}
    local_duplicates_deleted, accounts_path_repaired = _cleanup_local_duplicates(accounts)
    if accounts_path_repaired:
        save_accounts(accounts)

    active_files: dict[str, tuple[dict, Path]] = {}
    skipped_accounts = []
    for acc in accounts:
        if acc["status"] != STATUS_ACTIVE or acc.get("sync_disabled"):
            continue
        email = (acc.get("email") or "").strip().lower()
        auth_path = select_oauth_rt_auth_file(acc)
        if not auth_path:
            reason = "session_file_not_uploadable" if acc.get("session_auth_file") else "missing_oauth_rt_file"
            skipped_accounts.append({"email": email, "reason": reason})
            continue
        path = Path(auth_path)
        active_files[path.name] = (acc, path)

    cpa_files = list_cpa_files()
    cpa_names = {f["name"]: f for f in cpa_files}
    cpa_emails = {(f.get("email") or "").strip().lower() for f in cpa_files if f.get("email")}

    logger.info("[CPA] active 认证文件: %d, CPA 认证文件: %d", len(active_files), len(cpa_files))

    uploaded = 0
    skipped_existing = 0
    changed = False
    for name, (acc, path) in active_files.items():
        email = (acc.get("email") or "").strip().lower()
        if name in cpa_names or email in cpa_emails:
            skipped_existing += 1
            continue
        logger.info("[CPA] 上传: %s", name)
        if upload_to_cpa(path):
            uploaded += 1
            acc["cpa_uploaded_at"] = time.time()
            changed = True

    if changed:
        save_accounts(accounts)

    final_remote_count = len(cpa_files) + uploaded
    final_local_managed = [
        f for f in cpa_files if (f.get("email") or "").strip().lower() in local_emails
    ]
    logger.info(
        "[CPA] 同步完成: 上传 %d, 远端已有跳过 %d, 无 RT 跳过 %d, 本地去重 %d",
        uploaded,
        skipped_existing,
        len(skipped_accounts),
        local_duplicates_deleted,
    )
    return {
        "uploaded": uploaded,
        "deleted": 0,
        "skipped_existing": skipped_existing,
        "skipped": len(skipped_accounts),
        "skipped_accounts": skipped_accounts,
        "local_duplicates_deleted": local_duplicates_deleted,
        "local_active": len(active_files),
        "cpa_local_managed": len(final_local_managed),
        "cpa_remote_total": final_remote_count,
    }


def _cpa_file_identity(item):
    email = (item.get("email") or "").strip().lower()
    name = item.get("name") or ""
    return email, name


def maintain_cpa_inventory(target=100):
    """保证 CPA 云端至少有 target 个本地库存 RT 文件可用。"""
    from autoteam.accounts import (
        CPA_STATUS_SUCCESS,
        USAGE_INVENTORY,
        load_accounts,
        save_accounts,
    )

    target = max(0, int(target or 0))
    accounts = load_accounts()
    candidates = []
    for acc in accounts:
        if (acc.get("usage_status") or "").strip().lower() != USAGE_INVENTORY:
            continue
        if (acc.get("cpa_status") or "").strip().lower() != CPA_STATUS_SUCCESS:
            continue
        if acc.get("sync_disabled"):
            continue
        auth_path = _account_auth_path_for_cpa(acc)
        if auth_path:
            candidates.append((acc, auth_path))

    cpa_files = list_cpa_files()
    remote_names = {item.get("name") for item in cpa_files if item.get("name")}
    remote_emails = {(item.get("email") or "").strip().lower() for item in cpa_files if item.get("email")}
    local_remote_count = sum(
        1
        for acc, path in candidates
        if path.name in remote_names or (acc.get("email") or "").strip().lower() in remote_emails
    )

    uploaded = []
    errors = []
    changed = False
    for acc, auth_path in candidates:
        if local_remote_count >= target:
            break
        email = (acc.get("email") or "").strip().lower()
        if auth_path.name in remote_names or email in remote_emails:
            continue
        try:
            if upload_to_cpa(auth_path):
                now = time.time()
                acc["cloud_stocked_at"] = now
                acc["cpa_uploaded_at"] = now
                uploaded.append(auth_path.name)
                remote_names.add(auth_path.name)
                remote_emails.add(email)
                local_remote_count += 1
                changed = True
            else:
                errors.append({"email": email, "name": auth_path.name, "error": "upload_failed"})
        except Exception as exc:
            errors.append({"email": email, "name": auth_path.name, "error": str(exc)})

    if changed:
        save_accounts(accounts)

    return {
        "target": target,
        "remote_available": local_remote_count,
        "candidate_count": len(candidates),
        "uploaded": uploaded,
        "uploaded_count": len(uploaded),
        "missing": max(0, target - local_remote_count),
        "errors": errors,
    }


def _extract_401_names(result):
    names = set()
    for key in ("names", "deleted", "files", "items"):
        value = result.get(key) if isinstance(result, dict) else None
        if isinstance(value, list):
            for item in value:
                if isinstance(item, str):
                    names.add(item)
                elif isinstance(item, dict) and item.get("name"):
                    names.add(item["name"])
    return names


def _mark_http401_accounts_unavailable(result):
    names = _extract_401_names(result)
    if not names:
        return
    from autoteam.accounts import STATUS_UNAVAILABLE, load_accounts, save_accounts

    accounts = load_accounts()
    changed = False
    for acc in accounts:
        auth_names = {
            Path(value).name
            for value in (acc.get("auth_file"), acc.get("rt_auth_file"), acc.get("session_auth_file"))
            if value
        }
        if auth_names & names:
            acc["status"] = STATUS_UNAVAILABLE
            acc["sync_disabled"] = True
            acc["unavailable_reason"] = "http_401"
            acc["unavailable_at"] = time.time()
            changed = True
    if changed:
        save_accounts(accounts)


def _email_from_auth_filename(name):
    name = Path(name).name
    if not name.startswith("codex-"):
        return ""
    body = name[len("codex-") :]
    for marker in ("-team-", "-plus-", "-free-", "-unknown-"):
        if marker in body:
            return body.split(marker, 1)[0].strip().lower()
    return ""


def mark_unusable_account_deactivated_from_dir(directory="auths/unusable/account_deactivated"):
    """按 unusable/account_deactivated 目录把本地账号标记为不可用。"""
    from autoteam.accounts import STATUS_UNAVAILABLE, load_accounts, save_accounts

    base = Path(directory)
    files = sorted(base.glob("codex-*.json")) if base.exists() else []
    marked = {}
    parse_errors = []
    for path in files:
        email = ""
        try:
            data = json.loads(read_text(path))
            email = (data.get("email") or "").strip().lower()
        except Exception as exc:
            parse_errors.append({"name": path.name, "error": str(exc)})
        if not email:
            email = _email_from_auth_filename(path.name)
        if email:
            marked[email] = str(path)

    accounts = load_accounts()
    now = time.time()
    changed = []
    matched = 0
    for acc in accounts:
        email = (acc.get("email") or "").strip().lower()
        if email not in marked:
            continue
        matched += 1
        before = (
            acc.get("status"),
            acc.get("sync_disabled"),
            acc.get("unavailable_reason"),
            acc.get("unusable_auth_file"),
        )
        acc["status"] = STATUS_UNAVAILABLE
        acc["sync_disabled"] = True
        acc["unavailable_reason"] = "account_deactivated"
        acc["unavailable_at"] = now
        acc["unusable_auth_file"] = marked[email]
        acc["cpa_status"] = "failed"
        acc["cpa_error_message"] = "account_deactivated"
        after = (
            acc.get("status"),
            acc.get("sync_disabled"),
            acc.get("unavailable_reason"),
            acc.get("unusable_auth_file"),
        )
        if before != after:
            changed.append(email)

    if changed:
        save_accounts(accounts)

    missing_local = sorted(set(marked) - {(acc.get("email") or "").strip().lower() for acc in accounts})
    return {
        "directory": str(base),
        "files": len(files),
        "marked_emails": len(marked),
        "matched_accounts": matched,
        "changed_accounts": len(changed),
        "changed": changed,
        "missing_local_accounts": missing_local,
        "parse_errors": parse_errors,
    }


def sync_main_codex_to_cpa(filepath):
    """同步主号 Codex 认证文件到 CPA。"""
    filepath = Path(filepath)
    if not filepath.exists():
        raise FileNotFoundError(f"主号认证文件不存在: {filepath}")

    name = filepath.name
    existing = {item.get("name"): item for item in list_cpa_files()}

    for old_name in existing:
        if old_name and old_name.startswith("codex-main-"):
            logger.info("[CPA] 删除旧主号文件: %s", old_name)
            delete_from_cpa(old_name)

    if not upload_to_cpa(filepath):
        raise RuntimeError(f"上传主号认证文件失败: {name}")

    logger.info("[CPA] 主号 Codex 已同步: %s", name)
    return {"uploaded": name}


def delete_main_codex_from_cpa():
    """删除 CPA 中的主号 Codex 认证文件。"""
    existing = list_cpa_files()
    deleted = []

    for item in existing:
        name = item.get("name") or ""
        if not name.startswith("codex-main-"):
            continue
        logger.info("[CPA] 删除主号文件: %s", name)
        if delete_from_cpa(name):
            deleted.append(name)

    return {"deleted": deleted, "count": len(deleted)}
