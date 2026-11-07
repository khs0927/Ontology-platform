"""Contract ``aec-cair-snapshot/1``: khs0927/Ontology ingestion result → Sion graph + evidence.

Consolidation phase 1 (docs/CONSOLIDATION_PLAN.md, docs/INTEGRATION_CONTRACTS.md §11).

* Fixtures under ``tests/contracts/fixtures/aec-cair/`` are CAIR snapshots captured from
  khs0927/Ontology @ d81598f (PROVENANCE.md). They pin what the upstream producer emits.
* The live tests run the bundled ``packages/aec`` CLI through ``sion_cair.ingest`` in a subprocess,
  exactly as an external checkout or a pinned venv would be run.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from sion_api import models
from sion_api.db import Base, build_engine, build_session_factory
from sion_api.repository import seed_core_types
from sion_cair import AecCairError
from sion_cair.ingest import (
    CONTRACT,
    cair_snapshot_to_map_export,
    ingest_cair_snapshot,
    ingest_with_ontology,
    run_ontology_ingest,
    snapshot_errors,
)
from sion_core import contracts, is_available
from sqlalchemy import func, select

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "contracts" / "fixtures" / "aec-cair"
AEC_FIXTURES = ROOT / "packages" / "aec" / "fixtures"
UPSTREAM = sorted(FIXTURES.glob("*.cair.json"))


def _session():
    engine = build_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = build_session_factory(engine)
    session = factory()
    seed_core_types(session)
    return session


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_contract_is_registered_and_pinned_to_ontology():
    assert CONTRACT in contracts.names()
    assert contracts.is_pinned(CONTRACT)
    schema = contracts.load(CONTRACT)
    assert schema["x-sion-contract"]["upstream"] == "khs0927/Ontology"
    assert schema["x-sion-contract"]["upstream_commit"] == "d81598f"
    docs = (ROOT / "docs" / "INTEGRATION_CONTRACTS.md").read_text(encoding="utf-8")
    assert "`d81598f`" in docs and CONTRACT in docs


def test_upstream_fixtures_present():
    assert {p.name for p in UPSTREAM} == {"simple_house.dxf.cair.json", "simple_house.ifc.cair.json"}


@pytest.mark.parametrize("path", UPSTREAM, ids=lambda p: p.name)
def test_upstream_snapshot_validates(path):
    snapshot = _load(path)
    assert contracts.errors(CONTRACT, snapshot) == []
    assert snapshot_errors(snapshot) == []


@pytest.mark.parametrize("path", UPSTREAM, ids=lambda p: p.name)
def test_upstream_snapshot_maps_into_sion_graph_with_evidence(path):
    snapshot = _load(path)
    export = cair_snapshot_to_map_export(snapshot)
    artifacts = [n for n in export.nodes if n.entity_type_id == "Artifact"]
    concepts = [n for n in export.nodes if n.entity_type_id == "Concept"]
    assert len(artifacts) == 1 and artifacts[0].external_uri.startswith("urn:sha256:")
    assert len(concepts) == len(snapshot["objects"])
    extracted = [e for e in export.edges if e.relation_type_id == "EXTRACTED_FROM"]
    assert len(extracted) == len(snapshot["objects"])
    assert all(e.verification_state == "unverified" for e in export.edges)

    session = _session()
    first = ingest_cair_snapshot(session, snapshot)
    assert first["created_nodes"] == len(export.nodes)
    assert first["created_edges"] == len(export.edges)
    assert first["evidence_created"] == len(extracted)
    assert first["verification_state"] == "unverified"
    evidence = session.scalars(select(models.Evidence)).all()
    assert evidence and all(e.verification_state == "unverified" for e in evidence)
    assert all(e.extractor.startswith("aec-cair/") for e in evidence)
    assert all(e.source_uri == artifacts[0].external_uri for e in evidence)
    assert all(e.properties["contract"] == CONTRACT for e in evidence)

    again = ingest_cair_snapshot(session, snapshot)  # idempotent, non-destructive
    assert again["created_nodes"] == again["created_edges"] == again["evidence_created"] == 0
    assert session.scalar(select(func.count()).select_from(models.Evidence)) == len(extracted)


def test_dxf_hosted_by_and_ifc_contains_become_part_of():
    dxf = cair_snapshot_to_map_export(_load(FIXTURES / "simple_house.dxf.cair.json"))
    assert sum(1 for e in dxf.edges if e.properties.get("cair_predicate") == "hostedBy" and e.relation_type_id == "PART_OF") == 3
    assert not any(e.properties.get("cair_predicate") == "containsElement" for e in dxf.edges)

    ifc_snapshot = _load(FIXTURES / "simple_house.ifc.cair.json")
    ifc = cair_snapshot_to_map_export(ifc_snapshot)
    contains = [r for r in ifc_snapshot["relations"] if r["predicate"] == "contains"]
    part_of = [e for e in ifc.edges if e.properties.get("cair_predicate") == "contains"]
    assert len(part_of) == len(contains) == 4
    for relation in contains:  # child PART_OF parent
        assert any(
            e.source_stable_key == "cair:" + relation["object"] and e.target_stable_key == "cair:" + relation["subject"]
            and e.relation_type_id == "PART_OF"
            for e in part_of
        )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda s: s.update(schema_version="2.0.0"),
        lambda s: s.update(status="FAILED"),
        lambda s: s.pop("objects"),
        lambda s: s["objects"][0].pop("source"),
        lambda s: s["objects"][0].update(id=None),
    ],
    ids=["future-major", "failed", "no-objects", "no-source", "no-id"],
)
def test_contract_violations_are_refused(mutate):
    snapshot = copy.deepcopy(_load(FIXTURES / "simple_house.dxf.cair.json"))
    mutate(snapshot)
    assert snapshot_errors(snapshot)
    with pytest.raises(AecCairError):
        cair_snapshot_to_map_export(snapshot)


def test_unsupported_suffix_and_bad_project_id_are_refused(tmp_path):
    other = tmp_path / "x.pdf"
    other.write_bytes(b"%PDF-1.4")
    with pytest.raises(AecCairError, match="DXF/IFC"):
        run_ontology_ingest(other, "p1")
    with pytest.raises(AecCairError, match="project_id"):
        run_ontology_ingest(AEC_FIXTURES / "simple_house.dxf", "../escape")
    with pytest.raises(AecCairError, match="not an Ontology checkout"):
        run_ontology_ingest(AEC_FIXTURES / "simple_house.dxf", "p1", ontology_root=tmp_path)


@pytest.mark.skipif(not is_available("ezdxf"), reason="needs the 'cad' (or 'aec') extra")
def test_live_bundled_dxf_ingest_round_trip():
    session = _session()
    result = ingest_with_ontology(session, AEC_FIXTURES / "simple_house.dxf", "simple-house-dxf")
    upstream = _load(FIXTURES / "simple_house.dxf.cair.json")
    assert result["contract"] == CONTRACT
    # bundled subtree and pinned upstream agree on the object set (CAIR ids are uuid5 of the source id)
    ids = {e.external_uri for e in session.scalars(select(models.Entity).where(models.Entity.entity_type_id == "Concept"))}
    assert ids == {o["id"] for o in upstream["objects"]}
    assert result["evidence_created"] == len(upstream["objects"])


@pytest.mark.skipif(not is_available("ifcopenshell"), reason="needs the 'bim' (or 'aec') extra")
def test_live_bundled_ifc_ingest_round_trip():
    session = _session()
    result = ingest_with_ontology(session, AEC_FIXTURES / "simple_house.ifc", "simple-house-ifc")
    upstream = _load(FIXTURES / "simple_house.ifc.cair.json")
    ids = {e.external_uri for e in session.scalars(select(models.Entity).where(models.Entity.entity_type_id == "Concept"))}
    assert ids == {o["id"] for o in upstream["objects"]}
    assert result["created_edges"] == len(upstream["objects"]) + 4
