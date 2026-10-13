# 도면 온톨로지 에이전트 메모리

짧은 사실 메모. 항목마다 날짜와 근거를 적고, 낡은 항목은 지우지 말고 `(대체됨: 날짜)`로 표시합니다.
`packages/aec/global/09_AGENT_MEMORY/`는 CAIR에서 재생성되는 파생물(jsonl/parquet)이므로 사람이 쓰는 메모는 이 파일에 둡니다.
상세 지침: [`docs/guidelines/DRAWING-ANALYSIS.ko.md`](../guidelines/DRAWING-ANALYSIS.ko.md).

- 2026-10-09: 큐 QUEUED 21,726 / SUCCEEDED 691 / FAILED 0, documents 674. 적재는 끝나지 않음. 숫자는 쓰기 직전 재조회.
- 2026-10-09: 큐 작업의 약 85%가 `G:\내 드라이브` 원본. `G:`는 해제돼 있다가 사용자가 다시 마운트함. 해제 중 FileNotFoundError는 "접근 불가"이지 "파일 없음"이 아님.
- 2026-10-09: 적재 게이트 = 가용 RAM >= 2048MB, workers=1. 게이트 충족 전 증설 금지.
- 2026-10-09: rclone gdrive 토큰 만료. 재연결은 계정 소유자만 가능.
- 2026-10-05: 덤프 SHA256 `7c0228ab7e965f94a6720f1dfd52221c1d473d08b52189c2906abdc23f7b581b`만 RECOVERY_VERIFIED(888 테이블 / 3,968,576 행 / 1,357 인덱스 일치).
- 2026-10-08: 덤프 2건(1.65GB)은 미검증. BACKUP_VERIFIED와 RECOVERY_VERIFIED를 섞어 쓰지 않음.
- 2026-10-08: PR #51 파일명 중립 20건 평가에서 도면번호 0/14 -> 12/14. 존재 적중이며 정밀도 아님, gold는 에이전트 검토. 리뷰의 분류 순서 수정 뒤 재평가는 미실시.
- 2026-10-08: 표제란 텍스트 번호 채택 규칙 = 라벨 근접 +4 / 시트 레이어 +2 / 대시 +1, 합계 3 이상, 후보 4개 초과면 번호 없음. 상세 참조 버블(A-501) 오채택 위험 잔존.
- 2026-10-05: 과거 "샘플 정확도 98.9%"는 pr1 94/95에서만 재현, master 80/95(84.21%), 60셀은 독립 키 없음. 정확도로 인용 금지.
- 2026-10-05: "546건 적재"는 KG Drawing 노드 수였음. jobs / documents / KG 노드는 서로 다른 분모.
- 2026-10-05: 처리율 약 13건/h(6시간 평균). "27건/h"는 철회.
- 2026-10-08: Sion `/api/v1/aec/query`는 `canonical:false, read_only:true`. 정본 상태는 열린 CAD에서 `cad_*`로 재확인. 네이티브 호스트 검증은 UNVERIFIED_NATIVE.
