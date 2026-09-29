import db
from conftest import GOOD_WEBHOOK


def _task(language="es"):
    c, _ = db.create_client("X", GOOD_WEBHOOK)
    return db.save_meeting(c.id, "s", language, [{"task": "Enviar <b>reporte</b>", "owner": "Juan", "deadline": "viernes"}])[0]


def _status(code):
    return db.get_task_by_code(code).status


def test_get_does_not_mark_done(client):
    t = _task()
    del client.headers["X-API-Key"]
    r = client.get(f"/t/{t.done_code}")
    assert r.status_code == 200 and "Marcar como hecha" in r.text
    assert "<b>reporte</b>" not in r.text  # escapado
    assert _status(t.done_code) == "open"
    assert r.headers["Referrer-Policy"] == "no-referrer"


def test_post_marks_done_and_is_idempotent(client):
    t = _task("en")
    r = client.post(f"/t/{t.done_code}")
    assert r.status_code == 200 and "marked as done" in r.text
    assert _status(t.done_code) == "done"
    assert client.post(f"/t/{t.done_code}").status_code == 200
    assert "already done" in client.get(f"/t/{t.done_code}").text


def test_unknown_code_404(client):
    assert client.get("/t/nope").status_code == 404
    assert client.post("/t/nope").status_code == 404
