import importlib

from autoteam import config


def test_playwright_headless_defaults_true(monkeypatch):
    monkeypatch.setenv("PLAYWRIGHT_BROWSER_MODE", "")
    monkeypatch.setenv("PLAYWRIGHT_HEADLESS", "true")
    reloaded = importlib.reload(config)

    assert reloaded.get_playwright_launch_options()["headless"] is True


def test_playwright_headless_can_be_disabled(monkeypatch):
    monkeypatch.setenv("PLAYWRIGHT_BROWSER_MODE", "")
    monkeypatch.setenv("PLAYWRIGHT_HEADLESS", "false")
    reloaded = importlib.reload(config)

    assert reloaded.get_playwright_launch_options()["headless"] is False

    monkeypatch.setenv("PLAYWRIGHT_HEADLESS", "true")
    importlib.reload(config)


def test_playwright_browser_mode_controls_visibility(monkeypatch):
    monkeypatch.setenv("PLAYWRIGHT_BROWSER_MODE", "visible")
    monkeypatch.setenv("PLAYWRIGHT_HEADLESS", "true")
    reloaded = importlib.reload(config)

    assert reloaded.PLAYWRIGHT_BROWSER_MODE == "visible"
    assert reloaded.get_playwright_launch_options()["headless"] is False

    monkeypatch.setenv("PLAYWRIGHT_BROWSER_MODE", "embedded")
    reloaded = importlib.reload(config)

    assert reloaded.PLAYWRIGHT_BROWSER_MODE == "embedded"
    assert reloaded.get_playwright_launch_options()["headless"] is False

    monkeypatch.setenv("PLAYWRIGHT_BROWSER_MODE", "")
    monkeypatch.setenv("PLAYWRIGHT_HEADLESS", "true")
    importlib.reload(config)


def test_playwright_proxy_falls_back_to_process_proxy_env(monkeypatch):
    monkeypatch.setenv("PLAYWRIGHT_PROXY_URL", "")
    monkeypatch.setenv("PLAYWRIGHT_PROXY_SERVER", "")
    monkeypatch.setenv("PLAYWRIGHT_PROXY_BYPASS", "")
    monkeypatch.setenv("OUTBOUND_PROXY_ENABLED", "false")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:10808")
    monkeypatch.delenv("https_proxy", raising=False)
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    monkeypatch.delenv("http_proxy", raising=False)
    monkeypatch.delenv("ALL_PROXY", raising=False)
    monkeypatch.delenv("all_proxy", raising=False)
    reloaded = importlib.reload(config)

    options = reloaded.get_playwright_launch_options()
    assert options["proxy"]["server"] == "http://127.0.0.1:10808"
    assert options["proxy"]["bypass"] == "localhost,127.0.0.1"

    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    importlib.reload(config)


def test_playwright_proxy_defaults_to_outbound_proxy(monkeypatch):
    monkeypatch.setenv("PLAYWRIGHT_PROXY_URL", "")
    monkeypatch.setenv("PLAYWRIGHT_PROXY_SERVER", "")
    monkeypatch.setenv("PLAYWRIGHT_PROXY_BYPASS", "")
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.delenv("https_proxy", raising=False)
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    monkeypatch.delenv("http_proxy", raising=False)
    monkeypatch.delenv("ALL_PROXY", raising=False)
    monkeypatch.delenv("all_proxy", raising=False)
    monkeypatch.setenv("OUTBOUND_PROXY_ENABLED", "true")
    monkeypatch.setenv("OUTBOUND_PROXY_POOL", "http://127.0.0.1:10808")
    reloaded = importlib.reload(config)

    options = reloaded.get_playwright_launch_options()
    assert options["proxy"]["server"] == "http://127.0.0.1:10808"
    assert options["proxy"]["bypass"] == "localhost,127.0.0.1"


def test_playwright_proxy_uses_current_task_proxy(monkeypatch):
    monkeypatch.setenv("PLAYWRIGHT_PROXY_URL", "")
    monkeypatch.setenv("PLAYWRIGHT_PROXY_SERVER", "")
    monkeypatch.setenv("PLAYWRIGHT_PROXY_BYPASS", "")
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.delenv("https_proxy", raising=False)
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    monkeypatch.delenv("http_proxy", raising=False)
    monkeypatch.delenv("ALL_PROXY", raising=False)
    monkeypatch.delenv("all_proxy", raising=False)
    monkeypatch.setenv("OUTBOUND_PROXY_ENABLED", "true")
    monkeypatch.setenv("OUTBOUND_PROXY_POOL", "http://proxy-a:8080,http://proxy-b:8080")
    reloaded = importlib.reload(config)

    with reloaded.outbound_proxy.task_proxy_context("http://proxy-b:8080"):
        options = reloaded.get_playwright_launch_options()

    assert options["proxy"]["server"] == "http://proxy-b:8080"
    assert options["proxy"]["bypass"] == "localhost,127.0.0.1"


def test_playwright_explicit_proxy_overrides_outbound_proxy(monkeypatch):
    monkeypatch.setenv("OUTBOUND_PROXY_POOL", "http://127.0.0.1:10808")
    monkeypatch.setenv("PLAYWRIGHT_PROXY_URL", "socks5://browser-proxy.local:1080")
    reloaded = importlib.reload(config)

    options = reloaded.get_playwright_launch_options()
    assert options["proxy"]["server"] == "socks5://browser-proxy.local:1080"
