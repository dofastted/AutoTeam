import importlib

from autoteam import proxy_nodes


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


def reload_proxy_nodes(monkeypatch, **env):
    for key in (
        "PROXY_NODE_ENABLED",
        "PROXY_NODE_PROVIDER",
        "PROXY_NODE_API_KEY",
        "PROXY_NODE_BASE_URL",
        "PROXY_NODE_PROTOCOL",
        "PROXY_NODE_AUTO_REFRESH",
        "PROXY_NODE_REFRESH_BEFORE_TASK",
        "PROXY_NODE_POLL_INTERVAL_SECONDS",
        "PROXY_NODE_POLL_TIMEOUT_SECONDS",
        "PROXY_NODE_COUNTRY",
        "PROXY_NODE_APPLY_TO_OUTBOUND_POOL",
        "OUTBOUND_PROXY_POOL",
    ):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return importlib.reload(proxy_nodes)


def _node(ip="203.0.113.10", *, valid=True):
    return {
        "proxy_address": ip,
        "port": 9000,
        "username": "user",
        "password": "pass",
        "valid": valid,
        "country_code": "US",
    }


def test_webshare_current_proxy_node_formats_http_url(monkeypatch):
    nodes = reload_proxy_nodes(
        monkeypatch,
        PROXY_NODE_ENABLED="true",
        PROXY_NODE_PROVIDER="webshare",
        PROXY_NODE_API_KEY="node-key",
        PROXY_NODE_PROTOCOL="http",
    )

    def fake_request(method, url, **kwargs):
        assert method == "GET"
        assert "Authorization" in kwargs["headers"]
        return FakeResponse(payload={"results": [_node()]})

    monkeypatch.setattr(nodes.outbound_proxy, "request", fake_request)

    result = nodes.get_current_proxy_node()

    assert result["provider"] == "webshare"
    assert result["proxy_url"] == "http://user:pass@203.0.113.10:9000"
    assert result["node"]["password"] == "***"


def test_refresh_proxy_node_polls_new_node_and_updates_outbound_pool(monkeypatch):
    nodes = reload_proxy_nodes(
        monkeypatch,
        PROXY_NODE_ENABLED="true",
        PROXY_NODE_PROVIDER="webshare",
        PROXY_NODE_API_KEY="node-key",
        PROXY_NODE_PROTOCOL="socks5",
        PROXY_NODE_POLL_INTERVAL_SECONDS="1",
        PROXY_NODE_POLL_TIMEOUT_SECONDS="5",
        OUTBOUND_PROXY_POOL="http://old-proxy:8080",
    )
    calls = []
    list_calls = [_node("203.0.113.1"), _node("203.0.113.2")]

    def fake_request(method, url, **kwargs):
        calls.append((method, url))
        if url.endswith("/subscription/plan/"):
            return FakeResponse(
                payload={
                    "results": [
                        {
                            "status": "active",
                            "proxy_replacements_total": 10,
                            "proxy_replacements_used": 1,
                            "proxy_replacements_available": 9,
                        }
                    ]
                }
            )
        if url.endswith("/proxy/list/refresh/"):
            return FakeResponse(status_code=204)
        if "/proxy/list/" in url:
            return FakeResponse(payload={"results": [list_calls.pop(0)]})
        raise AssertionError(url)

    monkeypatch.setattr(nodes.outbound_proxy, "request", fake_request)

    result = nodes.refresh_proxy_node(force_rotate=True)

    assert result["proxy_url"] == "socks5://user:pass@203.0.113.2:9000"
    assert result["applied"] is True
    assert result["previous_proxy_pool"] == "http://old-proxy:8080"
    assert nodes.os.environ["OUTBOUND_PROXY_POOL"] == "socks5://user:pass@203.0.113.2:9000"
    assert [method for method, _url in calls] == ["GET", "GET", "POST", "GET"]


def test_maybe_refresh_before_task_respects_disabled_config(monkeypatch):
    nodes = reload_proxy_nodes(monkeypatch, PROXY_NODE_ENABLED="false", PROXY_NODE_PROVIDER="webshare")

    assert nodes.maybe_refresh_before_task() is None
