# SENTRY PoC Assumption Register

## 1. 목적

이 문서는 공식 자료로 확인된 사실, 프로젝트 설계 결정, 해커톤 PoC를 위한 가정 및 향후 검증해야 할 값을 구분한다. 가정값을 코드에 숨겨 넣지 않고 설정과 문서에서 추적 가능하게 유지하는 것이 목적이다.

## 2. 상태 정의

| 상태 | 의미 |
|---|---|
| `SOURCE_VERIFIED` | 제공된 공식 또는 공개 자료에서 확인함 |
| `PROJECT_DECISION` | 프로젝트 범위를 위해 명시적으로 결정함 |
| `POC_ASSUMPTION` | 해커톤 시뮬레이션을 위해 채택한 비공식 가정 |
| `PROVISIONAL` | 후속 계산 또는 자료 검증에 따라 조정할 값 |
| `DEFERRED` | MVP 이후에 검증하거나 구현할 항목 |

## 3. 근거 우선순위

충돌하는 정보가 있을 때 다음 순서로 판단한다.

1. 적용 시점이 확인된 공식 AIP, 법령 및 항공교통관제절차
2. 프로젝트에 제공된 공식 과제 기술서
3. 공개 연구자료와 검증 가능한 공개 성능자료
4. 프로젝트 설정값과 Scenario Contract
5. 데모 편의를 위한 임의값

공식 자료가 갱신되면 문서의 적용일과 변경 내용을 먼저 확인한 뒤 반영한다.

## 4. Assumption 목록

### ASM-001 - 시스템 목적

- 상태: `PROJECT_DECISION`
- 내용: SENTRY는 자율 관제 시스템이 아니라 관제사 의사결정 지원 시스템이다.
- 영향: 모든 Recommendation에는 관제사의 Accept, Modify 또는 Reject가 필요하다.
- 검증: `SC-008` 및 Controller Decision 통합 테스트

### ASM-002 - 공간적 범위

- 상태: `PROJECT_DECISION`
- 내용: PoC는 RKTU 중심 Terminal Simulation Area 하나만 다룬다.
- 주의: 이 명칭과 경계는 실제 공식 TMA, CTR 또는 특정 기관의 책임공역을 의미하지 않는다.
- 검증: Architecture 및 UI 용어 검토

### ASM-003 - RKTU 좌표 원점

- 상태: `SOURCE_VERIFIED`
- 내용: RKTU ARP `36°42'59\"N, 127°29'57\"E`를 local x/y 좌표의 원점으로 사용한다.
- 출처: 제공된 `자료/RKTU-TEXT.pdf`, RKTU AD 2.2
- 영향: East는 +x, North는 +y다.
- 검증: Phase 1 좌표 원점 테스트

### ASM-004 - Simulation Area 계산 경계

- 상태: `PROVISIONAL`
- 내용: 최초 계산 Envelope는 RKTU ARP 반경 30 NM, 고도 0~20,000 ft로 둔다.
- 주의: 레이더 통달범위나 실제 공역 경계라고 설명하지 않는다.
- 검증: RKTU 절차와 대표 항적을 배치한 뒤 Phase 1 이전 또는 중에 조정

### ASM-005 - 관제 조직 추상화

- 상태: `PROJECT_DECISION`
- 내용: PoC에서는 하나의 가상 `Terminal Radar Controller`가 Simulation Area Traffic을 담당한다.
- 주의: 실제 Jungwon APP, Cheongju GCA, Tower 또는 ACC의 운영 책임을 재현한다고 주장하지 않는다.
- 검증: Scenario 및 UI 명칭 검토

### ASM-006 - MCRC 역할

- 상태: `PROJECT_DECISION`
- 내용: MCRC는 Golden Demo의 항공교통관제 의사결정자가 아니다.
- 이유: 작전 통제와 항공교통관제의 책임을 혼동하지 않기 위함이다.
- 검증: 발표자료와 UI에서 MCRC 명령 기능이 없는지 확인

### ASM-007 - Tower 경계

