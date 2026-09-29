"""Persistencia: clientes, reuniones y tareas.

DATABASE_URL (Postgres en Render) o SQLite local por defecto.
Las API keys se guardan solo como hash SHA-256; nunca en texto plano.
"""
import hashlib
import os
import secrets
import threading
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import (Boolean, Date, DateTime, ForeignKey, Integer, String, Text,
                        create_engine, func, select)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

DEFAULT_URL = "sqlite:///./notemeeting.db"
DEFAULT_MONTHLY_LIMIT = 20


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Client(Base):
    __tablename__ = "clients"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    api_key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    webhook_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    monthly_limit: Mapped[int] = mapped_column(Integer, default=DEFAULT_MONTHLY_LIMIT)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_digest_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Meeting(Base):
    __tablename__ = "meetings"
    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    language: Mapped[str] = mapped_column(String(5), default="en")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)


class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True)
    meeting_id: Mapped[int] = mapped_column(ForeignKey("meetings.id"), index=True)
    task: Mapped[str] = mapped_column(Text)
    owner: Mapped[str] = mapped_column(String(200), default="Unassigned")
    deadline_text: Mapped[str] = mapped_column(String(200), default="")
    due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True, index=True)
    language: Mapped[str] = mapped_column(String(5), default="en")
    status: Mapped[str] = mapped_column(String(10), default="open", index=True)
    done_code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    done_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


_engine = None
_Session = None
_lock = threading.Lock()


def _url() -> str:
    url = os.getenv("DATABASE_URL", DEFAULT_URL)
    # Render entrega postgres:// ; SQLAlchemy + psycopg 3 necesita postgresql+psycopg://
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def get_sessionmaker():
    global _engine, _Session
    if _Session is None:
        with _lock:
            if _Session is None:
                engine = create_engine(_url(), pool_pre_ping=True)
                Base.metadata.create_all(engine)
                _engine = engine
                _Session = sessionmaker(engine, expire_on_commit=False)
    return _Session


def reset() -> None:
    """Olvida el engine actual (tests / cambio de DATABASE_URL)."""
    global _engine, _Session
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _Session = None


def session() -> Session:
    return get_sessionmaker()()


def hash_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode()).hexdigest()


def new_api_key() -> str:
    return "nm_" + secrets.token_urlsafe(32)


def create_client(name: str, webhook_url: Optional[str], monthly_limit: int = DEFAULT_MONTHLY_LIMIT):
    """Crea un cliente y devuelve (client, api_key). La key solo se ve esta vez."""
    api_key = new_api_key()
    with session() as s:
        c = Client(name=name, api_key_hash=hash_key(api_key), webhook_url=webhook_url,
                   monthly_limit=monthly_limit)
        s.add(c)
        s.commit()
        return c, api_key


def find_client_by_key(api_key: str) -> Optional[Client]:
    h = hash_key(api_key)
    with session() as s:
        c = s.scalar(select(Client).where(Client.api_key_hash == h))
        if c is None or not c.active:
            return None
        # compare_digest para no filtrar por timing (el índice ya hizo el lookup)
        return c if secrets.compare_digest(c.api_key_hash, h) else None


def meetings_this_month(client_id: int, now: Optional[datetime] = None) -> int:
    now = now or _utcnow()
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    with session() as s:
        return s.scalar(select(func.count(Meeting.id)).where(
            Meeting.client_id == client_id, Meeting.created_at >= start)) or 0


def new_done_code() -> str:
    return secrets.token_urlsafe(24)


def save_meeting(client_id: int, summary: str, language: str, items: list,
                 codes: Optional[list] = None) -> list:
    """Guarda la reunión y sus tareas. Devuelve las tareas creadas (con done_code).
    codes: códigos pre-generados (para poner los links en Slack antes de guardar)."""
    with session() as s:
        m = Meeting(client_id=client_id, summary=summary, language=language)
        s.add(m)
        s.flush()
        tasks = []
        for i, it in enumerate(items):
            t = Task(client_id=client_id, meeting_id=m.id, task=str(it.get("task", ""))[:2000],
                     owner=str(it.get("owner") or "Unassigned")[:200],
                     deadline_text=str(it.get("deadline") or "")[:200],
                     due_date=it.get("due_date"), language=language,
                     done_code=codes[i] if codes and i < len(codes) else new_done_code())
            s.add(t)
            tasks.append(t)
        s.commit()
        return tasks


def get_task_by_code(code: str) -> Optional[Task]:
    with session() as s:
        return s.scalar(select(Task).where(Task.done_code == code))


def mark_done(code: str) -> Optional[Task]:
    with session() as s:
        t = s.scalar(select(Task).where(Task.done_code == code))
        if t is None:
            return None
        if t.status != "done":
            t.status = "done"
            t.done_at = _utcnow()
            s.commit()
        return t


def claim_digest(client_id: int, today: date) -> Optional[date]:
    """Reserva el recordatorio de hoy de forma atómica.
    Devuelve el valor anterior de last_digest_on si se reservó, o la fecha de hoy si ya estaba tomado."""
    from sqlalchemy import or_, update
    with session() as s:
        prev = s.scalar(select(Client.last_digest_on).where(Client.id == client_id))
        res = s.execute(update(Client).where(
            Client.id == client_id,
            or_(Client.last_digest_on.is_(None), Client.last_digest_on < today)
        ).values(last_digest_on=today))
        s.commit()
        return prev if res.rowcount == 1 else today


def release_digest(client_id: int, previous: Optional[date]) -> None:
    from sqlalchemy import update
    with session() as s:
        s.execute(update(Client).where(Client.id == client_id).values(last_digest_on=previous))
        s.commit()
