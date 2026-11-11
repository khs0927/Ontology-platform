# 클라우드 운영 준비 런북 (CLOUD-OPS)

근거: Issue #71 step H(코드 부분). 대상: `apps/api` (Sion Ontology API).
상태: **운영 준비(readiness) 문서 + 최소 코드**. 실제 클라우드 배포 대상, 계정, 시크릿은 이 저장소에
존재하지 않으며 이 문서도 만들지 않는다. 아래 배포 흐름은 템플릿이다.

관련 문서: `docs/STORAGE.md`, `docs/ops/DRIVE-LAYOUT.ko.md`, `apps/api/README.md`,
`docs/INTEGRATION_CONTRACTS.md`. PC의 `aec-db`/`aec-api`를 그 PC가 꺼져 있어도 휴대폰에서
읽기만 하게 두는 설계와 배포 파일은 `docs/ops/PC-INDEPENDENT-RUNTIME.md`에 있다. 이 런북의
배포 템플릿은 바꾸지 않는다.

---

## 1. 헬스 체크

| 엔드포인트 | 용도 | 인증 | DB 접근 | 실패 시 |
| --- | --- | --- | --- | --- |
| `GET /health/live` | 생존(liveness) 프로브. 프로세스가 요청을 처리하는지만 확인 | 없음 | 없음 | 응답 없음 → 오케스트레이터가 재시작 |
| `GET /health/ready` | 준비(readiness) 프로브. DB 연결을 읽기 전용 `SELECT 1` 로 확인 | 없음 | 읽기 전용, 트랜잭션 rollback | `503` + `{"status":"unavailable","checks":{"database":"unavailable"}}` → 트래픽에서 제외 |
| `GET /health` | 기존 호환용 요약(버전, DB dialect) | 없음 | 없음 | — |

원칙:

- 응답에는 상태 값, 버전, DB dialect 이름만 담는다. **DSN, 호스트, 사용자, 드라이버 오류 메시지는 절대
  출력하지 않는다.** 실패 원인은 서버 측 경고 로그(`sion_api.ops`)에도 원문 없이 한 줄만 남긴다.
- readiness 는 쓰기·마이그레이션·시드를 하지 않는다(`tests/test_ops_health.py` 가 SQLite 파일 바이트
  불변으로 검증).
- liveness 를 DB 에 묶지 않는다. DB 장애 때 전체 인스턴스가 재시작 루프에 빠지는 것을 막기 위함이다.
- 권장 프로브 설정(예): liveness 주기 10s / 실패 3회, readiness 주기 5s / 실패 2회, 초기 지연 10s.

수동 확인:

```bash
curl -fsS http://127.0.0.1:8000/health/live
curl -fsS http://127.0.0.1:8000/health/ready   # 503 이면 DB 연결부터 점검
```

## 2. 로그

### 2.1 구조화 접근 로그

- 로거 이름 `sion_api.access`, 요청 1건당 JSON 한 줄(INFO).
- 필드: `event`, `request_id`, `method`, `path`(쿼리 문자열 제외), `status`, `duration_ms`.
- **기록하지 않는 것**: 요청 헤더 전체(`Authorization`, `Cookie`, `Proxy-Authorization`, `X-API-Key` 포함),
  쿼리 문자열, 요청/응답 본문, 클라이언트 IP. 쿼리 문자열에는 이메일·주소 같은 PII 가 들어갈 수 있으므로
  경로만 남긴다.
- `X-Request-ID` 요청 헤더가 안전한 형식(`[A-Za-z0-9._-]{8,64}`)이면 그대로 쓰고, 아니면 새 ID 를 만든다.
  응답에는 항상 `X-Request-ID` 가 붙는다. 장애 문의 시 이 값으로 로그를 찾는다.
- 끄기: `SION_API_ACCESS_LOG=0`. 출력 대상·레벨은 uvicorn/호스트의 logging 설정으로 정한다
  (기본 Python 루트 로거는 WARNING 이라 INFO 접근 로그가 보이지 않을 수 있다).
- 보조 함수 `sion_api.ops.redact_headers()` 는 헤더를 디버그 출력해야 할 때 민감 값을 `[REDACTED]` 로 바꾼다.
  새 로그 코드가 헤더를 다룰 때는 반드시 이 함수를 거친다.

