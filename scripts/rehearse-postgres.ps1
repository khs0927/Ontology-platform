#Requires -Version 7.0
[CmdletBinding()]
param(
    [string]$Image = "pgvector/pgvector:0.8.6-pg16",
    [int]$ReadyTimeoutSeconds = 90
)

$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $true

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
    throw "Python environment not found: $Python"
}

$docker = Get-Command docker -ErrorAction Stop
& $docker.Source version --format "{{.Server.Version}}"
if ($LASTEXITCODE -ne 0) {
    throw "Docker engine is unavailable. Start Docker Desktop and retry."
}

$suffix = ([guid]::NewGuid().ToString("N")).Substring(0, 12)
$containerName = "sion-pg-rehearsal-$suffix"
$volumeName = "sion-pg-rehearsal-$suffix"
$databaseName = "sion_rehearsal"
$password = [guid]::NewGuid().ToString("N")
$listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0)
$listener.Start()
$hostPort = ([System.Net.IPEndPoint]$listener.LocalEndpoint).Port
$listener.Stop()
$databaseUrl = "postgresql+psycopg://postgres:$password@127.0.0.1:$hostPort/$databaseName"
$volumeCreated = $false
$containerCreated = $false

function Invoke-Step {
    param([string]$Name, [scriptblock]$Command)
    Write-Host "[rehearsal] $Name"
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "Rehearsal step failed: $Name"
    }
}

