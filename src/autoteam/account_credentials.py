"""认证文件类型识别辅助函数。"""

from __future__ import annotations

import json
import re
from copy import deepcopy
from collections.abc import Mapping
from pathlib import Path
from typing import Any

CREDENTIAL_TYPE_SESSION = "session"
CREDENTIAL_TYPE_OAUTH_RT = "oauth_rt"
CREDENTIAL_TYPE_MAIN = "main_auth"
CREDENTIAL_TYPE_INVALID = "invalid_json"
CREDENTIAL_TYPE_MISSING = "missing"
CREDENTIAL_TYPE_UNKNOWN = "unknown"

_MAIN_AUTH_FILENAME_RE = re.compile(r"^codex-main-.+\.json$", re.IGNORECASE)


def _normalize_path(path: str | Path) -> Path:
    return path if isinstance(path, Path) else Path(path)


def _is_main_auth_filename(path: Path) -> bool:
    return bool(_MAIN_AUTH_FILENAME_RE.match(path.name))


def _is_session_filename(path: Path) -> bool:
    return path.name.lower().endswith("-session.json")


def _is_oauth_filename(path: Path) -> bool:
    return path.name.lower().endswith("-oauth.json")


def _get_nested_refresh_token(data: Mapping[str, Any]) -> str:
    tokens = data.get("tokens")
    if isinstance(tokens, Mapping):
        return str(tokens.get("refresh_token") or "").strip()
    return ""


def _get_refresh_token(data: Mapping[str, Any]) -> str:
    direct_refresh_token = str(data.get("refresh_token") or "").strip()
    if direct_refresh_token:
        return direct_refresh_token
    return _get_nested_refresh_token(data)


def _looks_like_oauth_payload(data: Mapping[str, Any]) -> bool:
    if _get_refresh_token(data):
        return True
    if str(data.get("OPENAI_API_KEY") or "").strip():
        return True

    tokens = data.get("tokens")
    if isinstance(tokens, Mapping):
        return any(str(tokens.get(key) or "").strip() for key in ("access_token", "id_token"))
    return False


def _build_result(
    credential_type: str,
    path: Path,
    *,
    details: dict[str, Any] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "type": credential_type,
        "path": str(path),
        "details": details or {},
        "error": error,
    }


