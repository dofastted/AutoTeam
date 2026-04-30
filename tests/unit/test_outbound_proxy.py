import importlib

import pytest
import requests

from autoteam import outbound_proxy


def reload_proxy(monkeypatch, **env):
    for key in (
        "OUTBOUND_PROXY_ENABLED",
        "OUTBOUND_PROXY_POOL",
        "OUTBOUND_PROXY_BYPASS",
        "OUTBOUND_PROXY_FAILOVER",
    ):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return importlib.reload(outbound_proxy)


def test_default_proxy_pool_uses_windows_proxy(monkeypatch):
    proxy = reload_proxy(monkeypatch)

    assert proxy.configured_proxy_pool() == ["http://127.0.0.1:10808"]


def test_proxy_pool_normalizes_bare_hosts_and_direct(monkeypatch):
    proxy = reload_proxy(monkeypatch, OUTBOUND_PROXY_POOL="host.local:8080, direct, socks5://proxy.local:1080")

    assert proxy.configured_proxy_pool() == [
        "http://host.local:8080",
        "direct",
        "socks5://proxy.local:1080",
    ]


def test_proxy_pool_can_be_disabled(monkeypatch):
    proxy = reload_proxy(monkeypatch, OUTBOUND_PROXY_ENABLED="false")

    assert proxy.configured_proxy_pool() == []
    assert proxy.requests_proxies_for("https://chatgpt.com/") == {}


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:8787/api/auth/check",
        "http://127.0.0.1:8787/api/auth/check",
        "http://[::1]:8787/api/auth/check",
    ],
)
def test_local_addresses_bypass_proxy(monkeypatch, url):
    proxy = reload_proxy(monkeypatch)

    assert proxy.should_bypass_proxy(url) is True
    assert proxy.requests_proxies_for(url) == {}


def test_external_addresses_use_task_proxy(monkeypatch):
    proxy = reload_proxy(monkeypatch, OUTBOUND_PROXY_POOL="http://proxy-a:8080,http://proxy-b:8080")

    with proxy.task_proxy_context("http://proxy-b:8080"):
        assert proxy.requests_proxies_for("https://chatgpt.com/") == {
            "http": "http://proxy-b:8080",
            "https": "http://proxy-b:8080",
        }


def test_task_proxy_context_keeps_single_proxy(monkeypatch):
    proxy = reload_proxy(monkeypatch, OUTBOUND_PROXY_POOL="http://proxy-a:8080,http://proxy-b:8080")

    with proxy.task_proxy_context() as first:
        assert first == proxy.current_proxy_url()
        assert proxy.current_proxy_url() == first
        assert proxy.current_proxy_url() == first


def test_request_fails_over_on_network_error(monkeypatch):
    proxy = reload_proxy(monkeypatch, OUTBOUND_PROXY_POOL="http://proxy-a:8080,http://proxy-b:8080")
    calls = []

    def fake_request(self, method, url, **kwargs):
        calls.append(kwargs.get("proxies"))
        if len(calls) == 1:
            raise requests.exceptions.ProxyError("proxy down")

        class Response:
            status_code = 200

        return Response()

    monkeypatch.setattr(requests.Session, "request", fake_request)

    resp = proxy.request("GET", "https://chatgpt.com/", timeout=1)

    assert resp.status_code == 200
    assert calls == [
        {"http": "http://proxy-a:8080", "https": "http://proxy-a:8080"},
        {"http": "http://proxy-b:8080", "https": "http://proxy-b:8080"},
    ]
