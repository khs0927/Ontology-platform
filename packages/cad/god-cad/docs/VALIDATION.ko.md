# 검증 범위와 재현 방법

## 현재 확인하는 것

테스트는 합성 DXF를 임시 디렉터리에 만들어 실행한다. 실제 고객 도면이나 ZWCAD 설치에 의존하지 않는다.

| 영역 | 확인 내용 |
| --- | --- |
| Source | 파일 checksum, 반복 분석의 재현성, 다른 도면 ID 간 충돌 방지, 수정 revision 구분 |
| Geometry | 지원 단위 환산, 비기본 OCS·bulge·width·Z·INSERT의 미지원 기록 |
| Semantic | 후보 상태, 미보정 점수, RDF에서 벽으로 성급히 확정하지 않음 |
| Patch | 오래된 revision, 다른 drawing ID, 없는 대상, 비유한 수, 3D 이동, 잠긴 레이어 거부 |
| Dependency | 끝점 영향 대상 누락 거부, 입력 edge를 삭제해도 기하 재계산, 순환이 있는 영향 탐색 종료 |
| Preservation | 원본 DXF와 메모리 입력 불변, CLI 출력 덮어쓰기 거부 |
| Interchange | JSON Schema와 코드 일치, 참조 무결성 검사, Turtle 문법 |
| Preview | 실제 도형 경로가 있는 SVG 생성 |

```powershell
python -m ruff check .
python -m ruff format --check .
python -m pytest -q
python scripts/export_schemas.py --check
python scripts/demo.py --out artifacts/validation-run
```

의존성은 `requirements-dev.lock`에 검증 환경의 버전으로 고정한다. Python package 설치 후 위 명령을 실행한다. GitHub Actions는 Windows/Linux × Python 3.11/3.12로 설정한다. 실행 결과는 저장소 Actions에서 확인한다.

초기 작성 시 로컬 Windows / Python 3.12.3에서 **27 tests passed**, Ruff 검사·포맷 검사, 스키마 일치 검사, 의존성 검사와 합성 데모 실행을 확인했다. 데모는 6개 최상위 객체를 기록하고, 고립된 원의 이동은 `simulation_passed`, 연결된 선 하나만의 이동은 `rejected`를 반환했다. 데모 입력 DXF의 checksum은 유지됐다. 실제 ZWCAD 통합은 실행하지 않았다.

## 현재 확인하지 않는 것

실제 DWG 파싱·저장·ZWCAD 로드, native↔DXF handle 매핑, 모든 layout/block/Xref의 데이터 보존, 방 영역의 정확도, 충돌, 치수/해치 연동, 독립 렌더 비교, 사용자 의도·설계의 적합성은 현재 테스트 범위 밖이다.

`simulation_passed`는 제한된 산술·대상·알려진 영향 검사를 통과했다는 뜻이다. `verified` 또는 저장 가능 상태로 번역하면 안 된다. `native_write_eligible`은 JSON Schema에서도 `false` 상수다.

## Native 완료 판정의 필수 검사

후속 validator는 각 검사를 `pass / fail / not_run / unsupported`로 기록한다. 미실행·미지원 필수 검사가 하나라도 있으면 전체 verified를 금지한다.

1. source identity, live document revision, 단위·좌표계 일치.
2. 요청한 대상·변경량·대상 외 객체 보존 및 새/삭제 객체 manifest.
3. 객체별 위상·기하 제약, dimension reference, hatch boundary, host relation.
4. 임시 출력 저장 후 실제 ZWCAD 재열기·audit 및 재추출.
5. 원본 기준과 같은 카메라·viewport·레이어·폰트·plot style의 렌더 비교.
6. 성공/실패 모두 journal과 원본 파일의 유지 확인.

Structural/visual 검증은 독립 채널의 불일치를 찾는 보완책이다. 두 채널의 성공만으로 의미 인식이 참임을 자동 증명하지 않는다.
