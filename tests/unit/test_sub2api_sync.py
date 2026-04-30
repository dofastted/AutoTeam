import base64
import json
from datetime import datetime, timezone

from autoteam import sub2api_sync
from autoteam.codex_auth import CODEX_CLIENT_ID


def _jwt(payload: dict) -> str:
    header = base64.urlsafe_b64encode(json.dumps({"alg": "none"}).encode()).rstrip(b"=").decode()
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    return f"{header}.{body}."


def test_build_credentials_matches_openai_oauth_shape():
    expires_iso = "2026-04-25T05:44:19Z"
    id_token = _jwt(
        {
            "aud": [CODEX_CLIENT_ID],
            "email": "tmp@example.com",
            "https://api.openai.com/auth": {
                "chatgpt_account_id": "acct-1",
                "chatgpt_user_id": "user-1",
                "chatgpt_plan_type": "team",
                "chatgpt_subscription_active_until": "2026-05-05T15:55:38+00:00",
                "organizations": [{"id": "org-1", "is_default": True}],
            },
        }
    )

    credentials = sub2api_sync._build_credentials(
        {
            "access_token": "at-1",
            "refresh_token": "rt-1",
            "id_token": id_token,
            "expired": expires_iso,
            "model_mapping": {"gpt-5.4": "gpt-5.4"},
        }
    )

    assert credentials == {
        "access_token": "at-1",
        "expires_at": int(datetime.fromisoformat(expires_iso.replace("Z", "+00:00")).timestamp()),
        "refresh_token": "rt-1",
        "id_token": id_token,
        "client_id": CODEX_CLIENT_ID,
        "email": "tmp@example.com",
        "chatgpt_account_id": "acct-1",
        "chatgpt_user_id": "user-1",
        "organization_id": "org-1",
        "plan_type": "team",
        "subscription_expires_at": "2026-05-05T15:55:38+00:00",
        "model_mapping": {
            "gpt-5.3-codex": "gpt-5.3-codex",
            "gpt-5.4": "gpt-5.4",
            "gpt-5.4-mini": "gpt-5.4-mini",
            "gpt-5.4-pro": "gpt-5.4-pro",
            "gpt-5.5": "gpt-5.5",
        },
    }


def test_build_extra_includes_codex_usage_snapshot(monkeypatch):
    monkeypatch.setattr(sub2api_sync.time, "time", lambda: 1_700_000_000)

    extra = sub2api_sync._build_extra(
        "tmp@example.com",
        "codex-tmp@example.com-team-123.json",
        kind="pool",
        quota_info={
            "primary_pct": 42,
            "primary_resets_at": 1_700_003_600,
            "weekly_pct": 88,
            "weekly_resets_at": 1_700_086_400,
        },
    )

    assert extra["autoteam_managed"] is True
    assert extra["autoteam_kind"] == "pool"
    assert extra["autoteam_email"] == "tmp@example.com"
    assert extra["autoteam_auth_file"] == "sub2api-codex-tmp@example.com-team-123.json"
    assert extra["autoteam_source"] == "autoteam"
    assert extra["email"] == "tmp@example.com"
    assert extra["openai_oauth_responses_websockets_v2_enabled"] is False
    assert extra["openai_oauth_responses_websockets_v2_mode"] == "off"
    assert extra["privacy_mode"] == "training_off"
    assert extra["codex_5h_used_percent"] == 42
    assert extra["codex_5h_reset_after_seconds"] == 3600
    assert extra["codex_5h_reset_at"] == sub2api_sync._to_local_iso(1_700_003_600)
    assert extra["codex_7d_used_percent"] == 88
    assert extra["codex_7d_reset_after_seconds"] == 86_400
    assert extra["codex_7d_reset_at"] == sub2api_sync._to_local_iso(1_700_086_400)
    assert extra["codex_primary_used_percent"] == 42
    assert extra["codex_secondary_used_percent"] == 88
    assert extra["codex_usage_updated_at"] == datetime.fromtimestamp(
        1_700_000_000, timezone.utc
    ).astimezone().isoformat(timespec="seconds")


def test_attach_group_metadata_records_autoteam_group_binding():
    extra = sub2api_sync._build_extra("tmp@example.com", "codex-tmp@example.com-team-123.json", kind="pool")
    sub2api_sync._attach_group_metadata(extra, [7], ["Team Pool"])

    assert extra["autoteam_sub2api_group_ids"] == [7]
    assert extra["autoteam_sub2api_group_names"] == ["Team Pool"]


def test_resolve_group_binding_supports_name_and_id(monkeypatch):
    monkeypatch.setattr(
        sub2api_sync,
        "_list_openai_groups",
        lambda token: [
            {"id": 7, "name": "Team Pool", "platform": "openai"},
        ],
    )
    monkeypatch.setattr(
        sub2api_sync,
        "_get_group_by_id",
        lambda token, group_id: {"id": group_id, "name": f"Group-{group_id}", "platform": "openai"},
    )

    group_ids, group_names = sub2api_sync._resolve_group_binding("token", "Team Pool, 9")

    assert group_ids == [7, 9]
    assert group_names == ["Team Pool", "Group-9"]


