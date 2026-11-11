# 프로젝트 법규 검토와 MCP 연결

온톨로지 플랫폼의 `/regulation`에서 프로젝트를 선택하고 법규 조회 결과를 저장한다. 저장한 검토에는 원본 보고서, 근거의 출처·발췌·해시·시행일, 작업 메모, 후속 과제가 함께 남는다. 브리핑은 저장된 근거를 정리한 Markdown이다. 생성형 모델이 법률 해석을 새로 만들어 내지 않는다.

검토 결과는 Document 엔티티와 Evidence, 프로젝트 PART_OF 관계로 한 트랜잭션에 저장된다. 기존 outbox와 설정된 DriveExporter가 변경을 전달한다. 별도 작업 DB나 라이브 DB의 Drive 동기화는 추가하지 않는다. 원문 스냅샷은 게이트웨이에 보관되므로 게이트웨이 저장소도 별도로 백업해야 한다.

## 실행 설정

플랫폼 프로세스에 `SION_REGULATION_GATEWAY_URL`(예: `http://127.0.0.1:8019`)과 `GATEWAY_TOKEN`을 주입한다. 공공 API 키는 게이트웨이 프로세스에만 Doppler로 주입한다. 토큰은 파일이나 Git에 기록하지 않는다. 플랫폼은 기존 `SION_DATABASE_URL`, 인증 및 Drive 내보내기 설정을 사용한다.

플랫폼과 게이트웨이는 독립 서비스다. 플랫폼 Python 환경에 게이트웨이 패키지를 복사하거나 MCP 의존성을 강제로 합치지 않는다. 기준 생산자 커밋은 `21e146574c2ba173ed436c685b376f5cefa813b0`이며, 보고서 계약과 테스트를 함께 갱신했다.

## 기존 AEC MCP 라우터

이 플랫폼과 별도로 관리되는 `aec-mcp-router`에 [어댑터 패치](../integrations/aec-mcp-router/workspace.patch)를 적용한다. 패치는 HTTP 어댑터와 테스트만 변경한다. 기존 CAD/Revit/Jev 흐름은 유지한다. 설치 경로에서 `git apply --check` 후 `git apply`하고 라우터를 재시작한다.

라우터의 `downstream`에 다음 설정을 추가한다. `base_url`은 실제 플랫폼 주소로 바꾼다.

```json
{
  "regulation_work": {
    "type": "ontology-http",
    "base_url": "http://127.0.0.1:8020",
    "token_env": "SION_API_TOKEN",
    "timeout_s": 65
  }
}
```

도구는 `regulation_work.produce_compliance_report`, `list_regulation_works`, `get_regulation_work`, `get_regulation_briefing`, `save_regulation_work`, `update_regulation_work`다. 저장에는 플랫폼 Project UUID와 게이트웨이 run UUID가 필요하다. 조회에 원격 인증을 쓸 때는 read:knowledge, 저장/수정에는 write:knowledge 권한이 필요하다.

저장과 수정은 쓰기 도구다. Jev 게이트를 통과해 기본 `dry_run:true`로 미리보기한 뒤 같은 인자로 `dry_run:false`를 호출한다. 미리보기는 프로젝트·근거·outbox에 쓰지 않는다. 동일 프로젝트와 run 재저장은 중복 생성하지 않는다. 기존 `regulation` 네임스페이스는 직접 게이트웨이의 7개 핵심 도구 및 health/audit를 제공한다.

## 모바일용 프로젝트 요약 (읽기 전용)

`GET /api/v1/regulation/summary`는 저장된 검토를 프로젝트별로 요약한다. 보고서 본문, 메모, 후속 과제는 내려주지 않고 `project_id`, `project_name`, `work_count`, `status_counts`, 최신 검토의 `id`·`title`·`status`·`decision_status`·`as_of`·`updated_at`만 반환한다. 응답은 `read_only:true`, `canonical:false`이며 쓰기는 하지 않는다.

