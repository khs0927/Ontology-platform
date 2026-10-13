"""Contract tests for the bridged repositories (docs/INTEGRATION_CONTRACTS.md).

Pinned producer/consumer commits: power-cad-mcp 461df6c, hs-steel-cad cefd395,
korean-land-mcp 9bca5ea, HS-CAD 8bf34e1, All-In-Cad 329f9ad, CAD-MCP 50ae134.
"""

from __future__ import annotations

import copy
import glob
import hashlib
import json
from pathlib import Path

import pytest

jsonschema = pytest.importorskip("jsonschema")

from fastapi.testclient import TestClient  # noqa: E402
from sion_api import regulation  # noqa: E402
from sion_api.main import create_app  # noqa: E402
from sion_cad.reader import dxf_census, ezdxf_available  # noqa: E402
from sion_core import contracts  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "contracts" / "fixtures"
CAD_MCP_DXF = FIX / "cad-mcp_arch_sample_room.dxf"
DXF_FILES = [ROOT / "packages" / "aec" / "fixtures" / "simple_house.dxf", CAD_MCP_DXF] + [
    Path(p) for p in sorted(glob.glob(str(ROOT / "packages" / "aec" / "tests" / "fixtures" / "drawings_ko" / "*.dxf")))
]
needs_ezdxf = pytest.mark.skipif(not ezdxf_available(), reason="needs the 'cad' extra (ezdxf)")
needs_regulation = pytest.mark.skipif(not regulation.status()["available"], reason="needs the 'regulation' extra")


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


# --------------------------------------------------------------------------- registry


def test_every_contract_schema_is_valid_draft_2020_12_and_packaged():
    assert len(contracts.names()) == 10
    for name in contracts.names():
        schema = contracts.load(name)
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        jsonschema.Draft202012Validator.check_schema(schema)
    with pytest.raises(KeyError):
        contracts.load("nope")


# --------------------------------------------------------------------------- power-cad-mcp <-> Sion API

# What power-cad-mcp sends (dotnet/PowerCad.Server/OntologyRestTools.cs + OntologyContext.cs @ 086ee35; unchanged since f2a8469).
POWER_CAD_GETS = {
    "/v1/catalog": {"project_id"},
    "/v1/elements": {"kind", "project_id", "storey", "text", "drawing_category", "layer", "block_name", "bbox",
                     "include_properties", "limit", "cursor"},
    "/v1/blocks": {"project_id", "name_like", "limit", "cursor"},
    "/v1/drawings": {"project_id", "category", "limit", "cursor"},
    "/v1/elements/{object_id}/context": {"hops"},
}
POWER_CAD_POSTS = {
    "/v1/ask": {"question", "project", "top_k", "generate"},
    "/v1/search": {"query", "top_k", "kind", "storey", "project_id", "model"},
}


def _aec_openapi():
    try:
        from aec_intelligence.operational.api import create_app as create_aec_app
    except ImportError as exc:  # psycopg etc. not installed
        pytest.skip(f"aec operational API not importable: {exc}")
    return create_aec_app().openapi()


def test_aec_operational_api_serves_every_power_cad_request_shape():
    spec = _aec_openapi()
    for path, params in POWER_CAD_GETS.items():
        assert "get" in spec["paths"][path], path
        accepted = {p["name"] for p in spec["paths"][path]["get"].get("parameters", [])}
        assert params <= accepted, (path, params - accepted)
    schemas = spec["components"]["schemas"]
    for path, fields in POWER_CAD_POSTS.items():
        ref = spec["paths"][path]["post"]["requestBody"]["content"]["application/json"]["schema"]["$ref"]
        accepted = set(schemas[ref.rsplit("/", 1)[1]]["properties"])
        assert fields <= accepted, (path, fields - accepted)
    ask = schemas["AskRequest"]["properties"]
    # power-cad clamps top_k to 1..30 and question to 1..2000 characters
    assert (ask["top_k"]["minimum"], ask["top_k"]["maximum"]) == (1, 30)
    assert ask["question"]["maxLength"] == 2000
    search = schemas["SearchRequest"]["properties"]
    assert (search["top_k"]["minimum"], search["top_k"]["maximum"]) == (1, 100)
    # power-cad's embedding-model hint is accepted and validated (422 for a different model)
    assert any(option.get("type") == "string" for option in search["model"]["anyOf"])


