from datetime import date

from autoteam import about_you


def test_about_you_profiles_are_20_us_local_sets_with_valid_age_range():
    profiles = about_you.ABOUT_YOU_PROFILES
    assert len(profiles) == 20

    names = {(profile.first_name, profile.last_name) for profile in profiles}
    assert len(names) == 20

    as_of = date(2026, 4, 30)
    ages = [profile.age(as_of=as_of) for profile in profiles]
    assert min(ages) >= 18
    assert max(ages) <= 40


def test_select_about_you_profile_is_stable_for_same_email():
    first = about_you.select_about_you_profile("person@example.com")
    second = about_you.select_about_you_profile("person@example.com")
    third = about_you.select_about_you_profile("PERSON@example.com")

    assert first == second == third


def test_select_about_you_profile_defaults_when_email_missing():
    profile = about_you.select_about_you_profile("")
    assert profile == about_you.ABOUT_YOU_PROFILES[0]
