from autoteam import mo_email


def test_format_email_name_uses_default_pattern(monkeypatch):
    monkeypatch.delenv("MO_EMAIL_NAME_PATTERN", raising=False)

    assert mo_email.format_email_name("abc", 7) == "abc-007"


def test_format_email_name_supports_compact_pattern():
    assert mo_email.format_email_name("abc", 7, "{prefix}{index:03d}") == "abc007"


def test_format_email_name_falls_back_for_empty_pattern():
    assert mo_email.format_email_name("abc", 7, "") == "abc-007"


def test_format_email_name_falls_back_for_missing_placeholders():
    assert mo_email.format_email_name("abc", 7, "no-placeholders") == "abc-007"


def test_format_email_name_accepts_any_pattern_with_both_placeholders():
    assert mo_email.format_email_name("abc", 7, "{prefix}@{index}") == "abc@7"


def test_format_email_name_reads_env_when_pattern_is_omitted(monkeypatch):
    monkeypatch.setenv("MO_EMAIL_NAME_PATTERN", "{prefix}_{index:02d}")

    assert mo_email.format_email_name("xy", 3) == "xy_03"
