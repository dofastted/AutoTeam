from autoteam import accounts, manual_account


def test_manual_account_finalize_saves_local_oauth_without_remote_sync(tmp_path, monkeypatch):
    accounts_file = tmp_path / "accounts.json"
    auth_file = tmp_path / "codex-user@example.com-team-abc-oauth.json"
    auth_file.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(accounts, "ACCOUNTS_FILE", accounts_file)
    save_sources = []
    monkeypatch.setattr(
        manual_account,
        "save_auth_file",
        lambda _bundle, source=None: save_sources.append(source) or str(auth_file),
    )
    monkeypatch.setattr(manual_account, "check_codex_quota", lambda *_args, **_kwargs: ("ok", {"primary_pct": 20}))

    flow = manual_account.ManualAccountFlow()
    result = flow._finalize_account(
        {
            "email": "user@example.com",
            "plan_type": "team",
            "access_token": "token-1",
            "account_id": "acc-1",
        }
    )

    latest = accounts.find_account(accounts.load_accounts(), "user@example.com")
    assert result["status"] == "completed"
    assert result["account"]["auth_file"] == str(auth_file)
    assert result["account"]["rt_auth_file"] == str(auth_file)
    assert latest["status"] == accounts.STATUS_ACTIVE
    assert latest["auth_file"] == str(auth_file)
    assert latest["rt_auth_file"] == str(auth_file)
    assert latest["last_quota"] == {"primary_pct": 20}
    assert save_sources == ["oauth"]
