# Hindsight advisory memory for Sion

검토 기준: Hindsight `v0.10.2`.

이 통합은 **Sion/CAIR의 사실 저장소를 대체하지 않는다.**
Hindsight는 장기 agent memory를 위한 선택적 sidecar이며 모든 recall/reflect 결과는
`canonical=false`, `advisory=true`로 취급한다.

## 기본 원칙

- 기본 비활성화.
- 기존 agent bridge의 canonical DB/Drive export와 독립.
- 원본 transcript 전체를 자동 retain하지 않는다.
- 기본 retain 대상은 reader가 명시적으로 추출한 `AgentSession.decisions`만이다.
- session title, raw transcript, `source_uri`, full `cwd`, device path, tool log는 memory content에 넣지 않는다.
- credential/secret 형태가 감지된 decision은 retain 후보에서 제외한다.
- project별 bank를 SHA-256 기반 opaque ID로 분리한다.
- Hindsight 장애가 Sion canonical ingest를 막지 않는다.
- `reflect`는 기본 비활성화.
- recall/reflect 결과를 자동으로 Sion entity/relation으로 승격하지 않는다.

## 설치

기본 Sion 설치에는 Hindsight client를 강제로 추가하지 않는다.

```bash
pip install hindsight-client==0.10.2
```

Hindsight 서버는 별도 프로세스/컨테이너로 운영한다. 이 저장소는 서버를 자동으로
다운로드하거나 시작하지 않는다.

## 환경 변수

```text
SION_HINDSIGHT_ENABLED=0
SION_HINDSIGHT_URL=http://127.0.0.1:8888
SION_HINDSIGHT_API_KEY=<configure-outside-source>
SION_HINDSIGHT_BANK_PREFIX=sion-project
SION_HINDSIGHT_TIMEOUT=20
SION_HINDSIGHT_REFLECT_ENABLED=0
```

loopback이 아닌 Hindsight URL은 HTTPS + API key가 모두 필요하다.
URL 안에 credential을 넣는 것은 거부한다.

가능하면 Hindsight 서버에서도 raw document text 저장을 비활성화한다.

```text
HINDSIGHT_API_STORE_DOCUMENT_TEXT=false
```

## 사용

네트워크 호출 없이 후보만 확인:

```bash
python scripts/run_hindsight_memory.py --provider all --limit 20 --dry-run
```

명시적으로 durable decision retain:

```bash
SION_HINDSIGHT_ENABLED=1 \
python scripts/run_hindsight_memory.py --provider all --limit 20 --retain
```

프로젝트 memory recall:

```bash
SION_HINDSIGHT_ENABLED=1 \
python scripts/run_hindsight_memory.py \
  --project ontology-platform \
  --recall "What did we decide about canonical provenance?"
```

reflect는 환경변수로 따로 opt-in해야 한다.

```bash
SION_HINDSIGHT_ENABLED=1 \
SION_HINDSIGHT_REFLECT_ENABLED=1 \
python scripts/run_hindsight_memory.py \
  --project ontology-platform \
  --reflect "What recurring architectural risks have we seen?"
```

## 데이터 경계

```text
Antigravity / Codex / Claude
          ↓
existing AgentSession readers
          ↓
explicit decisions only
          ↓
secret filter
          ↓
opaque per-project bank
          ↓
Hindsight retain
          ↓
recall / optional reflect
          ↓
ADVISORY CONTEXT ONLY

Sion canonical DB ──────────────── unchanged
CAIR / evidence / provenance ──── unchanged
```

Hindsight memory가 유용해도 법규, 허가 판단, CAD 수정 대상, canonical relation의
근거로 자동 승격해서는 안 된다. 필요한 사실은 원본 evidence/provenance 경로에서
독립적으로 재확인해야 한다.
