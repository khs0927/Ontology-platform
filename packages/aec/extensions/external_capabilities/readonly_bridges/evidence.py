"""Bridge contract outcomes into the append-only evidence lifecycle.

This records only headless contract verification. It never upgrades a provider to
native verification, authenticated acquisition, canonical authority or execution.
"""
from datetime import datetime

from capability_registry import _hash, evidence_record
from capability_registry.history import EvidenceHistory

from . import IDENTITY_FIELDS, PROVIDERS, _expected_capabilities


CONTRACT_CAPABILITY_ID = "readonly-bridge-contract"
CONTRACT_SCOPE = "headless-contract/1"
CONTRACT_HOST = "headless-contract"
CONTRACT_HOST_VERSION = "1"


def _time(value):
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("Evidence timestamps require timezone")
    return stamp


_NON_AUTHORIZING = ("execution_allowed", "canonical_allowed", "native_mapping_verified",
                    "probe_authenticated", "host_identity_verified")
_CATALOG_ONLY_FIELDS = ("rows", "units")


def _validate_probe_projection(projection):
    """Require the exact shape ``ingest_readonly_probe`` produces before anything is recorded.

    Any other projection (e.g. an ``ingest_section_catalog`` result, a hand-written JSON object, or a
    probe that claims authority) is refused, so the ledger can only report TESTED for a contract that
    was actually evaluated by the read-only probe ingestion.
    """
    identity = projection.get("identity")
    if not isinstance(identity, dict) or set(identity) != set(IDENTITY_FIELDS):
        raise ValueError("Require exact readonly probe identity")
    for key in IDENTITY_FIELDS:
        if not isinstance(identity[key], str) or not identity[key].strip():
            raise ValueError("Incomplete probe identity")
    if identity["provider_id"] not in PROVIDERS:
        raise ValueError("Unsupported readonly provider for probe evidence")
    _hash(identity["upstream_commit"], 40)
    if projection.get("verification_kind") != "contract_only" or projection.get("contract_scope") != CONTRACT_SCOPE:
        raise ValueError("Projection is not a headless readonly probe contract result")
    if any(field in projection for field in _CATALOG_ONLY_FIELDS):
        raise ValueError("Catalog projections are not readonly probe evidence")
    for field in _NON_AUTHORIZING:
        if projection.get(field) is not False:
            raise ValueError(f"Probe projection must carry {field}=false")

    status = projection.get("status")
    transport = projection.get("transport_state")
    capabilities = projection.get("capabilities")
    if transport not in {"ok", "timeout", "empty"}:
        raise ValueError("Unsupported probe transport state")
    if transport in {"timeout", "empty"}:
        if status != "NOT_RUN" or projection.get("payload_sha256") is not None or capabilities != []:
            raise ValueError("Transport failure projection must be NOT_RUN without payload or capabilities")
        return
    if not isinstance(capabilities, list) or _expected_capabilities(capabilities) != capabilities:
        raise ValueError("Probe projection requires its sorted, declared capability contract")
    _hash(projection.get("payload_sha256"), 64)
    if status == "DECLARED":
        host, version = projection.get("host"), projection.get("host_version")
        if not isinstance(host, str) or not host.strip() or not isinstance(version, str) or not version.strip():
            raise ValueError("Accepted probe evidence requires the declared host identity")
        if host.strip().lower() != identity["provider_id"].lower():
            raise ValueError("Host/provider declaration mismatch")
    elif status == "NOT_RUN":
        if not isinstance(projection.get("reason"), str) or not projection["reason"].strip():
            raise ValueError("NOT_RUN probe projection requires its reason")


def record_readonly_probe_evidence(history: EvidenceHistory, identifier: str, projection: dict, *,
                                   run_url: str, run_timestamp: str, valid_until: str):
    """Append one readonly-bridge contract outcome to EvidenceHistory.

    DECLARED means only that the headless contract accepted the projection.
    NOT_RUN stays NOT_RUN. No other status is promoted. The projection must be an
    ``ingest_readonly_probe`` result (provider, scope/kind, capabilities and the
    non-authorizing fields are re-checked); anything else is refused, never recorded.
    """
    if not isinstance(history, EvidenceHistory):
        raise ValueError("Require EvidenceHistory")
    if not isinstance(identifier, str) or not identifier.strip():
        raise ValueError("Require evidence identifier")
    if not isinstance(projection, dict):
        raise ValueError("Require readonly probe projection")
    if projection.get("status") not in {"DECLARED", "NOT_RUN"}:
        raise ValueError("Unsupported probe status for evidence lifecycle")
    _validate_probe_projection(projection)

    identity = projection.get("identity")
    if not isinstance(identity, dict):
        raise ValueError("Missing probe identity")
    for key in ("provider_id", "upstream_commit", "adapter_version"):
        if not isinstance(identity.get(key), str) or not identity[key].strip():
            raise ValueError("Incomplete probe identity")

    status = projection.get("status")
    if status == "DECLARED":
        outcome = "PASS"
    elif status == "NOT_RUN":
        outcome = "NOT_RUN"
    else:
        raise ValueError("Unsupported probe status for evidence lifecycle")

    fixture_sha256 = projection.get("payload_sha256")
    if outcome == "PASS" and (not isinstance(fixture_sha256, str) or len(fixture_sha256) != 64):
        raise ValueError("Accepted contract evidence requires payload hash")
    if outcome == "NOT_RUN" and fixture_sha256 is None:
        # Use an explicit synthetic fixture identity for transport-only NOT_RUN evidence.
        import hashlib
        fixture_sha256 = hashlib.sha256(
            f"readonly-bridge:{identity['provider_id']}:{projection.get('transport_state','not-run')}".encode()
        ).hexdigest()

    _time(run_timestamp)
    _time(valid_until)
    record = evidence_record(
        capability_id=CONTRACT_CAPABILITY_ID,
        provider_id=identity["provider_id"],
        upstream_commit=identity["upstream_commit"],
        host=CONTRACT_HOST,
        host_version=CONTRACT_HOST_VERSION,
        adapter_version=identity["adapter_version"],
        fixture_sha256=fixture_sha256,
        verification_kind="headless",
        outcome=outcome,
        run_url=run_url,
        run_timestamp=run_timestamp,
        valid_until=valid_until,
    )
    history.add(identifier, record)
    return record
