from __future__ import annotations

import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
import uuid

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from . import models, repository, schemas, vector_repository
from .config import Settings, load_settings
from .db import Base, build_engine, build_session_factory, session_dependency
from .health import check_readiness
from .security import is_loopback_host, require_local_bearer, validate_startup_settings

try:  # pragma: no cover - exercised through the API tests
    from sion_ingestion.dlp import DLPDecision, scan_payload as _dlp_scan_payload
except Exception:  # the API must stay importable without the ingestion package
    DLPDecision = None  # type: ignore[assignment]
    _dlp_scan_payload = None  # type: ignore[assignment]


DLP_HMAC_KEY_ENV = "SION_DLP_HMAC_KEY"
DLP_GATE_STATUS_CODE = 422
DLP_SANITIZED_UNDECIDED = {
    "allowed": False,
    "action": "quarantine",
    "findings": [],
    "metadata": {"reason": "dlp_scanner_unavailable", "fail_closed": True},
}
# The evidence contract stores an opaque provenance reference in the top level
# ``source_uri`` field. The scanner classifies that key as INTERNAL, so the
# field is exempted by exact path. The value itself is still scanned for
# secrets, PII and local paths, and a nested ``properties.source_uri`` is not
# exempt, which keeps the key from being used as a smuggling channel.
_DLP_EXEMPT_FINDINGS = {("source_uri", "$.source_uri")}

_dlp_logger = logging.getLogger("sion_api.dlp")


def _dlp_hmac_key() -> bytes | None:
    raw = os.getenv(DLP_HMAC_KEY_ENV)
    if not raw:
        return None
    return raw.encode("utf-8")


def _blocking_findings(decision: Any) -> list[Any]:
    return [
        finding
        for finding in decision.findings
        if (finding.kind, finding.path) not in _DLP_EXEMPT_FINDINGS
    ]


def _reject_dlp_payload(
    sink: str,
    decision: Any,
    session: Session | None,
    reason: str,
) -> None:
    if session is not None:
        session.rollback()
    if decision is not None:
        _dlp_logger.warning(
            "api dlp gate rejected sink=%s action=%s metadata=%s",
            sink,
            decision.action,
            decision.metadata,
        )
    else:
        _dlp_logger.warning("api dlp gate rejected sink=%s reason=%s", sink, reason)
    raise HTTPException(
        status_code=DLP_GATE_STATUS_CODE,
        detail={
            "detail": "payload rejected by DLP gate",
            "sink": sink,
            "reason": reason,
            "dlp": decision.to_dict() if decision is not None else dict(DLP_SANITIZED_UNDECIDED),
        },
    )


def enforce_dlp_gate(payload: Any, *, sink: str, session: Session | None = None) -> Any:
    """Fail-closed pre-write DLP gate for an authenticated API write sink.

    The payload is scanned before any repository call, so a rejected write
    never reaches a commit. A blocked payload is refused with sanitized
    decision metadata only; raw values are never logged or echoed. PII-only
    payloads admitted as ``tokenized`` are persisted in their sanitized form
    instead of being written raw.
    """

    try:
        raw_payload = payload.model_dump(mode="json")
    except Exception:
        _reject_dlp_payload(sink, None, session, "payload_not_serializable")

    exempt_source_uri = raw_payload.get("source_uri")

    if _dlp_scan_payload is None:
        _reject_dlp_payload(sink, None, session, "dlp_scanner_unavailable")

    try:
        decision = _dlp_scan_payload(raw_payload, hmac_key=_dlp_hmac_key())
    except Exception:
        _reject_dlp_payload(sink, None, session, "scanner_error")

    if decision.metadata.get("fail_closed"):
        _reject_dlp_payload(
            sink, decision, session, decision.metadata.get("reason", "scanner_fail_closed")
        )

    blocking = _blocking_findings(decision)

    if not blocking and isinstance(decision.sanitized_payload, dict):
        sanitized = dict(decision.sanitized_payload)
        if exempt_source_uri is not None and "source_uri" in sanitized:
            sanitized["source_uri"] = exempt_source_uri
        try:
            return type(payload).model_validate(sanitized)
        except Exception:
            _reject_dlp_payload(sink, decision, session, "sanitized_payload_invalid")

    if decision.action == "tokenized" and isinstance(decision.sanitized_payload, dict):
        try:
            return type(payload).model_validate(dict(decision.sanitized_payload))
        except Exception:
            _reject_dlp_payload(sink, decision, session, "sanitized_payload_invalid")

    _reject_dlp_payload(
        sink, decision, session, decision.metadata.get("reason", "payload_not_allowed")
    )
    raise AssertionError("unreachable")  # pragma: no cover


