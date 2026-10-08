from datetime import datetime, timezone
import hashlib
import json
from copy import deepcopy

import pytest

from capability_registry.history import EvidenceHistory
from readonly_bridges import ingest_readonly_probe, ingest_section_catalog
from readonly_bridges.evidence import (
    CONTRACT_CAPABILITY_ID,
    CONTRACT_HOST,
    CONTRACT_HOST_VERSION,
    record_readonly_probe_evidence,
)


NOW = datetime(2026, 10, 5, 9, 0, tzinfo=timezone.utc)


IDENTITY = {
    "provider_id": "rhino",
    "upstream_repo": "https://example.test/rhino-bridge",
    "upstream_commit": "a" * 40,
    "source_path": "bridge/probe.json",
    "adapter_version": "1",
}


def probe_response(**changes):
    data = dict(schema_version=1, identity=dict(IDENTITY), read_only=True, mutation_count=0,
                capabilities=["read_context", "health"], authenticated=False, complete=True,
                host="Rhino", host_version="8")
    data.update(changes)
    return json.dumps(data).encode()


def real_probe(**changes):
    """A projection produced by ingest_readonly_probe itself (the only accepted source)."""
    return ingest_readonly_probe(probe_response(**changes), expected_identity=dict(IDENTITY),
                                 expected_capabilities=["read_context", "health"])


def projection(status="DECLARED", **changes):
    if status == "NOT_RUN" and changes.get("transport_state") in {"timeout", "empty"}:
        row = ingest_readonly_probe(None, expected_identity=dict(IDENTITY), expected_capabilities=["health"],
                                    transport_state=changes["transport_state"])
    else:
        row = real_probe()
        row["status"] = status
    row.update(changes)
    return row


def test_declared_contract_is_recorded_as_headless_only(tmp_path):
    history = EvidenceHistory(tmp_path / "evidence.db")
    record = record_readonly_probe_evidence(
        history, "probe-1", projection(),
        run_url="https://example.test/run/1",
        run_timestamp="2026-10-05T08:00:00Z",
        valid_until="2026-10-06T08:00:00Z",
    )
    assert record["capability_id"] == CONTRACT_CAPABILITY_ID
    assert record["host"] == CONTRACT_HOST
    assert record["host_version"] == CONTRACT_HOST_VERSION
    assert record["verification_kind"] == "headless"
    assert record["outcome"] == "PASS"
    result = history.project(scope=record, now=NOW)
    assert result["status"] == "TESTED"
    assert result["execution_allowed"] is False
    assert result["canonical_allowed"] is False
    history.close()


def test_not_run_stays_not_run_and_never_becomes_tested(tmp_path):
    history = EvidenceHistory(tmp_path / "evidence.db")
    row = projection("NOT_RUN", payload_sha256=None, transport_state="timeout")
    record = record_readonly_probe_evidence(
        history, "probe-timeout", row,
        run_url="https://example.test/run/2",
        run_timestamp="2026-10-05T08:00:00Z",
        valid_until="2026-10-06T08:00:00Z",
    )
    assert record["outcome"] == "NOT_RUN"
    result = history.project(scope=record, now=NOW)
    assert result["status"] == "UNKNOWN"
    assert result["observations"][0]["outcome"] == "NOT_RUN"
    assert result["execution_allowed"] is False
    history.close()


@pytest.mark.parametrize("status", ["VERIFIED", "ERROR", "PASS", None])
def test_unsupported_projection_status_cannot_enter_ledger(tmp_path, status):
    history = EvidenceHistory(tmp_path / "evidence.db")
    with pytest.raises(ValueError):
        record_readonly_probe_evidence(
            history, "probe-1", projection(status),
            run_url="https://example.test/run/3",
            run_timestamp="2026-10-05T08:00:00Z",
            valid_until="2026-10-06T08:00:00Z",
        )
    history.close()