class _FakeAec:
    enabled = True

    def __init__(self):
        self.calls = []

    def query_global_memory(self, question, *, top_k=10, project_id=None):
        self.calls.append((question, top_k, project_id))
        return {"answer": None, "citations": [], "question": question}


def test_sion_aec_query_satisfies_power_cad_refusal_rules():
    fake = _FakeAec()
    app = create_app(database_url="sqlite://", auto_create_schema=True, aec_adapter=fake)
    with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000)) as client:
        r = client.get("/api/v1/aec/query", params={"question": "1층 방화문", "top_k": 12, "project_id": "P1"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert contracts.errors("sion-aec-query-response", body) == []
    # power-cad Flag(): JSON booleans only, not strings/numbers
    assert body["canonical"] is False and body["read_only"] is True
    assert fake.calls == [("1층 방화문", 12, "P1")]
    assert contracts.errors("sion-aec-query-response", {**body, "canonical": "false"})
    assert contracts.errors("sion-aec-query-response", {**body, "read_only": 1})
    assert contracts.errors("sion-aec-query-response", {k: v for k, v in body.items() if k != "result"})


# --------------------------------------------------------------------------- power-cad execution receipt


def _receipt(status: str, **overrides):
    """Shape example following ExecutionReceiptContract.Project (power-cad-mcp @ 086ee35; unchanged since f2a8469)."""
    base = {
        "schema": "power-cad-execution-receipt/1",
        "receipt_status": status,
        "plan_state": {"COMMITTED": "Committed", "ROLLED_BACK": "Failed", "REJECTED": "Failed",
                       "INDETERMINATE": "Indeterminate"}[status],
        "plan_terminal": True,
        "executor": "power-cad",
        "plan_id": "plan-synthetic-1",
        "document_id": "doc-synthetic-1",
        "committed": status == "COMMITTED",
        "rollback_verified": status == "ROLLED_BACK",
        "mutation_started": {"REJECTED": False, "ROLLED_BACK": True}.get(status),
        "error_code": None if status == "COMMITTED" else "SYNTHETIC",
        "auto_retry_allowed": False,
        "requires_manual_reconciliation": status == "INDETERMINATE",
        "safe_to_create_replacement_plan": status in {"ROLLED_BACK", "REJECTED"},
        "canonical_mutation": False,
        "evidence_only": True,
        "reasons": ["plan_state_indeterminate"] if status == "INDETERMINATE" else [],
        "receipt_digest": sha(f"receipt:{status}"),  # opaque to Sion (CadJson serialization)
    }
    if status == "COMMITTED":
        base["executor_result_digest"] = sha("result")
    base.update(overrides)
    return base


@pytest.mark.parametrize("status", ["COMMITTED", "ROLLED_BACK", "REJECTED", "INDETERMINATE"])
def test_receipt_statuses_validate(status):
    assert contracts.errors("power-cad-execution-receipt/1", _receipt(status)) == []


def test_receipt_executing_plan_is_indeterminate_and_not_terminal():
    ok = _receipt("INDETERMINATE", plan_state="Executing", plan_terminal=False,
                  reasons=["plan_state_executing_outcome_unknown"])
    assert contracts.errors("power-cad-execution-receipt/1", ok) == []
    assert contracts.errors("power-cad-execution-receipt/1", {**ok, "plan_terminal": True})
    assert contracts.errors("power-cad-execution-receipt/1", {**ok, "receipt_status": "COMMITTED"})


@pytest.mark.parametrize(
    "status,tamper",
    [
        ("COMMITTED", {"auto_retry_allowed": True}),
        ("COMMITTED", {"canonical_mutation": True}),
        ("COMMITTED", {"evidence_only": False}),
        ("COMMITTED", {"reasons": ["committed_result_plan_id_mismatch"]}),  # must have been downgraded
        ("COMMITTED", {"executor": "other"}),
        ("INDETERMINATE", {"safe_to_create_replacement_plan": True}),
        ("INDETERMINATE", {"requires_manual_reconciliation": False}),
        ("REJECTED", {"mutation_started": True}),
        ("REJECTED", {"rollback_verified": True}),  # conflicting evidence is INDETERMINATE
        ("ROLLED_BACK", {"rollback_verified": False}),
        ("COMMITTED", {"receipt_digest": "ABC"}),
    ],
)
def test_receipt_rejects_unsafe_or_inconsistent_payloads(status, tamper):
    assert contracts.errors("power-cad-execution-receipt/1", _receipt(status, **tamper))


def test_receipt_without_executor_result_digest_cannot_be_committed():
    r = _receipt("COMMITTED")
    del r["executor_result_digest"]
    assert contracts.errors("power-cad-execution-receipt/1", r)


# --------------------------------------------------------------------------- hs-steel-cad -> power-cad


def _canonical(node) -> str:
    """Python mirror of DrawPlan.CanonicalJson for ASCII strings and integral numbers."""
    if isinstance(node, dict):
        return "{" + ",".join(f"{json.dumps(k)}:{_canonical(node[k])}" for k in sorted(node)) + "}"
    if isinstance(node, list):
        return "[" + ",".join(_canonical(v) for v in node) + "]"
    return json.dumps(node)


def _draw_plan():
    """The payload of hs-steel-cad PowerCadHandoffTests.Sample() (tests/HsSteel.Tests @ 4958a11; unchanged since 233a4a4)."""
    payload = {
        "schema": "hs-steel-draw-plan/1",
        "producer": "khs0927/hs-steel-cad",
        "title": "A-001",
        "units": "mm",
        "scale": 10,
        "meta": {"kind": "part"},
        "entities": [
            {"spec": {"type": "line", "layer": "STEEL", "start": [0, 0], "end": [1000, 0]},
             "tag": {"mark": "B1", "spec": "H400x200x8x13"}},
        ],
        "execution_authorized": False,
        "may_execute_mutation": False,
        "requires_live_document_binding": True,
        "tags_require_xdata_persistence": True,
    }
    payload["contract_digest"] = sha(_canonical(payload))
    return payload


def test_hs_steel_draw_plan_handoff_validates():
    plan = _draw_plan()
    assert contracts.errors("hs-steel-draw-plan/1", plan) == []
    unsigned = {k: v for k, v in plan.items() if k != "contract_digest"}
    assert sha(_canonical(unsigned)) == plan["contract_digest"]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p.update(execution_authorized=True),
        lambda p: p.update(may_execute_mutation=True),
        lambda p: p.update(units="inch"),
        lambda p: p["entities"][0]["spec"].update(hs={"mark": "B1"}),  # tags must not leak into the strict spec
        lambda p: p["entities"][0].pop("tag"),
        lambda p: p["entities"][0]["spec"].update(type="spline"),
        lambda p: p.update(contract_digest="0" * 63),
    ],
)
def test_hs_steel_draw_plan_rejects_authorizing_or_mixed_payloads(mutate):
    plan = copy.deepcopy(_draw_plan())
    mutate(plan)
    assert contracts.errors("hs-steel-draw-plan/1", plan)