def create_app(
    *,
    database_url: str | None = None,
    auto_create_schema: bool | None = None,
) -> FastAPI:
    settings: Settings = load_settings()
    if database_url is not None:
        settings = Settings(
            database_url=database_url,
            auto_create_schema=(
                auto_create_schema
                if auto_create_schema is not None
                else database_url.startswith("sqlite")
            ),
            ontology_path=settings.ontology_path,
            map_inventory_path=settings.map_inventory_path,
            cors_origins=settings.cors_origins,
            api_host=settings.api_host,
            local_api_token=settings.local_api_token,
            environment=settings.environment,
        )
    elif auto_create_schema is not None:
        settings = Settings(
            database_url=settings.database_url,
            auto_create_schema=auto_create_schema,
            ontology_path=settings.ontology_path,
            map_inventory_path=settings.map_inventory_path,
            cors_origins=settings.cors_origins,
            api_host=settings.api_host,
            local_api_token=settings.local_api_token,
            environment=settings.environment,
        )
    validate_startup_settings(settings)

    engine = build_engine(settings.database_url)
    factory = build_session_factory(engine)
    get_session = session_dependency(factory)

    if settings.auto_create_schema:
        Base.metadata.create_all(engine)
        with factory() as session:
            repository.seed_core_types(session)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if settings.environment == "production":
            result = check_readiness(engine)
            if result["status"] != "ready":
                raise RuntimeError(f"production readiness failed: {result}")
        yield

    app = FastAPI(
        title="Sion Ontology API",
        version="0.1.0",
        description="Canonical API for Sion ontology, knowledge graph and evidence.",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = factory

    @app.middleware("http")
    async def authenticate_local_api(request, call_next):
        protected_docs = request.url.path in {"/docs", "/redoc", "/openapi.json"}
        if (
            request.url.path.startswith("/api/")
            or request.url.path == "/health/ready"
            or (request.app.state.settings.local_api_token is not None and protected_docs)
        ):
            try:
                authorization = request.headers.get("authorization", "")
                scheme, _, token = authorization.partition(" ")
                credentials = (
                    HTTPAuthorizationCredentials(scheme=scheme, credentials=token)
                    if scheme and token
                    else None
                )
                require_local_bearer(request, credentials)
            except HTTPException as exc:
                from fastapi.responses import JSONResponse
                return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail}, headers=exc.headers)
        return await call_next(request)

    original_openapi = app.openapi

    def secured_openapi():
        schema = original_openapi()
        schema.setdefault("components", {}).setdefault("securitySchemes", {})["BearerAuth"] = {
            "type": "http", "scheme": "bearer", "bearerFormat": "opaque"
        }
        for path, item in schema.get("paths", {}).items():
            if path.startswith("/api/") or path == "/health/ready" or path in {"/docs", "/redoc", "/openapi.json"}:
                for operation in item.values():
                    if isinstance(operation, dict):
                        operation.setdefault("security", [{"BearerAuth": []}])
        return schema

    app.openapi = secured_openapi

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    @app.get("/health/live")
    def health_live():
        return {
            "status": "ok",
            "service": "sion-ontology-api",
            "version": "0.1.0",
        }

    @app.get("/health")
    def health():
        body = health_live()
        body["database"] = engine.dialect.name
        return body

    @app.get("/health/ready")
    def health_ready():
        result = check_readiness(engine)
        if result["status"] != "ready":
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=503, content=result)
        return result

    @app.get("/api/v1/schema/ontology", response_class=PlainTextResponse)
    def ontology_schema():
        path: Path = settings.ontology_path
        if not path.exists():
            raise HTTPException(status_code=503, detail="ontology schema unavailable")
        return path.read_text(encoding="utf-8")

    @app.get("/api/v1/bootstrap/map-inventory")
    def map_inventory():
        path: Path = settings.map_inventory_path
        if not path.exists():
            raise HTTPException(status_code=503, detail="map inventory unavailable")
        return json.loads(path.read_text(encoding="utf-8"))

    @app.post(
        "/api/v1/entities",
        response_model=schemas.EntityRead,
        status_code=201,
    )
    def create_entity(
        payload: schemas.EntityCreate,
        session: Session = Depends(get_session),
    ):
        payload = enforce_dlp_gate(payload, sink="entity", session=session)
        try:
            return repository.create_entity(session, payload)
        except repository.MissingReferenceError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except repository.ConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/v1/entities", response_model=list[schemas.EntityRead])
    def list_entities(
        limit: int = Query(default=100, ge=1, le=1000),
        offset: int = Query(default=0, ge=0),
        session: Session = Depends(get_session),
    ):
        return repository.list_entities(session, limit=limit, offset=offset)

    @app.get("/api/v1/entities/{entity_id}", response_model=schemas.EntityRead)
    def get_entity(
        entity_id: uuid.UUID,
        session: Session = Depends(get_session),
    ):
        row = session.get(models.Entity, entity_id)
        if row is None:
            raise HTTPException(status_code=404, detail="entity not found")
        return row

    @app.post(
        "/api/v1/relations",
        response_model=schemas.RelationRead,
        status_code=201,
    )
    def create_relation(
        payload: schemas.RelationCreate,
        session: Session = Depends(get_session),
    ):
        payload = enforce_dlp_gate(payload, sink="relation", session=session)
        try:
            return repository.create_relation(session, payload)
        except repository.MissingReferenceError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except repository.ConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/v1/relations", response_model=list[schemas.RelationRead])
    def list_relations(
        limit: int = Query(default=100, ge=1, le=1000),
        offset: int = Query(default=0, ge=0),
        session: Session = Depends(get_session),
    ):
        return repository.list_relations(session, limit=limit, offset=offset)

    @app.post(
        "/api/v1/evidence",
        response_model=schemas.EvidenceRead,
        status_code=201,
    )
    def create_evidence(
        payload: schemas.EvidenceCreate,
        session: Session = Depends(get_session),
    ):
        payload = enforce_dlp_gate(payload, sink="evidence", session=session)
        try:
            return repository.create_evidence(session, payload)
        except repository.MissingReferenceError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/v1/evidence", response_model=list[schemas.EvidenceRead])
    def list_evidence(
        limit: int = Query(default=100, ge=1, le=1000),
        offset: int = Query(default=0, ge=0),
        session: Session = Depends(get_session),
    ):
        return repository.list_evidence(session, limit=limit, offset=offset)

    @app.get("/api/v1/graph", response_model=schemas.GraphResponse)
    def graph(
        limit: int = Query(default=500, ge=1, le=5000),
        session: Session = Depends(get_session),
    ):
        nodes, edges = repository.get_graph(session, limit=limit)
        return schemas.GraphResponse(
            nodes=[schemas.EntityRead.model_validate(node) for node in nodes],
            edges=[
                schemas.GraphEdge(
                    id=edge.id,
                    source=edge.source_entity_id,
                    target=edge.target_entity_id,
                    type=edge.relation_type_id,
                    confidence=edge.confidence,
                    verification_state=edge.verification_state,
                )
                for edge in edges
            ],
            node_count=len(nodes),
            edge_count=len(edges),
        )

    @app.post(
        "/api/v1/artifacts",
        response_model=schemas.ArtifactRead,
        status_code=201,
    )
    def create_artifact(
        payload: schemas.ArtifactCreate,
        session: Session = Depends(get_session),
    ):
        payload = enforce_dlp_gate(payload, sink="artifact", session=session)
        try:
            return repository.create_artifact(session, payload)
        except repository.ConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/v1/artifacts", response_model=list[schemas.ArtifactRead])
    def list_artifacts(
        limit: int = Query(default=100, ge=1, le=1000),
        offset: int = Query(default=0, ge=0),
        session: Session = Depends(get_session),
    ):
        return repository.list_artifacts(session, limit=limit, offset=offset)

    @app.get("/api/v1/artifacts/{artifact_id}", response_model=schemas.ArtifactRead)
    def get_artifact(
        artifact_id: uuid.UUID,
        session: Session = Depends(get_session),
    ):
        row = session.get(models.Artifact, artifact_id)
        if row is None:
            raise HTTPException(status_code=404, detail="artifact not found")
        return row

    @app.post(
        "/api/v1/embeddings",
        response_model=schemas.EmbeddingRead,
        status_code=201,
    )
    def create_embedding(
        payload: schemas.EmbeddingCreate,
        session: Session = Depends(get_session),
    ):
        payload = enforce_dlp_gate(payload, sink="embedding", session=session)
        try:
            return vector_repository.create_embedding(session, payload)
        except vector_repository.VectorBackendUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except vector_repository.VectorReferenceError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except vector_repository.VectorConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post(
        "/api/v1/vector/search",
        response_model=schemas.VectorSearchResponse,
    )
    def vector_search(
        payload: schemas.VectorSearchRequest,
        session: Session = Depends(get_session),
    ):
        payload = enforce_dlp_gate(payload, sink="vector_search", session=session)
        try:
            hits = vector_repository.search_vectors(session, payload)
        except vector_repository.VectorBackendUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return schemas.VectorSearchResponse(
            hits=[schemas.VectorHit.model_validate(hit) for hit in hits],
            count=len(hits),
        )

    return app


app = create_app()