### 2.2 로그 보관과 금지 사항

- 보관 기간은 비용 상한(§4)에 맞춰 짧게(예: 14일) 잡고, 장기 보관이 필요하면 집계 지표만 남긴다.
- 로그·트레이스·에러 리포터에 시크릿, OAuth 토큰, Doppler 값, `.env` 내용, 개인 이메일, 개인 경로를
  남기지 않는다. 의심되는 로그가 발견되면 해당 로그 묶음을 폐기하고 토큰을 교체(rotate)한다.

## 3. 백업과 복구

정본 규칙(AGENTS.md): 런타임 DB 는 로컬/재생성 가능 자원이며, **라이브 PostgreSQL/SQLite WAL 파일을
복사하지 않고 덤프/스냅샷만 백업한다.**

| 작업 | 도구 | 비고 |
| --- | --- | --- |
| 스키마 적용 | `python -m sion_api.migrate --dsn ...` / `--status` | 파일별 체크섬 추적, 적용 후 변경된 파일은 오류 |
| PostgreSQL 마이그레이션 검증 | `scripts/verify-postgres.sh` | 임시 클러스터를 만들어 마이그레이션을 재생하고 정리 |
| pgvector 검증 | `scripts/verify-vector.sh` | pgvector 설치 환경에서 벡터 경로 확인 |
| 코드 스냅샷 | `scripts/snapshot-project.sh <out-dir>` | Git 인덱스 기준 tar.gz + manifest(sha256) |
| DB 스냅샷/그래프 내보내기 | `sion_api.drive_export` (`SION_DRIVE_EXPORT_ON_WRITE`, `SION_DRIVE_SNAPSHOT_KEEP`) | 쓰기 커밋 후 디바운스 스냅샷, 최신 N개 유지 |

클라우드 PostgreSQL 백업 절차(템플릿):

1. 매일 1회 `pg_dump --format=custom --no-owner` 로 덤프를 만들고 sha256 을 영수증에 기록한다.
2. 덤프는 접근 제한된 객체 저장소로 단방향 업로드한다. 삭제 동기화(mirror) 금지.
3. **복구 리허설**: 최소 월 1회 빈 스테이징 DB 에 `pg_restore` → `python -m sion_api.migrate --status` →
   `GET /health/ready` 200 → 표본 조회. 결과(성공/실패, 소요 시간, 덤프 sha256)를 남긴다.
   리허설이 없는 백업은 "BACKUP_VERIFIED, 복원 미검증" 으로 표기한다(DRIVE-LAYOUT 과 같은 용어).
4. 복구 시 운영 DB 를 덮어쓰기 전에 현재 상태를 먼저 덤프한다.

## 4. 비용 상한과 안전 장치

- 클라우드 계정에 **월 예산 + 50/80/100% 알림**을 먼저 설정한다. 예산 없는 계정에는 배포하지 않는다.
- 컴퓨트: 인스턴스 최소 0~1, 최대 2 로 시작(자동 확장 상한 명시). 요청 타임아웃과 동시성 제한을 둔다.
- DB: 가장 작은 관리형 등급으로 시작, 스토리지 자동 증가 상한 설정, 공개 IP 비활성화.
- LLM/임베딩/외부 API 호출은 키별 일일 한도를 공급자 콘솔에서 설정한다. 키는 시크릿 관리자에서만 주입한다.
- 로그 수집량 상한과 보관 기간(§2.2)을 설정한다. 접근 로그는 요청당 한 줄이므로 트래픽에 비례한다.
- 인증: 원격 배포는 `SION_API_AUTH_MODE=bearer` + `SION_API_TOKENS_JSON`(시크릿 관리자 주입)만 허용.
  `local-only` 기본값을 원격에서 쓰지 않는다. `SION_CORS_ORIGINS` 는 실제 프런트 출처만 나열한다.
- Sion 은 CAD 변경을 실행하지 않는다. 브리지 저장소 데이터는 증거/요청 범위 사실이며 정본 상태가 아니다.
- 긴급 차단: 트래픽을 0 으로 내리거나(최소 인스턴스 0, 진입점 비활성화) 토큰을 교체한다. 데이터 삭제로
  대응하지 않는다.

