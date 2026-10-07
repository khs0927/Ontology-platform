# GOD-CAD

**원본 CAD 객체에 연결된 의미·기하·편집 의존성을 바탕으로 도면을 이해하고, 변경 결과를 검증하는 CAD 엔진.**

현재 버전은 **v0.1.0 개발 뼈대**입니다. DXF 분석, 의미 후보 생성, 구조화된 수정 계획의 메모리 시뮬레이션, SVG 미리보기가 실행됩니다. 실제 DWG 읽기·쓰기, 완성된 건축 객체 인식, ZWCAD 플러그인, 자연어 에이전트는 다음 단계입니다.

- [최종 결론과 제품 방향](docs/FINAL_CONCLUSION.ko.md)
- [아키텍처와 데이터 계약](docs/ARCHITECTURE.ko.md)
- [개발 순서와 완료 조건](docs/ROADMAP.ko.md)
- [다른 에이전트에게 줄 실행 가이드](docs/AGENT_GUIDE.ko.md)
- [복사해서 사용하는 에이전트 명령](docs/agents/PROMPTS.ko.md)
- [검증 범위](docs/VALIDATION.ko.md) · [공식 출처와 검토 기록](docs/REFERENCES.ko.md)

## 빠른 실행

Python 3.11 또는 3.12 환경에서:

```powershell
git clone https://github.com/khs0927/GOD-CAD.git
cd GOD-CAD
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.lock
python -m pip install --no-deps -e .
python scripts/demo.py
python -m pytest -q
```

macOS/Linux에서는 활성화 명령만 `source .venv/bin/activate`로 바꿉니다. 비공개 저장소 접근에는 GitHub 인증이 필요합니다. 데모를 다시 실행하려면 새 출력 폴더를 지정합니다: `python scripts/demo.py --out artifacts/demo-2`.

데모는 합성 DXF를 만들고 다음 파일을 `artifacts/demo/`에 생성합니다.

| 파일 | 의미 |
| --- | --- |
| `synthetic.dxf` | 합성 입력 도면. 실제 고객 데이터 없음 |
| `drawing.json` | 원본 참조, 기하, 의미 후보, 관계, 누락 경고 |
| `preview.svg` | ezdxf 렌더러의 미리보기 |
| `move-column.patch.json` / `.report.json` | 고립된 원의 이동 시뮬레이션 통과 사례 |
| `move-one-wall-rejected.patch.json` / `.report.json` | 연결된 선을 누락한 이동 계획의 거부 사례 |

`move-column`은 예제 이름입니다. 실제 기둥의 인식·구조적 이동 검증이 아닙니다. 모든 보고서의 `native_write_eligible`은 `false`입니다.

## 자신의 DXF 분석

```powershell
god-cad ingest floor.dxf --drawing-id project-a-floor-01 --out artifacts/floor.json
god-cad render floor.dxf --out artifacts/floor.svg
god-cad plan artifacts/floor.json path/to/patch.json --out artifacts/plan.json
```

단위 헤더가 없으면 실제 입력 단위를 확인한 후 `--units mm` 등으로 지정합니다. 같은 논리 도면의 재분석에는 동일한 `--drawing-id`를 사용합니다. 모든 출력 명령은 기존 파일 덮어쓰기를 거부합니다. `plan` 거부 및 잘못된 입력의 종료 코드는 `2`입니다.

## 현재 구현

| 영역 | v0.1.0 |
| --- | --- |
| DXF | 최상위 Model 공간 객체 목록; LINE, 직선/무폭 LWPOLYLINE, CIRCLE, ARC의 제한된 2D 기하 |
| 식별자 | 논리 도면 ID + layout + handle; 파일 SHA-256 버전을 별도 유지 |
| 단위 | mm, cm, m, in, ft → WCS mm; 모르는 단위는 거부 |
| 의미 | WAL1/2/3, COL, DOOR, WIN 레이어를 근거로 미확정 후보 생성 |
| 위상 | 선/열린 직선 폴리라인의 끝점 접촉 관계 |
| 수정 계획 | `TRANSLATE_ENTITIES` 시뮬레이션; 버전·대상·잠긴 레이어·영향 대상 누락 검사 |
| 렌더 | DXF SVG 미리보기. 독립 교차검증은 미구현 |
| 온톨로지 | 작은 CAD 확장 TTL, 후보 예제, BEO URI 매핑. 추론기는 미구현 |
| Native CAD | Python 인터페이스와 명시적 미구현 오류. ZRX.NET 설계 가이드 |

## 구조

```text
src/god_cad/
  models.py            # 버전이 있는 Canonical Model / Patch / Report
  adapters/dxf.py      # 읽기 전용 DXF 어댑터
  adapters/native.py   # 향후 Native executor 경계
  topology.py          # 끝점 접촉 관계
  semantics.py         # 증거가 붙은 의미 후보
  planner.py           # 영향 범위 + 순수 시뮬레이션
  render.py            # SVG 미리보기
  cli.py               # ingest / plan / render / schema
schemas/               # 생성된 JSON Schema
ontology/              # CAD 확장 어휘와 예제
adapters/zwcad/        # ZRX.NET 연결 계약 및 환경 확인 지침
scripts/               # 합성 데모와 스키마 생성
tests/                 # 데이터 보존 및 거부 조건 테스트
docs/                  # 결정, 설계, 단계별 작업 지시
```

초기 저장소는 비공개입니다. 프로젝트 코드의 배포 라이선스는 소유자가 결정하기 전까지 지정하지 않습니다. 외부 SDK·폰트·도면·학습 데이터의 사용 조건은 각 자산에서 별도로 확인합니다.
