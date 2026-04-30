from autoteam import auth_archive


def test_archive_account_auth_file_copies_into_email_dir(tmp_path, monkeypatch):
    auth_dir = tmp_path / "auths"
    source = auth_dir / "codex-user@example.com-team-abc.json"
    source.parent.mkdir()
    source.write_text('{"type":"codex"}', encoding="utf-8")

    monkeypatch.setattr(auth_archive, "AUTH_DIR", auth_dir)
    monkeypatch.setattr(auth_archive, "ARCHIVE_DIR", auth_dir / "archive")
    monkeypatch.setattr(auth_archive, "ensure_auth_file_permissions", lambda _path: None)

    archived = auth_archive.archive_account_auth_file("User@Example.com", source)

    archived_path = tmp_path / "auths" / "archive" / "user@example.com" / source.name
    assert archived == str(archived_path.resolve())
    assert archived_path.read_text(encoding="utf-8") == '{"type":"codex"}'