try {
    Invoke-Step "pull pinned pgvector image" { & $docker.Source pull $Image }

    Invoke-Step "create isolated temporary volume" {
        & $docker.Source volume create --label "purpose=sion-postgres-rehearsal" $volumeName
    }
    $volumeCreated = $true

    Invoke-Step "start isolated temporary container" {
        & $docker.Source run --detach --name $containerName `
            --label "purpose=sion-postgres-rehearsal" `
            --mount "type=volume,source=$volumeName,target=/var/lib/postgresql/data" `
            --publish "127.0.0.1:$hostPort`:5432" `
            --env "POSTGRES_PASSWORD=$password" `
            --env "POSTGRES_DB=$databaseName" `
            $Image
    }
    $containerCreated = $true

    $deadline = [DateTimeOffset]::UtcNow.AddSeconds($ReadyTimeoutSeconds)
    $nativeErrors = $PSNativeCommandUseErrorActionPreference
    $PSNativeCommandUseErrorActionPreference = $false
    do {
        & $docker.Source exec $containerName pg_isready --username postgres --dbname $databaseName *> $null
        if ($LASTEXITCODE -eq 0) { break }
        Start-Sleep -Seconds 1
        $state = (& $docker.Source inspect --format "{{.State.Status}}" $containerName).Trim()
        if ($state -ne "running") {
            & $docker.Source logs $containerName
            $PSNativeCommandUseErrorActionPreference = $nativeErrors
            throw "Temporary PostgreSQL container stopped before readiness."
        }
    } while ([DateTimeOffset]::UtcNow -lt $deadline)
    $readyExitCode = $LASTEXITCODE
    $PSNativeCommandUseErrorActionPreference = $nativeErrors
    if ($readyExitCode -ne 0) {
        & $docker.Source logs $containerName
        throw "PostgreSQL did not become ready within $ReadyTimeoutSeconds seconds."
    }

    $previousDatabaseUrl = $env:SION_DATABASE_URL
    $previousVectorEnabled = $env:SION_VECTOR_ENABLED
    $previousSchemaCreate = $env:SION_ALEMBIC_EXECUTE_SCHEMA_CREATE
    $env:SION_DATABASE_URL = $databaseUrl
    $env:SION_VECTOR_ENABLED = "1"
    $env:SION_ALEMBIC_EXECUTE_SCHEMA_CREATE = "1"

        Invoke-Step "upgrade 0001 through 0004" {
            & $Python -m alembic -c (Join-Path $RepoRoot "alembic.ini") upgrade 0001_baseline
            if ($LASTEXITCODE -ne 0) { throw "Alembic 0001 upgrade failed." }
            & $Python -m alembic -c (Join-Path $RepoRoot "alembic.ini") upgrade head
        }

        $verification = @'
from __future__ import annotations

import os
import sys
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

ROOT = Path(sys.argv[1])
sys.path.insert(0, str(ROOT / "apps" / "api"))

from sion_api.db import build_session_factory  # noqa: E402
from sion_api.health import check_readiness  # noqa: E402
from sion_api.repository import seed_core_types  # noqa: E402

url = os.environ["SION_DATABASE_URL"]
engine = create_engine(url, pool_pre_ping=True)
factory = build_session_factory(engine)

with factory() as session:
    seed_core_types(session)
    entity_type_count = session.execute(text("SELECT count(*) FROM entity_types")).scalar_one()
    relation_type_count = session.execute(text("SELECT count(*) FROM relation_types")).scalar_one()
assert entity_type_count == 11, entity_type_count
assert relation_type_count == 14, relation_type_count
print(f"seed=ok entity_types={entity_type_count} relation_types={relation_type_count}")

required_constraints = {
    "ck_evidence_source", "ck_evidence_target_xor", "ck_evidence_excerpt_hash",
    "ck_evidence_verification_state", "ck_relation_no_self_loop",
    "ck_relation_temporal_order", "ck_relation_verification_state",
    "ck_embeddings_dimensions_positive", "ck_embeddings_shape",
    "ck_embeddings_target_xor", "uq_embeddings_entity_model_content",
    "uq_embeddings_chunk_model_content",
}
with engine.connect() as connection:
    names = {
        row[0] for row in connection.execute(text(
            "SELECT conname FROM pg_constraint WHERE conname = ANY(:names)"
        ), {"names": list(required_constraints)})
    }
missing = required_constraints - names
assert not missing, f"missing constraints: {sorted(missing)}"
print("constraints=ok")

with engine.begin() as connection:
    entity_id = connection.execute(text("""
        INSERT INTO entities (stable_key, entity_type_id, name)
        VALUES ('postgres-rehearsal-entity', 'Entity', 'Postgres rehearsal entity')
        RETURNING id
    """)).scalar_one()
    connection.execute(text("""
        INSERT INTO embeddings
            (entity_id, chunk_id, model, dimensions, embedding, content_hash)
        VALUES (:entity_id, NULL, 'rehearsal-3d', 3, '[1,0,0]', 'rehearsal-content')
    """), {"entity_id": entity_id})

def expect_check_violation(statement: str, params: dict[str, object] | None = None) -> None:
    try:
        with engine.begin() as connection:
            connection.execute(text(statement), params or {})
    except DBAPIError as exc:
        assert getattr(exc.orig, "sqlstate", None) == "23514", exc
        return
    raise AssertionError(f"expected check violation: {statement}")

expect_check_violation("""
    INSERT INTO relations
        (stable_key, source_entity_id, target_entity_id, relation_type_id)
    VALUES ('postgres-rehearsal-self-loop', :entity_id, :entity_id, 'RELATED_TO')
""", {"entity_id": entity_id})
expect_check_violation("""
    INSERT INTO embeddings
        (entity_id, chunk_id, model, dimensions, embedding, content_hash)
    VALUES (:entity_id, NULL, 'rehearsal-invalid', 2, '[1,0,0]', 'rehearsal-invalid')
""", {"entity_id": entity_id})
print("constraint_rejections=ok")

with engine.connect() as connection:
    nearest = connection.execute(text("""
        SELECT model, 1 - (embedding <=> '[1,0,0]'::vector) AS similarity
        FROM embeddings
        WHERE model = 'rehearsal-3d'
        ORDER BY embedding <=> '[1,0,0]'::vector
        LIMIT 1
    """)).one()
    assert nearest.model == "rehearsal-3d"
    assert abs(float(nearest.similarity) - 1.0) < 1e-6
print("embedding_search=ok")

result = check_readiness(engine, vector_enabled=True)
assert result["status"] == "ready", result
assert all(component["status"] == "ok" for component in result["components"].values()), result
print("readiness=ready")

with engine.connect() as connection:
    before = {
        "entity": connection.scalar(text(
            "SELECT count(*) FROM entities WHERE stable_key = 'postgres-rehearsal-entity'"
        )),
        "embedding": connection.scalar(text(
            "SELECT count(*) FROM embeddings WHERE model = 'rehearsal-3d'"
        )),
        "extension": connection.scalar(text(
            "SELECT count(*) FROM pg_extension WHERE extname = 'vector'"
        )),
    }
assert before == {"entity": 1, "embedding": 1, "extension": 1}, before
print(f"pre_downgrade_snapshot={before}")
'@
        $verification | & $Python - $RepoRoot

        Invoke-Step "downgrade 0004/0003 to 0002 without data loss" {
        & $Python -m alembic -c (Join-Path $RepoRoot "alembic.ini") downgrade 0002_evidence_contract
    }

    $postDowngrade = @'
from __future__ import annotations

import os
import sys
from pathlib import Path

from sqlalchemy import create_engine, text

ROOT = Path(sys.argv[1])
engine = create_engine(os.environ["SION_DATABASE_URL"], pool_pre_ping=True)
with engine.connect() as connection:
    revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
    entity_count = connection.scalar(text(
        "SELECT count(*) FROM entities WHERE stable_key = 'postgres-rehearsal-entity'"
    ))
    embedding_count = connection.scalar(text(
        "SELECT count(*) FROM embeddings WHERE model = 'rehearsal-3d'"
    ))
    extension_count = connection.scalar(text(
        "SELECT count(*) FROM pg_extension WHERE extname = 'vector'"
    ))
assert revision == "0002_evidence_contract", revision
assert (entity_count, embedding_count, extension_count) == (1, 1, 1)
print(f"non_destructive_downgrade=ok revision={revision} entity={entity_count} embedding={embedding_count} extension={extension_count}")
'@
        $postDowngrade | & $Python - $RepoRoot

        Write-Host "PASS: isolated pgvector PostgreSQL rehearsal completed and temporary resources will be removed."
}
finally {
    $env:SION_DATABASE_URL = $previousDatabaseUrl
    $env:SION_VECTOR_ENABLED = $previousVectorEnabled
    $env:SION_ALEMBIC_EXECUTE_SCHEMA_CREATE = $previousSchemaCreate
    if ($containerCreated) {
        & $docker.Source rm --force $containerName *> $null
    }
    if ($volumeCreated) {
        & $docker.Source volume rm --force $volumeName *> $null
    }
}
