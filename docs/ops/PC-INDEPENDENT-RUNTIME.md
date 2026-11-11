# PC-independent Sion runtime / PC 독립 Sion 런타임

Status: design plus the first runnable slice. Issue [#71](https://github.com/khs0927/Ontology-platform/issues/71).

The English and Korean sections describe the same design. If they disagree, the English section is the one to correct and the Korean section should be updated to match.

This document does not move the live database, does not register or edit Windows scheduled tasks, and does not change `packages/aec/docker-compose.yml` or `packages/aec/scripts/ops/switch-to-monorepo.ps1`.

Related: `packages/aec/docs/OPERATIONS.ko.md` (the PC runbook, unchanged), `packages/aec/docs/database-backup-restore.md`, `docs/STORAGE.md`, `docs/SYNC_ARCHITECTURE.md`, `docs/ops/CLOUD-OPS.ko.md`, `docs/ops/DRIVE-LAYOUT.ko.md`, `docs/API_AUTH.md`, `docs/mobile/MOBILE-READONLY-SNAPSHOT-MCP.md`.

---

## English

### 1. Problem

The canonical AEC graph runs on one Windows PC:

| Piece | Where it is today | What breaks when that PC is off |
| --- | --- | --- |
| PostgreSQL 16 + Apache AGE + pgvector + PostGIS | Docker container `aec-db`, loopback `127.0.0.1:55432`, named volume for that compose project | No graph, no vectors, no jobs |
| Operational API | Docker container `aec-api`, loopback `127.0.0.1:58000` | No search, no ask, no catalog |
| Writers | Host workers and scheduled tasks under `\AEC\` (Ollama, re-embed, GraphRAG refresh, WSL cache reclaim, Docker startup) plus `AEC-DB-Backup` | Ingest and refresh stop, which is acceptable. Reads should not stop with them |
| Google Drive | Drive for desktop mounts a `G:` letter inside the logged-on user session | The backup mirror and source archive are unreachable from that PC. Drive itself is still the archive |

A phone cannot open that loopback port. The existing Cloudflare name `sion-jesus.xyz` does not prove a Sion process is running. The supervision database on Neon has pgvector and PostGIS and does **not** have Apache AGE, so it cannot stand in for this graph.

Two neighboring read-only paths already exist and are not a substitute:

- `GET /api/v1/regulation/summary` on `apps/api` (`sion_api`) is a small project summary. It is not the AEC drawing graph.
- The Drive snapshot MCP in `docs/mobile/MOBILE-READONLY-SNAPSHOT-MCP.md` reads a fixed export. It is evidence, not the live AGE database.

### 2. Recommended path

Keep the Windows PC as the only writer. Add a small always-on Linux host that runs the same Postgres image from a **logical dump**, and publish only the new read-only API through a Cloudflare Tunnel on `sion-jesus.xyz`.

```
Windows PC (often off)                         Always-on host
  aec-db  ---- pg_dump custom format ------>   aec-db-copy  (new volume)
  \AEC\ tasks, ingest, Ollama, G: mirror       aec_reader role, read-only transactions
  aec-api on 127.0.0.1:58000                   aec-api-readonly on 127.0.0.1:58010
                                               Cloudflare Tunnel -> phone / ChatGPT
```

The phone never receives the database port, the owner role, the PC token, or a write route. Search and ask stay available. Ask does not call a model, so drawing text is not sent off the writer PC for generation. The copy's `/healthz` adds `read_only: true` and `canonical: false`. A response from the copy is the last restored dump, not the PC's current transactions.

Do this before any other hosting work:

1. Leave the PC compose file, the `\AEC\` tasks, `AEC-DB-Backup`, and `switch-to-monorepo.ps1` as they are.
2. Confirm a recent `aec-db-YYYYMMDDTHHMMSSZ.dump` from the existing backup, and compare SHA-256 on the PC and on the copy host before restore.
3. Restore into the new volume only (`aec-mobile-pgdata`, container `aec-db-copy`, host port `127.0.0.1:55433`).
4. Create `aec_reader` from `reader-role.sql` and set its password in a local `psql` session.
5. Start `aec-api-readonly` with a new token and that reader URL.
6. Put a Cloudflare Tunnel on the host, aimed at `http://127.0.0.1:58010`, with a monthly budget alarm already on. Do not publish Postgres.

OIDC, per-user project ACL, review writes, and the ChatGPT iOS login drill are later issue steps (C–G). They are not required to get a read-only mobile query path up.

### 3. Hosting options

Prices below are planning figures for a 2 vCPU / 4 GB class machine, not a quote. Recheck the vendor page before paying. The database dumps already described in `docs/ops/DRIVE-LAYOUT.ko.md` are on the order of 1 GB, so a 40 GB disk holds the restored database, one dump, and the image.

| Option | AGE + pgvector + PostGIS | Up while the Windows PC is off | Phone access | Planning cost | Decision |
| --- | --- | --- | --- | --- | --- |
| Small Linux VPS, this repo's Postgres image, Cloudflare Tunnel, read-only API | Yes. Same image as the PC | Yes | Tunnel to loopback. No public database port | About USD 5–15 / month (about 1–3만 원 at a planning rate of 1,400원/USD). Tunnel USD 0. The domain is already in use | **Use this** |
| Second computer at home | Yes | Only while that computer, power, and the home link are up | Tunnel | Hardware and power already paid, or a one-time mini PC | Does not meet the goal if it is the same PC that is often off. A second home machine still dies with the home network |
| Neon (supervision app) | pgvector and PostGIS only. No Apache AGE (`pg_available_extensions`, issue #71) | Yes | Yes | Leave that database on its own plan | Do not load AEC drawings or the AGE graph into it |
| RDS, Cloud SQL, AlloyDB | Apache AGE is not a managed extension | Yes | Yes | Often USD 15–80 / month before disk | Do not use for the canonical graph |
| Wake the Windows PC from the phone | Yes | No | No, whenever the PC is asleep, off, or the session that owns `G:` is logged out | USD 0 extra | Today's state. Keep it as the writer |

The VPS needs no GPU. Embeddings and Ollama stay on the PC. The read-only API is capped at 1 GB of memory in its compose file.

### 4. Data sync and backup

Rules that already apply, and that this move must not weaken:

- The live PostgreSQL data directory and WAL are never the backup, and they are never placed on a Drive-synced folder (`docs/SYNC_ARCHITECTURE.md`, `docs/STORAGE.md`).
- Copies are one-way. Do not use mirror or sync modes that delete a Drive file because a local file disappeared.
- CAD originals stay on the PC and on Drive. The always-on host does not mount `G:` and does not receive those files.
- A dump that has not been restored into an empty database and queried is unverified. Use the same words as `docs/ops/DRIVE-LAYOUT.ko.md`: `BACKUP_VERIFIED` is not a restore drill.

What continues on the PC, unchanged:

- `packages/aec/scripts/ops/backup.ps1` writes a custom-format dump from inside `aec-db`, keeps the newest dumps in the local backup directory, and copies them to the Drive mirror when `G:` is mounted. If the mirror is missing, the local dump remains and the next run retries the copy.
- `AEC-DB-Backup` and the `\AEC\` tasks are not edited by this work. Do not point them at the copy host.

What happens on the always-on host:

1. Copy one dump file. Compute SHA-256 on both sides. Do not restore on a mismatch.
2. Start only `postgres-copy.yml`. The volume name is `aec-mobile-pgdata` under compose project `aec-mobile-readonly`. It is not the PC volume.
3. `pg_restore --no-owner --no-privileges` into database `aec`. The image creates `postgis`, `vector`, `age`, and `pg_trgm` on first boot. An error that the extension already exists can be skipped. Any other error stops the restore. Take a dump of the copy before you retry a destructive flag such as `--clean`.
4. Apply `reader-role.sql`. Set the reader password with `\password`, not with a statement saved in the repo.
5. Run the grant check in that SQL file. Both write-privilege counts must be 0. If `cypher()` is `SECURITY DEFINER`, revoke `EXECUTE` from `aec_reader` and accept that graph expansion is unavailable until an invoker wrapper is reviewed.
6. Point the API at `postgresql://aec_reader:<password>@db-copy:5432/aec` on the shared compose project, or at `127.0.0.1:55433` from a process on the host. The API process refuses user `aec`, password `change-me` or `replace-with-password`, host `db` or `aec-db`, and port `55432` on loopback.
7. `GET /healthz` on port `58010` must show `read_only: true` and `canonical: false`. Then run one known `POST /v1/search`. `POST /v1/ingestions` and `POST /v1/reviews` must return 405.
8. When a newer dump is ready, restore it beside the current copy (second volume or second database), check search, then change `AEC_READONLY_DATABASE_URL`. Keep the previous dump until that check passes. Do not delete the Drive copy as part of the switch.

Restore drill: at least once a month, from a dump, into an empty copy, then `/healthz` and one search. Record the dump name, SHA-256, and whether search returned rows. A host that has never passed that drill is not the mobile backend.

Sion's own SQLite or `sion_api` PostgreSQL snapshots under the Drive storage root (`docs/STORAGE.md`) stay the export path for the ontology API. They are not loaded into `aec-db-copy`.

### 5. Auth

This slice is one bearer token and a hard read-only process. It is not OIDC.

| Check | PC API today | Read-only API |
| --- | --- | --- |
| Token | `AEC_API_TOKEN` from the PC `.env`, shared with power-cad-mcp as `POWERCAD_ONTOLOGY_TOKEN` | A different value, `AEC_READONLY_API_TOKEN`, injected as `AEC_API_TOKEN` only inside `aec-api-readonly` |
| Missing token | Loopback clients are allowed | The process exits. It will not serve |
| Placeholder token or password | PC defaults stay valid for the PC | Refused (`replace-with-token`, `change-me`, `replace-with-password`, shorter than 16 characters) |
| Database role | Owner `aec`, read-write | `aec_reader`: `SELECT` plus `EXECUTE` on `ag_catalog`, session `default_transaction_read_only=on` |
| Routes | Ingest, retry, and review write | `GET`, `HEAD`, `OPTIONS`, `POST /v1/search`, `POST /v1/ask` only. Ask forces `generate=false` |
| Activity stamp | Inserts into `aec.interactive_activity` so writers yield | Disabled. The session is read-only even if a handler tries to write |
| Bind | `127.0.0.1:58000` | `127.0.0.1:58010`. The tunnel is the front door |
| Identity | One shared token | Still one shared token. Enough for a single operator's phone. Not enough for a second person |

Later, in this order, still without putting a write token on this container:

1. Cloudflare Access in front of the tunnel (one-time pin or the operator's identity provider). Access does not replace the bearer check.
2. Per-user tokens or OIDC mapped onto the scopes in `docs/API_AUTH.md` (`read:knowledge` separate from `write:knowledge`, project allowlist). That work belongs on `sion_api` and on a future AEC scope split. It is issue step C.
3. Review writes (`POST /v1/reviews`, regulation decisions) only on the writer, with `expected_version`, a dry run, and an audit row. Issue steps E–F. The read-only container never gains those routes.

Tokens stay in the gitignored `.env` next to the compose file, or in the host secret store. They are not baked into the image. The image build already rejects a `.env` in the build context. Do not log the token, the URL, or the password. Startup errors name the missing piece and do not echo the value.

Rotate the mobile token by editing the copy host's `.env` and recreating `aec-api-readonly`. Do not rotate the PC token as part of that, or power-cad-mcp stops authenticating.

### 6. Costs and caps

Set the cap before creating the paid account.

| Item | Cap |
| --- | --- |
| Account budget | USD 30 / month (about 4만 원 at the planning rate), alarms at 50%, 80%, and 100%. No deployment on an account without that alarm |
| Compute | One VPS. Do not autoscale. Stop at two API replicas if a second is ever added, and do not add it in this slice |
| API container | `mem_limit: 1g`, `pids_limit: 256`, logs `10m × 3` |
| Database | The copy compose sets `shared_buffers=256MB` for a 4 GB host. Raise it only after the restore drill shows memory pressure. No public IP on Postgres |
| LLM and embeddings | Not on this host. `AEC_EMBEDDING_URL` empty (stored vectors and the offline hash). `AEC_LLM_ALLOW_REMOTE=0`. Ask does not call a model |
| Egress | Search and ask JSON only. Do not add a route that returns CAD or PDF bytes |
| Drive | Already paid. Do not buy a second copy of originals |
| Tunnel | USD 0 for the connector. Access, if added later, stays on the free tier until the user count exceeds it |
| Logs | 14 days, then discard. No token, no `.env`, no personal path (`docs/ops/CLOUD-OPS.ko.md`) |

Shutdown is "scale the API to zero and rotate the token", not "delete the volume". Take a dump of the copy before deleting a volume.

There is still no deploy workflow in `.github/workflows/`. `docs/ops/CLOUD-OPS.ko.md` keeps that hold until a real account, a pinned image digest, a staging check, and a manual production approval exist. This slice is files an operator runs by hand.

### 7. What this change adds

| File | Role |
| --- | --- |
| `packages/aec/deploy/mobile-readonly/compose.yml` | API only. Project `aec-mobile-readonly`, container `aec-api-readonly`, `AEC_API_READ_ONLY=1`, loopback port 58010, no volume, read-only root filesystem |
| `packages/aec/deploy/mobile-readonly/postgres-copy.yml` | Optional copy database. Container `aec-db-copy`, volume `aec-mobile-pgdata`, loopback port 55433. Not started by the API file |
| `packages/aec/deploy/mobile-readonly/reader-role.sql` | `aec_reader` grants. No password in the file |
| `packages/aec/deploy/mobile-readonly/env.example` | Empty secrets. Copy to `.env` in that directory (gitignored) |
| `packages/aec/src/aec_intelligence/operational/readonly.py` | Startup checks, 405 for writes, entrypoint `python -m aec_intelligence.operational.readonly` |

`AEC_API_READ_ONLY` unset means the PC process is unchanged: same health JSON, same write routes, same database session, same activity stamp. The PC compose file does not set the variable. The scheduled-task scripts do not set it.

```bash
# on the always-on host, from the repository root, after the .env is filled
docker compose -f packages/aec/deploy/mobile-readonly/postgres-copy.yml up -d
# restore, then reader-role.sql, then:
docker compose -f packages/aec/deploy/mobile-readonly/compose.yml up -d --build
curl -fsS http://127.0.0.1:58010/healthz
```

Build context for the API image remains the repository root and `packages/aec/docker/Dockerfile.app`. The PC image command is still `uvicorn`. Only the mobile compose overrides it.

### 8. Not in this change

- No edit to `packages/aec/docker-compose.yml`, `scripts/ops/*.ps1`, or any scheduled task.
- No live migration, no attachment to the PC volume, no `G:` mount on the new host.
- No public Postgres, no OIDC, no review approval, no ChatGPT OAuth end-to-end test.
- No claim that CI passing means the phone can log in. The tunnel and a real dump restore are operator steps outside this repository.

---

## 한국어

### 1. 문제

정규 AEC 그래프는 Windows PC 한 대에서 돈다.

| 구성 | 현재 위치 | 그 PC가 꺼지면 |
| --- | --- | --- |
| PostgreSQL 16 + Apache AGE + pgvector + PostGIS | Docker 컨테이너 `aec-db`, 루프백 `127.0.0.1:55432`, 그 compose 프로젝트의 이름 있는 볼륨 | 그래프·벡터·작업 큐가 사라진다 |
| 운영 API | Docker 컨테이너 `aec-api`, 루프백 `127.0.0.1:58000` | 검색, 질의, 카탈로그가 사라진다 |
| 기록 측 | 호스트 워커와 `\AEC\` 예약 작업(Ollama, 재임베딩, GraphRAG 갱신, WSL 캐시 회수, Docker 기동)과 `AEC-DB-Backup` | 적재와 갱신은 멈춰도 된다. 조회까지 같이 멈추면 안 된다 |
| Google Drive | 데스크톱 앱이 로그온 세션 안에서 `G:`를 마운트 | 그 PC에서는 백업 미러와 원본 보관소가 안 보인다. Drive 자체는 그대로 보관소다 |

휴대폰은 그 루프백 포트에 닿지 못한다. `sion-jesus.xyz`가 있다는 사실만으로 Sion 프로세스가 떠 있는 것은 아니다. 감리 쪽에서 쓰는 Neon은 pgvector와 PostGIS는 있고 Apache AGE는 없다(이슈 #71에서 `pg_available_extensions`로 확인). 그 데이터베이스로 이 그래프를 대체하지 않는다.

이미 있는 읽기 전용 경로 두 개는 대체가 아니다.

- `apps/api`(`sion_api`)의 `GET /api/v1/regulation/summary`는 프로젝트 요약이다. AEC 도면 그래프가 아니다.
- `docs/mobile/MOBILE-READONLY-SNAPSHOT-MCP.md`의 Drive 스냅샷 MCP는 고정된 내보내기를 읽는다. 증거이지 살아있는 AGE 데이터베이스가 아니다.

### 2. 권장 경로

Windows PC만 기록한다. 작은 Linux 호스트를 항상 켜 두고, **논리 덤프**로 같은 Postgres 이미지를 띄운 다음, 새 읽기 전용 API만 Cloudflare Tunnel로 `sion-jesus.xyz`에 연다.

```
Windows PC (자주 꺼짐)                          항상 켜 둔 호스트
  aec-db  ---- pg_dump custom format ------>   aec-db-copy  (새 볼륨)
  \AEC\ 작업, 적재, Ollama, G: 미러            aec_reader, 읽기 전용 트랜잭션
  aec-api  127.0.0.1:58000                     aec-api-readonly  127.0.0.1:58010
                                               Cloudflare Tunnel -> 휴대폰 / ChatGPT
```

휴대폰에는 데이터베이스 포트, 소유자 롤, PC 토큰, 쓰기 경로를 주지 않는다. 검색과 질의는 남긴다. 질의는 모델을 호출하지 않으므로, 답변 생성을 위해 도면 문자열이 기록 PC 밖으로 나가지 않는다. 복제본의 `/healthz`에는 `read_only: true`, `canonical: false`가 붙는다. 복제본의 응답은 마지막으로 복원한 덤프이지, PC의 현재 트랜잭션이 아니다.

다른 호스팅 작업보다 먼저 할 일:

1. PC compose 파일, `\AEC\` 작업, `AEC-DB-Backup`, `switch-to-monorepo.ps1`은 그대로 둔다.
2. 기존 백업의 `aec-db-YYYYMMDDTHHMMSSZ.dump` 하나를 고르고, 복원 전에 PC와 복제 호스트에서 SHA-256을 비교한다.
3. 새 볼륨에만 복원한다 (`aec-mobile-pgdata`, 컨테이너 `aec-db-copy`, 호스트 포트 `127.0.0.1:55433`).
4. `reader-role.sql`로 `aec_reader`를 만들고, 비밀번호는 로컬 `psql` 세션에서 정한다.
5. 새 토큰과 그 reader URL로 `aec-api-readonly`를 띄운다.
6. 호스트의 Cloudflare Tunnel을 `http://127.0.0.1:58010`으로 향하게 한다. 월 예산 알림을 먼저 켠다. Postgres는 공개하지 않는다.

OIDC, 사용자별 프로젝트 ACL, 검토 쓰기, ChatGPT iOS 로그인 점검은 이슈의 나중 단계(C–G)다. 읽기 전용 모바일 조회를 여는 데 필요하지 않다.

### 3. 호스팅 선택

아래 금액은 2 vCPU / 4 GB 급의 계획 수치이지 견적이 아니다. 결제 전에 공급자 가격표를 다시 본다. `docs/ops/DRIVE-LAYOUT.ko.md`에 적힌 덤프는 1 GB 안팎이므로, 디스크 40 GB면 복원된 데이터베이스, 덤프 하나, 이미지를 담는다.

| 선택 | AGE + pgvector + PostGIS | Windows PC가 꺼져 있어도 동작 | 휴대폰 접속 | 계획 비용 | 결정 |
| --- | --- | --- | --- | --- | --- |
| 작은 Linux VPS, 이 저장소의 Postgres 이미지, Cloudflare Tunnel, 읽기 전용 API | 가능. PC와 같은 이미지 | 가능 | 루프백으로 터널. 데이터베이스 포트는 공개하지 않음 | 월 약 USD 5–15 (계획 환율 1,400원 기준 약 1–3만 원). 터널 USD 0. 도메인은 이미 사용 중 | **이 경로를 쓴다** |
| 집의 두 번째 컴퓨터 | 가능 | 그 컴퓨터, 전원, 집 회선이 살아 있을 때만 | 터널 | 장비와 전기는 이미 내거나, 미니 PC를 한 번 산다 | 자주 꺼지는 그 PC와 같은 기계라면 목표가 아니다. 집의 두 번째 기계도 집 네트워크와 함께 죽는다 |
| Neon (감리 앱) | pgvector와 PostGIS만 있음. Apache AGE 없음 (이슈 #71) | 가능 | 가능 | 그 데이터베이스는 자기 요금제에 둔다 | AEC 도면이나 AGE 그래프를 올리지 않는다 |
| RDS, Cloud SQL, AlloyDB | Apache AGE가 관리형 확장이 아님 | 가능 | 가능 | 디스크 전에도 월 USD 15–80인 경우가 많다 | 정규 그래프에 쓰지 않는다 |
| 휴대폰으로 Windows PC를 깨움 | 가능 | 불가 | PC가 절전·종료이거나 `G:`를 가진 세션이 로그아웃이면 불가 | 추가 비용 USD 0 | 현재 상태. 기록 측으로 유지한다 |

VPS에 GPU는 필요 없다. 임베딩과 Ollama는 PC에 둔다. 읽기 전용 API는 compose에서 메모리 1 GB로 제한한다.

### 4. 데이터 동기화와 백업

이미 적용 중이고, 이번 이전에서 약해지면 안 되는 규칙:

- 살아있는 PostgreSQL 데이터 디렉터리와 WAL은 백업이 아니고, Drive로 동기화되는 폴더에 두지 않는다 (`docs/SYNC_ARCHITECTURE.md`, `docs/STORAGE.md`).
- 복사는 한 방향이다. 로컬 파일이 없어졌다고 Drive 파일을 지우는 mirror/sync는 쓰지 않는다.
- CAD 원본은 PC와 Drive에 둔다. 항상 켜 둔 호스트는 `G:`를 마운트하지 않고 그 파일을 받지 않는다.
- 빈 데이터베이스에 복원해서 조회해 보지 않은 덤프는 미검증이다. `docs/ops/DRIVE-LAYOUT.ko.md`와 같은 말을 쓴다. `BACKUP_VERIFIED`는 복구 훈련이 아니다.

PC에서 그대로 계속되는 것:

- `packages/aec/scripts/ops/backup.ps1`은 `aec-db` 안에서 custom format 덤프를 만들고, 로컬 백업 디렉터리에 최신본을 남긴 뒤, `G:`가 마운트되어 있으면 Drive 미러로 복사한다. 미러가 없으면 로컬 덤프는 남고 다음 실행이 복사를 다시 시도한다.
- `AEC-DB-Backup`과 `\AEC\` 작업은 이 변경에서 고치지 않는다. 그 작업을 복제 호스트로 옮기지 않는다.

항상 켜 둔 호스트에서 할 일:

1. 덤프 파일 하나를 복사한다. 양쪽에서 SHA-256을 계산한다. 다르면 복원하지 않는다.
2. `postgres-copy.yml`만 띄운다. 볼륨 이름은 compose 프로젝트 `aec-mobile-readonly` 아래의 `aec-mobile-pgdata`다. PC 볼륨이 아니다.
3. 데이터베이스 `aec`에 `pg_restore --no-owner --no-privileges` 한다. 이미지는 첫 기동 때 `postgis`, `vector`, `age`, `pg_trgm`을 만든다. 확장이 이미 있다는 오류만 건너뛴다. 그 외 오류면 복원을 멈춘다. `--clean` 같은 파괴적 옵션을 다시 시도하기 전에 복제본을 먼저 덤프한다.
4. `reader-role.sql`을 적용한다. 비밀번호는 저장소에 남기는 문이 아니라 `\password`로 정한다.
5. 그 SQL 파일의 권한 확인을 실행한다. 쓰기 권한 개수는 둘 다 0이어야 한다. `cypher()`가 `SECURITY DEFINER`이면 `aec_reader`의 `EXECUTE`를 회수하고, invoker 래퍼를 검토하기 전까지 그래프 확장은 없는 것으로 둔다.
6. API의 URL은 같은 compose 프로젝트에서 `postgresql://aec_reader:<비밀번호>@db-copy:5432/aec` 이거나, 호스트 프로세스에서는 `127.0.0.1:55433`이다. API 프로세스는 사용자 `aec`, 비밀번호 `change-me` 또는 `replace-with-password`, 호스트 `db` 또는 `aec-db`, 루프백의 포트 `55432`를 거부한다.
7. 포트 `58010`의 `GET /healthz`에 `read_only: true`와 `canonical: false`가 있어야 한다. 이어서 아는 값으로 `POST /v1/search`를 한 번 호출한다. `POST /v1/ingestions`와 `POST /v1/reviews`는 405여야 한다.
8. 더 새로운 덤프가 생기면 현재 복제본 옆(두 번째 볼륨 또는 두 번째 데이터베이스)에 복원하고, 검색을 확인한 다음 `AEC_READONLY_DATABASE_URL`을 바꾼다. 그 확인이 끝날 때까지 이전 덤프를 둔다. 전환하면서 Drive 복사본을 지우지 않는다.

복구 훈련: 한 달에 한 번 이상, 덤프에서 빈 복제본으로 복원한 뒤 `/healthz`와 검색 한 번. 덤프 이름, SHA-256, 검색이 행을 돌려줬는지를 남긴다. 이 훈련을 한 번도 통과하지 않은 호스트는 모바일 백엔드가 아니다.

Drive 저장 루트 아래의 Sion SQLite 또는 `sion_api` PostgreSQL 스냅샷(`docs/STORAGE.md`)은 온톨로지 API의 내보내기 경로로 남는다. `aec-db-copy`에 넣지 않는다.

### 5. 인증

이번 단계는 베어러 토큰 하나와 읽기 전용 프로세스다. OIDC가 아니다.

| 확인 | 오늘 PC API | 읽기 전용 API |
| --- | --- | --- |
| 토큰 | PC `.env`의 `AEC_API_TOKEN`. power-cad-mcp에는 `POWERCAD_ONTOLOGY_TOKEN`으로 같은 값 | 다른 값. `AEC_READONLY_API_TOKEN`이며 `aec-api-readonly` 안에서만 `AEC_API_TOKEN`으로 들어간다 |
| 토큰 없음 | 루프백 클라이언트는 허용 | 프로세스가 종료된다. 서비스하지 않는다 |
| 자리표시 토큰·비밀번호 | PC의 기본값은 PC에서 그대로 유효 | 거부 (`replace-with-token`, `change-me`, `replace-with-password`, 16자 미만) |
| 데이터베이스 롤 | 소유자 `aec`, 읽기·쓰기 | `aec_reader`: `SELECT`와 `ag_catalog`의 `EXECUTE`, 세션 `default_transaction_read_only=on` |
| 경로 | 적재, 재시도, 검토가 기록함 | `GET`, `HEAD`, `OPTIONS`, `POST /v1/search`, `POST /v1/ask`만. 질의는 `generate=false`로 고정 |
| 활동 도장 | 기록 측이 양보하도록 `aec.interactive_activity`에 INSERT | 꺼 둔다. 핸들러가 쓰려 해도 세션은 읽기 전용 |
| 바인드 | `127.0.0.1:58000` | `127.0.0.1:58010`. 정면은 터널 |
| 신원 | 공유 토큰 하나 | 여전히 공유 토큰 하나. 운영자 휴대폰 한 대에는 충분하다. 두 번째 사람에게는 부족하다 |

이후 순서는 다음과 같고, 이 컨테이너에 쓰기 토큰을 넣지 않는다.

1. 터널 앞에 Cloudflare Access (일회용 핀 또는 운영자의 신원 공급자). Access가 베어러 검사를 대신하지 않는다.
2. 사용자별 토큰 또는 OIDC를 `docs/API_AUTH.md`의 스코프에 맞춘다 (`read:knowledge`와 `write:knowledge` 분리, 프로젝트 허용 목록). 이 작업은 `sion_api`와 이후의 AEC 스코프 분리에 속한다. 이슈 단계 C다.
3. 검토 쓰기(`POST /v1/reviews`, 규제 결정)는 기록 측에서만, `expected_version`, 드라이런, 감사 행과 함께 한다. 이슈 단계 E–F. 읽기 전용 컨테이너는 그 경로를 받지 않는다.

토큰은 compose 옆의 gitignore된 `.env` 또는 호스트 비밀 저장소에만 둔다. 이미지에 굽지 않는다. 이미지 빌드는 빌드 맥락의 `.env`를 이미 거부한다. 토큰, URL, 비밀번호를 로그에 남기지 않는다. 기동 오류는 무엇이 빠졌는지만 말하고 값은 찍지 않는다.

모바일 토큰을 바꿀 때는 복제 호스트의 `.env`를 고치고 `aec-api-readonly`를 다시 만든다. 그때 PC 토큰까지 바꾸지 않는다. 바꾸면 power-cad-mcp 인증이 끊긴다.

### 6. 비용과 상한

유료 계정을 만들기 전에 상한을 둔다.

| 항목 | 상한 |
| --- | --- |
| 계정 예산 | 월 USD 30 (계획 환율 기준 약 4만 원). 50%, 80%, 100% 알림. 알림 없는 계정에는 배포하지 않는다 |
| 컴퓨트 | VPS 하나. 자동 확장은 하지 않는다. 두 번째 API 복제본을 더하더라도 둘에서 멈추고, 이번 단계에서는 더하지 않는다 |
| API 컨테이너 | `mem_limit: 1g`, `pids_limit: 256`, 로그 `10m × 3` |
| 데이터베이스 | 복제 compose는 4 GB 호스트에 맞춰 `shared_buffers=256MB`다. 복구 훈련에서 메모리 압박이 보인 뒤에만 올린다. Postgres에 공개 IP를 주지 않는다 |
| LLM과 임베딩 | 이 호스트에 두지 않는다. `AEC_EMBEDDING_URL`은 비운다 (저장된 벡터와 오프라인 해시). `AEC_LLM_ALLOW_REMOTE=0`. 질의는 모델을 호출하지 않는다 |
| 송신 | 검색·질의 JSON만. CAD나 PDF 바이트를 돌려주는 경로는 더하지 않는다 |
| Drive | 이미 비용을 내고 있다. 원본의 두 번째 사본을 사지 않는다 |
| 터널 | 커넥터는 USD 0. 나중에 Access를 더하면 사용자 수가 무료 한도를 넘기 전에는 무료 등급에 둔다 |
| 로그 | 14일 뒤 폐기. 토큰, `.env`, 개인 경로 금지 (`docs/ops/CLOUD-OPS.ko.md`) |

중단은 "API를 0으로 내리고 토큰을 교체"이지 "볼륨을 삭제"가 아니다. 볼륨을 지우기 전에 복제본을 덤프한다.

`.github/workflows/`에는 아직 배포 워크플로가 없다. 실제 계정, 고정된 이미지 다이제스트, 스테이징 확인, 수동 프로덕션 승인이 생기기 전에는 `docs/ops/CLOUD-OPS.ko.md`의 그 보류를 유지한다. 이번 단계는 운영자가 손으로 실행하는 파일이다.

### 7. 이번 변경이 더하는 것

| 파일 | 역할 |
| --- | --- |
| `packages/aec/deploy/mobile-readonly/compose.yml` | API만. 프로젝트 `aec-mobile-readonly`, 컨테이너 `aec-api-readonly`, `AEC_API_READ_ONLY=1`, 루프백 포트 58010, 볼륨 없음, 읽기 전용 루트 파일시스템 |
| `packages/aec/deploy/mobile-readonly/postgres-copy.yml` | 선택적 복제 데이터베이스. 컨테이너 `aec-db-copy`, 볼륨 `aec-mobile-pgdata`, 루프백 포트 55433. API 파일이 띄우지 않음 |
| `packages/aec/deploy/mobile-readonly/reader-role.sql` | `aec_reader` 권한. 파일에 비밀번호 없음 |
| `packages/aec/deploy/mobile-readonly/env.example` | 비밀은 비어 있음. 그 디렉터리의 `.env`로 복사 (gitignore) |
| `packages/aec/src/aec_intelligence/operational/readonly.py` | 기동 검사, 쓰기에 405, 진입점 `python -m aec_intelligence.operational.readonly` |

`AEC_API_READ_ONLY`가 없으면 PC 프로세스는 그대로다. 헬스 JSON, 쓰기 경로, 데이터베이스 세션, 활동 도장이 같다. PC compose 파일은 이 변수를 넣지 않는다. 예약 작업 스크립트도 넣지 않는다.

```bash
# 항상 켜 둔 호스트, 저장소 루트, .env를 채운 뒤
docker compose -f packages/aec/deploy/mobile-readonly/postgres-copy.yml up -d
# 복원 후 reader-role.sql, 이어서:
docker compose -f packages/aec/deploy/mobile-readonly/compose.yml up -d --build
curl -fsS http://127.0.0.1:58010/healthz
```

API 이미지의 빌드 맥락은 계속 저장소 루트와 `packages/aec/docker/Dockerfile.app`이다. PC 이미지 명령은 계속 `uvicorn`이다. 모바일 compose만 그 명령을 덮어쓴다.

### 8. 이번 변경에 없는 것

- `packages/aec/docker-compose.yml`, `scripts/ops/*.ps1`, 예약 작업을 고치지 않는다.
- 실시간 이전, PC 볼륨 연결, 새 호스트의 `G:` 마운트는 없다.
- 공개 Postgres, OIDC, 검토 승인, ChatGPT OAuth 종단 간 시험은 없다.
- CI가 통과했다고 휴대폰 로그인이 된다는 뜻은 아니다. 터널과 실제 덤프 복원은 이 저장소 밖에서 운영자가 한다.