def test_hs_steel_draw_plan_accepts_current_styled_text_and_dimension_specs():
    """Since 4958a11 DrawPlan text/dimension specs carry style=HS-KOR (power-cad cad_create_many creates the style)."""
    plan = _draw_plan()
    del plan["contract_digest"]
    plan["entities"] += [
        {"spec": {"type": "text", "layer": "HS-TEXT", "text": "B1", "position": [0, 100], "height": 3, "justify": "left",
                  "rotation": 0, "style": "HS-KOR"}, "tag": None},
        {"spec": {"type": "dimension", "layer": "HS-DIM", "kind": "rotated", "p1": [0, 0], "p2": [1000, 0],
                  "line_point": [0, -200], "rotation": 0, "style": "HS-KOR"}, "tag": None},
    ]
    plan["contract_digest"] = sha(_canonical(plan))
    assert contracts.errors("hs-steel-draw-plan/1", plan) == []


# --------------------------------------------------------------------------- hs-steel-cad section catalog -> Sion aec


def _section_catalog(**overrides):
    """Shape of SectionCatalogHandoff.Build (src/HsSteel.Assets/SectionCatalogHandoff.cs @ 4958a11); synthetic rows."""
    rows = [
        {"spec": "H100x50x5x7", "shape": "H", "dimensions_mm": [100, 50, 5, 7, 8, 0], "unit_weight_kg_m": 9.3,
         "paint_area_m2_m": 0.4, "aci_color": 1, "family": "H-BEAM"},
        {"spec": "H300x150x6.5x9", "shape": "H", "dimensions_mm": [300, 150, 6.5, 9, 13, 0], "unit_weight_kg_m": 36.7,
         "paint_area_m2_m": 1.16, "aci_color": 1, "family": "H-BEAM"},
    ]
    payload = {
        "schema": "hs-steel-section-catalog/1",
        "producer": "khs0927/hs-steel-cad",
        "family": "H-BEAM",
        "source_file": "H-BEAM.dat",
        "source_sha256": sha("synthetic section table"),
        "encoding": "euc-kr",
        "validation_status": "PASS",
        "capability_scope": "single_family_file",
        "global_legacy_catalog_verified": False,
        "read_rows": 2,
        "accepted_rows": 2,
        "quarantined_rows": 0,
        "query": None,
        "returned_rows": len(rows),
        "rows": rows,
        "execution_authorized": False,
        "may_execute_mutation": False,
    }
    payload.update(overrides)
    payload["contract_digest"] = sha(_canonical(payload))
    return payload


