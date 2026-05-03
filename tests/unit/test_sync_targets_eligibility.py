from autoteam.sync_targets import account_skip_reason, filter_sync_eligible, should_sync_account


def test_should_sync_inventory_account():
    account = {
        "email": "inventory@example.com",
        "usage_status": "inventory",
        "role": "child",
        "health_status": "valid",
        "sync_disabled": False,
    }

    assert should_sync_account(account) is True
    assert account_skip_reason(account) is None


def test_should_skip_sync_disabled_account():
    account = {"email": "disabled@example.com", "sync_disabled": True}

    assert should_sync_account(account) is False
    assert account_skip_reason(account) == "sync_disabled"


def test_should_skip_sold_account():
    account = {"email": "sold@example.com", "usage_status": "sold"}

    assert should_sync_account(account) is False
    assert account_skip_reason(account) == "sold"


def test_should_skip_main_account():
    account = {"email": "main@example.com", "role": "main"}

    assert should_sync_account(account) is False
    assert account_skip_reason(account) == "main_account"


def test_should_skip_deactivated_account():
    account = {"email": "dead@example.com", "health_status": "deactivated"}

    assert should_sync_account(account) is False
    assert account_skip_reason(account) == "deactivated"


def test_filter_sync_eligible_preserves_order_for_mixed_accounts():
    accounts = [
        {"email": "first@example.com", "usage_status": "inventory"},
        {"email": "skip-disabled@example.com", "sync_disabled": True},
        {"email": "second@example.com", "status": "active"},
        {"email": "skip-main@example.com", "role": "main"},
        {"email": "third@example.com", "health_status": "valid"},
    ]

    result = filter_sync_eligible(accounts)

    assert result == [
        accounts[0],
        accounts[2],
        accounts[4],
    ]


def test_filter_sync_eligible_returns_empty_list_for_empty_input():
    assert filter_sync_eligible([]) == []
