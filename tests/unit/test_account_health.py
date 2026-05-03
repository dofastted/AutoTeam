from autoteam.account_health import (
    ALL_INVALID_REASONS,
    INVALID_REASON_AUTH_ERROR,
    INVALID_REASON_DEACTIVATED,
    INVALID_REASON_QUOTA,
    INVALID_REASON_TOKEN_REVOKED,
    is_invalid,
    mark_deactivated,
    mark_invalid,
    summarize_health,
)
from autoteam.account_models import (
    HEALTH_DEACTIVATED,
    HEALTH_INVALID,
    HEALTH_VALID,
    USAGE_IN_USE,
    USAGE_INVENTORY,
    USAGE_NORMAL,
    USAGE_SOLD,
    default_v2_account,
)


def test_mark_invalid_moves_inventory_account_back_to_normal():
    account = default_v2_account(
        email="inventory@example.com",
        usage_status=USAGE_INVENTORY,
        health_status=HEALTH_VALID,
    )

    result = mark_invalid(
        account,
        reason=INVALID_REASON_AUTH_ERROR,
        last_error="HTTP 401",
        now=1700000000,
    )

    assert result["changed"] is True
    assert result["warning"] is None
    assert "health_status" in result["applied"]
    assert "invalid_reason" in result["applied"]
    assert "invalid_at" in result["applied"]
    assert "usage_status_inventory_to_normal" in result["applied"]
    assert account["health_status"] == HEALTH_INVALID
    assert account["invalid_reason"] == INVALID_REASON_AUTH_ERROR
    assert account["invalid_at"] == 1700000000
    assert account["last_error"] == "HTTP 401"
    assert account["updated_at"] == 1700000000
    assert account["usage_status"] == USAGE_NORMAL


def test_mark_invalid_keeps_in_use_usage_status():
    account = default_v2_account(
        email="inuse@example.com",
        usage_status=USAGE_IN_USE,
        health_status=HEALTH_VALID,
    )

    result = mark_invalid(
        account,
        reason=INVALID_REASON_TOKEN_REVOKED,
        last_error="revoked",
        now=1700000001,
    )

    assert result["changed"] is True
    assert "usage_status_inventory_to_normal" not in result["applied"]
    assert account["usage_status"] == USAGE_IN_USE
    assert account["invalid_reason"] == INVALID_REASON_TOKEN_REVOKED


def test_mark_invalid_keeps_sold_usage_status():
    account = default_v2_account(
        email="sold@example.com",
        usage_status=USAGE_SOLD,
        health_status=HEALTH_VALID,
    )

    result = mark_invalid(
        account,
        reason="fatal_sync_error",
        last_error="fatal",
        now=1700000002,
    )

    assert result["changed"] is True
    assert "usage_status_inventory_to_normal" not in result["applied"]
    assert account["usage_status"] == USAGE_SOLD
    assert account["invalid_reason"] == "fatal_sync_error"


def test_mark_invalid_warns_for_main_account():
    account = default_v2_account(
        email="main@example.com",
        role="main",
        usage_status=USAGE_NORMAL,
        health_status=HEALTH_VALID,
    )

    result = mark_invalid(
        account,
        reason=INVALID_REASON_AUTH_ERROR,
        last_error="401",
        now=1700000003,
    )

    assert result["warning"] == "main_account"
    assert account["health_status"] == HEALTH_INVALID


def test_mark_deactivated_sets_sync_disabled_and_moves_inventory_to_normal():
    account = default_v2_account(
        email="dead@example.com",
        usage_status=USAGE_INVENTORY,
        health_status=HEALTH_VALID,
        sync_disabled=False,
    )

    result = mark_deactivated(account, last_error="account_deactivated", now=1700000004)

    assert result["changed"] is True
    assert "health_status" in result["applied"]
    assert "invalid_reason" in result["applied"]
    assert "sync_disabled" in result["applied"]
    assert "usage_status_inventory_to_normal" in result["applied"]
    assert account["health_status"] == HEALTH_DEACTIVATED
    assert account["invalid_reason"] == INVALID_REASON_DEACTIVATED
    assert account["sync_disabled"] is True
    assert account["usage_status"] == USAGE_NORMAL
    assert account["updated_at"] == 1700000004


def test_is_invalid_distinguishes_invalid_deactivated_and_valid():
    assert is_invalid({"health_status": HEALTH_INVALID}) is True
    assert is_invalid({"health_status": HEALTH_DEACTIVATED}) is True
    assert is_invalid({"health_status": HEALTH_VALID}) is False


def test_summarize_health_counts_mixed_statuses():
    accounts = [
        {"health_status": HEALTH_VALID},
        {"health_status": HEALTH_INVALID},
        {"health_status": HEALTH_INVALID},
        {"health_status": HEALTH_DEACTIVATED},
        {},
    ]

    summary = summarize_health(accounts)

    assert summary == {
        "valid": 1,
        "invalid": 2,
        "deactivated": 1,
        "unknown": 1,
    }


def test_mark_invalid_allows_free_form_reason():
    account = default_v2_account(email="free@example.com", health_status=HEALTH_VALID)

    result = mark_invalid(
        account,
        reason="custom_fatal_reason",
        last_error="custom",
        now=1700000005,
    )

    assert result["changed"] is True
    assert account["invalid_reason"] == "custom_fatal_reason"


def test_all_invalid_reasons_contains_known_constants():
    assert INVALID_REASON_AUTH_ERROR in ALL_INVALID_REASONS
    assert INVALID_REASON_DEACTIVATED in ALL_INVALID_REASONS
    assert INVALID_REASON_TOKEN_REVOKED in ALL_INVALID_REASONS
    assert INVALID_REASON_QUOTA in ALL_INVALID_REASONS
