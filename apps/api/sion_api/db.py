from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool


class Base(DeclarativeBase):
    pass


class SionSession(Session):
    """Session class whose flushes also write transactional outbox events (see sion_api.outbox)."""


def _install_outbox() -> None:
    from . import outbox

    if not event.contains(SionSession, "before_flush", outbox.before_flush):
        event.listen(SionSession, "before_flush", outbox.before_flush)


def build_engine(database_url: str) -> Engine:
    options: dict = {"pool_pre_ping": True}
    if database_url in {"sqlite://", "sqlite:///:memory:"}:
        options.update(
            {
                "connect_args": {"check_same_thread": False},
                "poolclass": StaticPool,
            }
        )
    elif database_url.startswith("sqlite:///"):
        Path(database_url.removeprefix("sqlite:///")).parent.mkdir(
            parents=True, exist_ok=True
        )
        options["connect_args"] = {"check_same_thread": False}

    engine = create_engine(database_url, **options)
    if engine.dialect.name == "sqlite":
        @event.listens_for(engine, "connect")
        def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA foreign_keys=ON")
            finally:
                cursor.close()

    return engine


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    _install_outbox()
    return sessionmaker(bind=engine, expire_on_commit=False, class_=SionSession)


def session_dependency(factory: sessionmaker[Session]):
    def _dependency() -> Generator[Session, None, None]:
        with factory() as session:
            yield session

    return _dependency
