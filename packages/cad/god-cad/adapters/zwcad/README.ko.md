# ZWCAD native adapter: 구현 준비 계약

상태: **미구현**. 현재 Python `UnavailableNativeExecutor`는 항상 명시적 오류를 낸다. SDK DLL, 빌드 가능한 ZRX.NET 프로젝트, CAD 명령 등록은 아직 없다. SDK 환경 없이 동작하는 것처럼 보이는 플러그인을 만들지 않는다.

호스트 연동 담당자가 먼저 아래 정보를 `docs/environment/zwcad.md`에 기록한다.

- 설치된 ZWCAD의 정확한 연도·빌드·에디션·아키텍처
- 해당 버전 공식 ZRX.NET SDK, 타깃 .NET 런타임과 개발 SDK
- 참조 DLL의 이름·경로·버전, 공식 예제의 빌드/로드 명령
- 테스트용 빈 DWG와 합성 도면, 로드·명령·저장·재열기 결과

공식 진입점: [ZWCAD 개발 지원](https://www.zwsoft.com/support/zwcad-devdoc). 빌드 대상이나 namespace를 AutoCAD 또는 다른 ZWCAD 버전에서 추정하지 않는다. SDK·DLL은 저장소에 커밋하지 않는다.

## 후속 인터페이스

| 단계 | 입력 | 출력과 필수 검사 |
| --- | --- | --- |
| capabilities | 호스트 | 제품/SDK 버전, 지원 객체/연산, 제한 |
| extract | 열린 테스트 DWG | 원본 참조, native geometry, layer/block/xref/metadata inventory, 누락 |
| export-analysis | 동일 revision | DXF와 native→DXF mapping 증거, 렌더 설정 |
| validate-plan | 실제 호스트 상태 + patch | drawing/revision/handle/context 일치, 잠금과 precondition |
| execute-copy | 검증된 실행 요청 | 원본과 다른 출력 파일, 변경 manifest, 전후 revision |
| verify-reopen | 출력 DWG | 재열기·재추출·검증 보고서; 실패/미실행을 pass로 만들지 않음 |

이 표는 향후 작업 계약이다. 현재 `Patch`에 production 실행 승인이나 거래 상태 필드를 임의로 추가하지 말고 스키마 버전 변경을 설계한다.

## 실행 상태 기계

`prepared → host-validated → executing-copy → saved-copy → reopened → verified`

각 단계에서 실패하면 `rejected`/`failed`로 종료한다. 원본은 그대로 둔다. 예외를 삼키고 성공 응답을 반환하지 않는다. 저장 후 검증 실패는 이미 커밋한 CAD transaction을 되돌렸다고 표현하지 않는다. 별도 출력물을 격리하고 원본을 유지한 상태로 실패를 보고한다.

실제 사용에서는 사용자가 허용한 작업 범위와 구체적 Patch를 연결한다. 이미 허용된 범위 내 동일한 작업에 반복 확인을 강제하지 않는다. 새로운 대상·연산·외부 전송 또는 범위를 벗어나는 변경이 필요할 때만 별도 판단을 요청한다.

## 필수 구현 조건

호스트 문서 잠금, transaction, 실행 직전 revision 재검사, idempotency key, 실행 journal, 원본/출력 경로 분리, 원본 백업, output collision 방지, save/reopen 검증을 구현한다. fingerprint가 있는 살아 있는 CAD DB 상태와 파일 checksum 사이의 차이를 명시적으로 처리한다.

기존 DWG를 DXF로 변환해 수정한 뒤 통째로 덮어쓰는 경로를 기본 writer로 사용하지 않는다. ACadSharp 등 별도 파서는 독립 추출의 후보이며 실제 도면 corpus로 검증한 뒤 채택한다.
