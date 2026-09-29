"""Loop de seguimiento: recordatorio diario de tareas por vencer y vencidas.

Se dispara con POST /api/cron/reminders (header X-Cron-Secret) o con el
scheduler interno (ENABLE_SCHEDULER=1). Es idempotente: cada cliente recibe
como máximo un recordatorio por día (clients.last_digest_on).
"""
import logging
import os
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Optional
from zoneinfo import ZoneInfo

import requests
from sqlalchemy import select

import db
from extract import _slack_escape, clip, labels

logger = logging.getLogger("meeting_notes")

DIGEST_LABELS = {
    "en": {"title": "⏰ Pending tasks from your meetings", "overdue": "Overdue", "today": "Due today",
           "tomorrow": "Due tomorrow", "nodate": "Open, no deadline", "since": "due"},
    "es": {"title": "⏰ Tareas pendientes de tus reuniones", "overdue": "Vencidas", "today": "Vencen hoy",
           "tomorrow": "Vencen mañana", "nodate": "Abiertas, sin fecha", "since": "vencía"},
}


def _tz() -> ZoneInfo:
    return ZoneInfo(os.getenv("REMINDER_TZ", "America/Chicago"))


def _hour() -> int:
    return int(os.getenv("REMINDER_HOUR", "9"))


def done_url(code: str) -> Optional[str]:
    base = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
    return f"{base}/t/{code}" if base.startswith("https://") else None


MAX_LINES_PER_GROUP = 15


def build_digest(tasks: list, today: date, language: str) -> Optional[dict]:
    """Arma el mensaje de Slack. None si no hay nada que recordar."""
    D = DIGEST_LABELS.get(language, DIGEST_LABELS["en"])
    L = labels(language)
    tomorrow = today + timedelta(days=1)
    groups = {
        "overdue": [t for t in tasks if t.due_date and t.due_date < today],
        "today": [t for t in tasks if t.due_date == today],
        "tomorrow": [t for t in tasks if t.due_date == tomorrow],
        # Los lunes también se recuerdan las tareas abiertas sin fecha
        "nodate": [t for t in tasks if t.due_date is None] if today.weekday() == 0 else [],
    }
    if not any(groups.values()):
        return None

    blocks = [{"type": "header", "text": {"type": "plain_text", "text": D["title"], "emoji": True}}]
    for key, items in groups.items():
        if not items:
            continue
        lines = []
        ordered = sorted(items, key=lambda x: (x.due_date or today, x.id))
        for t in ordered[:MAX_LINES_PER_GROUP]:
            line = f"• *{_slack_escape(clip(t.task, 150))}* · {_slack_escape(clip(t.owner, 60))}"
            if key == "overdue":
                line += f" · {D['since']} {t.due_date.isoformat()}"
            link = done_url(t.done_code)
            if link:
                line += f" · <{link}|{L['done']}>"
            lines.append(line)
        if len(ordered) > MAX_LINES_PER_GROUP:
            lines.append(f"… +{len(ordered) - MAX_LINES_PER_GROUP}")
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"*{D[key]}*\n" + "\n".join(lines)}})
    return {"text": D["title"], "blocks": blocks}


def run_reminders(now: Optional[datetime] = None, post: Optional[Callable] = None, force: bool = False) -> dict:
    """Manda el recordatorio del día a cada cliente activo. Devuelve un resumen."""
    now = now or datetime.now(timezone.utc)
    local = now.astimezone(_tz())
    today = local.date()
    post = post or (lambda url, payload: requests.post(url, json=payload, timeout=5, allow_redirects=False))
    stats = {"clients": 0, "sent": 0, "skipped": 0, "failed": 0}

    if not force and local.hour < _hour():
        return {**stats, "reason": "too_early"}

    with db.session() as s:
        clients = [(c.id, c.webhook_url, c.last_digest_on)
                   for c in s.scalars(select(db.Client).where(db.Client.active.is_(True))).all()]

    for client_id, webhook_url, last_digest_on in clients:
        stats["clients"] += 1
        if last_digest_on == today or not webhook_url:
            stats["skipped"] += 1
            continue
        # Reserva atómica: evita dobles envíos (scheduler + cron, o dos instancias en un deploy)
        previous = db.claim_digest(client_id, today)
        if previous == today:
            stats["skipped"] += 1
            continue
        try:
            with db.session() as s:
                tasks = s.scalars(select(db.Task).where(db.Task.client_id == client_id,
                                                        db.Task.status == "open")).all()
            language = Counter(t.language for t in tasks).most_common(1)[0][0] if tasks else "en"
            message = build_digest(tasks, today, language)
            if message is None:
                stats["skipped"] += 1
                continue
            r = post(webhook_url, message)
            code = getattr(r, "status_code", 0)
            if code == 200:
                stats["sent"] += 1
            elif 400 <= code < 500 and code != 429:
                # Error permanente (webhook borrado, mensaje inválido): no reintentar hoy
                logger.warning("reminder rejected client=%s status=%s", client_id, code)
                stats["failed"] += 1
            else:
                db.release_digest(client_id, previous)  # se reintenta en la próxima corrida
                stats["failed"] += 1
        except Exception as e:
            logger.warning("reminder failed client=%s: %s", client_id, type(e).__name__)
            db.release_digest(client_id, previous)
            stats["failed"] += 1
    return stats