- 상태: `PROJECT_DECISION`
- 내용: Golden Demo는 최종접근 안정화와 Tower 이양 준비까지 다루며 실제 착륙, 활주로 점유 및 지상 이동은 다루지 않는다.
- 검증: Scenario 종료 조건 확인

### ASM-008 - 시간 정책

- 상태: `PROJECT_DECISION`
- 내용: 내부 저장과 데이터 교환은 timezone-aware UTC를 사용하고 화면에서 KST로 변환한다.
- 금지: timezone 정보가 없는 naive datetime을 Domain Model에서 허용하지 않는다.
- 검증: Phase 0 시간 정책 테스트

### ASM-009 - 내부 단위

- 상태: `PROJECT_DECISION`
- 내용: 거리 NM, 고도 ft, 수평속도 kt, 수직속도 ft/min, Heading degree를 사용한다.
- Heading: 0도 North, 90도 East, 180도 South, 270도 West
- 검증: Phase 0 Domain 유효성 검사 및 Phase 1 Geometry 테스트

### ASM-010 - Golden Demo 데이터 Source

- 상태: `POC_ASSUMPTION`
- 내용: 재현 가능한 초기 Golden Demo의 모든 항공기는 `SYNTHETIC`으로 생성한다.
- 이유: 실제 군 레이더 항적은 확보와 공개가 어렵고 데모 결과를 결정론적으로 재현해야 한다.
- 검증: 모든 Golden Demo Aircraft의 `source` 값 확인

### ASM-011 - OpenSky 데이터 정책

- 상태: `DEFERRED`
- 내용: 민항기 Playback은 후속 Phase에서 OpenSky Historical State Vector를 사용할 수 있다.
- 정책: Raw 데이터는 수정하지 않고 `raw -> processed -> scenario` 방향으로만 변환한다.
- 검증: Data Adapter 구현 시 Raw checksum 및 Source 표시 확인

### ASM-012 - 군용기 성능 표현

- 상태: `PROJECT_DECISION`
- 내용: 실제 군 기종 대신 `FAST_JET`, `TRANSPORT`, `AIRLINER` 성능 등급을 사용한다.
- 금지: 비공개 또는 민감한 실제 군용기 성능값 사용
- 검증: Performance 설정에 출처 또는 `SIMULATION_ASSUMPTION` 표시

### ASM-013 - Synthetic 성능값

- 상태: `PROVISIONAL`
- 내용: 초기 Reference Seed는 실제 기종이 아닌 세 가지 Synthetic Category Envelope를 사용한다.
- 출처 표기: 모든 값은 `SIMULATION_ASSUMPTION` 및
  `ASM-013:SENTRY_POC_CATEGORY_ENVELOPE_V1`으로 저장한다.
- 주의: 아래 값은 실제 항공기 성능, BADA 성능 또는 공식 운용한계가 아니다.

| Profile | 속도 kt (min/max) | 상승/강하 ft/min | 선회 deg/s | 고도상한 ft |
|---|---:|---:|---:|---:|
| `AIRLINER-POC-V1` | 130 / 350 | 2,500 / 3,000 | 3.0 | 39,000 |
| `FAST-JET-POC-V1` | 160 / 480 | 6,000 / 6,000 | 6.0 | 50,000 |
| `TRANSPORT-POC-V1` | 110 / 320 | 2,000 / 2,500 | 3.0 | 35,000 |

- 검증: Predictor/Scenario 통합 시 도달 가능성과 데모 안정성을 측정한 뒤 값과 버전을 조정한다.

### ASM-014 - 대상 비행체

- 상태: `PROJECT_DECISION`
- 내용: MVP는 AIRLINER, FAST_JET, TRANSPORT만 다루고 소형 드론과 헬기는 제외한다.
- 이유: 소형 비행체의 식별, 성능 및 적용 관제절차는 별도 문제다.
- 검증: Scenario Aircraft Category 목록 확인

### ASM-015 - Golden Demo Traffic 수

