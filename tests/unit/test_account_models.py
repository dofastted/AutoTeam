from autoteam.account_models import (
    ALL_USAGE_STATUSES,
    HEALTH_DEACTIVATED,
    HEALTH_QUOTA_EXHAUSTED,
    REGISTRATION_PLANNED,
    TEAM_ACTIVE,
    TEAM_UNKNOWN,
    USAGE_NORMAL,
    USAGE_SELF_USE,
    USAGE_SOLD,
    default_v2_account,
    legacy_status_to_axes,
)


def test_legacy_status_to_axes_maps_sold_and_disables_sync():
    mapped = legacy_status_to_axes("sold")

    assert mapped["usage_status"] == USAGE_SOLD
    assert mapped["sync_disabled"] is True


def test_legacy_status_to_axes_maps_active_team_status():
    mapped = legacy_status_to_axes("active")

    assert mapped == {"team_status": TEAM_ACTIVE}


def test_legacy_status_to_axes_maps_exhausted_to_quota_exhausted():
    mapped = legacy_status_to_axes("exhausted")

    assert mapped["health_status"] == HEALTH_QUOTA_EXHAUSTED
    assert mapped["team_status"] == TEAM_ACTIVE


def test_legacy_status_to_axes_maps_unavailable_reason_to_deactivated():
    mapped = legacy_status_to_axes("unavailable", unavailable_reason="account_deactivated")

    assert mapped == {"health_status": HEALTH_DEACTIVATED}


def test_default_v2_account_has_schema_version_and_axis_defaults():
    account = default_v2_account(email="abc")

    assert account["schema_version"] == 2
    assert account["email"] == "abc"
    assert account["registration_status"] == REGISTRATION_PLANNED
    assert account["health_status"] == "unknown"
    assert account["usage_status"] == USAGE_NORMAL
    assert account["team_status"] == TEAM_UNKNOWN
    assert account["credentials"]["oauth_rt"]["has_refresh_token"] is False
    assert account["remote"]["cpa"]["status"] == "unknown"


def test_default_v2_account_merges_nested_overrides():
    account = default_v2_account(
        mail={"provider": "mo_email", "index": 7},
        credentials={"oauth_rt": {"present": True}},
        sale={"delivered": True},
    )

    assert account["mail"]["provider"] == "mo_email"
    assert account["mail"]["index"] == 7
    assert account["mail"]["domain"] is None
    assert account["credentials"]["oauth_rt"]["present"] is True
    assert account["credentials"]["oauth_rt"]["has_refresh_token"] is False
    assert account["sale"]["delivered"] is True


def test_all_usage_statuses_include_inventory_sold_and_self_use():
    assert "inventory" in ALL_USAGE_STATUSES
    assert "sold" in ALL_USAGE_STATUSES
    assert USAGE_SELF_USE in ALL_USAGE_STATUSES