def test_hs_steel_section_catalog_validates_and_feeds_aec_loader(tmp_path):
    payload = _section_catalog()
    assert contracts.errors("hs-steel-section-catalog/1", payload) == []
    unsigned = {k: v for k, v in payload.items() if k != "contract_digest"}
    assert sha(_canonical(unsigned)) == payload["contract_digest"]
    try:
        from aec_intelligence.operational.graphrag.integrations import SECTION_HANDOFF_SCHEMA, load_section_handoffs
    except ImportError as exc:
        pytest.skip(f"aec graphrag integrations not importable: {exc}")
    assert SECTION_HANDOFF_SCHEMA == "hs-steel-section-catalog/1"
    (tmp_path / "h.json").write_text(json.dumps(payload), encoding="utf-8")
    # what the loader drops must also fail the contract
    (tmp_path / "review.json").write_text(json.dumps(_section_catalog(validation_status="REVIEW")), encoding="utf-8")
    (tmp_path / "nohash.json").write_text(json.dumps(_section_catalog(source_sha256="ABC")), encoding="utf-8")
    catalog = load_section_handoffs(tmp_path)
    assert set(catalog) == {"H-100x50x5x7", "H-300x150x6.5x9"}
    entry = catalog["H-100x50x5x7"]
    assert entry["contract"] == "hs-steel-section-catalog/1" and entry["source_sha256"] == payload["source_sha256"]
    assert entry["contract_digest"] == payload["contract_digest"] and entry["dims_mm"] == [100, 50, 5, 7, 8, 0]


@pytest.mark.parametrize(
    "overrides",
    [
        {"validation_status": "REVIEW"},
        {"source_sha256": "ABC"},
        {"global_legacy_catalog_verified": True},
        {"capability_scope": "global"},
        {"quarantined_rows": 1},
        {"execution_authorized": True},
        {"may_execute_mutation": True},
        {"producer": "someone/else"},
        {"rows": [{"spec": "H100x50x5x7", "shape": "H", "family": "H-BEAM", "dimensions_mm": [100, 50, 5, 7],
                   "unit_weight_kg_m": 9.3, "paint_area_m2_m": 0.4, "aci_color": 1}]},  # power-cad requires six dimensions
        {"rows": [{"spec": " ", "shape": "H", "family": "H-BEAM", "dimensions_mm": [1, 1, 1, 1, 1, 1],
                   "unit_weight_kg_m": 1, "paint_area_m2_m": 1, "aci_color": 1}]},
        {"rows": [{"spec": "H1", "shape": "H", "family": "H-BEAM", "dimensions_mm": [1, 1, 1, 1, 1, -1],
                   "unit_weight_kg_m": 1, "paint_area_m2_m": 1, "aci_color": 1}]},
    ],
)
def test_hs_steel_section_catalog_rejects_unverified_or_authorizing_payloads(overrides):
    assert contracts.errors("hs-steel-section-catalog/1", _section_catalog(**overrides))


@pytest.mark.parametrize("field", ["aci_color", "spec", "dimensions_mm", "unit_weight_kg_m", "paint_area_m2_m"])
def test_hs_steel_section_catalog_rejects_rows_missing_a_handoff_field(field):
    # SectionCatalogHandoff.Build always emits these per row (aci_color = row.Color, used by
    # cad_hs_steel_catalog_prepare); a producer that drops or renames one must fail the contract.
    payload = _section_catalog()
    rows = [dict(row) for row in payload["rows"]]
    rows[0].pop(field)
    assert contracts.errors("hs-steel-section-catalog/1", _section_catalog(rows=rows))
    renamed = [dict(row) for row in payload["rows"]]
    if field == "aci_color":
        renamed[0]["color"] = renamed[0].pop("aci_color")
        assert contracts.errors("hs-steel-section-catalog/1", _section_catalog(rows=renamed))


