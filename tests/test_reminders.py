from datetime import date, datetime, timezone

import pytest

import db
import main
import reminders
from conftest import GOOD_WEBHOOK

# 2026-10-05 es lunes; 15:00 UTC = 10:00 en Houston (CDT)
MONDAY_10AM = datetime(2026, 10, 5, 15, 0, tzinfo=timezone.utc)
TUESDAY_10AM = datetime(2026, 10, 6, 15, 0, tzinfo=timezone.utc)
MONDAY_7AM = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)


class Poster:
    def __init__(self, status=200):
        self.calls, self.status = [], status

    def __call__(self, url, payload):
        self.calls.append((url, payload))
        return type("R", (), {"status_code": self.status})()


@pytest.fixture
def seeded():
    c, _ = db.create_client("Oficina", GOOD_WEBHOOK)
    db.save_meeting(c.id, "s", "es", [
        {"task": "Vencida", "owner": "A", "due_date": date(2026, 10, 1)},
        {"task": "Hoy", "owner": "B", "due_date": date(2026, 10, 5)},
        {"task": "Mañana", "owner": "C", "due_date": date(2026, 10, 6)},
        {"task": "Sin fecha", "owner": "D", "due_date": None},
        {"task": "Lejana", "owner": "E", "due_date": date(2026, 12, 1)},
    ])
    return c


def test_digest_groups_monday(seeded):
    p = Poster()
    stats = reminders.run_reminders(now=MONDAY_10AM, post=p)
    assert stats["sent"] == 1
    text = str(p.calls[0][1])
    for label in ("Vencidas", "Vencen hoy", "Vencen mañana", "Abiertas, sin fecha"):
        assert label in text
    assert "Lejana" not in text


def test_no_date_tasks_only_on_monday(seeded):
    p = Poster()
    reminders.run_reminders(now=TUESDAY_10AM, post=p)
    assert "Sin fecha" not in str(p.calls[0][1])


def test_once_per_day(seeded):
    p = Poster()
    reminders.run_reminders(now=MONDAY_10AM, post=p)
    reminders.run_reminders(now=MONDAY_10AM, post=p)
    assert len(p.calls) == 1


def test_too_early_does_nothing(seeded):
    p = Poster()
    assert reminders.run_reminders(now=MONDAY_7AM, post=p)["reason"] == "too_early"
    assert p.calls == []


def test_failed_post_retries_next_run(seeded):
    bad = Poster(status=500)
    assert reminders.run_reminders(now=MONDAY_10AM, post=bad)["failed"] == 1
    good = Poster()
    assert reminders.run_reminders(now=MONDAY_10AM, post=good)["sent"] == 1


def test_done_tasks_not_reminded(seeded):
    with db.session() as s:
        codes = [t.done_code for t in s.query(db.Task).all()]
    for code in codes:
        db.mark_done(code)
    p = Poster()
    reminders.run_reminders(now=MONDAY_10AM, post=p)
    assert p.calls == []


def test_digest_escapes_mentions():
    c, _ = db.create_client("X", GOOD_WEBHOOK)
    db.save_meeting(c.id, "s", "en", [{"task": "<!channel> hi", "owner": "A", "due_date": date(2026, 10, 5)}])
    p = Poster()
    reminders.run_reminders(now=MONDAY_10AM, post=p)
    assert "<!channel>" not in str(p.calls[0][1])


def test_cron_endpoint_requires_secret(client, monkeypatch):
    del client.headers["X-API-Key"]
    assert client.post("/api/cron/reminders").status_code == 403
    monkeypatch.setenv("CRON_SECRET", "s3cr3t-value")
    assert client.post("/api/cron/reminders", headers={"X-Cron-Secret": "wrong"}).status_code == 403
    r = client.post("/api/cron/reminders", headers={"X-Cron-Secret": "s3cr3t-value"})
    assert r.status_code == 200 and "clients" in r.json()
