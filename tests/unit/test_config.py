import importlib

from autoteam import config


def test_playwright_headless_defaults_true(monkeypatch):
    monkeypatch.setenv("PLAYWRIGHT_HEADLESS", "true")
    reloaded = importlib.reload(config)

    assert reloaded.get_playwright_launch_options()["headless"] is True


def test_playwright_headless_can_be_disabled(monkeypatch):
    monkeypatch.setenv("PLAYWRIGHT_HEADLESS", "false")
    reloaded = importlib.reload(config)

    assert reloaded.get_playwright_launch_options()["headless"] is False

    monkeypatch.setenv("PLAYWRIGHT_HEADLESS", "true")
    importlib.reload(config)