def test_resolve_group_binding_for_sync_warns_and_skips_missing_group(monkeypatch):
    monkeypatch.setattr(sub2api_sync, "_list_openai_groups", lambda token: [])

    group_ids, group_names, warnings = sub2api_sync._resolve_group_binding_for_sync("token", "team")

    assert group_ids == []
    assert group_names == []
    assert warnings == ["未找到分组: team，已跳过分组绑定"]


def test_merge_group_ids_preserves_manual_groups_and_replaces_previous_managed_group():
    account = {
        "group_ids": [11, 21],
        "extra": {
            "autoteam_sub2api_group_ids": [21],
        },
    }

    assert sub2api_sync._merge_group_ids(account, [22]) == [11, 22]
    assert sub2api_sync._merge_group_ids(account, []) == [11]


def test_remote_auth_file_candidates_include_legacy_and_prefixed_names():
    assert sub2api_sync._remote_auth_file_candidates(["codex-a.json"]) == {
        "codex-a.json",
        "sub2api-codex-a.json",
    }


def test_update_account_overwrites_sub2api_account_shape_and_preserves_proxy_key(monkeypatch):
    captured = {}

    def fake_request(method, path, **kwargs):
        captured["method"] = method
        captured["path"] = path
        captured["json"] = kwargs["json"]
        return {"id": 42}

    monkeypatch.setattr(sub2api_sync, "_request", fake_request)

    sub2api_sync._update_account(
        "token",
        {"id": 42, "name": "old", "proxy_key": "proxy-1"},
        name="user@example.com",
        credentials={"access_token": "new"},
        extra={"email": "user@example.com"},
        status="active",
        group_ids=[7],
    )

    assert captured["method"] == "PUT"
    assert captured["path"] == "/admin/accounts/42"
    assert captured["json"] == {
        "name": "user@example.com",
        "platform": "openai",
        "type": "oauth",
        "credentials": {"access_token": "new"},
        "extra": {"email": "user@example.com"},
        "concurrency": 10,
        "priority": 1,
        "rate_multiplier": 1,
        "auto_pause_on_expired": True,
        "status": "active",
        "group_ids": [7],
        "proxy_key": "proxy-1",
    }