def test_contract_pass_cannot_claim_native_host_scope(tmp_path):
    history = EvidenceHistory(tmp_path / "evidence.db")
    record = record_readonly_probe_evidence(
        history, "probe-1", projection(),
        run_url="https://example.test/run/4",
        run_timestamp="2026-10-05T08:00:00Z",
        valid_until="2026-10-06T08:00:00Z",
    )
    assert record["host"] == "headless-contract"
    assert record["host_version"] == "1"
    result = history.project(scope=record, now=NOW)
    assert result["status"] == "TESTED"
    assert result["execution_allowed"] is False
    assert result["canonical_allowed"] is False
    history.close()


RUN = dict(run_url="https://example.test/run/5", run_timestamp="2026-10-05T08:00:00Z",
           valid_until="2026-10-06T08:00:00Z")


@pytest.mark.parametrize("claims", [
    {"native_mapping_verified": True}, {"execution_allowed": True}, {"canonical_allowed": True},
    {"probe_authenticated": True}, {"host_identity_verified": True},
])
def test_authority_claims_are_refused_not_recorded(tmp_path, claims):
    history = EvidenceHistory(tmp_path / "evidence.db")
    with pytest.raises(ValueError):
        record_readonly_probe_evidence(history, "probe-1", projection(**claims), **RUN)
    assert history._read()[0] == []
    history.close()


def test_section_catalog_projection_is_not_recorded_as_probe_pass(tmp_path):
    # PR #37 review: a DECLARED ingest_section_catalog result for hs-steel-cad satisfied the old checks.
    asset = b"header\nH100 original row\n"
    identity = dict(IDENTITY, provider_id="hs-steel-cad", source_path="export/catalog.json")
    catalog = dict(schema_version=1, identity=deepcopy(identity),
                   units=dict(dimensions="mm", unit_weight="kg/m", paint_area="m2/m"), errors=[],
                   rows=[dict(source_path="attributes/H.txt", line_number=2,
                              source_file_sha256=hashlib.sha256(asset).hexdigest(), parse_success=True,
                              designation="H100", family="H", raw_value="H100 original row",
                              dimensions=[100, 100, 6, 8, 0, 0], unit_weight=17.2, paint_area=0.6, aci_color=7)])
    result = ingest_section_catalog(json.dumps(catalog).encode(), expected_identity=identity,
                                    source_files={"attributes/H.txt": asset})
    assert result["status"] == "DECLARED"
    history = EvidenceHistory(tmp_path / "evidence.db")
    with pytest.raises(ValueError):
        record_readonly_probe_evidence(history, "catalog-as-probe", result, **RUN)
    # even with the catalog-only fields stripped, the unsupported provider / missing probe fields fail
    stripped = {k: v for k, v in result.items() if k not in {"rows", "units"}}
    with pytest.raises(ValueError):
        record_readonly_probe_evidence(history, "catalog-as-probe", stripped, **RUN)
    assert history._read()[0] == []
    history.close()


@pytest.mark.parametrize("change", [
    lambda p: p.pop("contract_scope"),
    lambda p: p.update(contract_scope="native/1"),
    lambda p: p.update(verification_kind="native"),
    lambda p: p.update(capabilities=[]),
    lambda p: p.update(capabilities=["read_context", "health"]),  # not the sorted contract list
    lambda p: p.update(capabilities=["execute"]),
    lambda p: p.pop("host"),
    lambda p: p.update(host="freecad"),
    lambda p: p.update(transport_state="timeout"),
    lambda p: p.update(payload_sha256="B" * 64),
    lambda p: p["identity"].update(provider_id="hs-steel-cad"),
    lambda p: p["identity"].pop("upstream_repo"),
])
def test_hand_written_or_tampered_probe_projection_is_refused(tmp_path, change):
    row = projection()
    change(row)
    history = EvidenceHistory(tmp_path / "evidence.db")
    with pytest.raises(ValueError):
        record_readonly_probe_evidence(history, "probe-x", row, **RUN)
    history.close()


def test_ok_transport_without_host_is_recorded_as_not_run(tmp_path):
    row = ingest_readonly_probe(probe_response(host=None), expected_identity=dict(IDENTITY),
                                expected_capabilities=["read_context", "health"])
    assert row["status"] == "NOT_RUN"
    history = EvidenceHistory(tmp_path / "evidence.db")
    record = record_readonly_probe_evidence(history, "probe-nohost", row, **RUN)
    assert record["outcome"] == "NOT_RUN"
    history.close()
