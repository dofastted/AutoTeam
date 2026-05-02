"""MoEmail prefix/index 分组分配器。"""

from __future__ import annotations

import json
import random
import string
import time
from pathlib import Path

DEFAULT_GROUP_LIMIT = 50
DEFAULT_PREFIX_LENGTH = 4
DEFAULT_GROUPS_PATH = Path("data/account-email-groups/moemail-groups.json")
SCHEMA_VERSION = 1


def _empty_state() -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "groups": [],
    }


def _clone_state(state: dict) -> dict:
    return json.loads(json.dumps(state))


class EmailGroupAllocator:
    def __init__(
        self,
        *,
        store_path: Path | None = None,
        limit: int = DEFAULT_GROUP_LIMIT,
        prefix_length: int = DEFAULT_PREFIX_LENGTH,
        rng: random.Random | None = None,
    ):
        self.store_path = Path(store_path) if store_path is not None else None
        self.limit = max(1, int(limit or DEFAULT_GROUP_LIMIT))
        self.prefix_length = max(1, int(prefix_length or DEFAULT_PREFIX_LENGTH))
        self.rng = rng or random.Random()
        self._memory_state = _empty_state()

    def load(self) -> dict:
        if self.store_path is None:
            return _clone_state(self._memory_state)

        if not self.store_path.exists():
            return _empty_state()

        try:
            raw = self.store_path.read_text(encoding="utf-8").strip()
        except Exception:
            return _empty_state()

        if not raw:
            return _empty_state()

        try:
            data = json.loads(raw)
        except Exception:
            return _empty_state()

        return self._normalize_state(data)

    def save(self, state: dict) -> None:
        normalized = self._normalize_state(state)

        if self.store_path is None:
            self._memory_state = normalized
            return

        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        self.store_path.write_text(json.dumps(normalized, indent=2, ensure_ascii=False), encoding="utf-8")

    def allocate(self) -> dict:
        state = self.load()
        group = self._pick_active_group(state)
        is_new_group = group is None

        if group is None:
            group = self._create_new_group(state)

        index = int(group.get("next_index") or 1)
        group["next_index"] = index + 1
        group["exhausted"] = int(group["next_index"]) > int(group.get("max_index") or self.limit)

        self.save(state)

        return {
            "group_id": group["group_id"],
            "prefix": group["prefix"],
            "index": index,
            "is_new_group": is_new_group,
        }

    def _pick_active_group(self, state):
        for group in state.get("groups") or []:
            normalized = self._normalize_group(group)
            group.update(normalized)
            if not normalized["exhausted"]:
                return group
        return None

    def _create_new_group(self, state):
        groups = state.setdefault("groups", [])
        prefix = self._random_prefix()
        sequence = self._next_group_sequence(groups, prefix)
        group = {
            "group_id": f"{prefix}_{sequence:03d}",
            "prefix": prefix,
            "next_index": 1,
            "max_index": self.limit,
            "created_at": time.time(),
            "exhausted": False,
        }
        groups.append(group)
        return group

    def _random_prefix(self):
        return "".join(self.rng.choice(string.ascii_lowercase) for _ in range(self.prefix_length))

    def _normalize_state(self, state: dict) -> dict:
        if not isinstance(state, dict):
            return _empty_state()

        groups = []
        for item in state.get("groups") or []:
            if isinstance(item, dict):
                groups.append(self._normalize_group(item))

        return {
            "schema_version": SCHEMA_VERSION,
            "groups": groups,
        }

    def _normalize_group(self, group: dict) -> dict:
        prefix = str(group.get("prefix") or "").strip()
        group_id = str(group.get("group_id") or "").strip()
        next_index = self._coerce_int(group.get("next_index"), 1)
        max_index = max(1, self._coerce_int(group.get("max_index"), self.limit))
        created_at = group.get("created_at")
        exhausted = bool(group.get("exhausted"))
        if next_index > max_index:
            exhausted = True

        return {
            "group_id": group_id,
            "prefix": prefix,
            "next_index": next_index,
            "max_index": max_index,
            "created_at": created_at,
            "exhausted": exhausted,
        }

    @staticmethod
    def _coerce_int(value, default: int) -> int:
        try:
            return int(value)
        except Exception:
            return default

    @staticmethod
    def _next_group_sequence(groups: list[dict], prefix: str) -> int:
        max_sequence = 0
        for group in groups:
            group_prefix = str(group.get("prefix") or "").strip()
            if group_prefix != prefix:
                continue
            group_id = str(group.get("group_id") or "").strip()
            if not group_id.startswith(f"{prefix}_"):
                continue
            try:
                suffix = int(group_id.rsplit("_", 1)[1])
            except Exception:
                continue
            max_sequence = max(max_sequence, suffix)
        return max_sequence + 1


def allocate_email_slot(
    *,
    store_path: Path | None = None,
    limit: int = DEFAULT_GROUP_LIMIT,
    prefix_length: int = DEFAULT_PREFIX_LENGTH,
    rng: random.Random | None = None,
) -> dict:
    allocator = EmailGroupAllocator(
        store_path=store_path,
        limit=limit,
        prefix_length=prefix_length,
        rng=rng,
    )
    return allocator.allocate()