- 상태: `POC_ASSUMPTION`
- 내용: Golden Demo에는 8대의 항공기를 배치한다.
- 이유: 혼합 교통과 2차 충돌을 보여주면서 화면 가독성과 구현 범위를 유지하기 위함이다.
- 검증: Scenario Builder 테스트

### ASM-016 - Prediction Horizon

- 상태: `POC_ASSUMPTION`
- 내용: Baseline Predictor는 30, 60, 120초 Horizon을 우선 지원한다.
- Phase 6-B 결정: CPA/TCPA 계산기의 기본 연속시간 Look-ahead를 최대 예측 Horizon과 같은
  120초로 두며 생성자에서 교체할 수 있게 한다.
- 주의: 예선 기획서의 10분 Look-ahead는 장기 확장 KPI이며 초기 완료조건이 아니다.
- 검증: Phase 4 Predictor 테스트

### ASM-017 - Simulation Tick과 Rolling Prediction 주기

- 상태: `PROVISIONAL`
- 내용: Simulation Tick은 1초, Prediction 갱신은 5초를 기본값으로 사용한다.
- Phase 2-A 결정: Simulation Clock의 기본 Tick을 1초로 적용하고 명시적인 Tick 방식의 재현성을 테스트한다.
- Phase 4-C 결정: 5초 Simulation Time 구간당 최대 1회 실행하며 Pause·Reset·큰 Tick 이동의
  결정론적 동작을 테스트한다.
- Phase 6-D 결정: Conflict Assessment도 같은 기본 5초 구간을 사용하되 별도 Scheduler로
  실행하며 Prediction Scheduler나 Simulation Engine에 결합하지 않는다.
- 남은 검증: Golden Demo 통합 성능을 측정한 뒤 5초 주기의 최종 유지 여부를 확정한다.

### ASM-018 - PoC Alert Threshold Profile

- 상태: `PROVISIONAL`
- 내용: 초기 `POC_TERMINAL_V1` Profile은 수평 5 NM, 수직 1,000 ft를 Alert 계산의 시작값으로 검토한다.
- 주의: 모든 상황에 적용되는 공식 관제 분리기준으로 표현하거나 하드코딩하지 않는다.
- 설계: 공역, 비행방식, 운항조건에 따라 교체 가능한 Rule Profile이어야 한다.
- Phase 6-A 결정: `POC_TERMINAL_V1`을 주입 가능한 `SeparationRuleProfile` 객체로 정의한다.
  수평·수직 값이 동시에 각 기준보다 작은 경우만 `PREDICTED`로 분류하며 경계값은 `SAFE`다.
- Phase 6-C 결정: 전체 Pair에 Phase 6-B의 동일시각 CPA 분리를 적용하고 Rule Profile로 분류한다.
  모든 Assessment를 보존하되 실제 탐지 목록에는 `PREDICTED`만 포함한다.
- 남은 검증: 제공된 항공교통관제절차와 관련 자료를 검토한 뒤 운영별 Profile을 별도로 확정

### ASM-019 - TCAS/ACAS 활용 범위

- 상태: `PROJECT_DECISION`
- 내용: TCAS/ACAS 개념과 경보시간은 평가 참고자료로 사용할 수 있지만 지상 관제용 Conflict Detector와 동일한 시스템으로 간주하지 않는다.
- 검증: 기술 문서의 용어 검토

### ASM-020 - Sector Entry Conformance

- 상태: `POC_ASSUMPTION`
- 내용: 관제 이양 전체를 구현하지 않고 `Expected Entry State`와 `Actual Entry State`를 비교한다.
- 비교값: 진입 지점, 고도, Heading, 예상 시각
- Phase 5-B 결정: T+60 이벤트를 불변 `EntryConformanceDeviationPayload`로 정의하고,
  Clock 기반 Timeline이 1회 방출한다. Runtime 반영은 후속 단계에서 수행한다.
- Phase 6-E 결정: Golden Scenario Definition의 같은 T+60 State Anchor가 실제 진입 상태를
  제공한다. Timeline 방출은 여전히 Runtime을 직접 변경하지 않는다.
- 검증: `ENTRY_CONFORMANCE_DEVIATION` Scenario 테스트