def identify_credential_file(path: str | Path) -> dict[str, Any]:
    resolved_path = _normalize_path(path)

    if not resolved_path.exists():
        return _build_result(CREDENTIAL_TYPE_MISSING, resolved_path)

    if _is_main_auth_filename(resolved_path):
        return _build_result(CREDENTIAL_TYPE_MAIN, resolved_path)

    try:
        data = json.loads(resolved_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return _build_result(CREDENTIAL_TYPE_INVALID, resolved_path, error=str(exc))

    if not isinstance(data, Mapping):
        return _build_result(CREDENTIAL_TYPE_UNKNOWN, resolved_path)

    credential_source = str(data.get("credential_source") or "").strip().lower()
    if credential_source == "chatgpt_session" or _is_session_filename(resolved_path):
        return _build_result(CREDENTIAL_TYPE_SESSION, resolved_path)

    has_refresh_token = bool(_get_refresh_token(data))
    if _is_oauth_filename(resolved_path) or _looks_like_oauth_payload(data):
        return _build_result(
            CREDENTIAL_TYPE_OAUTH_RT,
            resolved_path,
            details={"has_refresh_token": has_refresh_token},
        )

    return _build_result(CREDENTIAL_TYPE_UNKNOWN, resolved_path)


def is_uploadable_oauth_rt(path: str | Path) -> bool:
    result = identify_credential_file(path)
    return result["type"] == CREDENTIAL_TYPE_OAUTH_RT and bool(result["details"].get("has_refresh_token"))


def _string_path(value: Any) -> str:
    return str(value or "").strip()


def _is_valid_oauth_result(result: Mapping[str, Any]) -> bool:
    return result.get("type") == CREDENTIAL_TYPE_OAUTH_RT and bool(result.get("details", {}).get("has_refresh_token"))


def _get_credentials_bucket(account: Mapping[str, Any], key: str) -> Mapping[str, Any] | None:
    credentials = account.get("credentials")
    if not isinstance(credentials, Mapping):
        return None
    bucket = credentials.get(key)
    return bucket if isinstance(bucket, Mapping) else None


def _get_credentials_file(account: Mapping[str, Any], key: str) -> str:
    bucket = _get_credentials_bucket(account, key)
    if not bucket:
        return ""
    return _string_path(bucket.get("file"))


def _ensure_dict(parent: dict[str, Any], key: str) -> dict[str, Any]:
    value = parent.get(key)
    if isinstance(value, dict):
        return value
    new_value: dict[str, Any] = {}
    parent[key] = new_value
    return new_value


def _sync_credential_bucket(
    account: dict[str, Any],
    credential_key: str,
    path_str: str,
) -> bool:
    changed = False
    credentials = _ensure_dict(account, "credentials")
    bucket = _ensure_dict(credentials, credential_key)

    if bucket.get("file") != path_str:
        bucket["file"] = path_str
        changed = True
    if bucket.get("present") is not True:
        bucket["present"] = True
        changed = True

    return changed


def _append_error(result: dict[str, Any], *, error_type: str, path: str, message: str | None = None) -> None:
    result["errors"].append(
        {
            "type": error_type,
            "path": path,
            "message": message or "",
        }
    )


def migrate_account_credentials(account: dict[str, Any], *, in_place: bool = True) -> dict[str, Any]:
    result: dict[str, Any] = {"changed": False, "actions": [], "errors": []}
    if not isinstance(account, dict):
        result["errors"].append({"type": "invalid_account", "message": "account must be a dict"})
        return result

    target = account if in_place else deepcopy(account)

    existing_oauth_file = _get_credentials_file(target, "oauth_rt")
    if existing_oauth_file:
        existing_oauth_result = identify_credential_file(existing_oauth_file)
        if _is_valid_oauth_result(existing_oauth_result):
            result["actions"].append(
                {
                    "type": "existing_oauth_rt_kept",
                    "path": existing_oauth_file,
                    "source": "credentials.oauth_rt.file",
                }
            )
            return result

    existing_rt_auth_file = _string_path(target.get("rt_auth_file"))
    if existing_rt_auth_file and is_uploadable_oauth_rt(existing_rt_auth_file):
        result["actions"].append(
            {
                "type": "existing_oauth_rt_kept",
                "path": existing_rt_auth_file,
                "source": "rt_auth_file",
            }
        )
        return result

    legacy_auth_file = _string_path(target.get("auth_file"))
    if not legacy_auth_file:
        result["actions"].append({"type": "no_auth_file"})
        return result

    identified = identify_credential_file(legacy_auth_file)
    identified_type = identified["type"]

    if identified_type == CREDENTIAL_TYPE_MAIN:
        result["actions"].append({"type": "skipped_main", "path": legacy_auth_file})
        return result

    if identified_type == CREDENTIAL_TYPE_MISSING:
        result["actions"].append({"type": "missing", "path": legacy_auth_file})
        return result

    if identified_type == CREDENTIAL_TYPE_INVALID:
        result["actions"].append({"type": "invalid_json", "path": legacy_auth_file})
        _append_error(result, error_type="invalid_json", path=legacy_auth_file, message=identified.get("error"))
        return result

    if identified_type == CREDENTIAL_TYPE_SESSION:
        existing_session_auth_file = _string_path(target.get("session_auth_file"))
        existing_session_credential_file = _get_credentials_file(target, "session")
        if existing_session_auth_file or existing_session_credential_file:
            kept_path = existing_session_auth_file or existing_session_credential_file
            kept_source = "session_auth_file" if existing_session_auth_file else "credentials.session.file"
            result["actions"].append(
                {
                    "type": "existing_session_kept",
                    "path": kept_path,
                    "source": kept_source,
                }
            )
            return result

        target["session_auth_file"] = legacy_auth_file
        result["actions"].append(
            {
                "type": "session_auth_file_set",
                "from": legacy_auth_file,
                "to": legacy_auth_file,
            }
        )
        if _sync_credential_bucket(
            target,
            "session",
            legacy_auth_file,
        ):
            result["actions"].append(
                {
                    "type": "credentials_session_synced",
                    "to": legacy_auth_file,
                }
            )
        result["changed"] = True
        return result

    if _is_valid_oauth_result(identified):
        target["rt_auth_file"] = legacy_auth_file
        result["actions"].append(
            {
                "type": "rt_auth_file_set",
                "from": legacy_auth_file,
                "to": legacy_auth_file,
            }
        )
        if _sync_credential_bucket(
            target,
            "oauth_rt",
            legacy_auth_file,
        ):
            result["actions"].append(
                {
                    "type": "credentials_oauth_rt_synced",
                    "to": legacy_auth_file,
                }
            )
        result["changed"] = True
        return result

    if identified_type == CREDENTIAL_TYPE_OAUTH_RT:
        result["actions"].append({"type": "invalid_oauth_rt", "path": legacy_auth_file})
        return result

    result["actions"].append({"type": "unknown", "path": legacy_auth_file})
    return result


def migrate_accounts_credentials(accounts: list[dict[str, Any]], *, in_place: bool = True) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "total": len(accounts),
        "changed": 0,
        "unchanged": 0,
        "actions": [],
    }

    for index, account in enumerate(accounts):
        migration_result = migrate_account_credentials(account, in_place=in_place)
        if migration_result["changed"]:
            summary["changed"] += 1
        else:
            summary["unchanged"] += 1

        summary["actions"].append(
            {
                "index": index,
                "email": account.get("email") if isinstance(account, Mapping) else "",
                "changed": migration_result["changed"],
                "actions": migration_result["actions"],
                "errors": migration_result["errors"],
            }
        )

    return summary


__all__ = [
    "CREDENTIAL_TYPE_INVALID",
    "CREDENTIAL_TYPE_MAIN",
    "CREDENTIAL_TYPE_MISSING",
    "CREDENTIAL_TYPE_OAUTH_RT",
    "CREDENTIAL_TYPE_SESSION",
    "CREDENTIAL_TYPE_UNKNOWN",
    "identify_credential_file",
    "is_uploadable_oauth_rt",
    "migrate_account_credentials",
    "migrate_accounts_credentials",
]