# --------------------------------------------------------------------------- hs-steel-cad asset registry (provenance)

REGISTRY_FIXTURE = FIX / "hs-steel_asset-registry_subset.json"


def test_hs_steel_asset_registry_subset_validates_against_upstream_schema():
    registry = json.loads(REGISTRY_FIXTURE.read_text(encoding="utf-8"))
    assert contracts.errors("hs-steel-asset-registry/1", registry) == []
    assert registry["counts"]["total"] == 819  # upstream header kept; assets[] trimmed (PROVENANCE.md)
    categories = {c["id"] for c in registry["categories"]}
    assert {a["category"] for a in registry["assets"]} == categories  # one row per category at least
    options = {p["name"] for a in registry["assets"] if a["id"] == "standard-option/project-options"
               for p in a["parameters"]}
    assert {"bolt_length_table", "hole_rule", "mark_scheme", "mark_format", "mark_digits"} <= options
    # Sion never treats registry rows as a way to run CAD: loaders are references, not grants
    assert all(not any(k in a for k in ("execution_authorized", "may_execute_mutation")) for a in registry["assets"])


def _registry_asset(registry, category, root):
    return next(a for a in registry["assets"] if a["category"] == category and a["source"]["root"] == root)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda r: r.update(schema="hs-steel-asset-registry/2"),
        lambda r: _registry_asset(r, "block", "legacy").update(disposition="code"),
        lambda r: _registry_asset(r, "layer", "repo").update(disposition="ingest"),
        lambda r: _registry_asset(r, "block", "legacy")["props"].pop("blockCategory"),
        lambda r: _registry_asset(r, "block", "legacy").update(insertion=None),
        lambda r: _registry_asset(r, "block", "legacy")["source"].update(path="HSSTEEL\\block\\x.dwg"),
        lambda r: _registry_asset(r, "block", "legacy")["insertion"].update(units="inch"),
        lambda r: r["roots"]["legacy"].update(env="OTHER"),
        lambda r: r["assets"][0].update(unknown=True),
    ],
)
def test_hs_steel_asset_registry_rejects_drift(mutate):
    registry = json.loads(REGISTRY_FIXTURE.read_text(encoding="utf-8"))
    mutate(registry)
    assert contracts.errors("hs-steel-asset-registry/1", registry)


# --------------------------------------------------------------------------- All-In-Cad / CAD-MCP DXF census


def _all_in_cad_census(path: Path):
    """All-In-Cad inspect_dxf (src/all_in_cad/dxf_evidence.py @ 329f9ad): recover + model-space walk."""
    from ezdxf import recover

    doc, auditor = recover.readfile(str(path))
    return [(str(e.dxf.handle), e.dxftype(), str(getattr(e.dxf, "layer", "0"))) for e in doc.modelspace()], auditor


@needs_ezdxf
@pytest.mark.parametrize("path", DXF_FILES, ids=lambda p: p.name)
def test_sion_census_matches_all_in_cad_lane(path):
    census = dxf_census(path)
    assert contracts.errors("all-in-cad-dxf-evidence", census) == []
    assert census["parser"] == "ezdxf"
    rows, auditor = _all_in_cad_census(path)
    ours = [(e["handle"], e["dxftype"]) for e in census["entities"]]
    assert ours == [(h, t) for h, t, _ in rows]
    assert census["entity_count"] == len(rows)
    assert census["auditor_has_errors"] == bool(auditor.has_errors)
    if not any("re-read as" in w for w in census["warnings"]):  # CP949 re-read may fix layer names
        assert [e["layer"] for e in census["entities"]] == [layer for _, _, layer in rows]
        assert sum(census["layer_counts"].values()) == census["entity_count"]


