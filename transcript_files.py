"""Convierte archivos de transcripción (Zoom/Meet/Teams) a texto plano.

Soporta .vtt (WebVTT: Zoom, Teams, Meet), .srt y .txt.
"""
import re

ALLOWED_EXTENSIONS = (".vtt", ".srt", ".txt")
MAX_FILE_BYTES = 1_000_000  # 1 MB

_TIMESTAMP = re.compile(r"^\s*(\d{1,2}:)?\d{1,2}:\d{2}[.,]\d{1,3}\s*-->\s*(\d{1,2}:)?\d{1,2}:\d{2}[.,]\d{1,3}.*$")
_CUE_NUMBER = re.compile(r"^\s*\d+\s*$")
_VOICE_TAG = re.compile(r"<v(?:\.[^ >]*)?\s+([^>]+)>(.*?)(?:</v>)?$")
_TAGS = re.compile(r"</?[^>]+>")


class TranscriptFileError(ValueError):
    pass


def decode(data: bytes) -> str:
    # UTF-16 solo con BOM: sin BOM, el decoder utf-16 "acepta" casi cualquier cosa y produce basura.
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def _captions_to_text(text: str) -> str:
    lines_out = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.upper().startswith("WEBVTT") or line.startswith(("NOTE", "STYLE", "REGION")):
            continue
        if _TIMESTAMP.match(line) or _CUE_NUMBER.match(line):
            continue
        voice = _VOICE_TAG.match(line)
        if voice:  # Teams/Meet: <v Ana García>texto</v>
            line = f"{voice.group(1).strip()}: {_TAGS.sub('', voice.group(2)).strip()}"
        else:
            line = _TAGS.sub("", line).strip()
        if not line:
            continue
        # Une líneas consecutivas del mismo hablante ("Ana: a" + "Ana: b")
        if lines_out and ":" in line and lines_out[-1].split(":", 1)[0] == line.split(":", 1)[0]:
            lines_out[-1] += " " + line.split(":", 1)[1].strip()
        else:
            lines_out.append(line)
    return "\n".join(lines_out)


def file_to_transcript(filename: str, data: bytes) -> str:
    name = (filename or "").lower()
    if not name.endswith(ALLOWED_EXTENSIONS):
        raise TranscriptFileError("Unsupported file type. Use .vtt, .srt or .txt")
    if len(data) > MAX_FILE_BYTES:
        raise TranscriptFileError("File too large (max 1 MB)")
    text = decode(data)
    if name.endswith((".vtt", ".srt")) or text.lstrip().upper().startswith("WEBVTT"):
        text = _captions_to_text(text)
    text = text.strip()
    if not text:
        raise TranscriptFileError("The file has no transcript text")
    return text
