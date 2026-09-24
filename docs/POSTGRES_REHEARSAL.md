# PostgreSQL/pgvector rehearsal

## 목적

이 rehearsal은 운영 DB나 운영 credential을 사용하지 않는다. `scripts/rehearse-postgres.ps1`이 실행할 때마다 임의 suffix의 container와 named volume을 만들고, loopback에만 임시 포트를 bind한다. container와 volume은 성공/실패 모두 `finally`에서 제거한다. 이미지 digest/tag는 `pgvector/pgvector:0.8.6-pg16`으로 고정한다.

## 자동 실행

저장소 루트에서 다음을 실행한다. `.venv`가 없으면 저장소의 test extra를 먼저 설치한다.

```powershell
pwsh -NoProfile -File .\scripts\rehearse-postgres.ps1
```

스크립트가 수행하는 검증 순서:

1. Docker server와 고정 이미지 접근 확인
2. 임시 volume/container 생성 및 `pg_isready`
3. 새 DB에 `SION_ALEMBIC_EXECUTE_SCHEMA_CREATE=1 alembic upgrade 0001_baseline`
4. `alembic upgrade head`로 0002, 0003, 0004 적용
5. `seed_core_types` 실행
6. `pg_constraint`에 정의된 constraint 이름 확인
7. self-loop relation과 shape-invalid embedding insert가 SQLSTATE `23514`로 거부되는지 확인
8. 3차원 embedding insert 및 `<=>` 검색
9. vector를 켠 `check_readiness(engine, vector_enabled=True)` 결과가 `ready`인지 확인
10. `alembic downgrade 0002_evidence_contract` 실행 후 entity, embedding row, `vector` extension이 모두 보존되는지 확인

## 2026-09-24 실제 실행 결과

Docker Desktop server `29.8.0`에서 pinned `pgvector/pgvector:0.8.6-pg16` 이미지로 임시 volume/container를 만들고 0001→0004를 실제 실행했다. 0003은 SQLAlchemy에 존재하지 않는 `postgresql.VECTOR` 참조를 제거하고 dependency-free `UserDefinedType`으로 native `VECTOR` DDL을 내보내도록 수정했다. seed, Evidence/embedding constraints, 3차원 embedding insert/search, readiness, 0002 non-destructive downgrade가 모두 통과했고 임시 container/volume은 정리됐다. 실행 blocker는 없다.

## 수동 명령과 blocker 확인

PowerShell에서 수동 재현할 때는 아래 순서를 사용한다. `$env:SION_DATABASE_URL`은 반드시 아래처럼 새로 만든 임시 container의 loopback URL이어야 하며, 기존 값이나 `.env`, Doppler, 운영 credential을 입력하지 않는다.

```powershell
$name = "sion-pg-manual-$([guid]::NewGuid().ToString('N').Substring(0,8))"
$password = [guid]::NewGuid().ToString('N')
$volume = docker volume create $name
$container = docker run -d --name $name --mount "type=volume,source=$volume,target=/var/lib/postgresql/data" `
  -e POSTGRES_PASSWORD=$password -e POSTGRES_DB=sion_rehearsal -p 127.0.0.1::5432 `
  pgvector/pgvector:0.8.6-pg16
$port = [int](docker port $name 5432/tcp).Split(':')[-1]
$env:SION_DATABASE_URL = "postgresql+psycopg://postgres:$password@127.0.0.1:$port/sion_rehearsal"
$env:SION_VECTOR_ENABLED = '1'
$env:SION_ALEMBIC_EXECUTE_SCHEMA_CREATE = '1'
.\.venv\Scripts\python.exe -m alembic -c .\alembic.ini upgrade 0001_baseline
.\.venv\Scripts\python.exe -m alembic -c .\alembic.ini upgrade head
```

`upgrade head`는 dependency-free `UserDefinedType`으로 native pgvector column을 생성하므로 별도 dialect 패키지 설치가 필요 없다. 다음 순서로 재현한다.

```powershell
.\.venv\Scripts\python.exe -m alembic -c .\alembic.ini upgrade head
# seed_core_types, pg_constraint 검사, embedding insert/search, readiness 검사
.\.venv\Scripts\python.exe -m alembic -c .\alembic.ini downgrade 0002_evidence_contract
```

downgrade는 `0003_vector_embeddings.downgrade()`의 의도된 no-op 경로만 검증한다. 따라서 `alembic_version`은 `0002_evidence_contract`가 되지만 `embeddings` table, row, `vector` extension은 삭제되지 않아야 한다. `0002_evidence_contract`의 downgrade는 비파괴 거부를 위해 `NotImplementedError`이므로 수행하지 않는다.

수동 실행 후 반드시 위에서 만든 이름의 container와 volume만 삭제한다.

```powershell
docker rm --force $name
docker volume rm --force $volume
```

## 계약 테스트

신규 계약 테스트는 Docker를 실행하지 않고, 이미지 pin, 임시 resource 격리, migration/seed/constraint/vector/readiness/downgrade 단계, 수동 fallback 문서를 검사한다.

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_postgres_rehearsal_contract.py
```