@pytest.mark.parametrize("path", DXF_FILES, ids=lambda p: p.name)
def test_builtin_census_is_a_superset_in_file_order(path):
    """Without ezdxf: same shape, no audit claim, never fewer entities than the audited lane."""
    census = dxf_census(path, prefer_ezdxf=False)
    assert contracts.errors("all-in-cad-dxf-evidence", census) == []
    assert census["parser"] == "text-fallback" and census["auditor_has_errors"] is None
    if ezdxf_available():
        audited = dxf_census(path)
        handles = [e["handle"] for e in census["entities"]]
        audited_handles = [e["handle"] for e in audited["entities"]]
        it = iter(handles)
        assert all(h in it for h in audited_handles)  # ordered subsequence
        removed = len(handles) - len(audited_handles)
        assert removed == sum(1 for w in audited["warnings"] if w.startswith("audit fix: Removed"))


@needs_ezdxf
def test_cad_mcp_fixture_dimensions_without_geometry_block_are_reported():
    audited = dxf_census(CAD_MCP_DXF)
    raw = dxf_census(CAD_MCP_DXF, prefer_ezdxf=False)
    assert raw["entity_count"] - audited["entity_count"] == 2
    assert raw["layer_counts"].get("DIM") == 2 and "DIM" not in audited["layer_counts"]
    assert sum("DIMENSION" in w and "geometry block" in w for w in audited["warnings"]) == 2


# --------------------------------------------------------------------------- HS-CAD


def test_hs_cad_scan_sample_validates():
    objects = json.loads((FIX / "hs-cad_layer_semantic_sample.json").read_text(encoding="utf-8"))
    assert contracts.errors("hs-cad-scan-objects", objects) == []
    assert contracts.errors("hs-cad-scan-objects", [{"entity_type": "LINE", "layer": "0"}])  # no handle


def test_hs_cad_command_allow_list_matches_upstream_examples():
    accepted = {}
    for path in sorted((FIX / "hs-cad_commands").glob("*.json")):
        accepted[path.stem] = not contracts.errors("hs-cad-command", json.loads(path.read_text(encoding="utf-8")))
    assert accepted == {
        "capture_screen": False,  # upstream example outside ALLOWED_COMMANDS
        "delete_layer_objects_safe": True,
        "move_layer": True,
        "replace_block_door": True,
        "xicad_safe_wall_plan": True,
    }
    assert contracts.errors("hs-cad-command", {"command": "move_layer", "params": {"layer": "  "}})
    assert contracts.errors("hs-cad-command", {"command": "xicad_safe_execute"})  # alias required


def test_sion_api_exposes_no_cad_mutation_route():
    """Sion stays read-only towards CAD hosts: no route executes HS-CAD/power-cad/All-In-Cad plans."""
    app = create_app(database_url="sqlite://", auto_create_schema=True)
    paths = {route.path for route in app.routes}
    assert not [p for p in paths if any(word in p for word in ("execute", "run-command", "plan.execute", "cad_create"))]


# --------------------------------------------------------------------------- korean-land-mcp -> regulation


def _parcel(**overrides):
    """Synthetic analyze_parcel record (shape of korean-land-mcp src/tools/analyze_parcel.ts @ ec25b13)."""
    record = {
        "query": "synthetic test parcel",
        "parcel": {
            "pnu": None,
            "jibun": None,
            "jimok": "대",
            "is_mountain_register": False,
            "address": None,
            "point_wgs84": {"x": 127.0, "y": 37.5},
            "land_price_won_per_m2": None,
            "land_price_gosi_date": None,
            "administrative": {},
        },
        "zoning": {
            "use_zone": [{"layer": "LT_C_UQ111", "name": "제2종일반주거지역"}],
            "use_district": [],
            "use_area": [],
            "land_transaction_permit": [],
        },
        "district_plan": [{"layer": "LT_C_UPISUQ161", "layer_label": "지구단위계획구역", "name": "synthetic 지구단위계획구역"}],
        "urban_facility": [],
        "other_law_designations": [],
        "priority_delegation_hint": {"applies": False},
        "buildings": {"present": True, "count": 1},
        "next_steps": [],
        "layer_errors": [],
        "source": {"precision": "polygon", "total_layers_queried": 0},
    }
    for key, value in overrides.items():
        record[key] = value
    return record


def test_land_record_validates_and_maps_to_facts():
    record = _parcel()
    assert contracts.errors("korean-land-parcel-analysis/2", record) == []
    land = regulation.facts_from_land_parcel(record)["land"]
    assert land["use_zone"] == "제2종일반주거지역"
    assert land["in_district_plan"] is True
    assert land["has_use_district"] is False and land["urban_facility_overlap"] is False
    assert land["in_development_restriction_zone"] is False and land["priority_delegation"] is False
    assert land["buildings_present"] is True and land["unverified"] == []
    assert "pnu" not in land  # null values are not turned into facts


