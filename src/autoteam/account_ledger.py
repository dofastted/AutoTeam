"""账号事件 ledger 的本地 jsonl 持久化。"""

from __future__ import annotations

import json
import random
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

_HEX_DIGITS = "0123456789abcdef"


def _resolve_ledger_dir(ledger_dir: Path | str) -> Path:
    return Path(ledger_dir)


def _event_file_for_ts(ledger_dir: Path | str, ts: int) -> Path:
    day = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
    return _resolve_ledger_dir(ledger_dir) / f"{day}.jsonl"


def _gen_event_id(now: int | None = None, *, rng: random.Random | None = None) -> str:
    """Return an event id in the form ``evt_<unix>_<6hex>``."""
    unix_ts = int(now if now is not None else time.time())
    rand = rng if rng is not None else random.Random()
    short_hash = "".join(rand.choice(_HEX_DIGITS) for _ in range(6))
    return f"evt_{unix_ts}_{short_hash}"


def append_event(
    event_type: str,
    email: str,
    *,
    actor: str = "system",
    payload: dict[str, Any] | None = None,
    ledger_dir: Path | str = "data/account-ledger",
    now: int | None = None,
) -> dict[str, Any]:
    """Append one event to today's ledger file and return the written event."""
    unix_ts = int(now if now is not None else time.time())
    event = {
        "event_id": _gen_event_id(unix_ts),
        "ts": unix_ts,
        "event_type": event_type,
        "email": email,
        "actor": actor,
        "payload": dict(payload or {}),
    }

    ledger_path = _event_file_for_ts(ledger_dir, unix_ts)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with ledger_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")
    return event


def _iter_events(ledger_dir: Path | str) -> list[dict[str, Any]]:
    base_dir = _resolve_ledger_dir(ledger_dir)
    if not base_dir.exists() or not base_dir.is_dir():
        return []

    events: list[dict[str, Any]] = []
    for path in sorted(base_dir.glob("*.jsonl")):
        with path.open(encoding="utf-8") as f:
            for line_no, raw_line in enumerate(f, start=1):
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    parsed = json.loads(line)
                except json.JSONDecodeError:
                    print(f"Skip corrupt ledger line: {path}:{line_no}", file=sys.stderr)
                    continue
                if isinstance(parsed, dict):
                    events.append(parsed)
    return events


def read_events(
    *,
    email: str | None = None,
    since_ts: int | None = None,
    until_ts: int | None = None,
    ledger_dir: Path | str = "data/account-ledger",
) -> list[dict[str, Any]]:
    """Read and filter ledger events sorted by ascending timestamp."""
    filtered: list[dict[str, Any]] = []
    for event in _iter_events(ledger_dir):
        event_email = event.get("email")
        event_ts = event.get("ts")
        if email is not None and event_email != email:
            continue
        if not isinstance(event_ts, (int, float)):
            continue
        if since_ts is not None and event_ts < since_ts:
            continue
        if until_ts is not None and event_ts >= until_ts:
            continue
        filtered.append(event)

    filtered.sort(key=lambda item: (item.get("ts", 0), item.get("event_id", "")))
    return filtered
