# Ontology Platform

로컬 우선(Local-first) 방식의 온톨로지 · 지식그래프 · GraphRAG 플랫폼입니다.

## 목표

프로젝트, 문서, CAD/BIM, 도구, 워크플로, 의사결정, 산출물과 근거(Evidence)를 하나의 검증 가능한 지식 구조로 연결합니다.

## 핵심 원칙

- **GitHub**: 코드와 변경 이력의 기준 원본
- **Google Drive**: 대용량 자산, 스냅샷, 백업, 복구 저장소
- **PostgreSQL**: 엔티티·관계·근거의 canonical truth store
- **Graph / Vector**: canonical DB에서 재생성 가능한 projection
- **Evidence-first**: 관계와 AI 추출 결과는 출처와 검증 상태를 보존
- **Local-first / Free-first**: 유료 API에 종속되지 않는 구조
- **Adapter-first**: CAD/BIM/AEC/CAIR 등 도메인 기능은 코어와 분리

## 개발 순서

1. Core ontology + validation
2. FastAPI CRUD/query
3. PostgreSQL runtime
4. Google Drive ArtifactStore metadata adapter
5. 기존 Ontology Map API 연결
6. Document ingestion + evidence
7. GraphRAG
8. Apache AGE graph projection
9. AEC/CAIR adapter
10. CAD/BIM ingestion

## 기존 저장소와의 관계

`khs0927/Ontology`는 AEC/CAIR 관련 기존 연구·프로토타입 보관소로 유지합니다. 통째로 병합하지 않고 실제로 검증된 기능만 adapter 방식으로 선택적으로 가져옵니다.

## 저장 원칙

활성 개발은 로컬 작업 디렉터리에서 수행합니다. Google Drive 동기화 폴더 안에서 직접 개발하지 않습니다. Google Drive는 스냅샷·대용량 자산·복구 계층으로 사용합니다.

## 상태

초기 구조 정리 단계입니다. 공개 배포용 안정 버전은 아직 아닙니다.
