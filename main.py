import asyncio
import html
import logging
import os
import secrets
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import date
from typing import Optional

import requests
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

import db
import reminders
from extract import extract_action_items, format_slack_message
from transcript_files import MAX_FILE_BYTES, TranscriptFileError, file_to_transcript

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("meeting_notes")

MAX_TRANSCRIPT_CHARS = 50_000
RATE_LIMIT = "10/minute"
SCHEDULER_INTERVAL_SECONDS = 15 * 60


def _rate_limit_key(request: Request) -> str:
    # Por API key; la key ya fue validada por require_client antes de contar.
    return request.headers.get("x-api-key", "")


async def _scheduler_loop():
    while True:
        try:
            stats = await run_in_threadpool(reminders.run_reminders)
            if stats.get("sent") or stats.get("failed"):
                logger.info("reminders: %s", stats)
        except Exception as e:  # nunca tumbar el proceso por el scheduler
            logger.error("reminders loop failed: %s", type(e).__name__)
        await asyncio.sleep(SCHEDULER_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = None
    try:
        await run_in_threadpool(db.get_sessionmaker)  # crea tablas una vez, antes del primer request
    except Exception as e:
        logger.error("database init failed: %s", type(e).__name__)
    if not os.getenv("DATABASE_URL"):
        logger.warning("DATABASE_URL not set: using local SQLite (data is lost on redeploy in Render)")
    if os.getenv("ENABLE_SCHEDULER") == "1":
        task = asyncio.create_task(_scheduler_loop())
    yield
    if task:
        task.cancel()


limiter = Limiter(key_func=_rate_limit_key)
app = FastAPI(title="Meeting Notes API", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

SECURITY_HEADERS = {
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    # Tailwind CDN genera estilos en runtime -> style-src necesita 'unsafe-inline'. Scripts: sin inline.
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self' https://cdn.tailwindcss.com; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
    ),
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",  # los links /t/<código> no deben filtrarse por Referer
}


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    for name, value in SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    return response


app.mount("/static", StaticFiles(directory="public"), name="static")


# ---------- Autenticación ----------

@dataclass
class ClientCtx:
    id: Optional[int]          # None = cliente "legacy" de CLIENT_API_KEYS (sin DB)
    name: str
    webhook_url: Optional[str]
    monthly_limit: Optional[int]


def _client_api_keys() -> list:
    # Se lee en cada request: sin keys configuradas no entra nadie (fail closed).
    return [k.strip() for k in os.getenv("CLIENT_API_KEYS", "").split(",") if k.strip()]


def require_client(x_api_key: Optional[str] = Header(None)) -> ClientCtx:
    if x_api_key:
        try:
            c = db.find_client_by_key(x_api_key)
        except Exception as e:
            logger.error("client lookup failed: %s", type(e).__name__)
            c = None
        if c is not None:
            return ClientCtx(c.id, c.name, c.webhook_url, c.monthly_limit)
        given = x_api_key.encode()
        ok = False
        for key in _client_api_keys():
            ok |= secrets.compare_digest(given, key.encode())
        if ok:
            return ClientCtx(None, "legacy", None, None)
    raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key")


# ---------- Validación de webhook ----------

SLACK_WEBHOOK_PREFIX = "https://hooks.slack.com/services/"


def _valid_webhook(url: Optional[str]) -> bool:
    return bool(url) and url.startswith(SLACK_WEBHOOK_PREFIX)


def _bad_webhook() -> JSONResponse:
    return JSONResponse(
        {"success": False, "error": f"webhook_url must start with {SLACK_WEBHOOK_PREFIX}"},
        status_code=400
    )


def _error(message: str, status: int) -> JSONResponse:
    return JSONResponse({"success": False, "error": message}, status_code=status)


class ExtractRequest(BaseModel):
    transcript: str = Field(min_length=1, max_length=MAX_TRANSCRIPT_CHARS)
    webhook_url: Optional[str] = None


class TestRequest(BaseModel):
    webhook_url: Optional[str] = None


# ---------- Flujo principal ----------

def _process(ctx: ClientCtx, transcript: str, webhook_override: Optional[str]):
    webhook = webhook_override or ctx.webhook_url
    if not _valid_webhook(webhook):
        return _bad_webhook()

    if ctx.id is not None and ctx.monthly_limit is not None:
        if db.meetings_this_month(ctx.id) >= ctx.monthly_limit:
            return _error(f"Monthly limit reached ({ctx.monthly_limit} meetings). "
                          "Upgrade to the Unlimited plan to keep going.", 429)

    extraction = extract_action_items(transcript)
    if not extraction["success"]:
        return _error("Extraction failed. Please try again later.", 502)

    items = extraction["action_items"]
    language = extraction.get("language", "en")
    decisions = extraction.get("decisions", [])
    summary = extraction.get("summary", "")

    # Los links de "hecha" se generan antes de publicar; la reunión solo se guarda
    # (y cuenta para el tope) si Slack la recibió, para no duplicar tareas en reintentos.
    codes = [db.new_done_code() for _ in items] if ctx.id is not None else None
    done_links = [reminders.done_url(c) for c in codes] if codes else None

    slack_message = format_slack_message(items, summary, decisions, language, done_links)

    slack_sent = False
    try:
        response = requests.post(webhook, json=slack_message, timeout=5, allow_redirects=False)
        slack_sent = response.status_code == 200
    except Exception as e:
        logger.warning("Slack webhook post failed: %s", type(e).__name__)

    saved = False
    if ctx.id is not None and slack_sent:
        db.save_meeting(ctx.id, summary, language, items, codes)
        saved = True

    return {
        "success": True,
        "language": language,
        "summary": summary,
        "decisions": decisions,
        "action_items": [{**i, "due_date": i["due_date"].isoformat() if isinstance(i.get("due_date"), date) else None}
                         for i in items],
        "saved": saved,
        "slack_sent": slack_sent,
    }


@app.get("/")
async def root():
    return FileResponse("public/index.html")


@app.post("/api/extract")
@limiter.shared_limit(RATE_LIMIT, scope="api")
async def extract(request: Request, body: ExtractRequest, ctx: ClientCtx = Depends(require_client)):
    return await run_in_threadpool(_process, ctx, body.transcript, body.webhook_url)


@app.post("/api/extract-file")
@limiter.shared_limit(RATE_LIMIT, scope="api")
async def extract_file(request: Request, file: UploadFile = File(...),
                       webhook_url: Optional[str] = Form(None),
                       ctx: ClientCtx = Depends(require_client)):
    data = await file.read(MAX_FILE_BYTES + 1)
    try:
        transcript = file_to_transcript(file.filename or "", data)
    except TranscriptFileError as e:
        return _error(str(e), 400)
    if len(transcript) > MAX_TRANSCRIPT_CHARS:
        return _error(f"Transcript too long (max {MAX_TRANSCRIPT_CHARS} characters)", 413)
    return await run_in_threadpool(_process, ctx, transcript, webhook_url or None)


@app.get("/api/me")
@limiter.shared_limit(RATE_LIMIT, scope="api")
async def me(request: Request, ctx: ClientCtx = Depends(require_client)):
    used = await run_in_threadpool(db.meetings_this_month, ctx.id) if ctx.id is not None else None
    return {"name": ctx.name, "has_saved_webhook": bool(ctx.webhook_url),
            "meetings_this_month": used, "monthly_limit": ctx.monthly_limit}


@app.post("/api/test")
@limiter.shared_limit(RATE_LIMIT, scope="api")
async def test_webhook(request: Request, body: Optional[TestRequest] = None,
                       ctx: ClientCtx = Depends(require_client)):
    webhook = (body.webhook_url if body else None) or ctx.webhook_url
    if not _valid_webhook(webhook):
        return _bad_webhook()

    test_message = {
        "text": "🧪 Test message from NoteMeeting",
        "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": "✅ Working!"}}]
    }

    try:
        response = requests.post(webhook, json=test_message, timeout=5, allow_redirects=False)
        return {"success": response.status_code == 200, "status_code": response.status_code}
    except Exception as e:
        logger.warning("Slack webhook test failed: %s", type(e).__name__)
        return {"success": False, "error": "Could not reach the Slack webhook"}


