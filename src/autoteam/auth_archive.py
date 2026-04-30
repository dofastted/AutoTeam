"""Local archive for account CPA auth files."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from autoteam.auth_storage import AUTH_DIR, ensure_auth_file_permissions

ARCHIVE_DIR = AUTH_DIR / "archive"


def _safe_email_dir(email: str) -> str:
    value = str(email or "").strip().lower()
    if not value:
        return "unknown"
    return re.sub(r"[^a-z0-9@._+-]+", "_", value)


def archive_account_auth_file(email: str, auth_file: str | Path) -> str:
    """Copy an account auth file into auths/archive/<email>/ and return the archive path."""
    source = Path(auth_file)
    if not source.exists() or not source.is_file():
        raise FileNotFoundError(f"认证文件不存在: {source}")

    target_dir = ARCHIVE_DIR / _safe_email_dir(email)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / source.name
    shutil.copy2(source, target)
    ensure_auth_file_permissions(target)
    return str(target.resolve())
