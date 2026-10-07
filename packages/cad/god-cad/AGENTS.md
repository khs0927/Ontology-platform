# GOD-CAD repository instructions

이 문서는 이 저장소에서 작업하는 모든 코딩 에이전트의 공통 지침이다. 현재 사용자의 명시적 지시가 우선한다.

## 시작

1. `README.md`, `docs/FINAL_CONCLUSION.ko.md`, `docs/ARCHITECTURE.ko.md`를 읽는다.
2. `docs/ROADMAP.ko.md`에서 배정된 작업 ID와 선행 조건을 확인한다.
3. `docs/AGENT_GUIDE.ko.md`와 배정 작업의 `docs/agents/PROMPTS.ko.md` 지시를 따른다.
4. `git status`를 확인하고 사용자 변경을 보존한다. 현재 작업에 필요한 범위만 수정한다.

## 구현 원칙

- 원본 도면을 덮어쓰지 않는다. 합성 fixture 또는 명시된 테스트 복사본에서 개발한다.
- 미지원·누락·모호함을 데이터와 보고서에 남긴다. 빈 결과나 성공으로 숨기지 않는다.
- drawing ID, revision, handle, layout, block/Xref 문맥을 분리한다. DWG/DXF handle 일치를 가정하지 않는다.
- 좌표계·단위·허용오차를 명시한다. 곡선이나 block transform을 근거 없이 단순화하지 않는다.
- 레이어명·LLM 응답은 증거이며 확정 의미가 아니다. 후보와 확정 상태를 구분한다.
- 알려진 영향 대상이 없다는 것과 영향 분석이 완료됐다는 것을 구분한다.
- 현재 `simulation_passed`를 native 실행 허가나 verified로 바꾸지 않는다.
- 새로운 production writer는 별도 버전의 실행 계약·사전검사·저장 후 검증까지 구현해야 한다.
- 외부 LLM/서비스에 실제 도면을 보내는 기능은 기본 꺼짐으로 설계하고 사용자의 해당 전송 범위를 확인한다.
- 실제 SDK나 라이브러리의 공식 API를 확인한다. 확인되지 않은 API로 동작하는 플러그인을 주장하지 않는다.
- SDK DLL, 폰트, 고객 도면, 비밀정보, 개인 로컬 경로를 커밋하지 않는다.
- 과업에 필요한 라이브러리만 추가한다. DB, 클라우드, UI, 모델 학습은 해당 작업에 배정됐을 때 진행한다.

## 코드와 검증

Python package: `src/god_cad`. 계약의 기준: `models.py`. 계약 변경 때 스키마·버전·예제·소비자·테스트를 함께 업데이트한다.

```text
python -m pip install -r requirements-dev.lock
python -m pip install --no-deps -e .
python -m ruff check .
python -m ruff format --check .
python -m pytest -q
python scripts/export_schemas.py --check
python scripts/demo.py --out artifacts/<새로운-실행명>
```

버전 변경으로 스키마 재생성이 필요한 경우 `python scripts/export_schemas.py`를 실행한다. 실제 동작·데이터 보존·오류/미지원 경로를 검증한다. UI 문구 같은 낮은 영향 변경에 불필요한 테스트를 추가하지 않는다.

## 결과 보고

완료 동작, 변경 파일, 실행한 검증과 결과, 실행하지 못한 검증, 남은 작업 ID, 다음 에이전트의 시작점을 기록한다. SDK나 데이터가 없으면 독립적으로 가능한 계약/fixture 작업을 완료하고 막힌 단계만 명시한다. 실행하지 않은 CAD 통합을 완료했다고 쓰지 않는다.

사용자가 이미 허용한 범위에서 필요한 작업은 진행한다. 반복 승인을 요구하는 절차를 임의로 추가하지 않는다. 저장소 공개 전환, 유료 SDK 구매, 고객 도면 외부 전송처럼 새로운 결정이 필요한 행동은 일반 구현 작업과 구분한다.
