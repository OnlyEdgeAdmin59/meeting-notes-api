import json
from datetime import date
from types import SimpleNamespace

import extract

MEETING = date(2026, 9, 29)


def _llm(monkeypatch, payload, captured=None):
    def create(**kw):
        if captured is not None:
            captured.update(kw)
        return SimpleNamespace(content=[SimpleNamespace(text=json.dumps(payload))])
    monkeypatch.setattr(extract.client.messages, "create", create)


def test_spanish_meeting(monkeypatch):
    kw = {}
    _llm(monkeypatch, {"language": "es", "summary": "Se acordó lanzar.", "decisions": ["Lanzar el lunes"],
                       "action_items": [{"task": "Enviar reporte", "owner": "Juan", "deadline": "viernes",
                                         "due_date": "2026-10-02"}]}, kw)
    r = extract.extract_action_items("Juan: yo mando el reporte el viernes", meeting_date=MEETING)
    assert r["language"] == "es" and r["decisions"] == ["Lanzar el lunes"]
    assert r["action_items"][0]["due_date"] == date(2026, 10, 2)
    assert kw["max_tokens"] >= 4096
    assert "2026-09-29" in kw["messages"][0]["content"]


def test_bad_values_are_sanitized(monkeypatch):
    _llm(monkeypatch, {"language": "fr", "summary": "x", "action_items": [
        {"task": "a", "owner": None, "due_date": "2031-01-01"},
        {"task": "b", "due_date": "not a date"},
        {"owner": "no task"}, "garbage"]})
    r = extract.extract_action_items("t", meeting_date=MEETING)
    assert r["language"] == "en" and r["decisions"] == []
    assert [i["task"] for i in r["action_items"]] == ["a", "b"]
    assert all(i["due_date"] is None for i in r["action_items"])
    assert r["action_items"][0]["owner"] == "Unassigned"


def test_parse_due_date_window():
    assert extract.parse_due_date("2026-09-25", MEETING) == date(2026, 9, 25)
    assert extract.parse_due_date("2026-09-01", MEETING) is None
    assert extract.parse_due_date(None, MEETING) is None


def test_slack_message_spanish_with_decisions_and_links():
    msg = extract.format_slack_message(
        [{"task": "Enviar", "owner": "Juan", "deadline": "viernes"}], "Resumen", ["Lanzar"], "es",
        ["https://x.example/t/abc"])
    text = json.dumps(msg, ensure_ascii=False)
    assert "Seguimiento de la reunión" in text and "Decisiones" in text and "Responsable" in text
    assert "<https://x.example/t/abc|☑️ Marcar como hecha>" in text


def test_slack_message_escapes_mentions():
    msg = extract.format_slack_message([{"task": "<!channel> ping", "owner": "<@U1>"}], "<!here>")
    text = json.dumps(msg)
    assert "<!channel>" not in text and "<!here>" not in text and "<@U1>" not in text


def test_empty_message():
    msg = extract.format_slack_message([], "s", [], "es")
    assert "No se detectaron tareas" in msg["text"]
