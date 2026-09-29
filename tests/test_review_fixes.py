from datetime import date, datetime, timezone

import db
import extract
import main
import reminders
from conftest import GOOD_WEBHOOK
from transcript_files import file_to_transcript

MONDAY_10AM = datetime(2026, 10, 5, 15, 0, tzinfo=timezone.utc)


class Poster:
    def __init__(self, status=200):
        self.calls, self.status = [], status

    def __call__(self, url, payload):
        self.calls.append(payload)
        return type("R", (), {"status_code": self.status})()


def test_cp1252_spanish_txt_not_garbled():
    data = "Reunión: José dijo que sí.".encode("cp1252")
    assert len(data) % 2 == 0
    assert file_to_transcript("x.txt", data) == "Reunión: José dijo que sí."


def test_utf16_with_bom_ok():
    assert file_to_transcript("x.txt", "Ana: hola".encode("utf-16")) == "Ana: hola"


def test_big_digest_respects_slack_limits():
    c, _ = db.create_client("X", GOOD_WEBHOOK)
    db.save_meeting(c.id, "s", "en", [{"task": "t" * 500, "owner": "A", "due_date": date(2026, 10, 1)}] * 60)
    p = Poster()
    reminders.run_reminders(now=MONDAY_10AM, post=p)
    for block in p.calls[0]["blocks"]:
        if block["type"] == "section":
            assert len(block["text"]["text"]) <= 3000
    assert "+45" in str(p.calls[0])


def test_big_meeting_message_under_50_blocks():
    items = [{"task": "x" * 1000, "owner": "A", "deadline": "d"}] * 80
    msg = extract.format_slack_message(items, "s" * 5000, ["d"] * 20, "en")
    assert len(msg["blocks"]) <= 50
    assert all(len(b["text"]["text"]) <= 3000 for b in msg["blocks"] if b["type"] == "section")


def test_permanent_4xx_not_retried_same_day():
    c, _ = db.create_client("X", GOOD_WEBHOOK)
    db.save_meeting(c.id, "s", "en", [{"task": "a", "owner": "A", "due_date": date(2026, 10, 5)}])
    gone = Poster(status=404)
    reminders.run_reminders(now=MONDAY_10AM, post=gone)
    reminders.run_reminders(now=MONDAY_10AM, post=gone)
    assert len(gone.calls) == 1


def test_claim_is_atomic():
    c, _ = db.create_client("X", GOOD_WEBHOOK)
    today = date(2026, 10, 5)
    assert db.claim_digest(c.id, today) is None
    assert db.claim_digest(c.id, today) == today  # segundo intento: ya tomado


def test_slack_failure_not_saved_nor_counted(client, monkeypatch):
    c, key = db.create_client("X", GOOD_WEBHOOK, monthly_limit=1)
    monkeypatch.setattr(main, "extract_action_items", lambda t: {
        "success": True, "action_items": [{"task": "a", "owner": "A", "deadline": "x"}], "summary": "s"})
    monkeypatch.setattr(main.requests, "post", lambda url, **kw: type("R", (), {"status_code": 500})())
    r = client.post("/api/extract", json={"transcript": "a"}, headers={"X-API-Key": key})
    assert r.json()["slack_sent"] is False and r.json()["saved"] is False
    assert db.meetings_this_month(c.id) == 0
    monkeypatch.setattr(main.requests, "post", lambda url, **kw: type("R", (), {"status_code": 200})())
    r = client.post("/api/extract", json={"transcript": "a"}, headers={"X-API-Key": key})
    assert r.json()["saved"] is True and db.meetings_this_month(c.id) == 1


def test_meeting_date_uses_business_timezone(monkeypatch):
    monkeypatch.setenv("REMINDER_TZ", "America/Chicago")
    import datetime as dt
    assert extract.local_today() == dt.datetime.now(dt.timezone.utc).astimezone(
        __import__("zoneinfo").ZoneInfo("America/Chicago")).date()
