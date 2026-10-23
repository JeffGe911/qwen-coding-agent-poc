import pytest
from qwen_agent.client import Client, NoRedirect, validate_url


@pytest.mark.parametrize("url", ["http://example.com/v1", "http://127.0.0.1.evil.com/v1", "http://0.0.0.0:8000/v1", "file:///v1", "http://u:p@localhost/v1", "http://localhost/v1?url=evil", "http://localhost/other", "http://localhost/v1#x"])
def test_remote_or_ambiguous_endpoint_rejected(url):
    with pytest.raises(ValueError):
        validate_url(url)


@pytest.mark.parametrize("url", ["http://127.0.0.1:11434/v1", "http://localhost:8000/v1/", "http://[::1]:8000/v1"])
def test_loopback_endpoint(url):
    assert validate_url(url).endswith("/v1")


def test_redirects_rejected():
    with pytest.raises(ValueError, match="redirect"):
        NoRedirect().redirect_request(None, None, 302, "", {}, "https://evil.com")


def test_client_schema_and_payload_exclude_holdout(monkeypatch):
    client = Client("http://127.0.0.1:8000/v1", "local-model")
    captured = {}
    def request(path, body):
        captured.update(body)
        return {}
    monkeypatch.setattr(client, "request", request)
    client.propose({"description": "fix f"}, "def f(): pass", "visible", "failed")
    assert captured["response_format"]["type"] == "json_schema"
    assert "test_holdout" not in str(captured)
    assert captured["model"] == "local-model"