# ---------- Marcar tarea como hecha (link desde Slack) ----------
# GET solo muestra la tarea: Slack pre-carga links al hacer unfurl y eso NO debe cerrarla.
# El cierre real es un POST desde el botón de la página.

PAGE = """<!DOCTYPE html><html lang="{lang}"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="robots" content="noindex"><title>NoteMeeting</title>
<style>body{{font-family:system-ui,sans-serif;background:#f9fafb;margin:0;padding:24px;color:#111827}}
.card{{max-width:520px;margin:40px auto;background:#fff;border-radius:12px;padding:24px;box-shadow:0 1px 4px rgba(0,0,0,.08)}}
button{{background:#7c3aed;color:#fff;border:0;border-radius:8px;padding:12px 20px;font-size:16px;cursor:pointer;width:100%}}
.muted{{color:#6b7280;font-size:14px}}</style></head><body><div class="card">{body}</div></body></html>"""

T_TEXT = {
    "en": {"confirm": "Mark as done", "done": "✅ Task marked as done. You can close this page.",
           "already": "✅ This task was already done.", "missing": "Task not found.",
           "owner": "Owner", "deadline": "Deadline"},
    "es": {"confirm": "Marcar como hecha", "done": "✅ Tarea marcada como hecha. Ya puedes cerrar esta página.",
           "already": "✅ Esta tarea ya estaba hecha.", "missing": "No se encontró la tarea.",
           "owner": "Responsable", "deadline": "Fecha límite"},
}


