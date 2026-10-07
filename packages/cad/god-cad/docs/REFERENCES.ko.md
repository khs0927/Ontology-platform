# 출처와 검토 기록

확인일: 2026-09-10. 아래는 기술 선택을 뒷받침하는 1차 자료다. 제품별 지원 범위는 구현 시 채택 버전에서 다시 검증한다.

| 자료 | 확인한 내용 | GOD-CAD 적용 |
| --- | --- | --- |
| [사용자 공유 대화](https://chatgpt.com/share/6aa28833-6a2c-83e9-805f-c970c51367f7) | 도면 파싱, 온톨로지, 편집 그래프 아이디어 | 요구의 출발점. 근거 없는 완벽성/정확도 수치는 채택하지 않음 |
| [BOT 공식 저장소](https://github.com/w3c-lbd-cg/bot) | Building Topology Ontology와 공식 namespace | 후속 공간 모델 정렬 |
| [Built Element Ontology](https://cramonell.github.io/beo/actual/index-en.html) | `https://w3id.org/beo#`의 Wall/Door/Window/Column 등; 문서는 draft 표시 | 실제 v0.1 class URI 참조. 명칭이 비슷한 다른 ontology와 구분 |
| [OMG 저자 페이지](https://annawagner.github.io/omg/) | Ontology for Managing Geometry 자료 진입점 | 후속 표현 연결 설계. 배포 버전 미고정 |
| [FOG 공식 저장소](https://github.com/mathib/fog-ontology) | geometry format별 표현 관계, OMG 확장, 비포괄성 | 후속 mapping. 모든 CAD 데이터가 자동 보존된다는 뜻으로 해석하지 않음 |
| [bSDD 공식 소개](https://www.buildingsmart.org/users/services/buildingsmart-data-dictionary/) | 정의 사전 서비스와 URI 기반 참조 | 개념·속성 사전. 실제 도면 객체 DB는 직접 구축 |
| [PROV-O](https://www.w3.org/TR/prov-o/) | provenance 표현 온톨로지 | 자체 revision·source·activity 어휘의 기반 |
| [ezdxf 문서](https://ezdxf.readthedocs.io/en/stable/) | Python DXF 도구와 객체 API | v0.1 DXF adapter |
| [ezdxf 이미지 출력](https://ezdxf.readthedocs.io/en/stable/tutorials/image_export.html) | SVG backend와 출력 좌표 변환 | 미리보기. 독립 DWG 검증은 별도 |
| [ZWCAD 공식 개발 지원](https://www.zwsoft.com/support/zwcad-devdoc) | ZRX.NET, COM 등의 버전별 개발 자료 | 실제 버전 확인 후 native 연결 |
| [ACadSharp 공식 저장소](https://github.com/DomCR/ACadSharp) | DWG/DXF C# 라이브러리 | 독립 native parser 후보; 현재 의존성 아님 |
| [CADIR 논문](https://arxiv.org/abs/2608.00891) | executable IR, construction graph, cross-backend editing 연구 | 의존성 기록의 설계 참고. 임의 2D DWG 이력 복원 기능으로 채택하지 않음 |

## 원문에서 보완한 판단

‘모든 도면을 그래프화한 DB는 없다’는 표현을 전 세계 자산의 부재 증명으로 사용하지 않는다. 현재 요구에 맞는 완제품을 확보하지 못한 상태이므로, 재사용할 개념 사전과 직접 구축할 도면 인스턴스 데이터를 구분했다.

기존 연구가 있다는 사실과 우리 도면에서 정확하게 동작한다는 사실을 구분한다. 원문에 언급된 OntoCAD, ResPlan, FloorPlanCAD, CADTransformer, VecFormer는 후속 연구·데이터 후보로 남긴다. 이번 뼈대에는 내려받거나 학습·평가하지 않았고 데이터 크기·성능 수치를 제품 지표로 채택하지 않았다.

BOT/BEO/OMG/FOG를 한꺼번에 import하면 자동으로 일관된 통합 온톨로지가 완성된다는 가정도 채택하지 않는다. 초기에는 얇은 참조로 시작하고 실제 버전·관계 의미·mapping 충돌·이용 조건을 후속 작업에서 고정한다.
