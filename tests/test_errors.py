import logging
from types import SimpleNamespace

import pytest

import extract
import main
from conftest import GOOD_WEBHOOK

SECRET = "SECRET-CLIENT-DATA-7f3a"


@pytest.fixture
def real_extract(client, monkeypatch):
    monkeypatch.setattr(main, "extract_action_items", extract.extract_action_items)
    return client


def _set_llm(monkeypatch, fn):
    monkeypatch.setattr(extract.client.messages, "create", fn)


def _post(client):
    return client.post("/api/extract", json={"transcript": f"Ana: {SECRET}", "webhook_url": GOOD_WEBHOOK})


def test_llm_exception_generic_to_client_detail_to_log(real_extract, monkeypatch, caplog):
    def boom(**kw):
        raise RuntimeError("internal-detail-xyz")
    _set_llm(monkeypatch, boom)
    with caplog.at_level(logging.ERROR, logger="meeting_notes"):
        r = _post(real_extract)
    assert r.status_code == 502
    assert "internal-detail-xyz" not in r.text and "RuntimeError" not in r.text
    assert "RuntimeError: internal-detail-xyz" in caplog.text
    assert SECRET not in caplog.text


def test_bad_llm_json_does_not_log_transcript_or_model_output(real_extract, monkeypatch, caplog):
    # el modelo "hace eco" del transcript y no devuelve JSON
    _set_llm(monkeypatch, lambda **kw: SimpleNamespace(content=[SimpleNamespace(text=f"not json {SECRET}")]))
    with caplog.at_level(logging.DEBUG):
        r = _post(real_extract)
    assert r.status_code == 502
    assert SECRET not in r.text
    assert SECRET not in caplog.text
    assert "JSONDecodeError" in caplog.text


def test_webhook_network_error_generic(client, monkeypatch, caplog):
    def fail(url, **kw):
        raise ConnectionError("dns internals for hooks.slack.com")
    monkeypatch.setattr(main.requests, "post", fail)
    with caplog.at_level(logging.WARNING, logger="meeting_notes"):
        r = client.post("/api/test", json={"webhook_url": GOOD_WEBHOOK})
    assert r.json() == {"success": False, "error": "Could not reach the Slack webhook"}
    assert "ConnectionError" in caplog.text


def test_extract_ok_when_slack_fails(client, monkeypatch):
    monkeypatch.setattr(main.requests, "post", lambda url, **kw: (_ for _ in ()).throw(ConnectionError("x")))
    r = client.post("/api/extract", json={"transcript": "a", "webhook_url": GOOD_WEBHOOK})
    assert r.status_code == 200 and r.json()["slack_sent"] is False
