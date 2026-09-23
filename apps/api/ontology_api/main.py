from __future__ import annotations

import os
import secrets
from collections.abc import Generator

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ontology_map_bridge import MapExport

from . import models, repository, schemas
from .db import Database
from .map_import import MapImportConflict, MapImportInvalid, MapImportResult, import_map


def create_app(
    database_url: str | None = None,
    *,
    security_mode: str | None = None,
    api_token: str | None = None,
) -> FastAPI:
    url = database_url or os.getenv("ONTOLOGY_DATABASE_URL", "sqlite:///./runtime/ontology.db")
    database = Database(url)
    database.initialize()

    mode = security_mode or os.getenv("ONTOLOGY_SECURITY_MODE", "token")
    if mode not in {"token", "disabled"}:
        raise ValueError("ONTOLOGY_SECURITY_MODE must be 'token' or 'disabled'")
    configured_api_token = api_token or os.getenv("ONTOLOGY_API_TOKEN")
    bearer = HTTPBearer(auto_error=False)

    def require_write_auth(
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    ) -> None:
        if mode == "disabled":
            return
        if not configured_api_token:
            raise HTTPException(status_code=503, detail="write API disabled until ONTOLOGY_API_TOKEN is configured")
        if credentials is None or credentials.scheme.lower() != "bearer":
            raise HTTPException(status_code=401, detail="authentication required", headers={"WWW-Authenticate": "Bearer"})
        if not secrets.compare_digest(credentials.credentials, configured_api_token):
            raise HTTPException(status_code=401, detail="invalid bearer token", headers={"WWW-Authenticate": "Bearer"})

    write_dependencies = [Depends(require_write_auth)]

    app = FastAPI(title="Ontology Platform API", version="0.1.0")
    app.state.database = database

    def get_db() -> Generator[Session, None, None]:
        yield from database.session()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/security")
    def security_health() -> dict[str, str | bool]:
        return {
            "mode": mode,
            "write_auth_configured": mode == "disabled" or bool(configured_api_token),
        }

    @app.get("/health/db")
    def database_health(db: Session = Depends(get_db)) -> dict[str, str]:
        db.execute(text("SELECT 1"))
        return {"status": "ok", "database": database.engine.dialect.name}

    @app.get("/graph", response_model=schemas.GraphRead)
    def graph(
        node_limit: int = Query(default=5000, ge=1, le=20000),
        relation_limit: int = Query(default=10000, ge=1, le=50000),
        db: Session = Depends(get_db),
    ):
        return {
            "nodes": repository.list_entities(db, limit=node_limit, offset=0),
            "relations": repository.list_relations(db, limit=relation_limit, offset=0),
        }

    @app.post("/imports/map", response_model=MapImportResult, status_code=201, dependencies=write_dependencies)
    def import_structured_map(payload: MapExport, db: Session = Depends(get_db)):
        try:
            return import_map(db, payload)
        except MapImportConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except MapImportInvalid as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/entities", response_model=schemas.EntityRead, status_code=201, dependencies=write_dependencies)
    def create_entity(payload: schemas.EntityCreate, db: Session = Depends(get_db)):
        if repository.get_entity_type(db, payload.entity_type_id) is None:
            raise HTTPException(status_code=422, detail="entity type not found")
        try:
            return repository.create_entity(db, payload)
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(status_code=409, detail="entity stable_key already exists") from exc

    @app.get("/entities", response_model=list[schemas.EntityRead])
    def list_entities(limit: int = Query(default=100, ge=1, le=500), offset: int = Query(default=0, ge=0), db: Session = Depends(get_db)):
        return repository.list_entities(db, limit=limit, offset=offset)

    @app.get("/entities/{entity_id}", response_model=schemas.EntityRead)
    def get_entity(entity_id: str, db: Session = Depends(get_db)):
        row = repository.get_entity(db, entity_id)
        if row is None:
            raise HTTPException(status_code=404, detail="entity not found")
        return row

    @app.get("/entities/{entity_id}/evidence", response_model=list[schemas.EvidenceRead])
    def get_entity_evidence(entity_id: str, db: Session = Depends(get_db)):
        if repository.get_entity(db, entity_id) is None:
            raise HTTPException(status_code=404, detail="entity not found")
        return repository.list_entity_evidence(db, entity_id)

    @app.patch("/entities/{entity_id}", response_model=schemas.EntityRead, dependencies=write_dependencies)
    def update_entity(entity_id: str, payload: schemas.EntityUpdate, db: Session = Depends(get_db)):
        row = repository.get_entity(db, entity_id)
        if row is None:
            raise HTTPException(status_code=404, detail="entity not found")
        return repository.update_entity(db, row, payload)

    @app.delete("/entities/{entity_id}", status_code=204, dependencies=write_dependencies)
    def delete_entity(entity_id: str, db: Session = Depends(get_db)):
        row = repository.get_entity(db, entity_id)
        if row is None:
            raise HTTPException(status_code=404, detail="entity not found")
        repository.delete_entity(db, row)
        return None

    @app.get("/query/entities", response_model=list[schemas.EntityRead])
    def query_entities(q: str = Query(min_length=1), limit: int = Query(default=50, ge=1, le=200), db: Session = Depends(get_db)):
        return repository.search_entities(db, q, limit=limit)

    @app.post("/relations", response_model=schemas.RelationRead, status_code=201, dependencies=write_dependencies)
    def create_relation(payload: schemas.RelationCreate, db: Session = Depends(get_db)):
        if repository.get_entity(db, payload.source_entity_id) is None:
            raise HTTPException(status_code=422, detail="source entity not found")
        if repository.get_entity(db, payload.target_entity_id) is None:
            raise HTTPException(status_code=422, detail="target entity not found")
        if repository.get_relation_type(db, payload.relation_type_id) is None:
            raise HTTPException(status_code=422, detail="relation type not found")
        try:
            return repository.create_relation(db, payload)
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(status_code=409, detail="relation violates canonical constraints or stable_key already exists") from exc

    @app.get("/relations/{relation_id}", response_model=schemas.RelationRead)
    def get_relation(relation_id: str, db: Session = Depends(get_db)):
        row = repository.get_relation(db, relation_id)
        if row is None:
            raise HTTPException(status_code=404, detail="relation not found")
        return row

    @app.get("/relations/{relation_id}/evidence", response_model=list[schemas.EvidenceRead])
    def get_relation_evidence(relation_id: str, db: Session = Depends(get_db)):
        if repository.get_relation(db, relation_id) is None:
            raise HTTPException(status_code=404, detail="relation not found")
        return repository.list_relation_evidence(db, relation_id)

    @app.get("/relations/{relation_id}/explain", response_model=schemas.RelationExplanation)
    def explain_relation(relation_id: str, db: Session = Depends(get_db)):
        relation = repository.get_relation(db, relation_id)
        if relation is None:
            raise HTTPException(status_code=404, detail="relation not found")
        source = repository.get_entity(db, relation.source_entity_id)
        target = repository.get_entity(db, relation.target_entity_id)
        if source is None or target is None:
            raise HTTPException(status_code=500, detail="relation endpoint missing")
        return {
            "relation": relation,
            "source": source,
            "target": target,
            "evidence": repository.list_relation_evidence(db, relation_id),
        }

    @app.delete("/relations/{relation_id}", status_code=204, dependencies=write_dependencies)
    def delete_relation(relation_id: str, db: Session = Depends(get_db)):
        row = repository.get_relation(db, relation_id)
        if row is None:
            raise HTTPException(status_code=404, detail="relation not found")
        repository.delete_relation(db, row)
        return None

    @app.get("/relations", response_model=list[schemas.RelationRead])
    def list_relations(limit: int = Query(default=100, ge=1, le=500), offset: int = Query(default=0, ge=0), db: Session = Depends(get_db)):
        return repository.list_relations(db, limit=limit, offset=offset)

    @app.post("/artifacts", response_model=schemas.ArtifactRead, status_code=201, dependencies=write_dependencies)
    def create_artifact(payload: schemas.ArtifactCreate, db: Session = Depends(get_db)):
        if payload.entity_id:
            entity = repository.get_entity(db, payload.entity_id)
            if entity is None:
                raise HTTPException(status_code=422, detail="artifact entity not found")
            if entity.entity_type_id not in {"Artifact", "Dataset", "Deliverable"}:
                raise HTTPException(status_code=422, detail="entity type cannot back an artifact")
        try:
            return repository.create_artifact(db, payload)
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(status_code=409, detail="artifact violates canonical constraints or stable_key already exists") from exc

    @app.get("/artifacts/{artifact_id}", response_model=schemas.ArtifactRead)
    def get_artifact(artifact_id: str, db: Session = Depends(get_db)):
        row = repository.get_artifact(db, artifact_id)
        if row is None:
            raise HTTPException(status_code=404, detail="artifact not found")
        return row

    @app.get("/artifacts", response_model=list[schemas.ArtifactRead])
    def list_artifacts(limit: int = Query(default=100, ge=1, le=500), offset: int = Query(default=0, ge=0), db: Session = Depends(get_db)):
        return repository.list_artifacts(db, limit=limit, offset=offset)

    @app.post("/evidence", response_model=schemas.EvidenceRead, status_code=201, dependencies=write_dependencies)
    def create_evidence(payload: schemas.EvidenceCreate, db: Session = Depends(get_db)):
        if payload.entity_id and repository.get_entity(db, payload.entity_id) is None:
            raise HTTPException(status_code=422, detail="entity not found")
        if payload.relation_id and db.get(models.Relation, payload.relation_id) is None:
            raise HTTPException(status_code=422, detail="relation not found")
        if payload.artifact_id and repository.get_artifact(db, payload.artifact_id) is None:
            raise HTTPException(status_code=422, detail="artifact not found")
        if payload.chunk_id and repository.get_chunk(db, payload.chunk_id) is None:
            raise HTTPException(status_code=422, detail="chunk not found")
        try:
            return repository.create_evidence(db, payload)
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(status_code=409, detail="evidence violates canonical constraints") from exc

    @app.get("/evidence/{evidence_id}", response_model=schemas.EvidenceRead)
    def get_evidence(evidence_id: str, db: Session = Depends(get_db)):
        row = repository.get_evidence(db, evidence_id)
        if row is None:
            raise HTTPException(status_code=404, detail="evidence not found")
        return row

    @app.delete("/evidence/{evidence_id}", status_code=204, dependencies=write_dependencies)
    def delete_evidence(evidence_id: str, db: Session = Depends(get_db)):
        row = repository.get_evidence(db, evidence_id)
        if row is None:
            raise HTTPException(status_code=404, detail="evidence not found")
        repository.delete_evidence(db, row)
        return None

    @app.get("/evidence", response_model=list[schemas.EvidenceRead])
    def list_evidence(limit: int = Query(default=100, ge=1, le=500), offset: int = Query(default=0, ge=0), db: Session = Depends(get_db)):
        return repository.list_evidence(db, limit=limit, offset=offset)

    return app


app = create_app()
