from autoteam.account_remote import (
    ALL_REMOTE_STATUSES,
    REMOTE_KIND_CPA,
    REMOTE_KIND_SUB2API,
    REMOTE_STATUS_DISABLED,
    REMOTE_STATUS_FAILED,
    REMOTE_STATUS_MISSING,
    REMOTE_STATUS_PRESENT,
    REMOTE_STATUS_UNKNOWN,
    apply_disabled_status,
    default_remote_block,
    get_remote_status,
    set_remote_status,
    summarize_remote,
)


def test_default_remote_block_uses_unknown_for_both_kinds():
    block = default_remote_block()

    assert block == {
        REMOTE_KIND_CPA: {"status": REMOTE_STATUS_UNKNOWN},
        REMOTE_KIND_SUB2API: {"status": REMOTE_STATUS_UNKNOWN},
    }


def test_set_remote_status_writes_cpa_present_with_auth_name():
    account = {"email": "user@example.com"}

    result = set_remote_status(
        account,
        kind=REMOTE_KIND_CPA,
        status=REMOTE_STATUS_PRESENT,
        auth_name="codex-x.json",
        now=1700000000,
    )

    assert result["changed"] is True
    assert result["block"] == {
        "status": REMOTE_STATUS_PRESENT,
        "checked_at": 1700000000,
        "auth_name": "codex-x.json",
    }
    assert account["remote"][REMOTE_KIND_CPA] == result["block"]
    assert account["remote"][REMOTE_KIND_SUB2API] == {"status": REMOTE_STATUS_UNKNOWN}


def test_set_remote_status_repeated_same_value_returns_unchanged():
    account = {"email": "user@example.com"}

    first = set_remote_status(
        account,
        kind=REMOTE_KIND_CPA,
        status=REMOTE_STATUS_PRESENT,
        auth_name="codex-x.json",
        now=1700000001,
    )
    second = set_remote_status(
        account,
        kind=REMOTE_KIND_CPA,
        status=REMOTE_STATUS_PRESENT,
        auth_name="codex-x.json",
        now=1700000001,
    )

    assert first["changed"] is True
    assert second["changed"] is False


def test_set_remote_status_raises_for_invalid_kind():
    account = {"email": "user@example.com"}

    try:
        set_remote_status(account, kind="bad-kind", status=REMOTE_STATUS_PRESENT, now=1700000002)
    except ValueError as exc:
        assert "unsupported remote kind" in str(exc)
    else:
        raise AssertionError("expected ValueError for invalid kind")


def test_set_remote_status_raises_for_invalid_status():
    account = {"email": "user@example.com"}

    try:
        set_remote_status(account, kind=REMOTE_KIND_CPA, status="bad-status", now=1700000003)
    except ValueError as exc:
        assert "unsupported remote status" in str(exc)
    else:
        raise AssertionError("expected ValueError for invalid status")


def test_get_remote_status_returns_unknown_when_remote_is_missing():
    assert get_remote_status({}, REMOTE_KIND_CPA) == REMOTE_STATUS_UNKNOWN
    assert get_remote_status({"remote": {}}, REMOTE_KIND_SUB2API) == REMOTE_STATUS_UNKNOWN


def test_summarize_remote_counts_mixed_accounts():
    accounts = [
        {},
        {"remote": {REMOTE_KIND_CPA: {"status": REMOTE_STATUS_PRESENT}}},
        {"remote": {REMOTE_KIND_SUB2API: {"status": REMOTE_STATUS_MISSING}}},
        {
            "remote": {
                REMOTE_KIND_CPA: {"status": REMOTE_STATUS_FAILED},
                REMOTE_KIND_SUB2API: {"status": REMOTE_STATUS_PRESENT},
            }
        },
        {
            "sync_disabled": True,
            "remote": {
                REMOTE_KIND_CPA: {"status": REMOTE_STATUS_DISABLED},
                REMOTE_KIND_SUB2API: {"status": REMOTE_STATUS_DISABLED},
            },
        },
    ]

    summary = summarize_remote(accounts)

    assert summary == {
        REMOTE_KIND_CPA: {
            REMOTE_STATUS_PRESENT: 1,
            REMOTE_STATUS_MISSING: 0,
            REMOTE_STATUS_FAILED: 1,
            REMOTE_STATUS_DISABLED: 1,
            REMOTE_STATUS_UNKNOWN: 2,
        },
        REMOTE_KIND_SUB2API: {
            REMOTE_STATUS_PRESENT: 1,
            REMOTE_STATUS_MISSING: 1,
            REMOTE_STATUS_FAILED: 0,
            REMOTE_STATUS_DISABLED: 1,
            REMOTE_STATUS_UNKNOWN: 2,
        },
    }
    assert set(summary[REMOTE_KIND_CPA]) == set(ALL_REMOTE_STATUSES)


def test_apply_disabled_status_marks_both_targets_when_sync_disabled():
    account = {"email": "user@example.com", "sync_disabled": True}

    result = apply_disabled_status(account)

    assert result["changed"] is True
    assert account["remote"][REMOTE_KIND_CPA]["status"] == REMOTE_STATUS_DISABLED
    assert account["remote"][REMOTE_KIND_SUB2API]["status"] == REMOTE_STATUS_DISABLED
    assert isinstance(account["remote"][REMOTE_KIND_CPA]["checked_at"], int)
    assert account["remote"][REMOTE_KIND_CPA]["checked_at"] == account["remote"][REMOTE_KIND_SUB2API]["checked_at"]


def test_apply_disabled_status_keeps_account_unchanged_when_sync_not_disabled():
    account_false = {"email": "false@example.com", "sync_disabled": False}
    account_missing = {"email": "missing@example.com"}

    result_false = apply_disabled_status(account_false)
    result_missing = apply_disabled_status(account_missing)

    assert result_false["changed"] is False
    assert result_missing["changed"] is False
    assert "remote" not in account_false
    assert "remote" not in account_missing
