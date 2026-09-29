from conftest import GOOD_WEBHOOK


def _extract(client, transcript, **kw):
    return client.post("/api/extract", json={"transcript": transcript, "webhook_url": GOOD_WEBHOOK}, **kw)


def test_transcript_at_limit_ok(client):
    assert _extract(client, "x" * 50_000).status_code == 200


def test_huge_transcript_422_before_llm(client, monkeypatch):
    import main
    called = []
    monkeypatch.setattr(main, "extract_action_items", lambda t: called.append(t))
    assert _extract(client, "x" * 50_001).status_code == 422
    assert called == []


def test_empty_transcript_422(client):
    assert _extract(client, "").status_code == 422


def test_rate_limit_10_per_minute_per_key(client):
    codes = [_extract(client, "a").status_code for _ in range(10)]
    assert codes == [200] * 10
    assert _extract(client, "a").status_code == 429
    # el limite es compartido entre endpoints para la misma key
    assert client.post("/api/test", json={"webhook_url": GOOD_WEBHOOK}).status_code == 429
    # otra key tiene su propio cupo
    assert _extract(client, "a", headers={"X-API-Key": "key-beta"}).status_code == 200


def test_invalid_key_does_not_consume_quota(client):
    for _ in range(15):
        assert _extract(client, "a", headers={"X-API-Key": "nope"}).status_code == 401
    assert _extract(client, "a").status_code == 200
