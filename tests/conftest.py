import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)  # StaticFiles/FileResponse usan rutas relativas a public/
os.environ.setdefault("ANTHROPIC_API_KEY", "test-not-a-real-key")

GOOD_WEBHOOK = "https://hooks.slack.com/services/T000/B000/XXXX"
API_KEYS = "key-alpha,key-beta"
AUTH = {"X-API-Key": "key-alpha"}


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    pg = os.getenv("TEST_POSTGRES_URL")  # opcional: correr la suite contra Postgres real
    monkeypatch.setenv("DATABASE_URL", pg or f"sqlite:///{tmp_path}/test.db")
    import db
    db.reset()
    if pg:
        db.Base.metadata.drop_all(db.get_sessionmaker().kw["bind"])
        db.reset()
    yield
    db.reset()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("CLIENT_API_KEYS", API_KEYS)
    import main
    from fastapi.testclient import TestClient

    sent = []

    class FakeResp:
        status_code = 200

    def fake_post(url, **kwargs):
        sent.append(url)
        return FakeResp()

    main.limiter.reset()
    monkeypatch.setattr(main.requests, "post", fake_post)
    monkeypatch.setattr(main, "extract_action_items", lambda t: {
        "success": True,
        "action_items": [{"task": "Send report", "owner": "Juan", "deadline": "Friday"}],
        "summary": "ok",
    })
    c = TestClient(main.app, headers=AUTH)
    c.sent = sent
    return c