def test_land_negatives_are_withheld_when_not_verifiable():
    point = regulation.facts_from_land_parcel(_parcel(source={"precision": "point"}))["land"]
    assert point["in_district_plan"] is True  # a hit stays a hit
    for name in ("has_use_district", "urban_facility_overlap", "priority_delegation", "in_development_restriction_zone"):
        assert name not in point and name in point["unverified"]

    errored = _parcel(layer_errors=[{"layer": "LT_C_UPISUQ153", "layer_label": "공간시설", "error_code": "TIMEOUT",
                                     "error_message": "synthetic"}])
    land = regulation.facts_from_land_parcel(errored)["land"]
    assert "urban_facility_overlap" not in land and land["has_use_district"] is False

    unknown = _parcel(layer_errors=[{"layer": "?", "error_code": "X"}])
    assert "has_use_district" not in regulation.facts_from_land_parcel(unknown)["land"]

    unnamed = _parcel(zoning={**_parcel()["zoning"], "use_zone": [{"layer": "LT_C_UQ111", "name": "(unnamed)"}]})
    assert "use_zone" not in regulation.facts_from_land_parcel(unnamed)["land"]


def test_land_record_rejects_malformed_input():
    with pytest.raises(ValueError):
        regulation.facts_from_land_parcel({"parcel": {}})
    with pytest.raises(ValueError):
        regulation.land_facts_checked(_parcel(source={"precision": "exact"}))


GREENBELT_RULE = {
    "rule": {
        "if": {"==": [{"var": "land.in_development_restriction_zone"}, False]},
        "then": {"PASS": {"reason": "not in 개발제한구역"}},
        "else": {"FAIL": {"reason": "개발제한구역"}},
    }
}


@needs_regulation
def test_regulation_endpoint_uses_land_facts_fail_closed():
    with TestClient(create_app(database_url="sqlite://", auto_create_schema=True), base_url="http://localhost", client=("127.0.0.1", 50000)) as client:
        def run(record, facts=None):
            r = client.post("/api/v1/regulation/evaluate", json={"rule": GREENBELT_RULE, "land_parcel": record, "facts": facts or {}})
            assert r.status_code == 200, r.text
            return r.json()

        assert run(_parcel())["result"]["outcome"] == "PASS"
        greenbelt = _parcel(zoning={**_parcel()["zoning"], "use_area": [{"layer": "LT_C_UD801", "name": "개발제한구역"}]})
        assert run(greenbelt)["result"]["outcome"] == "FAIL"
        body = run(_parcel(source={"precision": "point"}))
        assert body["result"]["outcome"] == "REVIEW"  # absence not provable by point lookup
        assert "in_development_restriction_zone" in body["land"]["unverified"]
        # explicit facts still win
        override = run(_parcel(source={"precision": "point"}), {"land": {"in_development_restriction_zone": False}})
        assert override["result"]["outcome"] == "PASS"
        bad = client.post("/api/v1/regulation/evaluate", json={"rule": GREENBELT_RULE, "land_parcel": {"query": "x"}})
        assert bad.status_code == 422


# --------------------------------------------------------------------------- building-regulation-gateway -> Sion evidence


def test_building_regulation_report_contract():
    """Shape follows building-regulation-gateway gateway/engine.py @ d2cc08a (evidence-only v0.1)."""
    report = {
        "request_id": "r1", "input_hash": "sha256:" + "0" * 64, "retrieved_at": "2026-10-09T00:00:00+00:00",
        "as_of": "2026-10-09", "required_branches": ["site"],
        "results": {"site": {"status": "missing", "data": {}, "evidence": [], "reason": "PROVIDER_NOT_CONFIGURED"}},
        "verification": {"verified": False, "missing": ["site"], "conflicts": []},
        "decision": {"status": "insufficient_evidence", "reason_codes": ["MISSING_REQUIRED_EVIDENCE"]},
    }
    assert contracts.errors("building-regulation-report/1", report) == []
    report["decision"]["status"] = "unsupported_verdict"  # unknown statuses are rejected
    assert contracts.errors("building-regulation-report/1", report)
