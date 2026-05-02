import json

from autoteam.account_lifecycle import (
    inventory_kwargs,
    mark_inventory,
    mark_registered,
    record_rt_obtained,
    registered_kwargs,
    rt_obtained_kwargs,
)


def test_mark_registered_applies_registration_team_usage_and_updated_at():
    account = {"id": "a", "email": "x"}

    result = mark_registered(account, now=12345)

    assert result["changed"] is True
    assert result["applied"] == [
        "registration_status",
        "team_status",
        "usage_status",
        "updated_at",
    ]
    assert account["registration_status"] == "registered"
    assert account["team_status"] == "active"
    assert account["usage_status"] == "normal"
    assert account["updated_at"] == 12345


def test_mark_registered_preserves_inventory_usage_status():
    account = {"id": "a", "email": "x", "usage_status": "inventory"}

    result = mark_registered(account, now=12345)

    assert result["changed"] is True
    assert "usage_status" not in result["applied"]
    assert account["usage_status"] == "inventory"


def test_mark_registered_preserves_in_use_usage_status():
    account = {"id": "a", "email": "x", "usage_status": "in_use"}

    result = mark_registered(account, now=12345)

    assert result["changed"] is True
    assert "usage_status" not in result["applied"]
    assert account["usage_status"] == "in_use"


def test_mark_registered_returns_changed_false_for_compliant_account():
    account = {
        "id": "a",
        "email": "x",
        "registration_status": "registered",
        "team_status": "active",
        "usage_status": "normal",
        "updated_at": 12345,
    }

    result = mark_registered(account, now=12345)

    assert result == {
        "changed": False,
        "applied": [],
        "skipped": [
            "registration_status",
            "team_status",
            "usage_status",
            "updated_at",
        ],
    }


def test_registered_kwargs_returns_expected_fields():
    assert registered_kwargs(now=12345) == {
        "registration_status": "registered",
        "team_status": "active",
        "usage_status": "normal",
        "updated_at": 12345,
    }


def test_record_rt_obtained_writes_top_level_and_credentials_fields(tmp_path):
    account = {"id": "a", "email": "x"}
    rt_file = tmp_path / "codex-x-oauth.json"
    rt_file.write_text(json.dumps({"tokens": {"refresh_token": "RT"}}), encoding="utf-8")

    result = record_rt_obtained(account, rt_file, has_refresh_token=True, now=12345)

    assert result == {
        "changed": True,
        "applied": [
            "rt_auth_file",
            "rt_obtained_at",
            "credentials.oauth_rt.file",
            "credentials.oauth_rt.present",
            "credentials.oauth_rt.has_refresh_token",
            "credentials.oauth_rt.obtained_at",
            "updated_at",
        ],
        "has_refresh_token": True,
    }
    assert account["rt_auth_file"] == str(rt_file)
    assert account["rt_obtained_at"] == 12345
    assert account["updated_at"] == 12345
    assert account["credentials"]["oauth_rt"] == {
        "file": str(rt_file),
        "present": True,
        "has_refresh_token": True,
        "obtained_at": 12345,
    }


def test_record_rt_obtained_auto_detects_refresh_token_presence(tmp_path):
    with_rt_file = tmp_path / "codex-with-rt-oauth.json"
    with_rt_file.write_text(json.dumps({"tokens": {"refresh_token": "RT"}}), encoding="utf-8")
    without_rt_file = tmp_path / "codex-without-rt-oauth.json"
    without_rt_file.write_text("{}", encoding="utf-8")

    with_rt_account = {"id": "a", "email": "with@example.com"}
    without_rt_account = {"id": "b", "email": "without@example.com"}

    with_rt_result = record_rt_obtained(with_rt_account, with_rt_file, now=12345)
    without_rt_result = record_rt_obtained(without_rt_account, without_rt_file, now=12345)

    assert with_rt_result["has_refresh_token"] is True
    assert with_rt_account["credentials"]["oauth_rt"]["has_refresh_token"] is True
    assert without_rt_result["has_refresh_token"] is False
    assert without_rt_account["credentials"]["oauth_rt"]["has_refresh_token"] is False