### ASM-021 - Golden Demo 진입 지점 명칭

- 상태: `POC_ASSUMPTION`
- 내용: 최초 시나리오의 `ENTRY-A`와 `FINAL-GATE`는 Synthetic 지점이다.
- 주의: 공식 Fix, STAR 또는 Approach Procedure로 표현하지 않는다.
- 검증: AIP 절차 디지털화 단계에서 공식 지점으로 교체 여부 결정

### ASM-022 - 시나리오 수치

- 상태: `CALIBRATED_POC_ASSUMPTION`
- 내용: `MIL-F01`의 기대 9,000 ft, 실제 7,400 ft, 2.1 NM 이탈, 25초 지연 및 예상 최소 분리값은 Golden Demo 목표값이다.
- 정책: Phase 4와 Phase 6에서 실제 운동학 계산으로 재현되도록 초기 상태를 조정한다.
- Phase 5-A 결정: `docs/scenarios.md` 7.1의 8대 초기 State를 결정론적 Foundation으로 사용한다.
- Phase 5-B 결정: T+60 진입 불일치와 T+240 비상 선언을 절대 UTC 시각의 타입화된 이벤트로
  Scenario Definition에 포함한다. 이벤트 방출만으로 Aircraft State를 변경하지 않는다.
- Phase 6-E 결정: `MIL-F01`의 계획 초기 State와 T+60 실제 State Anchor를 보정했다. 기존
  CPA/Pairwise/Rolling 계산 결과 T+0은 0건, T+60은 TCPA 100초, T+70은 TCPA 90초이며 두
  평가 모두 CPA 수평 2.3 NM·수직 500 ft로 `CIV-A02`/`MIL-F01` 한 Pair만 탐지한다. 현재
  수평분리는 T+60 약 6.16 NM, T+70 약 5.63 NM로 분리기준 밖이다. `MIL-T02` 초기 위치는
  보정된 계획 궤적과의 무관한 초기 Conflict를 피하도록 0/18 NM로 조정했다.
- 금지: 목표 Conflict 결과를 코드에 하드코딩하는 것
- 검증: Golden Demo 통합 테스트

### ASM-023 - Risk와 Priority 분리

- 상태: `PROJECT_DECISION`
- 내용: Conflict Risk와 운항 Priority는 서로 다른 평가 결과다.
- 예시: `MIL-T01`은 현재 Conflict Risk가 낮아도 Emergency Priority가 가장 높을 수 있다.
- 검증: Phase 7 단위 테스트

### ASM-024 - Risk Level

- 상태: `POC_ASSUMPTION`
- 내용: 초기 Risk Level은 `LOW`, `MEDIUM`, `HIGH`, `CRITICAL` 네 단계로 표현한다.
- 검증: Phase 7 Risk Feature와 Threshold 설계 시 확정

### ASM-025 - 비상상황 추상화

- 상태: `PROJECT_DECISION`
- 내용: 비상은 `PRIORITY_RETURN`과 일반적인 `AIRCRAFT_CONDITION`으로 표현한다.
- Phase 5-B 결정: `EmergencyDeclaredPayload`에서 비상 유형과 사유 범주를 별도 Enum으로
  보존하고 T+240에 1회 방출한다.
- 금지: 실제 작전, 실제 기체 결함 또는 민감한 비상절차를 모사하는 것
- 검증: Scenario Event Payload 확인

### ASM-026 - 비상 항공기 처리 원칙

- 상태: `PROJECT_DECISION`
- 내용: 비상 항공기는 Priority가 가장 높지만 검증 없이 무조건 첫 순서 또는 직선 경로를 부여하지 않는다.
- 고려값: 현재 비행단계, 주변 Traffic, 2차 충돌, 최저고도 및 후보 실행 가능성
- 검증: `SC-010`부터 `SC-012`까지의 통합 테스트

### ASM-027 - Candidate Primitive

- 상태: `PROJECT_DECISION`
- 내용: 초기 후보는 Heading, Altitude, Speed, Entry Delay 및 Sequence Change로 제한한다.
- 제외: 자유형 3D 경로 생성과 강화학습 기반 명령
- 검증: Phase 9 Candidate Generator 테스트

