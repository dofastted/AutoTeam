"""accounts.json 清理辅助工具。

AT-003 backup; AT-004 scan; AT-005 dedupe; AT-008 reclassify will follow.
"""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from autoteam import accounts

BACKUP_TAG = "account-clean"


def backup_accounts_file(
    *,
    accounts_file: Path | None = None,
    tag: str = BACKUP_TAG,
    now: datetime | None = None,
) -> Path | None:
    """为 accounts.json 生成带时间戳的同目录备份文件。"""

    target_file = accounts_file or accounts.ACCOUNTS_FILE
    if not target_file.exists():
        return None

    backup_time = now or datetime.now()
    timestamp = backup_time.strftime("%Y%m%d-%H%M%S")
    backup_path = target_file.with_name(f"{target_file.name}.bak-{tag}-{timestamp}")
    shutil.copy2(target_file, backup_path)
    return backup_path


__all__ = ["BACKUP_TAG", "backup_accounts_file"]