def test_record_rt_obtained_returns_changed_false_for_compliant_account(tmp_path):
    rt_file = tmp_path / "codex-x-oauth.json"
    rt_file.write_text(json.dumps({"tokens": {"refresh_token": "RT"}}), encoding="utf-8")
    account = {
        "id": "a",
        "email": "x",
        "rt_auth_file": str(rt_file),
        "rt_obtained_at": 12345,
        "updated_at": 12345,
        "credentials": {
            "oauth_rt": {
                "file": str(rt_file),
                "present": True,
                "has_refresh_token": True,
                "obtained_at": 12345,
            }
        },
    }

    result = record_rt_obtained(account, rt_file, has_refresh_token=True, now=12345)

    assert result == {"changed": False, "applied": [], "has_refresh_token": True}


def test_rt_obtained_kwargs_returns_flat_fields_only(tmp_path):
    rt_file = tmp_path / "codex-x-oauth.json"
    rt_file.write_text(json.dumps({"tokens": {"refresh_token": "RT"}}), encoding="utf-8")

    assert rt_obtained_kwargs(rt_file, has_refresh_token=True, now=12345) == {
        "rt_auth_file": str(rt_file),
        "rt_obtained_at": 12345,
        "updated_at": 12345,
    }


def test_mark_inventory_applies_usage_health_cpa_updated_at_and_allocation():
    account = {"id": "a", "email": "x"}

    result = mark_inventory(account, now=12345)

    assert result == {
        "changed": True,
        "applied": [
            "usage_status",
            "health_status",
            "cpa_status",
            "allocation.status",
            "updated_at",
        ],
        "reason": None,
    }
    assert account["usage_status"] == "inventory"
    assert account["health_status"] == "valid"
    assert account["cpa_status"] == "success"
    assert account["updated_at"] == 12345
    assert account["allocation"] == {
        "status": "inventory",
        "project": "",
        "allocation_id": "",
    }


def test_mark_inventory_skips_main_account():
    account = {
        "id": "a",
        "email": "main@example.com",
        "role": "main",
        "usage_status": "normal",
        "health_status": "unknown",
    }

    result = mark_inventory(account, now=12345)

    assert result == {
        "changed": False,
        "applied": [],
        "reason": "main_account",
    }
    assert account == {
        "id": "a",
        "email": "main@example.com",
        "role": "main",
        "usage_status": "normal",
        "health_status": "unknown",
    }


def test_mark_inventory_skips_sold_account():
    account = {
        "id": "a",
        "email": "sold@example.com",
        "usage_status": "sold",
        "health_status": "valid",
    }

    result = mark_inventory(account, now=12345)

    assert result == {
        "changed": False,
        "applied": [],
        "reason": "sold",
    }
    assert account["usage_status"] == "sold"
    assert account["health_status"] == "valid"


def test_mark_inventory_returns_changed_false_for_compliant_account():
    account = {
        "id": "a",
        "email": "x",
        "usage_status": "inventory",
        "health_status": "valid",
        "cpa_status": "success",
        "updated_at": 12345,
        "allocation": {
            "status": "inventory",
            "project": "",
            "allocation_id": "",
        },
    }

    result = mark_inventory(account, now=12345)

    assert result == {
        "changed": False,
        "applied": [],
        "reason": None,
    }


def test_mark_inventory_overwrites_existing_allocation_status():
    account = {
        "id": "a",
        "email": "x",
        "allocation": {
            "status": "in_use",
            "project": "proj-1",
            "allocation_id": "alloc-1",
        },
    }

    result = mark_inventory(account, now=12345)

    assert result["changed"] is True
    assert "allocation.status" in result["applied"]
    assert account["allocation"] == {
        "status": "inventory",
        "project": "proj-1",
        "allocation_id": "alloc-1",
    }


def test_inventory_kwargs_returns_flat_fields_only():
    assert inventory_kwargs(now=12345) == {
        "usage_status": "inventory",
        "health_status": "valid",
        "cpa_status": "success",
        "updated_at": 12345,
    }
