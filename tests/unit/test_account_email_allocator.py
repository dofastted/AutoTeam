import json
import random

from autoteam.account_email_allocator import EmailGroupAllocator


def test_allocate_creates_first_group_and_state_file(tmp_path):
    store_path = tmp_path / "data" / "account-email-groups" / "moemail-groups.json"
    allocator = EmailGroupAllocator(store_path=store_path, rng=random.Random(1234))

    result = allocator.allocate()

    assert result["is_new_group"] is True
    assert result["index"] == 1
    assert store_path.exists()

    state = json.loads(store_path.read_text(encoding="utf-8"))
    assert state["schema_version"] == 1
    assert state["groups"][0]["group_id"] == f'{result["prefix"]}_001'
    assert state["groups"][0]["next_index"] == 2
    assert state["groups"][0]["max_index"] == 50
    assert state["groups"][0]["exhausted"] is False


def test_allocate_keeps_same_group_until_fiftieth_slot(tmp_path):
    store_path = tmp_path / "moemail-groups.json"
    allocator = EmailGroupAllocator(store_path=store_path, rng=random.Random(1234))

    first = allocator.allocate()
    last = first
    for _ in range(49):
        last = allocator.allocate()

    assert last["group_id"] == first["group_id"]
    assert last["prefix"] == first["prefix"]
    assert last["index"] == 50
    assert last["is_new_group"] is False

    state = json.loads(store_path.read_text(encoding="utf-8"))
    assert state["groups"][0]["next_index"] == 51
    assert state["groups"][0]["exhausted"] is True


def test_allocate_creates_new_group_on_fifty_first_slot(tmp_path):
    store_path = tmp_path / "moemail-groups.json"
    allocator = EmailGroupAllocator(store_path=store_path, rng=random.Random(1234))

    first = allocator.allocate()
    for _ in range(49):
        allocator.allocate()
    next_group = allocator.allocate()

    assert next_group["is_new_group"] is True
    assert next_group["index"] == 1
    assert next_group["prefix"] != first["prefix"]
    assert next_group["group_id"] != first["group_id"]

    state = json.loads(store_path.read_text(encoding="utf-8"))
    assert len(state["groups"]) == 2
    assert state["groups"][1]["group_id"] == next_group["group_id"]
    assert state["groups"][1]["next_index"] == 2


def test_allocator_persists_next_index_across_instances(tmp_path):
    store_path = tmp_path / "moemail-groups.json"

    first_allocator = EmailGroupAllocator(store_path=store_path, rng=random.Random(1234))
    first = first_allocator.allocate()
    second = first_allocator.allocate()

    second_allocator = EmailGroupAllocator(store_path=store_path, rng=random.Random(9999))
    third = second_allocator.allocate()

    assert first["index"] == 1
    assert second["index"] == 2
    assert third["index"] == 3
    assert third["group_id"] == first["group_id"]
    assert third["prefix"] == first["prefix"]
    assert third["is_new_group"] is False


def test_allocator_supports_in_memory_mode_without_writing_files(tmp_path):
    allocator = EmailGroupAllocator(store_path=None, rng=random.Random(1234))

    first = allocator.allocate()
    second = allocator.allocate()
    third = allocator.allocate()

    assert first["index"] == 1
    assert second["index"] == 2
    assert third["index"] == 3
    assert first["group_id"] == second["group_id"] == third["group_id"]
    assert list(tmp_path.iterdir()) == []


def test_random_prefix_is_reproducible_with_same_seed():
    first = EmailGroupAllocator(rng=random.Random(1234))
    second = EmailGroupAllocator(rng=random.Random(1234))

    assert first._random_prefix() == second._random_prefix()
