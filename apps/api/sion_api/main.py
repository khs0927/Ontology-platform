from __future__ import annotations

import json
from pathlib import Path
import uuid

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from sion_ingestion.aec_cair import AecCairAdapter, AecCairConfig, AecCairError

from . import models, repository, schemas, vector_repository
from .auth import AuthPolicy, require_scope
from .config import Settings, load_settings
from .db import Base, build_engine, build_session_factory, session_dependency


def create_app(
    *,
    database_url: str | None = None,
    auto_create_schema: bool | None = None,
    aec_adapter: AecCairAdapter | None = None,
    auth_policy: AuthPolicy | None = None,
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
        )
    elif auto_create_schema is not None:
        settings = Settings(
            database_url=settings.database_url,
            auto_create_schema=auto_create_schema,
            ontology_path=settings.ontology_path,
            map_inventory_path=settings.map_inventory_path,
            cors_origins=settings.cors_origins,
        )

    engine = build_engine(settings.database_url)
    factory = build_session_factory(engine)
    get_session = session_dependency(factory)

    if settings.auto_create_schema:
        Base.metadata.create_all(engine)
        with factory() as session:
            repository.seed_core_types(session)

    app = FastAPI(
        title="Sion Ontology API",
        version="0.1.0",
        description="Canonical API for Sion ontology, knowledge graph and evidence.",
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = factory

    auth_policy = auth_policy or AuthPolicy.from_env()
    app.state.auth_policy = auth_policy
    read_knowledge = require_scope(auth_policy, "read:knowledge")
    write_knowledge = require_scope(auth_policy, "write:knowledge")
    read_aec = require_scope(auth_policy, "read:aec")

    if aec_adapter is None:
        aec_config = AecCairConfig.from_env()
        aec_adapter = AecCairAdapter(aec_config) if aec_config is not None else None
    app.state.aec_adapter = aec_adapter

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "service": "sion-ontology-api",
            "version": "0.1.0",
            "database": engine.dialect.name,
        }

    @app.get("/api/v1/schema/ontology", response_class=PlainTextResponse, dependencies=[Depends(read_knowledge)])
    def ontology_schema():
        path: Path = settings.ontology_path
        if not path.exists():
            raise HTTPException(status_code=503, detail="ontology schema unavailable")
        return path.read_text(encoding="utf-8")

    @app.get("/api/v1/bootstrap/map-inventory", dependencies=[Depends(read_knowledge)])
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
        try:
            return repository.create_entity(session, payload)
        except repository.MissingReferenceError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except repository.ConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/v1/entities", response_model=list[schemas.EntityRead], dependencies=[Depends(read_knowledge)])
    def list_entities(
        limit: int = Query(default=100, ge=1, le=1000),
        offset: int = Query(default=0, ge=0),
        session: Session = Depends(get_session),
    ):
        return repository.list_entities(session, limit=limit, offset=offset)

    @app.get("/api/v1/entities/{entity_id}", response_model=schemas.EntityRead, dependencies=[Depends(read_knowledge)])
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
        try:
            return repository.create_relation(session, payload)
        except repository.MissingReferenceError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except repository.ConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/v1/relations", response_model=list[schemas.RelationRead], dependencies=[Depends(read_knowledge)])
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
        try:
            return repository.create_evidence(session, payload)
        except repository.MissingReferenceError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/v1/evidence", response_model=list[schemas.EvidenceRead], dependencies=[Depends(read_knowledge)])
    def list_evidence(
        limit: int = Query(default=100, ge=1, le=1000),
        offset: int = Query(default=0, ge=0),
        session: Session = Depends(get_session),
    ):
        return repository.list_evidence(session, limit=limit, offset=offset)

    @app.get("/api/v1/graph", response_model=schemas.GraphResponse, dependencies=[Depends(read_knowledge)])
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
        try:
            return repository.create_artifact(session, payload)
        except repository.ConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/v1/artifacts", response_model=list[schemas.ArtifactRead], dependencies=[Depends(read_knowledge)])
    def list_artifacts(
        limit: int = Query(default=100, ge=1, le=1000),
        offset: int = Query(default=0, ge=0),
        session: Session = Depends(get_session),
    ):
        return repository.list_artifacts(session, limit=limit, offset=offset)

    @app.get("/api/v1/artifacts/{artifact_id}", response_model=schemas.ArtifactRead, dependencies=[Depends(read_knowledge)])
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
        try:
            hits = vector_repository.search_vectors(session, payload)
        except vector_repository.VectorBackendUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return schemas.VectorSearchResponse(
            hits=[schemas.VectorHit.model_validate(hit) for hit in hits],
            count=len(hits),
        )

    @app.get("/api/v1/aec/status", dependencies=[Depends(read_aec)])
    def aec_status():
        enabled = aec_adapter is not None and aec_adapter.enabled
        return {
            "status": "ok" if enabled else "disabled",
            "enabled": enabled,
            "mode": "read_only_federation",
            "source": "khs0927/Ontology",
            "canonical": False,
        }

    @app.get("/api/v1/aec/query", dependencies=[Depends(read_aec)])
    def aec_query(
        question: str = Query(min_length=1, max_length=2000),
        top_k: int = Query(default=10, ge=0, le=100),
        project_id: str | None = Query(default=None, max_length=200),
    ):
        if aec_adapter is None or not aec_adapter.enabled:
            raise HTTPException(status_code=503, detail="AEC/CAIR federation is not configured")
        try:
            result = aec_adapter.query_global_memory(
                question,
                top_k=top_k,
                project_id=project_id,
            )
        except AecCairError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return {
            "source": "khs0927/Ontology",
            "canonical": False,
            "read_only": True,
            "result": result,
        }

    return app


app = create_app()