## 5. 배포 흐름: CI → 고정 아티팩트 → 스테이징 → 수동 승인 프로덕션

```
PR ──▶ CI(tests.yml, security.yml 등 green)
        │
        ▼
main 머지 ──▶ 아티팩트 빌드 (python -m build → wheel/sdist, 또는 컨테이너 이미지)
        │      · 커밋 SHA + 파일 sha256(또는 이미지 digest)로 고정, 태그 재사용 금지
        ▼
스테이징 배포 (같은 아티팩트) ──▶ migrate --status / /health/ready / 스모크 테스트
        │
        ▼
프로덕션 배포 (같은 아티팩트, GitHub Environment `production` 의 필수 승인자 수동 승인)
        │
        ▼
배포 후 확인: /health/live, /health/ready, 오류율, 접근 로그 request_id 표본
롤백: 이전 아티팩트 digest 로 재배포 (DB 마이그레이션은 전진 전용이므로 배포 전 덤프 필수)
```

규칙:

- 스테이징과 프로덕션은 **동일한 고정 아티팩트**를 쓴다. 프로덕션 단계에서 다시 빌드하지 않는다.
- 프로덕션 job 은 `environment: production` 을 사용하고, 저장소 설정에서 필수 승인자·브랜치 제한
  (`main` 만)·대기 타이머를 설정한다.
- 워크플로는 `workflow_dispatch` 수동 실행만 허용하고 `permissions` 는 최소(`contents: read`)로 둔다.
- 이 저장소에는 아직 배포 워크플로를 **추가하지 않는다**. 실제 배포 대상과 시크릿이 정해지면 아래 템플릿을
  `.github/workflows/` 로 옮기는 별도 PR 에서 검토한다.

### 5.1 워크플로 템플릿 (비활성, 문서 전용)

```yaml
# 템플릿: 실제 배포 대상/시크릿 없음. 채택 시 별도 PR 로 .github/workflows/deploy.yml 에 추가.
name: Deploy (manual)
on:
  workflow_dispatch:
    inputs:
      artifact_sha:
        description: "배포할 main 커밋 SHA (CI green 확인 후)"
        required: true
permissions:
  contents: read
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@<pinned-sha>
        with: { ref: "${{ inputs.artifact_sha }}" }
      - run: python -m pip install build && python -m build
      - run: cd dist && sha256sum * > SHA256SUMS  # 접두어 없이 기록해야 다운로드한 아티팩트에서 -c 검증 가능
      - uses: actions/upload-artifact@<pinned-sha>
        with: { name: sion-api-${{ inputs.artifact_sha }}, path: dist/ }
  staging:
    needs: build
    environment: staging
    runs-on: ubuntu-latest
    steps:
      - uses: actions/download-artifact@<pinned-sha>
        with: { name: sion-api-${{ inputs.artifact_sha }} }
      - run: sha256sum -c SHA256SUMS
      - run: echo "TODO: 스테이징 배포 명령 (대상 미정)"
      - run: echo "TODO: curl -fsS $STAGING_URL/health/ready"
  production:
    needs: staging
    environment: production   # 필수 승인자 설정 필수
    runs-on: ubuntu-latest
    steps:
      - uses: actions/download-artifact@<pinned-sha>
        with: { name: sion-api-${{ inputs.artifact_sha }} }
      - run: sha256sum -c SHA256SUMS
      - run: echo "TODO: 프로덕션 배포 명령 (대상 미정)"
```

## 6. 점검 체크리스트

- [ ] `/health/live` 200, `/health/ready` 200 (스테이징·프로덕션 모두)
- [ ] 접근 로그에 `Authorization`/쿼리 문자열이 없음을 표본으로 확인
- [ ] 월 예산과 알림 설정, 자동 확장 상한 설정
- [ ] 최근 30일 내 복구 리허설 기록 존재
- [ ] 프로덕션 Environment 필수 승인자 설정
- [ ] `python scripts/check_public_privacy.py` 통과 후 공개 커밋
