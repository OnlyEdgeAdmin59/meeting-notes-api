import pytest
from conftest import GOOD_WEBHOOK

ENDPOINTS = [("/api/extract", {"transcript": "a"}), ("/api/test", {})]


@pytest.mark.parametrize("path,extra", ENDPOINTS)
@pytest.mark.parametrize("headers", [
    {"X-API-Key": ""},            # vacía
    {"X-API-Key": "wrong"},       # inválida
    {"X-API-Key": "key-alph"},    # prefijo de una válida
])
def test_bad_key_401(client, path, extra, headers):
    r = client.post(path, json={**extra, "webhook_url": GOOD_WEBHOOK}, headers=headers)
    assert r.status_code == 401
    assert client.sent == []


@pytest.mark.parametrize("path,extra", ENDPOINTS)
def test_missing_key_401(client, path, extra):
    del client.headers["X-API-Key"]
    r = client.post(path, json={**extra, "webhook_url": GOOD_WEBHOOK})
    assert r.status_code == 401
    assert client.sent == []


@pytest.mark.parametrize("path,extra", ENDPOINTS)
@pytest.mark.parametrize("key", ["key-alpha", "key-beta"])
def test_each_valid_key_200(client, path, extra, key):
    r = client.post(path, json={**extra, "webhook_url": GOOD_WEBHOOK}, headers={"X-API-Key": key})
    assert r.status_code == 200


def test_no_keys_configured_denies_everyone(client, monkeypatch):
    monkeypatch.setenv("CLIENT_API_KEYS", "")
    r = client.post("/api/test", json={"webhook_url": GOOD_WEBHOOK})
    assert r.status_code == 401


def test_health_and_home_stay_public(client):
    del client.headers["X-API-Key"]
    assert client.get("/health").status_code == 200
    assert client.get("/").status_code == 200
