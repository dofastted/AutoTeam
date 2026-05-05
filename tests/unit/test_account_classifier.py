from autoteam.account_classifier import classify_account, derive_category, reconcile_usage_classification
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
        "usage_status": "inventory",
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
        "remote": {"sub2api": {"status": "present"}},
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
        "usage_status": "inventory",
        "cpa_status": "success",
        "rt_auth_file": "auths/example-oauth.json",
        "sync_disabled": False,
    }

    category = derive_category(account)

    assert category == "inventory"
    assert "category" not in account


def _make_account(**overrides):
    account = {
        "email": "user@example.com",
        "registration_status": REGISTRATION_REGISTERED,
        "health_status": HEALTH_VALID,
        "usage_status": "normal",
        "sync_disabled": False,
    }
    account.update(overrides)
    return account


def test_classifier_in_use_with_allocation_metadata():
    account = _make_account(
        usage_status=USAGE_IN_USE,
        cpa_status="success",
        rt_auth_file="auths/example-oauth.json",
        remote={"sub2api": {"status": "present"}},
        allocation={"allocated_to": "worker-1", "project": "proj-a"},
    )

    result = classify_account(account)

    assert result["category"] == "in_use"
    assert result["usage_status"] == USAGE_IN_USE


def test_classifier_not_registered_for_registering_status():
    account = _make_account(registration_status="registering")

    result = classify_account(account)

    assert result["category"] == "not_registered"


def test_classifier_in_use_reflects_sub2api_presence_before_registration_status():
    account = _make_account(
        registration_status="pending",
        health_status="unknown",
        usage_status=USAGE_IN_USE,
        allocation={"status": "in_use", "source": "sub2api"},
    )

    result = classify_account(account)

    assert result["category"] == "not_registered"


def test_classifier_rejects_in_use_with_401_marker():
    account = _make_account(
        usage_status=USAGE_IN_USE,
        cpa_status="success",
        rt_auth_file="auths/example-oauth.json",
        unavailable_reason="http_401",
        allocation={"status": "in_use", "source": "sub2api"},
    )

    result = classify_account(account)

    assert result["category"] == "invalid"


def test_classifier_rejects_in_use_with_string_sync_disabled():
    account = _make_account(
        usage_status=USAGE_IN_USE,
        cpa_status="success",
        rt_auth_file="auths/example-oauth.json",
        sync_disabled="true",
        remote={"sub2api": {"status": "present"}},
    )

    result = classify_account(account)

    assert result["category"] == "registered"
    assert result["usage_status"] == "normal"


def test_classifier_rejects_inventory_without_oauth_rt_file():
    account = _make_account(
        usage_status="inventory",
        cpa_status="success",
        auth_file="auths/example-session.json",
        credentials={"session": {"file": "auths/example-session.json", "present": True}},
    )

    result = classify_account(account)

    assert result["category"] == "registered"
    assert result["usage_status"] == "normal"


def test_classifier_accepts_legacy_oauth_auth_file_as_rt():
    account = _make_account(
        usage_status="inventory",
        cpa_status="success",
        auth_file="auths/example-oauth.json",
    )

    result = classify_account(account)

    assert result["category"] == "inventory"
    assert result["usage_status"] == "inventory"


def test_classifier_rejects_in_use_without_cpa_success():
    account = _make_account(
        usage_status=USAGE_IN_USE,
        cpa_status="pending",
        rt_auth_file="auths/example-oauth.json",
        allocation={"status": "in_use", "source": "sub2api"},
    )

    result = classify_account(account)

    assert result["category"] == "registered"


def test_classifier_rejects_in_use_without_sub2api_presence():
    account = _make_account(
        usage_status=USAGE_IN_USE,
        cpa_status="success",
        rt_auth_file="auths/example-oauth.json",
        allocation={"allocated_to": "worker-1"},
    )

    result = classify_account(account)

    assert result["category"] == "inventory"
    assert result["usage_status"] == "inventory"


def test_classifier_quota_exhausted_in_use_is_not_invalid():
    account = _make_account(
        health_status=HEALTH_QUOTA_EXHAUSTED,
        usage_status=USAGE_IN_USE,
        cpa_status="success",
        rt_auth_file="auths/example-oauth.json",
        remote={"sub2api": {"status": "present"}},
        allocation={"allocated_to": "worker-1"},
    )

    result = classify_account(account)

    assert result["category"] == "in_use"
    assert result["usage_status"] == "in_use"


def test_reconcile_usage_sets_in_use_only_when_sub2api_present():
    account = _make_account(
        usage_status="inventory",
        cpa_status="success",
        rt_auth_file="auths/example-oauth.json",
        remote={"sub2api": {"status": "missing"}},
        allocation={"status": "inventory"},
    )

    result = reconcile_usage_classification(account, sub2api_present=True)

    assert result["changed"] is True
    assert account["category"] == "in_use"
    assert account["usage_status"] == "in_use"
    assert account["allocation"]["status"] == "in_use"
    assert account["remote"]["sub2api"]["status"] == "present"


def test_reconcile_usage_demotes_unusable_in_use_to_normal_and_unavailable():
    account = _make_account(
        usage_status=USAGE_IN_USE,
        cpa_status="success",
        rt_auth_file="auths/example-oauth.json",
        health_status=HEALTH_INVALID,
        remote={"sub2api": {"status": "present"}},
        allocation={"status": "in_use"},
    )

    result = reconcile_usage_classification(account, sub2api_present=True)

    assert result["changed"] is True
    assert account["category"] == "invalid"
    assert account["usage_status"] == "normal"
    assert account["status"] == "unavailable"
    assert account["allocation"]["status"] == "released"


def test_classifier_main_account_keeps_current_inventory_behavior():
    account = _make_account(
        is_main_account=True,
        usage_status="inventory",
        cpa_status="success",
        rt_auth_file="auths/main-oauth.json",
    )

    result = classify_account(account)

    assert result["category"] == "inventory"
    assert result["usage_status"] == "inventory"


def test_classifier_email_only_account_falls_back_without_error():
    account = {"email": "only@example.com"}

    result = classify_account(account)

    assert result["category"] == "not_registered"
    assert result["email"] == "only@example.com"
