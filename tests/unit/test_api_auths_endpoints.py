"""Tests for /api/auths/* endpoints and helpers (auths/ flat scan)."""
import json
from pathlib import Path

import pytest
from fastapi import HTTPException

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
    assert info["kind"] == "oauth"
    assert info["filename"] == "codex-foo@bar.com-team-abc12345-oauth.json"


def test_parse_auth_filename_root_session():
    info = api._parse_auth_filename("codex-foo@bar.com-team-abc12345-session.json")
    assert info is not None
    assert info["email"] == "foo@bar.com"
    assert info["team_hash"] == "abc12345"
    assert info["kind"] == "session"
    assert info["filename"] == "codex-foo@bar.com-team-abc12345-session.json"


def test_parse_auth_filename_subdir_plain():
    info = api._parse_auth_filename("codex-foo@bar.com-team-abc12345.json")
    assert info is not None
    assert info["email"] == "foo@bar.com"
    assert info["team_hash"] == "abc12345"
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


def test_primary_category_priority_archive_over_active():
    assert api._bucket_primary_category({"active", "archive"}) == "archive"


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
    _write(auths_dir / "codex-iso@x.com-team-h-oauth.json", refresh_token="rt", expired="2026-05-10T00:00:00Z")
    _write(auths_dir / "codex-seconds@x.com-team-h-oauth.json", refresh_token="rt", expired=1778630400)
    _write(auths_dir / "codex-millis@x.com-team-h-oauth.json", refresh_token="rt", expired=1779840000000)
    _write(auths_dir / "codex-bad@x.com-team-h-oauth.json", refresh_token="rt", expired="not-a-date")
    _write(auths_dir / "codex-missing@x.com-team-h-oauth.json", refresh_token="rt")

    asc = api.get_auths_accounts(sort="expired_asc", page_size=10)
    desc = api.get_auths_accounts(sort="expired_desc", page_size=10)

    assert [r["email"] for r in asc["items"]] == [
        "iso@x.com",
        "seconds@x.com",
        "millis@x.com",
        "missing@x.com",
        "bad@x.com",
    ]
    assert [r["email"] for r in desc["items"]] == [
        "millis@x.com",
        "seconds@x.com",
        "iso@x.com",
        "missing@x.com",
        "bad@x.com",
    ]


def test_endpoint_facets_independent_of_filter(populated_dir):
    """facets 应反映全部 records 的主分类计数,与当前 category 过滤无关。"""
    resp_active = api.get_auths_accounts(category="active")
    resp_all = api.get_auths_accounts(category="all")
    assert resp_active["facets"] == resp_all["facets"]


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