def test_sync_to_sub2api_updates_existing_same_email_oauth_account(tmp_path, monkeypatch):
    auth_file = tmp_path / "codex-user@example.com-team.json"
    auth_file.write_text(
        json.dumps(
            {
                "access_token": "new-access",
                "id_token": _jwt({"email": "user@example.com"}),
                "expired": 2_000_000_000,
                "email": "user@example.com",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "autoteam.accounts.load_accounts",
        lambda: [
            {
                "email": "user@example.com",
                "status": "active",
                "auth_file": str(auth_file),
            }
        ],
    )
    monkeypatch.setattr(sub2api_sync, "_login", lambda: "token")
    monkeypatch.setattr(sub2api_sync, "_resolve_group_binding", lambda token: ([], []))
    monkeypatch.setattr(
        sub2api_sync,
        "_list_openai_oauth_accounts",
        lambda token: [
            {
                "id": 42,
                "name": "Existing User",
                "credentials": {"email": "user@example.com", "access_token": "old-access"},
                "extra": {},
                "group_ids": [3],
            }
        ],
    )
    created = []
    updated = []
    deleted = []
    local_updates = []
    monkeypatch.setattr(sub2api_sync, "_create_account", lambda *args, **kwargs: created.append(kwargs))
    monkeypatch.setattr(sub2api_sync, "_delete_account", lambda *args, **kwargs: deleted.append(args[1]))
    monkeypatch.setattr(
        "autoteam.accounts.update_account", lambda email, **kwargs: local_updates.append((email, kwargs))
    )

    def fake_update(_token, account, **kwargs):
        updated.append({"account": account, **kwargs})
        return {"id": account["id"]}

    monkeypatch.setattr(sub2api_sync, "_update_account", fake_update)

    result = sub2api_sync.sync_to_sub2api()

    assert result["created"] == 0
    assert result["updated"] == 1
    assert result["existing_email_matches"] == 1
    assert result["warnings"] == []
    assert created == []
    assert deleted == []
    assert updated[0]["account"]["id"] == 42
    assert updated[0]["name"] == "user@example.com"
    assert updated[0]["credentials"]["access_token"] == "new-access"
    assert updated[0]["credentials"]["model_mapping"]["gpt-5.5"] == "gpt-5.5"
    assert updated[0]["extra"]["autoteam_email"] == "user@example.com"
    assert updated[0]["extra"]["privacy_mode"] == "training_off"
    assert updated[0]["group_ids"] == [3]
    assert len(local_updates) == 1
    assert local_updates[0][0] == "user@example.com"
    assert isinstance(local_updates[0][1]["sub2api_synced_at"], float)


def test_sync_to_sub2api_uses_rt_auth_file_when_auth_file_is_session(tmp_path, monkeypatch):
    session_file = tmp_path / "codex-user@example.com-team-acc-session.json"
    session_file.write_text(
        json.dumps(
            {
                "access_token": "session-access",
                "email": "user@example.com",
                "credential_source": "chatgpt_session",
            }
        ),
        encoding="utf-8",
    )
    oauth_file = tmp_path / "codex-user@example.com-team-acc-oauth.json"
    oauth_file.write_text(
        json.dumps(
            {
                "access_token": "oauth-access",
                "refresh_token": "rt-1",
                "id_token": _jwt({"email": "user@example.com"}),
                "expired": 2_000_000_000,
                "email": "user@example.com",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "autoteam.accounts.load_accounts",
        lambda: [
            {
                "email": "user@example.com",
                "status": "active",
                "auth_file": str(session_file),
                "session_auth_file": str(session_file),
                "rt_auth_file": str(oauth_file),
            }
        ],
    )
    monkeypatch.setattr(sub2api_sync, "_login", lambda: "token")
    monkeypatch.setattr(sub2api_sync, "_resolve_group_binding", lambda token: ([], []))
    monkeypatch.setattr(sub2api_sync, "_list_openai_oauth_accounts", lambda token: [])
    created = []
    monkeypatch.setattr(sub2api_sync, "_create_account", lambda *args, **kwargs: created.append(kwargs))
    monkeypatch.setattr("autoteam.accounts.update_account", lambda *_args, **_kwargs: None)

    result = sub2api_sync.sync_to_sub2api()

    assert result["created"] == 1
    assert created[0]["credentials"]["access_token"] == "oauth-access"
    assert created[0]["credentials"]["refresh_token"] == "rt-1"


def test_sync_to_sub2api_skips_sold_accounts(tmp_path, monkeypatch):
    auth_file = tmp_path / "codex-sold@example.com-team.json"
    auth_file.write_text(json.dumps({"access_token": "new", "email": "sold@example.com"}), encoding="utf-8")
    monkeypatch.setattr(
        "autoteam.accounts.load_accounts",
        lambda: [
            {
                "email": "sold@example.com",
                "status": "sold",
                "sync_disabled": True,
                "auth_file": str(auth_file),
            }
        ],
    )
    monkeypatch.setattr(sub2api_sync, "_login", lambda: "token")
    monkeypatch.setattr(sub2api_sync, "_resolve_group_binding", lambda token: ([], []))
    monkeypatch.setattr(sub2api_sync, "_list_openai_oauth_accounts", lambda token: [])
    created = []
    monkeypatch.setattr(sub2api_sync, "_create_account", lambda *args, **kwargs: created.append(kwargs))

    result = sub2api_sync.sync_to_sub2api()

    assert created == []
    assert result["created"] == 0
    assert result["updated"] == 0


def test_sync_account_to_sub2api_does_not_delete_other_managed_accounts(tmp_path, monkeypatch):
    auth_file = tmp_path / "codex-user@example.com-team.json"
    auth_file.write_text(
        json.dumps(
            {
                "access_token": "new-access",
                "id_token": _jwt({"email": "user@example.com"}),
                "expired": 2_000_000_000,
                "email": "user@example.com",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "autoteam.accounts.load_accounts",
        lambda: [
            {
                "email": "user@example.com",
                "status": "active",
                "auth_file": str(auth_file),
            },
            {
                "email": "old@example.com",
                "status": "standby",
                "auth_file": str(auth_file),
            },
        ],
    )
    monkeypatch.setattr(sub2api_sync, "_login", lambda: "token")
    monkeypatch.setattr(sub2api_sync, "_resolve_group_binding", lambda token: ([], []))
    monkeypatch.setattr(
        sub2api_sync,
        "_list_openai_oauth_accounts",
        lambda token: [
            {
                "id": 42,
                "name": "Existing User",
                "credentials": {"email": "user@example.com", "access_token": "old-access"},
                "extra": {},
                "group_ids": [],
            },
            {
                "id": 43,
                "name": "old@example.com",
                "credentials": {"email": "old@example.com"},
                "extra": {
                    "autoteam_source": "autoteam",
                    "autoteam_kind": "pool",
                    "autoteam_email": "old@example.com",
                },
                "group_ids": [],
            },
        ],
    )
    created = []
    updated = []
    deleted = []
    local_updates = []
    monkeypatch.setattr(sub2api_sync, "_create_account", lambda *args, **kwargs: created.append(kwargs))
    monkeypatch.setattr(sub2api_sync, "_delete_account", lambda *args, **kwargs: deleted.append(args[1]))
    monkeypatch.setattr(
        "autoteam.accounts.update_account", lambda email, **kwargs: local_updates.append((email, kwargs))
    )
    monkeypatch.setattr(
        sub2api_sync,
        "_update_account",
        lambda _token, account, **kwargs: updated.append({"account": account, **kwargs}) or {"id": account["id"]},
    )

    result = sub2api_sync.sync_account_to_sub2api("user@example.com")

    assert result["created"] == 0
    assert result["updated"] == 1
    assert result["deleted"] == 0
    assert result["email"] == "user@example.com"
    assert created == []
    assert deleted == []
    assert updated[0]["account"]["id"] == 42
    assert len(local_updates) == 1
    assert local_updates[0][0] == "user@example.com"
