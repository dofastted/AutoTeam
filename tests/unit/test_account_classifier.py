from autoteam.account_classifier import classify_account, derive_category
from autoteam.account_models import (
    HEALTH_DEACTIVATED,
    HEALTH_INVALID,
    HEALTH_QUOTA_EXHAUSTED,
    HEALTH_RISK_BLOCKED,
    HEALTH_VALID,
    REGISTRATION_PLANNED,
    REGISTRATION_REGISTERED,
    USAGE_IN_USE,
    USAGE_SOLD,
)


def test_classify_account_returns_not_registered_for_none():
    account = classify_account(None)

    assert account["category"] == "not_registered"


def test_classify_account_returns_not_registered_for_empty_dict():
    account = {}

    result = classify_account(account)

    assert result is account
    assert account["category"] == "not_registered"


def test_classify_account_marks_registered_when_not_inventory_or_in_use():
    account = {
        "registration_status": REGISTRATION_REGISTERED,
        "health_status": HEALTH_VALID,
        "usage_status": "normal",
        "cpa_status": "pending",
        "sync_disabled": False,
    }

    result = classify_account(account)

    assert result["category"] == "registered"
    assert result["usage_status"] == "normal"


def test_classify_account_marks_inventory_when_rt_is_ready():
    account = {
        "registration_status": REGISTRATION_REGISTERED,
        "health_status": HEALTH_VALID,
        "usage_status": "normal",
        "cpa_status": "success",
        "rt_auth_file": "auths/example-oauth.json",
        "sync_disabled": False,
    }

    result = classify_account(account)

    assert result["category"] == "inventory"
    assert result["usage_status"] == "inventory"


def test_classify_account_marks_in_use_before_inventory():
    account = {
        "registration_status": REGISTRATION_REGISTERED,
        "health_status": HEALTH_VALID,
        "usage_status": USAGE_IN_USE,
        "cpa_status": "success",
        "rt_auth_file": "auths/example-oauth.json",
        "sync_disabled": False,
    }

    result = classify_account(account)

    assert result["category"] == "in_use"
    assert result["usage_status"] == USAGE_IN_USE


def test_classify_account_marks_invalid_for_invalid_health():
    for health_status in (HEALTH_INVALID, HEALTH_DEACTIVATED, HEALTH_RISK_BLOCKED):
        account = {
            "registration_status": REGISTRATION_REGISTERED,
            "health_status": health_status,
            "usage_status": "normal",
        }

        result = classify_account(account, in_place=False)

        assert result["category"] == "invalid"
        assert account.get("category") is None


def test_classify_account_marks_sold_when_sale_has_sold_at():
    account = {
        "registration_status": REGISTRATION_REGISTERED,
        "health_status": HEALTH_VALID,
        "usage_status": "normal",
        "sale": {"sold_at": 123.0},
        "sync_disabled": False,
    }

    result = classify_account(account)

    assert result["category"] == "sold"
    assert result["usage_status"] == USAGE_SOLD
    assert result["sync_disabled"] is True


def test_classify_account_marks_sold_when_usage_status_is_sold():
    account = {
        "registration_status": REGISTRATION_REGISTERED,
        "health_status": HEALTH_VALID,
        "usage_status": USAGE_SOLD,
    }

    result = classify_account(account)

    assert result["category"] == "sold"
    assert result["sync_disabled"] is True


def test_classify_account_marks_sold_when_legacy_status_is_sold():
    account = {
        "registration_status": REGISTRATION_REGISTERED,
        "health_status": HEALTH_VALID,
        "status": "sold",
    }

    result = classify_account(account)

    assert result["category"] == "sold"
    assert result["usage_status"] == USAGE_SOLD


def test_classify_account_marks_not_registered_when_registration_not_complete():
    account = {
        "registration_status": REGISTRATION_PLANNED,
        "health_status": HEALTH_VALID,
        "usage_status": "normal",
    }

    result = classify_account(account)

    assert result["category"] == "not_registered"


def test_classify_account_prefers_sold_over_invalid():
    account = {
        "registration_status": REGISTRATION_REGISTERED,
        "health_status": HEALTH_INVALID,
        "sale": {"sold_at": 123.0},
        "sync_disabled": False,
    }

    result = classify_account(account)

    assert result["category"] == "sold"
    assert result["sync_disabled"] is True


def test_classify_account_does_not_treat_quota_exhausted_as_invalid():
    account = {
        "registration_status": REGISTRATION_REGISTERED,
        "health_status": HEALTH_QUOTA_EXHAUSTED,
        "usage_status": "normal",
        "cpa_status": "pending",
    }

    result = classify_account(account)

    assert result["category"] == "registered"


def test_derive_category_is_pure_function():
    account = {
        "registration_status": REGISTRATION_REGISTERED,
        "health_status": HEALTH_VALID,
        "usage_status": "normal",
        "cpa_status": "success",
        "rt_auth_file": "auths/example-oauth.json",
        "sync_disabled": False,
    }

    category = derive_category(account)

    assert category == "inventory"
    assert "category" not in account
