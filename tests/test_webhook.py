import pytest
from conftest import GOOD_WEBHOOK

BAD = [
    None,
    "",
    "https://evil.example/hook",
    "http://hooks.slack.com/services/T/B/X",
    "https://hooks.slack.com.evil.example/services/T/B/X",
    "https://hooks.slack.com@evil.example/services/",
    "http://169.254.169.254/latest/meta-data/",
]


@pytest.mark.parametrize("url", BAD)
@pytest.mark.parametrize("path,extra", [("/api/extract", {"transcript": "a"}), ("/api/test", {})])
def test_bad_webhook_rejected_without_outbound_request(client, path, extra, url):
    r = client.post(path, json={**extra, "webhook_url": url})
    assert r.status_code == 400
    assert client.sent == []  # nunca sale un request (sin SSRF, sin fallback)


def test_no_fallback_to_env_webhook(client, monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", GOOD_WEBHOOK)
    r = client.post("/api/test", json={})
    assert r.status_code == 400
    assert client.sent == []


@pytest.mark.parametrize("path,extra", [("/api/extract", {"transcript": "a"}), ("/api/test", {})])
def test_good_webhook_accepted(client, path, extra):
    r = client.post(path, json={**extra, "webhook_url": GOOD_WEBHOOK})
    assert r.status_code == 200
    assert client.sent == [GOOD_WEBHOOK]