- 권한: `read:knowledge`가 필요하다. 토큰 스코프에 `project:<uuid>`가 있으면 그 프로젝트로만 제한되며, 허용되지 않은 `project_id`를 요청하면 DB를 읽기 전에 403을 반환한다. 단, 이 프로젝트 제한은 요약 경로에만 적용되며 아직 격리 경계가 아니다. 같은 토큰에 `read:knowledge`가 있으면 `GET /api/v1/regulation/works` 등 다른 읽기 경로로 모든 프로젝트의 보고서를 읽을 수 있으므로, 프로젝트로 한정해야 하는 상대에게 이런 토큰을 발급하지 않는다. 나머지 경로 적용은 후속 과제다.
- 필터: `project_id=<uuid>`를 최대 50개까지 반복 지정한다.
- 페이지: `limit` 기본 20, 최대 50. 응답의 `next_cursor`를 `cursor`로 넘기고 `null`이 될 때까지 반복한다.
- 크기 제한: 응답 본문은 `SION_SUMMARY_MAX_BYTES`(기본 65536, 최소 4096) 이하로 유지한다. 제한 때문에 잘린 페이지는 `truncated:true`와 이어받을 `next_cursor`를 준다. 항목 하나만으로 제한을 넘으면 `{"project_id": ..., "item_truncated": true}`로 대체한다.
- 호출 제한: 클라이언트(인증된 설정 토큰의 해시, 신뢰된 로컬 요청은 접속 주소)별 프로세스 내 슬라이딩 윈도로 제한한다. `SION_SUMMARY_RATE_LIMIT=<요청수>/<초>`(기본 `60/60`, `0`이면 끔)로 설정하며 초과 시 429와 `Retry-After`를 반환한다. 워커 간에는 공유되지 않는다.

## 판단 범위

`canonical:false`와 `unverified`는 저장 후에도 유지한다. 작업을 완료 처리해도 법적 적합성이 확인되는 것은 아니다. 플랫폼은 게이트웨이의 서버 소유 audit run만 가져오며 임의 보고서 업로드를 받지 않는다. 스키마 검사는 형식 검증이며 원문 진위나 법규 적용성을 증명하지 않는다. 검토된 규칙이 없는 경우, 조례·지구단위계획·공간 범위·시점 근거가 부족한 경우에는 판정이 보류된다.

## 중첩규제 검토 실행

`/regulation` 화면과 `/api/v1/regulation/reviews/*`는 필지·제안행위·기준일을 고정해 검토 범위와 미확인 항목을 만든다. 조회에는 read:knowledge, 제안·설명·실행·재개·취소·저장에는 write:knowledge가 필요하다. 쓰기 요청은 `dry_run`으로 미리 볼 수 있고 이 경로에는 Jev 단계가 없다. 다른 프로젝트의 실행은 없는 실행과 똑같이 404로 응답한다.

| 제안 도구 | REST |
|---|---|
| regulation.plan_review | `POST /api/v1/regulation/reviews/plan` |
| regulation.start_review | `POST /api/v1/regulation/reviews` |
| regulation.get_review | `GET /api/v1/regulation/reviews/{run_id}?project_id=` |
| regulation.resume_review | `POST /api/v1/regulation/reviews/{run_id}/resume` |
| regulation.get_basis | `GET /api/v1/regulation/reviews/basis/{evidence_id}?project_id=` |
| regulation.explain | `POST /api/v1/regulation/reviews/{run_id}/explain` |
| regulation.compare | `GET /api/v1/regulation/reviews/{run_id}/compare?project_id=&to=` |
| regulation.save_work | `POST /api/v1/regulation/reviews/{run_id}/works` |
| regulation.get_briefing | `GET /api/v1/regulation/reviews/works/{work_id}/briefing?project_id=` |

저장은 서버가 가진 실행 결과만 받는다. 응답의 `verified:true`는 저장한 행을 다시 읽어 digest를 대조했다는 뜻이다. 재개는 새 revision을 만들고 이전 결과를 바꾸지 않는다.

`aec-mcp-router` 어댑터는 아직 없다. 위 표는 어댑터가 호출할 경로이고, 라우터 쪽 구현과 시험은 그 저장소에서 해야 한다. 자세한 상태는 [구현 현황](regulation/IMPLEMENTATION-STATUS.md)에 있다.
