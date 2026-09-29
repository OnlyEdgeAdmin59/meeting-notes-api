import pytest

import main
from conftest import GOOD_WEBHOOK
from transcript_files import TranscriptFileError, file_to_transcript

VTT_ZOOM = """WEBVTT

1
00:00:01.000 --> 00:00:04.000
Ana García: Hola a todos.

2
00:00:04.500 --> 00:00:08.000
Ana García: Juan, ¿mandas el reporte el viernes?

3
00:00:08.500 --> 00:00:10.000
Juan: Sí, yo lo mando.
"""

VTT_TEAMS = """WEBVTT

00:00:01.000 --> 00:00:04.000
<v Ana García>Let's ship Friday.</v>

00:00:04.000 --> 00:00:06.000
<v Bob>I'll do QA.</v>
"""

SRT = """1
00:00:01,000 --> 00:00:03,000
Ana: Primera línea

2
00:00:03,000 --> 00:00:05,000
Bob: Segunda línea
"""


def test_zoom_vtt_merges_same_speaker():
    text = file_to_transcript("meeting.vtt", VTT_ZOOM.encode())
    assert text.splitlines() == ["Ana García: Hola a todos. Juan, ¿mandas el reporte el viernes?",
                                 "Juan: Sí, yo lo mando."]


def test_teams_voice_tags():
    assert file_to_transcript("t.VTT", VTT_TEAMS.encode()) == "Ana García: Let's ship Friday.\nBob: I'll do QA."


def test_srt():
    assert file_to_transcript("x.srt", SRT.encode()) == "Ana: Primera línea\nBob: Segunda línea"


def test_txt_passthrough_and_bom():
    assert file_to_transcript("x.txt", "﻿Ana: hola".encode("utf-8")) == "Ana: hola"


@pytest.mark.parametrize("name,data", [("x.pdf", b"a"), ("x.exe", b"a"), ("x.txt", b"   "),
                                       ("x.txt", b"a" * 1_000_001)])
def test_rejected_files(name, data):
    with pytest.raises(TranscriptFileError):
        file_to_transcript(name, data)


def test_extract_file_endpoint(client, monkeypatch):
    seen = []
    monkeypatch.setattr(main, "extract_action_items", lambda t: seen.append(t) or {
        "success": True, "action_items": [], "summary": "ok"})
    r = client.post("/api/extract-file", files={"file": ("m.vtt", VTT_ZOOM.encode(), "text/vtt")},
                    data={"webhook_url": GOOD_WEBHOOK})
    assert r.status_code == 200, r.text
    assert seen and seen[0].startswith("Ana García: Hola")


def test_extract_file_bad_type_400(client):
    r = client.post("/api/extract-file", files={"file": ("m.pdf", b"x", "application/pdf")},
                    data={"webhook_url": GOOD_WEBHOOK})
    assert r.status_code == 400


def test_extract_file_requires_key(client):
    del client.headers["X-API-Key"]
    r = client.post("/api/extract-file", files={"file": ("m.txt", b"hola", "text/plain")})
    assert r.status_code == 401


def test_extract_file_too_long_413(client):
    r = client.post("/api/extract-file", files={"file": ("m.txt", b"a" * 50_001, "text/plain")},
                    data={"webhook_url": GOOD_WEBHOOK})
    assert r.status_code == 413
