"""Local cache for ChatGPT Team member snapshots."""

from __future__ import annotations

import json
import time
from pathlib import Path

from autoteam.textio import read_text, write_text

PROJECT_ROOT = Path(__file__).parent.parent.parent
TEAM_CACHE_FILE = PROJECT_ROOT / "team_members_cache.json"


def load_team_members_cache() -> dict:
    if not TEAM_CACHE_FILE.exists():
        return {}
    try:
        data = json.loads(read_text(TEAM_CACHE_FILE))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def save_team_members_cache(payload: dict) -> dict:
    snapshot = {
        **payload,
        "cached": True,
        "cache_updated_at": time.time(),
    }
    write_text(TEAM_CACHE_FILE, json.dumps(snapshot, indent=2, ensure_ascii=False))
    return snapshot
