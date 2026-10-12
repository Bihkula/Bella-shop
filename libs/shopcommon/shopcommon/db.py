"""SQLAlchemy engine/session management. Each service owns its own database."""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    global _engine, _session_factory
    if _engine is None:
        url = get_settings().database_url
        kwargs: dict = {"pool_pre_ping": True}
        if url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False}
        else:
            kwargs.update(pool_size=5, max_overflow=10)
        _engine = create_engine(url, **kwargs)
        _session_factory = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def _factory() -> sessionmaker[Session]:
    get_engine()
    if _session_factory is None:  # pragma: no cover - get_engine always sets it
        raise RuntimeError("database not initialised")
    return _session_factory


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a session that is always closed."""
    session = _factory()()
    try:
        yield session
    finally:
        session.close()


def session_scope() -> Session:
    """Use as `with session_scope() as db:` outside request handlers."""
    return _factory()()


def ping() -> bool:
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001 - readiness must never raise
        return False


def init_schema() -> None:
    # Fine for a demo. For real schema evolution, switch to Alembic migrations
    # run as a Kubernetes Job / Argo CD PreSync hook.
    Base.metadata.create_all(get_engine())
