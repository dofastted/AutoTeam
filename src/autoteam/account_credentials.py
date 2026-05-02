"""认证文件类型识别辅助函数。"""

from __future__ import annotations

import json
import re
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


__all__ = [
    "CREDENTIAL_TYPE_INVALID",
    "CREDENTIAL_TYPE_MAIN",
    "CREDENTIAL_TYPE_MISSING",
    "CREDENTIAL_TYPE_OAUTH_RT",
    "CREDENTIAL_TYPE_SESSION",
    "CREDENTIAL_TYPE_UNKNOWN",
    "identify_credential_file",
    "is_uploadable_oauth_rt",
]
