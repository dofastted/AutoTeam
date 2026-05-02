from autoteam.account_lifecycle import mark_registered, registered_kwargs


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
