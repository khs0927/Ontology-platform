# 온톨로지 API 읽기 전용 점검

실행 예: `python scripts/audit_ontology_readonly.py --base-url https://<승인된-staging-host>`

인증이 있는 API는 `SION_AUDIT_BEARER_TOKEN` 환경변수에 **읽기 전용** 토큰을 넣고 실행합니다. 셸 이력에 토큰을 직접 적지 않습니다. 원격 HTTP는 거부하고 로컬 루프백 HTTP만 허용합니다. Redirect는 따라가지 않습니다.

- GET 요청만 합니다: `/health`, `/health/ready`, `/api/v1/graphrag/status`, `/api/v1/storage/status`, `/api/v1/aec/status`.
- `configured=true`는 실제 지식그래프 검색 성공을 증명하지 않습니다. 출력의 `end_to_end_verified`는 항상 `false`입니다.
- `configuration_preflight_passed`는 API 응답, DB 준비, GraphRAG 설정 세 가지만 판정합니다. OAuth, MCP, CAD, Drive 전수 인덱스, 법규 판단을 검증하지 않습니다.
- 임베딩·LLM 모델 이름, 경로, 상세 오류, 토큰과 실제 데이터는 출력하지 않습니다. 모델 호출, 인덱싱, 관계 승인, 파일 쓰기, 배포도 하지 않습니다.
- 인증 토큰이 없으면 보호된 엔드포인트를 `skipped_no_token`으로 표시합니다.
- 서버에 readiness 경로가 없다면 `not_implemented`로 표시하며 완료 판정을 하지 않습니다.
- 종료 코드 0은 **설정 사전 점검만** 통과, 1은 미통과, 2는 잘못된 입력입니다.

테스트(네트워크 없음): `pytest -q tests/test_ontology_readonly_audit.py`

> 후속: 승인된 스테이징 엔드포인트와 읽기 전용 계정이 준비되면 실제 API에 적용하고, 별도의 실제 GraphRAG 검색·MCP OAuth·iPhone 수동 E2E와 원본 DWG census를 진행해야 합니다. 합성 테스트만으로 완료 처리하지 않습니다.