def _task_page(task, body_html: str) -> HTMLResponse:
    lang = task.language if task else "en"
    return HTMLResponse(PAGE.format(lang=lang, body=body_html),
                        status_code=200 if task else 404,
                        headers={"Cache-Control": "no-store"})


def _task_summary(task) -> str:
    T = T_TEXT.get(task.language, T_TEXT["en"])
    return (f"<h2>{html.escape(task.task)}</h2>"
            f"<p class='muted'>{T['owner']}: {html.escape(task.owner)} · "
            f"{T['deadline']}: {html.escape(task.deadline_text or '-')}</p>")


@app.get("/t/{code}")
@limiter.limit("30/minute", key_func=get_remote_address)
async def task_page(request: Request, code: str):
    task = await run_in_threadpool(db.get_task_by_code, code)
    if task is None:
        return _task_page(None, f"<p>{T_TEXT['en']['missing']} / {T_TEXT['es']['missing']}</p>")
    T = T_TEXT.get(task.language, T_TEXT["en"])
    if task.status == "done":
        return _task_page(task, _task_summary(task) + f"<p>{T['already']}</p>")
    form = (f"<form method='post' action='/t/{html.escape(code)}'>"
            f"<button type='submit'>☑️ {T['confirm']}</button></form>")
    return _task_page(task, _task_summary(task) + form)


@app.post("/t/{code}")
@limiter.limit("30/minute", key_func=get_remote_address)
async def task_done(request: Request, code: str):
    task = await run_in_threadpool(db.mark_done, code)
    if task is None:
        return _task_page(None, f"<p>{T_TEXT['en']['missing']} / {T_TEXT['es']['missing']}</p>")
    T = T_TEXT.get(task.language, T_TEXT["en"])
    return _task_page(task, _task_summary(task) + f"<p>{T['done']}</p>")


# ---------- Recordatorios (cron) ----------

@app.post("/api/cron/reminders")
async def cron_reminders(x_cron_secret: Optional[str] = Header(None)):
    expected = os.getenv("CRON_SECRET", "")
    if not expected or not x_cron_secret or not secrets.compare_digest(x_cron_secret.encode(), expected.encode()):
        raise HTTPException(status_code=403, detail="Forbidden")
    return await run_in_threadpool(reminders.run_reminders)


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
