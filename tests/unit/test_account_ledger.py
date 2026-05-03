import json
import re
from datetime import datetime

from autoteam.account_ledger import _gen_event_id, append_event, read_events


def _ledger_file(tmp_path, ts: int):
    day = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
    return tmp_path / f"{day}.jsonl"


def test_append_event_writes_jsonl(tmp_path):
    now = 1714834567

    event = append_event(
        "register",
        "alice@example.com",
        payload={"registration_status": "registered"},
        ledger_dir=tmp_path,
        now=now,
    )

    ledger_file = _ledger_file(tmp_path, now)
    assert ledger_file.exists()
    lines = ledger_file.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    written = json.loads(lines[0])
    assert written == event


def test_append_event_returns_event_with_id(tmp_path):
    now = 1714834568

    event = append_event("inventory", "alice@example.com", ledger_dir=tmp_path, now=now)

    assert event["ts"] == now
    assert re.fullmatch(rf"evt_{now}_[0-9a-f]{{6}}", event["event_id"])


def test_append_event_appends_to_existing_file(tmp_path):
    now = 1714834569

    append_event("register", "a@example.com", ledger_dir=tmp_path, now=now)
    append_event("inventory", "a@example.com", ledger_dir=tmp_path, now=now)

    ledger_file = _ledger_file(tmp_path, now)
    lines = ledger_file.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2


def test_read_events_filter_by_email(tmp_path):
    append_event("register", "alice@example.com", ledger_dir=tmp_path, now=1714834500)
    append_event("inventory", "bob@example.com", ledger_dir=tmp_path, now=1714834501)
    append_event("allocate", "alice@example.com", ledger_dir=tmp_path, now=1714834502)

    events = read_events(email="alice@example.com", ledger_dir=tmp_path)

    assert [event["event_type"] for event in events] == ["register", "allocate"]
    assert all(event["email"] == "alice@example.com" for event in events)


def test_read_events_filter_by_time_range(tmp_path):
    append_event("register", "alice@example.com", ledger_dir=tmp_path, now=100)
    append_event("inventory", "alice@example.com", ledger_dir=tmp_path, now=200)
    append_event("allocate", "alice@example.com", ledger_dir=tmp_path, now=300)

    events = read_events(since_ts=200, until_ts=300, ledger_dir=tmp_path)

    assert [event["ts"] for event in events] == [200]


def test_read_events_handles_corrupt_line(tmp_path, capsys):
    ledger_file = tmp_path / "2024-05-04.jsonl"
    ledger_file.write_text(
        '{"event_id":"evt_1_abcdef","ts":1,"event_type":"register","email":"ok@example.com","actor":"system","payload":{}}\n'
        "{bad json}\n",
        encoding="utf-8",
    )

    events = read_events(ledger_dir=tmp_path)

    captured = capsys.readouterr()
    assert len(events) == 1
    assert events[0]["email"] == "ok@example.com"
    assert "Skip corrupt ledger line" in captured.err


def test_read_events_sorted_by_ts(tmp_path):
    old_file = tmp_path / "2024-05-03.jsonl"
    new_file = tmp_path / "2024-05-04.jsonl"
    old_file.write_text(
        '{"event_id":"evt_200_bbbbbb","ts":200,"event_type":"inventory","email":"b@example.com","actor":"system","payload":{}}\n',
        encoding="utf-8",
    )
    new_file.write_text(
        '{"event_id":"evt_300_cccccc","ts":300,"event_type":"allocate","email":"c@example.com","actor":"system","payload":{}}\n'
        '{"event_id":"evt_100_aaaaaa","ts":100,"event_type":"register","email":"a@example.com","actor":"system","payload":{}}\n',
        encoding="utf-8",
    )

    events = read_events(ledger_dir=tmp_path)

    assert [event["ts"] for event in events] == [100, 200, 300]


def test_read_events_missing_dir_returns_empty(tmp_path):
    missing_dir = tmp_path / "missing"

    events = read_events(ledger_dir=missing_dir)

    assert events == []


def test_gen_event_id_format():
    event_id = _gen_event_id(now=1700000000)

    assert re.fullmatch(r"evt_1700000000_[0-9a-f]{6}", event_id)
