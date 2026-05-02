import importlib
import random
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
import requests

from autoteam import outbound_proxy


def reload_proxy(monkeypatch, **env):
    for key in (
        "OUTBOUND_PROXY_ENABLED",
        "OUTBOUND_PROXY_POOL",
        "OUTBOUND_PROXY_BYPASS",
        "OUTBOUND_PROXY_STRATEGY",
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


def test_rotate_task_proxy_switches_current_task_proxy(monkeypatch):
    proxy = reload_proxy(monkeypatch, OUTBOUND_PROXY_POOL="http://proxy-a:8080,http://proxy-b:8080")

    with proxy.task_proxy_context("http://proxy-a:8080"):
        assert proxy.rotate_task_proxy() == "http://proxy-b:8080"
        assert proxy.current_proxy_url() == "http://proxy-b:8080"


def test_rotate_in_one_thread_does_not_leak_to_another_thread(monkeypatch):
    proxy = reload_proxy(monkeypatch, OUTBOUND_PROXY_POOL="http://proxy-a:8080,http://proxy-b:8080")
    rotate_done = threading.Event()
    release_other = threading.Event()

    def rotating_worker():
        with proxy.task_proxy_context("http://proxy-a:8080"):
            assert proxy.rotate_task_proxy() == "http://proxy-b:8080"
            rotate_done.set()
            release_other.wait(timeout=2)
            return proxy.current_proxy_url()

    def isolated_worker():
        with proxy.task_proxy_context("http://proxy-a:8080"):
            rotate_done.wait(timeout=2)
            value = proxy.current_proxy_url()
            release_other.set()
            return value

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(rotating_worker)
        second = executor.submit(isolated_worker)

    assert first.result() == "http://proxy-b:8080"
    assert second.result() == "http://proxy-a:8080"


def test_task_proxy_context_isolates_concurrent_tasks(monkeypatch):
    proxy = reload_proxy(monkeypatch, OUTBOUND_PROXY_POOL="http://proxy-a:8080,http://proxy-b:8080")
    results = []

    async def worker(initial_proxy, delay):
        with proxy.task_proxy_context(initial_proxy):
            before = proxy.current_proxy_url()
            await delay()
            after = proxy.rotate_task_proxy()
            await delay()
            results.append((initial_proxy, before, after, proxy.current_proxy_url()))

    async def run():
        import asyncio

        async def delay():
            await asyncio.sleep(0)

        await asyncio.gather(
            worker("http://proxy-a:8080", delay),
            worker("http://proxy-b:8080", delay),
        )

    import asyncio

    asyncio.run(run())

    assert sorted(results) == [
        ("http://proxy-a:8080", "http://proxy-a:8080", "http://proxy-b:8080", "http://proxy-b:8080"),
        ("http://proxy-b:8080", "http://proxy-b:8080", "http://proxy-a:8080", "http://proxy-a:8080"),
    ]


def test_strategy_round_robin_and_random_select_within_pool(monkeypatch):
    pool = "http://proxy-a:8080,http://proxy-b:8080,http://proxy-c:8080"
    proxy = reload_proxy(monkeypatch, OUTBOUND_PROXY_POOL=pool, OUTBOUND_PROXY_STRATEGY="round-robin")

    assert [proxy.select_proxy() for _ in range(4)] == [
        "http://proxy-a:8080",
        "http://proxy-b:8080",
        "http://proxy-c:8080",
        "http://proxy-a:8080",
    ]
    assert proxy.select_proxy(after="http://proxy-b:8080") == "http://proxy-c:8080"

    proxy = reload_proxy(monkeypatch, OUTBOUND_PROXY_POOL=pool, OUTBOUND_PROXY_STRATEGY="random")
    choices = []

    def fake_choice(candidates):
        choices.append(list(candidates))
        return candidates[-1]

    monkeypatch.setattr(random, "choice", fake_choice)

    assert proxy.select_proxy() == "http://proxy-c:8080"
    assert proxy.select_proxy(after="http://proxy-c:8080") == "http://proxy-b:8080"
    assert choices == [
        ["http://proxy-a:8080", "http://proxy-b:8080", "http://proxy-c:8080"],
        ["http://proxy-a:8080", "http://proxy-b:8080"],
    ]


def test_residential_proxy_pool_parses_and_rotates_in_order(monkeypatch):
    pool = (
        "http://rwhapmdk:eexy06lcufiz@208.66.79.48:5423,"
        "http://rwhapmdk:eexy06lcufiz@208.66.79.18:5393,"
        "http://rwhapmdk:eexy06lcufiz@63.246.131.37:6552,"
        "http://jqcjjkua:rjqi149y9j7x@45.58.228.3:5675"
    )
    proxy = reload_proxy(monkeypatch, OUTBOUND_PROXY_POOL=pool)
    expected = [
        "http://rwhapmdk:eexy06lcufiz@208.66.79.48:5423",
        "http://rwhapmdk:eexy06lcufiz@208.66.79.18:5393",
        "http://rwhapmdk:eexy06lcufiz@63.246.131.37:6552",
        "http://jqcjjkua:rjqi149y9j7x@45.58.228.3:5675",
    ]

    assert proxy.configured_proxy_pool() == expected
    with proxy.task_proxy_context(expected[0]):
        assert proxy.rotate_task_proxy() == expected[1]
        assert proxy.rotate_task_proxy() == expected[2]
        assert proxy.rotate_task_proxy() == expected[3]
        assert proxy.rotate_task_proxy() == expected[0]


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
