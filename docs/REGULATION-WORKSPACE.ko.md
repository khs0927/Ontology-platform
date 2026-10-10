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

## 판단 범위

`canonical:false`와 `unverified`는 저장 후에도 유지한다. 작업을 완료 처리해도 법적 적합성이 확인되는 것은 아니다. 플랫폼은 게이트웨이의 서버 소유 audit run만 가져오며 임의 보고서 업로드를 받지 않는다. 스키마 검사는 형식 검증이며 원문 진위나 법규 적용성을 증명하지 않는다. 검토된 규칙이 없는 경우, 조례·지구단위계획·공간 범위·시점 근거가 부족한 경우에는 판정이 보류된다.
