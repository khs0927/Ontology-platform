from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
import uuid

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from sqlalchemy.orm import Session

from sion_graphrag import GraphRagConfig, GraphRagUnavailable, SionGraphRag
from sion_ingestion.aec_cair import AecCairAdapter, AecCairConfig, AecCairError
from sion_ingestion.document_ingest import ingest_documents
from sion_ingestion.dxf_ingest import ingest_dxf
from sion_ingestion.project_contracts import (
    ProjectContractCatalog,
    ProjectContractCatalogError,
)

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
    graphrag: SionGraphRag | None = None,
    project_contract_catalog: ProjectContractCatalog | None = None,
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

    if project_contract_catalog is None:
        project_contract_catalog = ProjectContractCatalog.from_env()
    app.state.project_contract_catalog = project_contract_catalog

    if graphrag is None:
        graphrag_config = GraphRagConfig.from_env()
        graphrag = SionGraphRag(graphrag_config) if graphrag_config is not None else None
    app.state.graphrag = graphrag

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
        dependencies=[Depends(write_knowledge)],
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
        dependencies=[Depends(write_knowledge)],
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
        at: datetime | None = Query(default=None, description="Return relations valid at this instant"),
        active_only: bool = Query(default=False, description="Return relations valid now; ignored when at is supplied"),
        session: Session = Depends(get_session),
    ):
        return repository.list_relations(
            session,
            limit=limit,
            offset=offset,
            at=at,
            active_only=active_only,
        )

    @app.post(
        "/api/v1/relations/{relation_id}/invalidate",
        response_model=schemas.RelationRead,
        dependencies=[Depends(write_knowledge)],
    )
    def invalidate_relation(
        relation_id: uuid.UUID,
        payload: schemas.RelationInvalidate,
        session: Session = Depends(get_session),
    ):
        try:
            return repository.invalidate_relation(session, relation_id, payload)
        except repository.MissingReferenceError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except repository.ConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post(
        "/api/v1/evidence",
        response_model=schemas.EvidenceRead,
        status_code=201,
        dependencies=[Depends(write_knowledge)],
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
        at: datetime | None = Query(default=None, description="Return graph edges valid at this instant"),
        active_only: bool = Query(default=False, description="Return graph edges valid now; ignored when at is supplied"),
        session: Session = Depends(get_session),
    ):
        nodes, edges = repository.get_graph(
            session,
            limit=limit,
            at=at,
            active_only=active_only,
        )
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
                    valid_from=edge.valid_from,
                    valid_to=edge.valid_to,
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
        dependencies=[Depends(write_knowledge)],
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
        dependencies=[Depends(write_knowledge)],
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
        dependencies=[Depends(read_knowledge)],
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

    @app.get("/api/v1/contracts/status", dependencies=[Depends(read_knowledge)])
    def project_contract_status():
        enabled = project_contract_catalog is not None and project_contract_catalog.enabled
        return {
            "configured": project_contract_catalog is not None,
            "enabled": enabled,
            "mode": "read_only_catalog",
            "source": "khs0927/All-in-memory",
            "canonical": False,
        }

    @app.get("/api/v1/contracts", dependencies=[Depends(read_knowledge)])
    def project_contracts(
        producer: str | None = Query(default=None, max_length=200),
        consumer: str | None = Query(default=None, max_length=200),
        schema: str | None = Query(default=None, max_length=200),
        verification_status: str | None = Query(default=None, max_length=80),
    ):
        if project_contract_catalog is None or not project_contract_catalog.enabled:
            raise HTTPException(status_code=503, detail="project contract registry is not configured")
        try:
            rows = project_contract_catalog.find(
                producer=producer,
                consumer=consumer,
                schema=schema,
                verification_status=verification_status,
            )
        except ProjectContractCatalogError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return {
            "source": "khs0927/All-in-memory",
            "canonical": False,
            "read_only": True,
            "count": len(rows),
            "contracts": rows,
        }

    def require_graphrag() -> SionGraphRag:
        if graphrag is None:
            raise HTTPException(status_code=503, detail="GraphRAG layer is not configured")
        return graphrag

    @app.get("/api/v1/graphrag/status", dependencies=[Depends(read_knowledge)])
    def graphrag_status():
        if graphrag is None:
            return {"configured": False, "canonical": False}
        config = graphrag.config
        return {
            "configured": True,
            "canonical": False,
            "engine": "lightrag",
            "storage": config.storage,
            "workspace": config.workspace,
            "embedding_model": config.embedding_model,
            "answers_enabled": config.answers_enabled,
        }

    @app.post("/api/v1/graphrag/project", dependencies=[Depends(write_knowledge)])
    async def graphrag_project():
        engine = require_graphrag()
        try:
            written = await engine.project(factory)
        except GraphRagUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {"canonical": False, "written": written}

    @app.post("/api/v1/graphrag/query", dependencies=[Depends(read_knowledge)])
    async def graphrag_query(payload: schemas.GraphRagQuery):
        engine = require_graphrag()
        try:
            result = await engine.query(payload.question, mode=payload.mode, top_k=payload.top_k)
        except GraphRagUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {"canonical": False, **result}

    @app.get("/map")
    def ontology_map():
        page = Path(__file__).resolve().parents[3] / "apps" / "web" / "index.html"
        if not page.exists():
            raise HTTPException(status_code=404, detail="map page missing")
        return FileResponse(page)

    @app.post("/api/v1/ingest/documents", dependencies=[Depends(write_knowledge)])
    def ingest_document_route(payload: dict, session: Session = Depends(get_session)):
        paths = [Path(item) for item in payload.get("paths", [])]
        if not paths:
            raise HTTPException(status_code=422, detail="paths required")
        return ingest_documents(session, paths)

    @app.post("/api/v1/ingest/dxf", dependencies=[Depends(write_knowledge)])
    def ingest_dxf_route(payload: dict, session: Session = Depends(get_session)):
        raw = payload.get("path")
        if not raw:
            raise HTTPException(status_code=422, detail="path required")
        path = Path(raw)
        if path.suffix.lower() != ".dxf" or not path.is_file():
            raise HTTPException(status_code=422, detail="dxf file required")
        return ingest_dxf(session, path)

    return app


app = create_app()
