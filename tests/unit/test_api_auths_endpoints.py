"""Tests for /api/auths/* endpoints and helpers (auths/ flat scan)."""
import json
import threading
from pathlib import Path

import pytest
from fastapi import HTTPException

from autoteam import accounts as accounts_module
from autoteam import api, auth_storage


@pytest.fixture
def auths_dir(tmp_path, monkeypatch):
    """构造一个真实 auths/ 目录布局,并 monkeypatch AUTH_DIR。"""
    root = tmp_path / "auths"
    root.mkdir()
    (root / "sold").mkdir()
    (root / "tradable").mkdir()
    (root / "unusable" / "account_deactivated").mkdir(parents=True)
    (root / "archive").mkdir()
    monkeypatch.setattr(auth_storage, "AUTH_DIR", root)
    return root


def _write(path: Path, **payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


# ----- _parse_auth_filename ------------------------------------------------


def test_parse_auth_filename_root_oauth():
    info = api._parse_auth_filename("codex-foo@bar.com-team-abc12345-oauth.json")
    assert info is not None
    assert info["email"] == "foo@bar.com"
    assert info["team_hash"] == "abc12345"
    assert info["plan_type"] == "team"
    assert info["kind"] == "oauth"
    assert info["filename"] == "codex-foo@bar.com-team-abc12345-oauth.json"


def test_parse_auth_filename_root_session():
    info = api._parse_auth_filename("codex-foo@bar.com-team-abc12345-session.json")
    assert info is not None
    assert info["email"] == "foo@bar.com"
    assert info["team_hash"] == "abc12345"
    assert info["plan_type"] == "team"
    assert info["kind"] == "session"
    assert info["filename"] == "codex-foo@bar.com-team-abc12345-session.json"


@pytest.mark.parametrize("plan_type", ["team", "plus", "free", "unknown"])
def test_parse_auth_filename_plan_types(plan_type):
    info = api._parse_auth_filename(f"codex-foo@bar.com-{plan_type}-abc12345-oauth.json")
    assert info is not None
    assert info["email"] == "foo@bar.com"
    assert info["team_hash"] == "abc12345"
    assert info["plan_type"] == plan_type
    assert info["kind"] == "oauth"


def test_parse_auth_filename_subdir_plain():
    info = api._parse_auth_filename("codex-foo@bar.com-plus-abc12345.json")
    assert info is not None
    assert info["email"] == "foo@bar.com"
    assert info["team_hash"] == "abc12345"
    assert info["plan_type"] == "plus"
    # 子目录 plain 文件没有 -oauth/-session 后缀 → kind 留空字符串
    assert info["kind"] == ""


def test_parse_auth_filename_skips_main():
    assert api._parse_auth_filename("codex-main-oauth.json") is None
    assert api._parse_auth_filename("codex-main-team-deadbeef-oauth.json") is None


def test_parse_auth_filename_invalid_returns_none():
    assert api._parse_auth_filename("random.json") is None
    assert api._parse_auth_filename("codex-noteam.json") is None


# ----- _bucket_primary_category --------------------------------------------


def test_primary_category_priority_sold_over_active():
    assert api._bucket_primary_category({"active", "sold"}) == "sold"


def test_primary_category_priority_active_over_archive():
    assert api._bucket_primary_category({"active", "archive"}) == "active"


def test_primary_category_priority_sold_over_tradable():
    assert api._bucket_primary_category({"sold", "tradable", "archive"}) == "sold"


def test_primary_category_active_alone():
    assert api._bucket_primary_category({"active"}) == "active"


def test_primary_category_empty_returns_unknown():
    assert api._bucket_primary_category(set()) == "unknown"
    assert api._bucket_primary_category(None) == "unknown"


# ----- _scan_auths_files ---------------------------------------------------


def test_scan_aggregates_root_oauth_session(auths_dir):
    _write(
        auths_dir / "codex-a@x.com-team-h1-oauth.json",
        refresh_token="rt", expired="2026-05-10T00:00:00Z", credential_source="oauth",
    )
    _write(
        auths_dir / "codex-a@x.com-team-h1-session.json",
        access_token="t", expired="2026-05-09T00:00:00Z", credential_source="chatgpt_session",
    )

    scan = api._scan_auths_files()

    assert scan["stats"]["total_files"] == 2
    assert scan["stats"]["oauth_files"] == 1
    assert scan["stats"]["session_files"] == 1
    assert scan["stats"]["active_files"] == 2
    assert scan["stats"]["unique_emails"] == 1
    assert scan["stats"]["accounts_active"] == 1

    bucket = scan["by_email"]["a@x.com"]
    assert bucket["has_oauth"] is True
    assert bucket["has_session"] is True
    assert bucket["categories"] == {"active"}
    assert bucket["plan_types"] == {"team"}
    assert bucket["team_hash"] == "h1"


def test_scan_subdir_plain_json(auths_dir):
    _write(auths_dir / "sold" / "codex-b@x.com-team-h2.json", refresh_token="rt")
    _write(auths_dir / "tradable" / "codex-c@x.com-team-h3.json", refresh_token="rt")
    _write(auths_dir / "unusable" / "account_deactivated" / "codex-d@x.com-team-h4.json", refresh_token="rt")
    _write(auths_dir / "archive" / "codex-e@x.com-team-h5.json", refresh_token="rt")

    scan = api._scan_auths_files()

    assert scan["stats"]["sold_files"] == 1
    assert scan["stats"]["tradable_files"] == 1
    assert scan["stats"]["unusable_files"] == 1
    assert scan["stats"]["archive_files"] == 1
    assert scan["stats"]["accounts_sold"] == 1
    assert scan["stats"]["accounts_tradable"] == 1
    assert scan["stats"]["accounts_unusable"] == 1
    assert scan["stats"]["accounts_archive"] == 1
    assert scan["stats"]["unique_emails"] == 4


def test_scan_cross_directory_same_email_uses_priority(auths_dir):
    """同邮箱跨根目录和 sold 子目录,主分类应是 sold,accounts_active 不计。"""
    _write(auths_dir / "codex-x@x.com-team-h-session.json", access_token="t")
    _write(auths_dir / "sold" / "codex-x@x.com-team-h.json", refresh_token="rt")

    scan = api._scan_auths_files()

    assert scan["stats"]["unique_emails"] == 1
    assert scan["stats"]["accounts_sold"] == 1
    assert scan["stats"]["accounts_active"] == 0
    # 文件计数仍然两侧各加一
    assert scan["stats"]["active_files"] == 1
    assert scan["stats"]["sold_files"] == 1

    rec = api._bucket_to_record(scan["by_email"]["x@x.com"])
    assert rec["category"] == "sold"
    assert "active" in rec["categories"] and "sold" in rec["categories"]


def test_scan_cross_directory_active_over_archive(auths_dir):
    """同邮箱跨根目录和 archive 子目录时,主分类应是 active。"""
    _write(auths_dir / "codex-x@x.com-team-h-oauth.json", refresh_token="rt")
    _write(auths_dir / "archive" / "x@x.com" / "codex-x@x.com-team-h-oauth.json", refresh_token="rt")

    scan = api._scan_auths_files()

    assert scan["stats"]["unique_emails"] == 1
    assert scan["stats"]["accounts_active"] == 1
    assert scan["stats"]["accounts_archive"] == 0
    assert scan["stats"]["active_files"] == 1
    assert scan["stats"]["archive_files"] == 1

    rec = api._bucket_to_record(scan["by_email"]["x@x.com"])
    assert rec["category"] == "active"
    assert "active" in rec["categories"] and "archive" in rec["categories"]


def test_scan_handles_missing_auth_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(auth_storage, "AUTH_DIR", tmp_path / "does-not-exist")
    scan = api._scan_auths_files()
    assert scan["by_email"] == {}
    assert scan["stats"]["unique_emails"] == 0
    assert scan["stats"]["total_files"] == 0


# ----- /api/auths/accounts -------------------------------------------------


@pytest.fixture
def populated_dir(auths_dir):
    """两个 active、一个 sold、一个 archive、一个跨目录 sold 的样本数据。"""
    _write(auths_dir / "codex-a1@x.com-team-h-oauth.json", refresh_token="rt", expired="2026-05-10")
    _write(auths_dir / "codex-a2@x.com-team-h-session.json", access_token="t", expired="2026-05-11")
    _write(auths_dir / "sold" / "codex-s1@x.com-team-h.json", refresh_token="rt")
    _write(auths_dir / "archive" / "codex-arch@x.com-team-h.json", refresh_token="rt")
    # 跨目录:既在根又在 sold => 主分类应为 sold
    _write(auths_dir / "codex-cross@x.com-team-h-session.json", access_token="t")
    _write(auths_dir / "sold" / "codex-cross@x.com-team-h.json", refresh_token="rt")
    return auths_dir


def test_endpoint_default_hides_archive(populated_dir):
    resp = api.get_auths_accounts()
    emails = [r["email"] for r in resp["items"]]
    # 默认 category="" 隐藏 archive
    assert "arch@x.com" not in emails
    # 但 active / sold / cross 都应可见
    assert "a1@x.com" in emails
    assert "s1@x.com" in emails
    assert "cross@x.com" in emails
    assert all("plan_type" in r for r in resp["items"])
    # cross 的 primary 应为 sold
    cross = next(r for r in resp["items"] if r["email"] == "cross@x.com")
    assert cross["category"] == "sold"


def test_endpoint_category_all_includes_archive(populated_dir):
    resp = api.get_auths_accounts(category="all")
    emails = [r["email"] for r in resp["items"]]
    assert "arch@x.com" in emails


def test_endpoint_category_archive_only(populated_dir):
    resp = api.get_auths_accounts(category="archive")
    assert resp["total"] == 1
    assert resp["items"][0]["email"] == "arch@x.com"


def test_endpoint_category_sold_includes_cross(populated_dir):
    resp = api.get_auths_accounts(category="sold")
    emails = sorted(r["email"] for r in resp["items"])
    assert emails == ["cross@x.com", "s1@x.com"]


def test_endpoint_has_oauth_filter(populated_dir):
    resp_with = api.get_auths_accounts(has_oauth=True)
    resp_without = api.get_auths_accounts(has_oauth=False)
    emails_with = sorted(r["email"] for r in resp_with["items"])
    emails_without = sorted(r["email"] for r in resp_without["items"])
    assert "a1@x.com" in emails_with  # oauth file
    assert "a1@x.com" not in emails_without
    # a2 / cross 只有 session,没有 oauth
    assert "a2@x.com" in emails_without


def test_endpoint_has_session_filter(populated_dir):
    resp = api.get_auths_accounts(has_session=True)
    emails = sorted(r["email"] for r in resp["items"])
    assert "a2@x.com" in emails
    assert "cross@x.com" in emails  # 有 session(根目录) + sold 文件


def test_endpoint_search_q(populated_dir):
    resp = api.get_auths_accounts(q="cross")
    assert resp["total"] == 1
    assert resp["items"][0]["email"] == "cross@x.com"


def test_endpoint_pagination_beyond_last(populated_dir):
    resp = api.get_auths_accounts(page=99, page_size=20)
    assert resp["items"] == []
    assert resp["page"] == 99
    assert resp["has_next"] is False


def test_endpoint_invalid_page_raises():
    with pytest.raises(HTTPException) as exc:
        api.get_auths_accounts(page=0)
    assert exc.value.status_code == 400


def test_endpoint_invalid_page_size_raises():
    with pytest.raises(HTTPException) as exc:
        api.get_auths_accounts(page_size=999)
    assert exc.value.status_code == 400


def test_endpoint_invalid_category_raises():
    with pytest.raises(HTTPException) as exc:
        api.get_auths_accounts(category="bogus")
    assert exc.value.status_code == 400


def test_endpoint_invalid_sort_raises():
    with pytest.raises(HTTPException) as exc:
        api.get_auths_accounts(sort="bogus")
    assert exc.value.status_code == 400


def test_endpoint_sort_expired_handles_missing(auths_dir):
    """有的 bucket 没有 expired 字段,排序不应崩。"""
    _write(auths_dir / "codex-with@x.com-team-h-oauth.json", refresh_token="rt", expired="2026-05-10")
    _write(auths_dir / "codex-no@x.com-team-h-oauth.json", refresh_token="rt")  # 缺 expired

    resp = api.get_auths_accounts(sort="expired_asc")
    emails = [r["email"] for r in resp["items"]]
    assert set(emails) == {"with@x.com", "no@x.com"}


def test_endpoint_sort_expired_handles_mixed_formats(auths_dir):
    """expired 可能是 Unix 秒、毫秒、数字字符串、ISO 字符串或坏值,排序不应崩。"""
    _write(auths_dir / "codex-seconds@x.com-team-h-oauth.json", refresh_token="rt", expired=1700000000)
    _write(auths_dir / "codex-numeric@x.com-team-h-oauth.json", refresh_token="rt", expired="1700000001")
    _write(auths_dir / "codex-millis@x.com-team-h-oauth.json", refresh_token="rt", expired=1700000002000)
    _write(auths_dir / "codex-iso@x.com-team-h-oauth.json", refresh_token="rt", expired="2023-11-14T22:13:23Z")
    _write(auths_dir / "codex-bad@x.com-team-h-oauth.json", refresh_token="rt", expired="not-a-date")
    _write(auths_dir / "codex-missing@x.com-team-h-oauth.json", refresh_token="rt")

    asc = api.get_auths_accounts(sort="expired_asc", page_size=10)
    desc = api.get_auths_accounts(sort="expired_desc", page_size=10)

    asc_emails = [r["email"] for r in asc["items"]]
    desc_emails = [r["email"] for r in desc["items"]]
    assert asc_emails[:4] == ["seconds@x.com", "numeric@x.com", "millis@x.com", "iso@x.com"]
    assert desc_emails[:4] == ["iso@x.com", "millis@x.com", "numeric@x.com", "seconds@x.com"]
    assert set(asc_emails[4:]) == {"bad@x.com", "missing@x.com"}
    assert set(desc_emails[4:]) == {"bad@x.com", "missing@x.com"}


def test_endpoint_facets_independent_of_filter(populated_dir):
    """facets 应反映全部 records 的主分类计数,与当前 category 过滤无关。"""
    resp_active = api.get_auths_accounts(category="active")
    resp_all = api.get_auths_accounts(category="all")
    assert resp_active["facets"] == resp_all["facets"]


def test_endpoint_default_includes_non_team_and_marks_limited(auths_dir):
    _write(auths_dir / "codex-team@x.com-team-h-oauth.json", refresh_token="rt")
    _write(auths_dir / "codex-plus@x.com-plus-h-oauth.json", refresh_token="rt")
    _write(auths_dir / "codex-free@x.com-free-h-oauth.json", refresh_token="rt")
    _write(auths_dir / "codex-unknown@x.com-unknown-h-oauth.json", refresh_token="rt")
    _write(auths_dir / "archive" / "codex-arch@x.com-plus-h.json", refresh_token="rt")

    resp = api.get_auths_accounts()
    by_email = {r["email"]: r for r in resp["items"]}

    assert set(by_email) == {"team@x.com", "plus@x.com", "free@x.com", "unknown@x.com"}
    assert by_email["team@x.com"]["is_team_plan"] is True
    assert by_email["team@x.com"]["is_limited_view"] is False
    for email in ("plus@x.com", "free@x.com", "unknown@x.com"):
        assert by_email[email]["is_team_plan"] is False
        assert by_email[email]["is_limited_view"] is True


def test_endpoint_plan_type_filter(auths_dir):
    _write(auths_dir / "codex-team@x.com-team-h-oauth.json", refresh_token="rt")
    _write(auths_dir / "codex-plus@x.com-plus-h-oauth.json", refresh_token="rt")
    _write(auths_dir / "codex-free@x.com-free-h-oauth.json", refresh_token="rt")
    _write(auths_dir / "codex-unknown@x.com-unknown-h-oauth.json", refresh_token="rt")

    assert [r["email"] for r in api.get_auths_accounts(plan_type="team")["items"]] == ["team@x.com"]
    assert [r["email"] for r in api.get_auths_accounts(plan_type="plus")["items"]] == ["plus@x.com"]
    assert [r["email"] for r in api.get_auths_accounts(plan_type="free")["items"]] == ["free@x.com"]
    assert [r["email"] for r in api.get_auths_accounts(plan_type="unknown")["items"]] == ["unknown@x.com"]
    assert api.get_auths_accounts(plan_type="all")["total"] == 4


def test_endpoint_invalid_plan_type_raises():
    with pytest.raises(HTTPException) as exc:
        api.get_auths_accounts(plan_type="enterprise")
    assert exc.value.status_code == 400


# ----- /api/auths/stats ----------------------------------------------------


def test_stats_endpoint_returns_split_fields(populated_dir):
    stats = api.get_auths_stats()
    # 文件口径 + 账号口径都返回
    assert "total_files" in stats
    assert "active_files" in stats
    assert "accounts_active" in stats
    assert "accounts_sold" in stats
    assert "accounts_archive" in stats
    assert "unique_emails" in stats
    # accounts_* 之和等于 unique_emails
    accounts_sum = sum(stats[k] for k in stats if k.startswith("accounts_"))
    assert accounts_sum == stats["unique_emails"]


# ----- /api/accounts/bulk-action ------------------------------------------


@pytest.fixture
def accounts_file(tmp_path, monkeypatch):
    path = tmp_path / "accounts.json"
    monkeypatch.setattr(accounts_module, "ACCOUNTS_FILE", path)
    monkeypatch.setattr(api, "_is_main_account_email", lambda email: (email or "").lower() == "main@x.com")
    return path


def _save_accounts(path: Path, rows: list[dict]):
    path.write_text(json.dumps(rows), encoding="utf-8")


def _load_accounts(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_bulk_action_confirm_false_previews_without_writes(auths_dir, accounts_file, monkeypatch):
    auth_file = auths_dir / "codex-sell@x.com-team-h-oauth.json"
    _write(auth_file, refresh_token="rt")
    _save_accounts(
        accounts_file,
        [{"email": "sell@x.com", "status": "active", "auth_file": str(auth_file)}],
    )
    cleanup_calls = []
    monkeypatch.setattr(
        "autoteam.sync_targets.delete_account_from_configured_targets",
        lambda *args, **kwargs: cleanup_calls.append((args, kwargs)) or {},
    )

    result = api.post_accounts_bulk_action(
        api.BulkActionParams(
            action="sell",
            confirm=False,
            items=[api.BulkActionItem(email="sell@x.com", plan_type="team")],
        )
    )

    assert result["preview"] is True
    assert result["results"][0]["status"] == "preview"
    assert _load_accounts(accounts_file)[0]["status"] == "active"
    assert cleanup_calls == []


def test_bulk_action_skips_main_non_team_missing_account_and_missing_oauth(auths_dir, accounts_file):
    _write(auths_dir / "codex-plus@x.com-plus-h-oauth.json", refresh_token="rt")
    _write(auths_dir / "codex-noauth@x.com-team-h-session.json", access_token="t")
    _save_accounts(
        accounts_file,
        [
            {"email": "main@x.com", "status": "active"},
            {"email": "plus@x.com", "status": "active"},
            {"email": "noauth@x.com", "status": "active"},
        ],
    )

    result = api.post_accounts_bulk_action(
        api.BulkActionParams(
            action="sell",
            confirm=False,
            items=[
                api.BulkActionItem(email="main@x.com", plan_type="team"),
                api.BulkActionItem(email="plus@x.com", plan_type="plus"),
                api.BulkActionItem(email="missing@x.com", plan_type="team"),
                api.BulkActionItem(email="noauth@x.com", plan_type="team"),
            ],
        )
    )

    reasons = [item["skipped_reason"] for item in result["results"]]
    assert reasons == ["main_account", "non_team_plan", "missing_account", "missing_oauth_rt"]


def test_bulk_sell_rejects_session_backup(auths_dir, accounts_file):
    session_file = auths_dir / "codex-session@x.com-team-h-session.json"
    _write(session_file, refresh_token="rt", credential_source="chatgpt_session")
    _save_accounts(
        accounts_file,
        [{"email": "session@x.com", "status": "active", "auth_file": str(session_file)}],
    )

    result = api.post_accounts_bulk_action(
        api.BulkActionParams(
            action="sell",
            confirm=False,
            items=[api.BulkActionItem(email="session@x.com", plan_type="team")],
        )
    )

    assert result["results"][0]["status"] == "skipped"
    assert result["results"][0]["skipped_reason"] == "missing_oauth_rt"


def test_bulk_sell_continues_after_item_failure(auths_dir, accounts_file, monkeypatch):
    good_auth = auths_dir / "codex-good@x.com-team-h-oauth.json"
    bad_auth = auths_dir / "codex-bad@x.com-team-h-oauth.json"
    _write(good_auth, refresh_token="rt")
    _write(bad_auth, refresh_token="rt")
    _save_accounts(
        accounts_file,
        [
            {"email": "bad@x.com", "status": "active", "auth_file": str(bad_auth)},
            {"email": "good@x.com", "status": "active", "auth_file": str(good_auth)},
        ],
    )
    monkeypatch.setattr("autoteam.auth_archive.archive_account_auth_file", lambda email, auth: str(Path(auth)))

    def fake_delete(email, **_kwargs):
        if email == "bad@x.com":
            raise RuntimeError("remote failed")
        return {"cpa": {"deleted": [email]}}

    monkeypatch.setattr("autoteam.sync_targets.delete_account_from_configured_targets", fake_delete)

    result = api.post_accounts_bulk_action(
        api.BulkActionParams(
            action="sell",
            confirm=True,
            items=[
                api.BulkActionItem(email="bad@x.com", plan_type="team"),
                api.BulkActionItem(email="good@x.com", plan_type="team"),
            ],
        )
    )

    assert [r["status"] for r in result["results"]] == ["failed", "done"]
    accounts_by_email = {a["email"]: a for a in _load_accounts(accounts_file)}
    assert accounts_by_email["bad@x.com"]["status"] == "active"
    assert accounts_by_email["good@x.com"]["status"] == "sold"


def test_bulk_delete_and_team_actions_return_409_when_lock_busy(accounts_file, monkeypatch):
    _save_accounts(accounts_file, [{"email": "delete@x.com", "status": "active"}])
    lock = threading.Lock()
    assert lock.acquire(blocking=False) is True
    monkeypatch.setattr(api, "_playwright_lock", lock)
    monkeypatch.setattr(api, "_auth_record_by_email", lambda: {"delete@x.com": {"plan_type": "team"}})
    try:
        with pytest.raises(HTTPException) as exc:
            api.post_accounts_bulk_action(
                api.BulkActionParams(
                    action="delete",
                    confirm=True,
                    items=[api.BulkActionItem(email="delete@x.com", plan_type="team")],
                )
            )
    finally:
        lock.release()

    assert exc.value.status_code == 409


def test_bulk_delete_continues_after_item_failure(accounts_file, monkeypatch):
    _save_accounts(
        accounts_file,
        [
            {"email": "bad@x.com", "status": "active"},
            {"email": "good@x.com", "status": "active"},
        ],
    )
    monkeypatch.setattr(api, "_auth_record_by_email", lambda: {
        "bad@x.com": {"plan_type": "team"},
        "good@x.com": {"plan_type": "team"},
    })
    monkeypatch.setattr(api, "_playwright_lock", threading.Lock())

    def fake_run(func, email, **kwargs):
        if email == "bad@x.com":
            raise RuntimeError("delete failed")
        return {"deleted": email, "kwargs": kwargs}

    monkeypatch.setattr(api._pw_executor, "run", fake_run)

    result = api.post_accounts_bulk_action(
        api.BulkActionParams(
            action="delete",
            confirm=True,
            options={"sync_cpa_after": False},
            items=[
                api.BulkActionItem(email="bad@x.com", plan_type="team"),
                api.BulkActionItem(email="good@x.com", plan_type="team"),
            ],
        )
    )

    assert [r["status"] for r in result["results"]] == ["failed", "done"]
    assert result["results"][1]["data"]["kwargs"] == {"sync_cpa_after": False}


def test_bulk_team_actions_continue_after_failure(accounts_file, monkeypatch):
    _save_accounts(
        accounts_file,
        [
            {"email": "bad@x.com", "status": "active"},
            {"email": "good@x.com", "status": "active"},
        ],
    )
    monkeypatch.setattr(api, "_auth_record_by_email", lambda: {
        "bad@x.com": {"plan_type": "team"},
        "good@x.com": {"plan_type": "team"},
    })
    monkeypatch.setattr(api, "_playwright_lock", threading.Lock())
    monkeypatch.setattr("autoteam.admin_state.get_admin_session_token", lambda: "session")
    monkeypatch.setattr("autoteam.admin_state.get_chatgpt_account_id", lambda: "acc-1")

    class FakeChatGPT:
        def _api_fetch(self, _method, path):
            if path.endswith("/users/u-bad"):
                return {"status": 500}
            return {"status": 204}

    monkeypatch.setattr(api, "_run_with_chatgpt_session", lambda callback: callback(FakeChatGPT()))
    monkeypatch.setattr(api._pw_executor, "run", lambda func, *args, **kwargs: func(*args, **kwargs))

    result = api.post_accounts_bulk_action(
        api.BulkActionParams(
            action="remove-team",
            confirm=True,
            items=[
                api.BulkActionItem(email="bad@x.com", type="member", user_id="u-bad", plan_type="team"),
                api.BulkActionItem(email="good@x.com", type="member", user_id="u-good", plan_type="team"),
            ],
        )
    )

    assert [r["status"] for r in result["results"]] == ["failed", "done"]
    accounts_by_email = {a["email"]: a for a in _load_accounts(accounts_file)}
    assert accounts_by_email["bad@x.com"]["status"] == "active"
    assert accounts_by_email["good@x.com"]["status"] == "standby"


def test_bulk_cancel_invite_executes_invite_path(accounts_file, monkeypatch):
    _save_accounts(accounts_file, [{"email": "invite@x.com", "status": "pending"}])
    monkeypatch.setattr(api, "_auth_record_by_email", lambda: {"invite@x.com": {"plan_type": "team"}})
    monkeypatch.setattr(api, "_playwright_lock", threading.Lock())
    monkeypatch.setattr("autoteam.admin_state.get_admin_session_token", lambda: "session")
    monkeypatch.setattr("autoteam.admin_state.get_chatgpt_account_id", lambda: "acc-1")
    paths = []

    class FakeChatGPT:
        def _api_fetch(self, method, path):
            paths.append((method, path))
            return {"status": 204}

    monkeypatch.setattr(api, "_run_with_chatgpt_session", lambda callback: callback(FakeChatGPT()))
    monkeypatch.setattr(api._pw_executor, "run", lambda func, *args, **kwargs: func(*args, **kwargs))

    result = api.post_accounts_bulk_action(
        api.BulkActionParams(
            action="cancel-invite",
            confirm=True,
            items=[api.BulkActionItem(email="invite@x.com", type="invite", user_id="inv-1", plan_type="team")],
        )
    )

    assert result["results"][0]["status"] == "done"
    assert paths == [("DELETE", "/backend-api/accounts/acc-1/invites/inv-1")]


def test_bulk_mark_invalid_writes_local_only(auths_dir, accounts_file, monkeypatch):
    _write(auths_dir / "codex-invalid@x.com-team-h-oauth.json", refresh_token="rt")
    _save_accounts(accounts_file, [{"email": "invalid@x.com", "status": "active", "health_status": "valid"}])
    remote_calls = []
    monkeypatch.setattr(
        "autoteam.sync_targets.delete_account_from_configured_targets",
        lambda *args, **kwargs: remote_calls.append((args, kwargs)),
    )

    result = api.post_accounts_bulk_action(
        api.BulkActionParams(
            action="mark-invalid",
            confirm=False,
            options={"reason": "auth_error", "last_error": "bad rt"},
            items=[api.BulkActionItem(email="invalid@x.com", plan_type="team")],
        )
    )

    assert result["preview"] is True
    assert result["results"][0]["status"] == "preview"
    assert _load_accounts(accounts_file)[0]["health_status"] == "valid"
    assert remote_calls == []

    result = api.post_accounts_bulk_action(
        api.BulkActionParams(
            action="mark-invalid",
            confirm=True,
            options={"reason": "auth_error", "last_error": "bad rt"},
            items=[api.BulkActionItem(email="invalid@x.com", plan_type="team")],
        )
    )

    assert result["results"][0]["status"] == "done"
    updated = _load_accounts(accounts_file)[0]
    assert updated["health_status"] == "invalid"
    assert updated["invalid_reason"] == "auth_error"
    assert updated["last_error"] == "bad rt"
    assert remote_calls == []
