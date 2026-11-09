# Cloud work completion, 2026-11-05

This file is identical on PR #100 and PR #101, so merging both does not conflict.

## Local Windows run (2026-11-05)

Host: Windows 10, Python 3.12.10, fresh clone. `SION_*` environment variables were unset for the final runs.

### PR #100 (GraphRAG rejected relations)

| Command | Result |
|---|---|
| `uv lock --check`, `uv sync --locked --extra all --extra dev` | passed |
| `ruff check .` | passed |
| `python scripts/check_public_privacy.py` | 0 findings |
| `pytest` (root, final) | 853 passed, 7 skipped |

The first run failed one test. `test_config_requires_embedding_model` read `SION_GRAPHRAG_STORAGE=local` from the workstation environment, so the test now clears that variable. It passes with the variable set and unset.

Open: after merging, re-project once into a fresh `SION_GRAPHRAG_WORKSPACE` so previously projected rejected rows are gone.

### PR #101 (regulation review W05–W13)

| Command | Result |
|---|---|
| `pytest` (root, all extras) | 923 passed, 7 skipped |
| `pytest` (root, core install as in the "SQLite and API tests" job) | 605 passed, 34 skipped |
| `pytest` in `packages/regulation` | 270 passed, 39 skipped (PostgreSQL integration tests need `ARCHONTOS_TEST_DATABASE_URL`; CI runs them) |
| `ruff check .` at the root and in the package, `ruff format --check .`, `mypy` in the package | passed |
| `python scripts/check_public_privacy.py` | 0 findings |
| `/regulation` in a browser against a local server with SQLite | scope plan, run, briefing and save worked, no console errors |

Scenarios S01–S32 are synthetic processing tests. They are not legal answers and the release metrics were not measured.

Open, with details in `docs/regulation/IMPLEMENTATION-STATUS.md`:

- The `aec-mcp-router` adapter is not done. Its source is not on this PC or in the GitHub account, so the MCP tools are documented as REST mappings only.
- No real provider executors, official data or reviewed rules are connected. Without a bundle every checklist row stays unresolved.
- W02, W03 and W14 need decisions and reviewed data from people. D01–D10 are not closed.
- The LightRAG index has not been tested with the scoped projection.
- The new REST routes were not run on PostgreSQL locally.

## Round 2 (2026-11-07)

통합 1단계: Ontology-platform이 제품이 되고 Ontology는 수집·어댑터 패키지가 됩니다. 계획은 [CONSOLIDATION_PLAN.md](CONSOLIDATION_PLAN.md)에 있습니다.

- 새 계약 `aec-cair-snapshot/1`을 추가했습니다(`sion_core.contracts`, khs0927/Ontology @ `d81598f`에 고정). 업스트림 CAIR 픽스처 2개(DXF, IFC)를 함께 넣었습니다.
- 얇은 어댑터 `sion_cair.ingest`를 추가했습니다. Ontology CLI(`ingest-dxf`, `ingest-file`)를 서브프로세스로 실행하고, 결과를 Sion 그래프로 옮깁니다(Artifact 1개, Concept, `EXTRACTED_FROM`, `PART_OF`, `RELATED_TO`). 관계마다 증거 행을 붙이며 모두 `unverified`입니다. Ontology는 세 가지로 실행할 수 있습니다: 번들(`packages/aec`), 로컬 체크아웃(`ontology_root`), 고정 버전 venv(`python`).
- `[aec]` extra(`cad` + `bim`)를 추가했습니다. `uv.lock`은 해당 줄만 직접 고쳤고 `uv lock --check`를 통과합니다.
- 테스트 `tests/test_aec_cair_ingest_contract.py`를 추가했습니다. 업스트림 픽스처 검증, 그래프·증거 매핑, 멱등성, 거부 규칙을 확인합니다. 번들 DXF/IFC 실구동 결과의 객체 id가 업스트림과 같습니다.
- 코드는 삭제하지 않았습니다. 열린 PR은 닫지 않았고, 각 PR의 영향은 계획 문서 §6에 정리했습니다.

## Round 3 (2026-11-09)

통합 2단계(드리프트 해소): Ontology `master`에서 가져오기 이후 바뀐 내용을 `packages/aec`로 이식했습니다. 자세한 목록은 [AEC_CATCHUP_2026-11-09.md](AEC_CATCHUP_2026-11-09.md), 남은 의도적 차이는 [`packages/aec/UPSTREAM.md`](../packages/aec/UPSTREAM.md)에 있습니다.

- 가져오기 기준 `d39a56a`부터 **`8938175`(#104)까지 동기화**했습니다. 이식한 PR: #97, #98, #95, #99, #100(나머지 문서·테스트), #102(#101 포함), #103, #104. #94와 #96은 이미 이식되어 있었습니다.
- 이식하지 않은 것: `.github/workflows`(모노레포에서는 `aec.yml`만 실행됨)와 Ontology 저장소 메타 문서 3개.
- 충돌은 플랫폼 쪽을 우선해 해결했습니다. 예외: netguard는 더 새롭고 엄격한 업스트림 #99(DNS를 신뢰하지 않음)를 택했습니다. LAN 호스트는 `AEC_LOCAL_HOSTNAMES`로 허용합니다.
- 추가 수정: `restore_db.sh` 기본 원격 경로를 `backup_db.sh`와 같게(`gdrive:AEC-INTELLIGENCE/backups`) 맞췄습니다.
- `aec-cair-snapshot/1` 출력은 바뀌지 않았습니다(객체 id·필드가 픽스처와 같고 타임스탬프만 다름). 픽스처와 `upstream_commit`은 그대로입니다.
- 검증(Python 3.13): 루트 `pytest` 1971 passed / 59 skipped, `packages/aec/tests` 908 passed / 53 skipped, 확장 테스트 13+135+116 passed, `ruff` 통과. PostgreSQL 테스트와 E2E 스모크는 이 컨테이너에서 실행하지 못했습니다(디스크 공간 부족).
