from __future__ import annotations

import pytest
from sqlalchemy import select

from sion_api.db import Base, build_engine, build_session_factory
from sion_api.models import Entity
from sion_api.repository import seed_core_types
from sion_ingestion.agent_bridge import AgentOntologyBridge, AgentSession
from sion_ingestion.map_import import GraphIdentityConflictError, MapExport, import_map_export


def factory():
    engine = build_engine("sqlite://")
    Base.metadata.create_all(engine)
    sf = build_session_factory(engine)
    with sf() as session:
        seed_core_types(session)
    return sf


def export_for(session: AgentSession, name: str = "original") -> MapExport:
    export = AgentOntologyBridge().convert_sessions_to_map_export([session])
    for node in export.nodes:
        if node.entity_type_id == "Workflow":
            node.properties.pop("source_uri", None)
            node.properties["source_reference"] = f"urn:sion:agent-session:{session.session_id}"
    return export


def test_session_key_uses_full_identity_and_cwd_hash():
    bridge = AgentOntologyBridge()
    a = AgentSession("same-prefix-123456789", "codex", "A", device_id="dev", cwd="/one/project")
    b = AgentSession("same-prefix-987654321", "codex", "B", device_id="dev", cwd="/one/project")
    c = AgentSession("same-prefix-123456789", "codex", "C", device_id="dev", cwd="/two/project")
    keys = {n.stable_key for n in bridge.convert_sessions_to_map_export([a, b, c]).nodes if n.entity_type_id == "Workflow"}
    assert len(keys) == 3


def test_changed_session_payload_conflicts_and_rolls_back():
    sf = factory()
    original = AgentSession("session-123456789", "codex", "Original", device_id="dev", cwd="/work/project")
    changed = AgentSession("session-123456789", "codex", "Changed", device_id="dev", cwd="/work/project")
    export = export_for(original)
    changed_export = export_for(changed)
    with sf() as session:
        import_map_export(session, export)
        before = session.scalar(select(Entity).where(Entity.stable_key.in_([n.stable_key for n in export.nodes])))
        with pytest.raises(GraphIdentityConflictError):
            import_map_export(session, changed_export)
        after = session.scalar(select(Entity).where(Entity.stable_key == before.stable_key))
        assert after is not None


def test_same_session_same_payload_is_skipped():
    sf = factory()
    export = export_for(AgentSession("session-123456789", "codex", "Same", device_id="dev", cwd="/work/project"))
    with sf() as session:
        first = import_map_export(session, export)
        second = import_map_export(session, export)
    assert first.created_nodes > 0
    assert second.created_nodes == 0
    assert second.skipped_nodes == first.created_nodes


def test_sql_export_is_non_destructive():
    export = export_for(AgentSession("session-123456789", "codex", "Same", device_id="dev", cwd="/work/project"))
    sql = AgentOntologyBridge.export_to_postgres_sql(export)
    assert "ON CONFLICT (stable_key) DO NOTHING;" in sql
    assert "DO UPDATE SET" not in sql
