from __future__ import annotations

import os
from collections.abc import Generator

from fastapi import Depends, FastAPI, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ontology_map_bridge import MapExport

from . import models, repository, schemas
from .db import Database
from .map_import import MapImportConflict, MapImportInvalid, MapImportResult, import_map


def create_app(database_url: str | None = None) -> FastAPI:
    url = database_url or os.getenv("ONTOLOGY_DATABASE_URL", "sqlite:///./runtime/ontology.db")
    database = Database(url)
    database.initialize()

    app = FastAPI(title="Ontology Platform API", version="0.1.0")
    app.state.database = database

    def get_db() -> Generator[Session, None, None]:
        yield from database.session()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

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

    @app.post("/imports/map", response_model=MapImportResult, status_code=201)
    def import_structured_map(payload: MapExport, db: Session = Depends(get_db)):
        try:
            return import_map(db, payload)
        except MapImportConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except MapImportInvalid as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/entities", response_model=schemas.EntityRead, status_code=201)
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

    @app.patch("/entities/{entity_id}", response_model=schemas.EntityRead)
    def update_entity(entity_id: str, payload: schemas.EntityUpdate, db: Session = Depends(get_db)):
        row = repository.get_entity(db, entity_id)
        if row is None:
            raise HTTPException(status_code=404, detail="entity not found")
        return repository.update_entity(db, row, payload)

    @app.delete("/entities/{entity_id}", status_code=204)
    def delete_entity(entity_id: str, db: Session = Depends(get_db)):
        row = repository.get_entity(db, entity_id)
        if row is None:
            raise HTTPException(status_code=404, detail="entity not found")
        repository.delete_entity(db, row)
        return None

    @app.get("/query/entities", response_model=list[schemas.EntityRead])
    def query_entities(q: str = Query(min_length=1), limit: int = Query(default=50, ge=1, le=200), db: Session = Depends(get_db)):
        return repository.search_entities(db, q, limit=limit)

    @app.post("/relations", response_model=schemas.RelationRead, status_code=201)
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
            raise HTTPException(status_code=409, detail="relation stable_key already exists") from exc

    @app.get("/relations/{relation_id}", response_model=schemas.RelationRead)
    def get_relation(relation_id: str, db: Session = Depends(get_db)):
        row = repository.get_relation(db, relation_id)
        if row is None:
            raise HTTPException(status_code=404, detail="relation not found")
        return row

    @app.delete("/relations/{relation_id}", status_code=204)
    def delete_relation(relation_id: str, db: Session = Depends(get_db)):
        row = repository.get_relation(db, relation_id)
        if row is None:
            raise HTTPException(status_code=404, detail="relation not found")
        repository.delete_relation(db, row)
        return None

    @app.get("/relations", response_model=list[schemas.RelationRead])
    def list_relations(limit: int = Query(default=100, ge=1, le=500), offset: int = Query(default=0, ge=0), db: Session = Depends(get_db)):
        return repository.list_relations(db, limit=limit, offset=offset)

    @app.post("/artifacts", response_model=schemas.ArtifactRead, status_code=201)
    def create_artifact(payload: schemas.ArtifactCreate, db: Session = Depends(get_db)):
        try:
            return repository.create_artifact(db, payload)
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(status_code=409, detail="artifact stable_key already exists") from exc

    @app.get("/artifacts/{artifact_id}", response_model=schemas.ArtifactRead)
    def get_artifact(artifact_id: str, db: Session = Depends(get_db)):
        row = repository.get_artifact(db, artifact_id)
        if row is None:
            raise HTTPException(status_code=404, detail="artifact not found")
        return row

    @app.get("/artifacts", response_model=list[schemas.ArtifactRead])
    def list_artifacts(limit: int = Query(default=100, ge=1, le=500), offset: int = Query(default=0, ge=0), db: Session = Depends(get_db)):
        return repository.list_artifacts(db, limit=limit, offset=offset)

    @app.post("/evidence", response_model=schemas.EvidenceRead, status_code=201)
    def create_evidence(payload: schemas.EvidenceCreate, db: Session = Depends(get_db)):
        if payload.entity_id and repository.get_entity(db, payload.entity_id) is None:
            raise HTTPException(status_code=422, detail="entity not found")
        if payload.relation_id and db.get(models.Relation, payload.relation_id) is None:
            raise HTTPException(status_code=422, detail="relation not found")
        if payload.artifact_id and repository.get_artifact(db, payload.artifact_id) is None:
            raise HTTPException(status_code=422, detail="artifact not found")
        return repository.create_evidence(db, payload)

    @app.get("/evidence/{evidence_id}", response_model=schemas.EvidenceRead)
    def get_evidence(evidence_id: str, db: Session = Depends(get_db)):
        row = repository.get_evidence(db, evidence_id)
        if row is None:
            raise HTTPException(status_code=404, detail="evidence not found")
        return row

    @app.delete("/evidence/{evidence_id}", status_code=204)
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