### ASM-028 - Controller 승인 전 상태 불변

- 상태: `PROJECT_DECISION`
- 내용: Recommendation 생성만으로 Actual Aircraft Runtime을 변경하지 않는다.
- 검증: 승인 전후 State Snapshot 비교

### ASM-029 - UI 형태

- 상태: `PROJECT_DECISION`
- 내용: 주 화면은 2D Radar Display와 Exception Queue이며, Vertical Profile과 Recommendation Panel을 보조로 둔다.
- 주의: 3D 지도는 선택적 보조 시각화이며 필수 MVP가 아니다.
- 검증: Phase 12 UI Acceptance Test

### ASM-030 - 공식 공역 및 절차 자료

- 상태: `DEFERRED`
- 내용: 제공된 RKTU AIP, SID, STAR, Approach 및 ATC Surveillance Minimum Altitude Chart는 향후 Airspace/Rule 입력으로 사용할 수 있다.
- 주의: PDF를 직접 계산에 사용하지 않고 검증된 구조화 데이터로 변환해야 한다.
- 검증: Source, 적용일, 좌표 및 고도 제약을 이중 확인한 뒤 반영

### ASM-031 - 평가 방식

- 상태: `PROJECT_DECISION`
- 내용: 화면 동작만으로 성공을 판단하지 않고 결정론적 Scenario Test와 반복 Simulation으로 평가한다.
- 기본 지표: 예측 오차, Conflict Lead Time, 탐지 결과, 회피 성공률, 2차 충돌, 추가 지연
- 검증: Phase 5, Phase 6 및 Phase 10 평가 코드

### ASM-032 - 반복 실험 횟수

- 상태: `PROVISIONAL`
- 내용: 확률 또는 초기조건 변화 실험은 최소 30회로 시작하고 계산비용이 허용되면 300회까지 확장한다.
- 주의: 반복 횟수와 신뢰구간 없이 성공률만 보고하지 않는다.
- 검증: Evaluation 설계 단계에서 확정

### ASM-033 - 보안 및 개인정보

- 상태: `PROJECT_DECISION`
- 내용: 실제 군 레이더 항적, 실제 군 Callsign, 개인 식별정보, API Key 및 인증정보를 저장소에 포함하지 않는다.
- 검증: Commit 전 staged diff와 Secret Scan 확인

### ASM-034 - 좌표 변환 지구 모델

- 상태: `POC_ASSUMPTION`
- 내용: Phase 1의 RKTU Local Tangent Plane은 평균 지구 반지름 3,440.065 NM인 구면 지구 모델을 사용한다.
- 이유: 외부 측지 라이브러리 없이 Terminal 범위의 결정론적 좌표 변환과 역변환을 제공하기 위함이다.
- 주의: WGS84 타원체 기반 공식 측지 변환이나 실제 감시체계 좌표변환을 대체하지 않는다.
- 검증: 원점, 축 방향, 30 NM Envelope 왕복 변환 테스트

## 5. Phase별 확정 시점

| Phase | 반드시 확정할 Assumption |
|---|---|
| Phase 0 | ASM-001, 002, 005~009, 012, 014, 023, 025~029, 033 |
| Phase 1 | ASM-003, 004, 034 |
| Phase 2 | ASM-017 |
| Phase 3 | ASM-010, 013, 015 |
| Phase 4 | ASM-016, 022 |
| Phase 6 | ASM-018, 019 |
| Phase 7 | ASM-024 |
| Phase 12 이후 | ASM-011, 021, 030, 032 |

## 6. 변경 규칙

Assumption을 변경할 때는 다음을 함께 기록한다.

1. 변경 전 값
2. 변경 후 값
3. 변경 근거와 출처
4. 영향받는 Scenario, Config, 코드 및 테스트
5. 변경일과 문서 버전

`SOURCE_VERIFIED` 항목을 변경할 때는 반드시 새 공식 자료의 적용일과 원문 위치를 남긴다.
