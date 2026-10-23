import json
import threading
import urllib.error
import urllib.request
import pytest
from qwen_agent.gateway import create_server
from qwen_agent.client import Client

TOKEN = "test-only-0123456789-0123456789"


@pytest.fixture
def gateway(monkeypatch):
    def request(self, path, body=None):
        if path == "/models":
            return {"data": [{"id": "fixture"}]}
        return {"choices": [{"message": {"content": "fixture"}}]}
    monkeypatch.setattr(Client, "request", request)
    server = create_server("http://127.0.0.1:1/v1", TOKEN, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    thread.join(timeout=3)
    server.server_close()


def request(url, path, auth=True, body=None):
    req = urllib.request.Request(url + path, headers={"Authorization": "Bearer " + TOKEN} if auth else {}, data=body)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return opener.open(req, timeout=3)


def test_auth_routes_health_metrics(gateway):
    with pytest.raises(urllib.error.HTTPError) as denied:
        request(gateway, "/v1/models", auth=False)
    assert denied.value.code == 401
    with request(gateway, "/v1/models") as response:
        assert json.load(response)["data"][0]["id"] == "fixture"
    with request(gateway, "/health") as response:
        assert json.load(response)["status"] == "ready"
    with request(gateway, "/metrics") as response:
        assert "qwen_gateway_denied_total 1" in response.read().decode()
    for path in ("/api/pull", "/invocations", "/v1/models?redirect=https://evil.com"):
        with pytest.raises(urllib.error.HTTPError) as disabled:
            request(gateway, path)
        assert disabled.value.code == 404


def test_upstream_failure_is_closed(gateway, monkeypatch):
    def fail(*args):
        raise OSError("sensitive upstream error")
    monkeypatch.setattr(Client, "request", fail)
    with pytest.raises(urllib.error.HTTPError) as down:
        request(gateway, "/health")
    assert down.value.code == 503
    assert "sensitive" not in down.value.read().decode()


def test_oversize_body_and_streaming_rejected(gateway):
    for body, status in [(b"x" * 65537, 413), (b'{"stream":true}', 400)]:
        with pytest.raises(urllib.error.HTTPError) as error:
            request(gateway, "/v1/chat/completions", body=body)
        assert error.value.code == status


def test_missing_key_cannot_start():
    with pytest.raises(ValueError, match="24"):
        create_server("http://127.0.0.1:1/v1", "")
