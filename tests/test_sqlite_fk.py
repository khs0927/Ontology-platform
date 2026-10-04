from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from sion_api import models
from sion_api.db import Base, build_engine, build_session_factory


def test_sqlite_foreign_keys_are_enabled_and_reject_invalid_references():
    engine = build_engine("sqlite://")
    try:
        with engine.connect() as connection:
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1

        Base.metadata.create_all(engine)
        session_factory = build_session_factory(engine)
        with session_factory() as session:
            session.add(
                models.Entity(
                    stable_key="fk:missing-entity-type",
                    entity_type_id="missing-type",
                    name="Invalid entity",
                )
            )
            with pytest.raises(IntegrityError):
                session.flush()
            session.rollback()
    finally:
        engine.dispose()
