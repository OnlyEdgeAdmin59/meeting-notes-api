from datetime import date

import pytest

import db
import main
from conftest import GOOD_WEBHOOK

ITEMS = [{"task": "Enviar reporte", "owner": "Juan", "deadline": "viernes", "due_date": date(2026, 10, 2)},
         {"task": "Llamar al proveedor", "owner": "Ana", "deadline": "ASAP", "due_date": None}]


@pytest.fixture
def db_client(client, monkeypatch):
    c, key = db.create_client("Oficina Demo", GOOD_WEBHOOK, monthly_limit=3)
    captured = {}

    def fake_post(url, **kw):
        client.sent.append(url)
        captured["json"] = kw.get("json")
        return type("R", (), {"status_code": 200})()

    monkeypatch.setattr(main.requests, "post", fake_post)
    monkeypatch.setattr(main, "extract_action_items", lambda t: {
        "success": True, "language": "es", "summary": "Resumen", "decisions": ["Lanzar el lunes"],
        "action_items": [dict(i) for i in ITEMS]})
    client.headers["X-API-Key"] = key
    client.captured = captured
    client.db_id = c.id
    return client


def test_key_stored_only_as_hash():
    c, key = db.create_client("X", GOOD_WEBHOOK)
    assert key.startswith("nm_") and c.api_key_hash == db.hash_key(key)
    assert key not in c.api_key_hash


def test_db_key_uses_saved_webhook(db_client):
    r = db_client.post("/api/extract", json={"transcript": "hola"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["saved"] is True and body["slack_sent"] is True
    assert body["language"] == "es" and body["decisions"] == ["Lanzar el lunes"]
    assert body["action_items"][0]["due_date"] == "2026-10-02"
    assert db_client.sent == [GOOD_WEBHOOK]


def test_tasks_saved_with_done_codes(db_client):
    db_client.post("/api/extract", json={"transcript": "hola"})
    with db.session() as s:
        tasks = s.query(db.Task).all()
    assert [t.task for t in tasks] == ["Enviar reporte", "Llamar al proveedor"]
    assert all(t.status == "open" and len(t.done_code) >= 30 for t in tasks)
    assert tasks[0].due_date == date(2026, 10, 2) and tasks[0].language == "es"


def test_done_links_in_slack_when_base_url_set(db_client, monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://nm.example.com")
    db_client.post("/api/extract", json={"transcript": "hola"})
    text = str(db_client.captured["json"])
    assert "https://nm.example.com/t/" in text and "Marcar como hecha" in text


def test_no_links_without_https_base_url(db_client, monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://insecure.example.com")
    db_client.post("/api/extract", json={"transcript": "hola"})
    assert "/t/" not in str(db_client.captured["json"])


def test_monthly_limit(db_client):
    codes = [db_client.post("/api/extract", json={"transcript": "hola"}).status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]


def test_inactive_client_rejected(db_client):
    with db.session() as s:
        s.get(db.Client, db_client.db_id).active = False
        s.commit()
    assert db_client.post("/api/extract", json={"transcript": "hola"}).status_code == 401


def test_me_endpoint(db_client):
    db_client.post("/api/extract", json={"transcript": "hola"})
    r = db_client.get("/api/me")
    assert r.json() == {"name": "Oficina Demo", "has_saved_webhook": True,
                        "meetings_this_month": 1, "monthly_limit": 3}


def test_legacy_key_not_saved_and_no_limit(client):
    for _ in range(3):
        r = client.post("/api/extract", json={"transcript": "a", "webhook_url": GOOD_WEBHOOK})
        assert r.json()["saved"] is False
    with db.session() as s:
        assert s.query(db.Meeting).count() == 0


def test_bad_override_webhook_still_rejected_for_db_client(db_client):
    r = db_client.post("/api/extract", json={"transcript": "hola", "webhook_url": "https://evil.example/x"})
    assert r.status_code == 400


def test_basic_plan_capped_at_6(client, monkeypatch):
    c, key = db.create_client("Basico", GOOD_WEBHOOK)
    monkeypatch.setattr(main, "extract_action_items", lambda t: {"success": True, "action_items": [], "summary": "s"})
    codes = [client.post("/api/extract", json={"transcript": "a"}, headers={"X-API-Key": key}).status_code
             for _ in range(7)]
    assert codes == [200] * 6 + [429]


def test_unlimited_plan_has_no_cap(client, monkeypatch):
    c, key = db.create_client("Ilimitado", GOOD_WEBHOOK, monthly_limit=None)
    monkeypatch.setattr(main, "extract_action_items", lambda t: {"success": True, "action_items": [], "summary": "s"})
    for _ in range(9):
        assert client.post("/api/extract", json={"transcript": "a"}, headers={"X-API-Key": key}).status_code == 200
    me = client.get("/api/me", headers={"X-API-Key": key}).json()
    assert me["monthly_limit"] is None and me["meetings_this_month"] == 9
