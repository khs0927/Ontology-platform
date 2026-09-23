from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool


class Base(DeclarativeBase):
    pass


CORE_ENTITY_TYPES = (
    ("Project", "Project"),
    ("Tool", "Tool"),
    ("Concept", "Concept"),
    ("Document", "Document"),
    ("Artifact", "Artifact"),
    ("Dataset", "Dataset"),
    ("SystemComponent", "System Component"),
    ("Workflow", "Workflow"),
    ("Decision", "Decision"),
    ("Deliverable", "Deliverable"),
)

CORE_RELATION_TYPES = (
    ("RELATED_TO", "Related To"),
    ("USES", "Uses"),
    ("PRODUCES", "Produces"),
    ("DERIVED_FROM", "Derived From"),
    ("PART_OF", "Part Of"),
    ("DEPENDS_ON", "Depends On"),
    ("VALIDATES", "Validates"),
    ("REFERENCES", "References"),
    ("IMPLEMENTS", "Implements"),
    ("SUPPORTS", "Supports"),
)


def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


class Database:
    def __init__(self, url: str):
        kwargs: dict = {"future": True}
        if url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False}
            if ":memory:" in url:
                kwargs["poolclass"] = StaticPool
            elif url.startswith("sqlite:///"):
                db_path = Path(url.removeprefix("sqlite:///"))
                if db_path.parent != Path("."):
                    db_path.parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(url, **kwargs)
        if self.engine.dialect.name == "sqlite":
            event.listen(self.engine, "connect", _enable_sqlite_foreign_keys)
        self.SessionLocal = sessionmaker(bind=self.engine, autoflush=False, expire_on_commit=False)

    @property
    def is_sqlite(self) -> bool:
        return self.engine.dialect.name == "sqlite"

    def initialize(self) -> None:
        if not self.is_sqlite:
            return
        Base.metadata.create_all(self.engine)
        from .models import EntityType, RelationType
        with self.SessionLocal() as db:
            for type_id, label in CORE_ENTITY_TYPES:
                if db.get(EntityType, type_id) is None:
                    db.add(EntityType(id=type_id, label=label, properties={}))
            for type_id, label in CORE_RELATION_TYPES:
                if db.get(RelationType, type_id) is None:
                    db.add(RelationType(id=type_id, label=label, properties={}))
            db.commit()

    def session(self) -> Generator[Session, None, None]:
        db = self.SessionLocal()
        try:
            yield db
        finally:
            db.close()
