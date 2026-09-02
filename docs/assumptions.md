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
  보정된 계획 궤적과의 무관한 초기 Conflict 및 Medium Risk를 피하도록 -1/18 NM로 조정했다.
- Phase 9-E 결정: 기존 1차 CPA와 T+0/T+60 탐지 건수를 유지하면서 `CIV-A02` 초기 고도를
  9,075 ft, T+60 `MIL-F01` 수직속도를 +185 ft/min으로 보정했다. `MIL-F02`는 초기
  -11.3194/20.3194 NM·6,946.25 ft, +400 ft/min으로 조정해 CAND-B의 우측 20도 기동에서만
  `MIL-F01`과 계산된 2차 Conflict를 만들고 CAND-A는 안전하게 유지한다.
- 금지: 목표 Conflict 결과를 코드에 하드코딩하는 것
- 검증: Golden Demo 통합 테스트

### ASM-023 - Risk와 Priority 분리

- 상태: `PROJECT_DECISION`
- 내용: Conflict Risk와 운항 Priority는 서로 다른 평가 결과다.
- 예시: `MIL-T01`은 현재 Conflict Risk가 낮아도 Emergency Priority가 가장 높을 수 있다.
- Phase 7-A 결정: Risk는 `ConflictPair`, Priority는 개별 Aircraft를 대상으로 별도 Assessment ID,
  Score, Level, Reason Code와 Policy Profile ID를 보존한다. 두 Score를 하나로 합치지 않는다.
- 검증: Phase 7 단위 테스트

### ASM-024 - Risk Level

- 상태: `POC_ASSUMPTION`
- 내용: 초기 Risk Level은 `LOW`, `MEDIUM`, `HIGH`, `CRITICAL` 네 단계로 표현한다.
- Phase 7-A 결정: `POC_RISK_V1` 시작값은 Critical TCPA 30초, High TCPA 120초 및 Medium
  수평·수직 비율 1.25다. LOW/MEDIUM/HIGH/CRITICAL Score는 0/40/75/100이며 실제 Level
  판정은 Phase 7-B에서 구현한다.
- Phase 7-B 결정: `PREDICTED` TCPA 0~30초는 `CRITICAL`, 30초 초과~120초는 `HIGH`, 그보다
  길면 `MEDIUM`이다. `SAFE`이면서 수평·수직 비율이 모두 1.25 미만이면 `MEDIUM`, 나머지는
  `LOW`다. Event Status는 적용 Separation Rule로 다시 검증한다.
- 주의: 공식적이거나 보편적인 Risk 기준이 아닌 Golden Demo용 잠정 입력이다.
- 검증: Phase 7 Risk Evaluator 및 Golden Demo 테스트

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
- Phase 9-A 결정: 각 Primitive는 절대 목표값을 가진 별도 타입으로 표현하고 Primary Objective를
  고정한다. `NO_ACTION`은 실행 후보가 아닌 전후 비교 기준선으로 Batch마다 정확히 한 개 둔다.
  예상 비용은 지연 sec, 경로 연장 NM와 0~100 PoC Score로 표현하며 정밀 연료/운항비용으로 해석하지
  않는다.
- Phase 9-B 결정: `POC_RESOLUTION_V1`은 우측 20도, 고도 1,000 ft, 속도 30 kt, Entry Delay
  30초와 Sequence Position 1을 생성 입력으로 사용한다. Golden Template의 Cost Score는 A=10,
  B=25, C=20, D=30이고 B의 Path Extension은 1.5 NM, C의 Delay는 30초인 잠정 비교값이다.
  Callsign이나 군/민 Category가 아니라 명시적인 Preferred Target과 Pair 역할로 Template 대상을 정한다.
- 제외: 자유형 3D 경로 생성과 강화학습 기반 명령
- 검증: Phase 9 Candidate Domain 및 Generator 테스트

### ASM-028 - Controller 승인 전 상태 불변

- 상태: `PROJECT_DECISION`
- 내용: Recommendation 생성만으로 Actual Aircraft Runtime을 변경하지 않는다.
- Phase 9-C 결정: Safety Validation은 Candidate별 복제 State의 결과만 기록한다. SAFE는 1차 Conflict
  해소와 실패 없음, INEFFECTIVE는 Action의 1차 Conflict만 지속, UNSAFE는 2차 Conflict·성능·Rule
  실패 또는 Conflict가 남은 NO_ACTION 기준선으로 정의한다.
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

### ASM-035 - Operational Priority Level

- 상태: `POC_ASSUMPTION`
- 내용: 초기 Level은 `ROUTINE`, `ATTENTION`, `URGENT`, `EMERGENCY`로 표현한다.
- Phase 7-A 결정: `POC_OPERATIONAL_PRIORITY_V1`에서 정상 운항은 0/`ROUTINE`, 진입 조건
  불일치는 40/`ATTENTION`, 비상 선언은 100/`EMERGENCY`로 매핑한다. `URGENT`는 후속 검증된
  비상 외 운항 규칙을 위해 예약한다.
- Phase 7-B 결정: 평가시각까지 발생한 대상 Aircraft의 Event만 적용하고, 비상 선언이 진입 이탈보다
  높은 Level을 사용한다. Conflict Risk는 Priority 입력에 포함하지 않는다.
- 금지: 군용 Category 자체를 Priority 상승 조건으로 사용하는 것
- 검증: Phase 7 Priority Evaluator 및 `VAL-EMERGENCY-PRIORITY`

### ASM-036 - Exception Queue 교차 타입 순서

- 상태: `POC_ASSUMPTION`
- 내용: 초기 Queue Rank는 Emergency Priority, Critical Risk, Urgent Priority, High Risk,
  Attention Priority, Medium Risk, Routine Priority, Low Risk 순서다.
- Phase 8-A 결정: Resolved 여부, 교차 타입 Rank, Acknowledge 여부, TCPA 오름차순, Score 내림차순,
  Exception ID 사전순으로 전체 정렬 키를 구성한다.
- Phase 8-B 결정: LOW/ROUTINE은 새 항목에서 제외하고, 기존 항목은 같은 Subject의 명시적인
  LOW/ROUTINE 평가가 도착할 때만 해결한다. 누락은 해결로 추정하지 않으며 해결 후 재상승은 새
  Open 시각으로 재개한다. 확인 상태는 활성 평가가 계속되는 동안 보존한다.
- 주의: 관제사 화면의 잠정 표시 순서이며 자동 항공기 기동 또는 공식 관제 우선순위를 의미하지 않는다.
- 검증: 입력 순서 변경, 동일 등급 TCPA, Stable ID, Lifecycle 및 Golden T+0/T+70/T+240 Queue 테스트

### ASM-037 - 격리 Candidate 검증 입력

- 상태: `PROVISIONAL`
- 내용: Phase 9-D의 `POC_SAFETY_V1`은 120초 재평가 Horizon, 60초 명령 실행시간, 한 Candidate의
  최대 속도 변화 50 kt와 Altitude Candidate 목표에만 적용하는 7,500 ft 잠정 최저고도를 사용한다.
- 적용 모델: Heading·Altitude·Speed는 격리 State의 목표값을 즉시 교체하고, Entry Delay는 현재
  운동량만큼 State를 뒤로 이동한다. Sequence Change는 아직 운동학적 State를 변경하지 않는다.
- 주의: 7,500 ft는 공식 최저안전고도 또는 모든 현재 Traffic에 적용되는 규칙이 아니다. 구조화·검증된
  공식 공역 및 절차 Rule이 준비되면 Profile을 교체해야 한다 (`ASM-030`).
- 검증: Phase 9-D Performance, Rule, 1차·2차 Conflict 및 원본 State 불변 테스트

### ASM-038 - 추천 가능성 및 관제사 경계

- 상태: `PROJECT_DECISION`
- 내용: Recommendation은 `SAFE`로 검증된 Action Candidate만 포함한다. `UNSAFE`, `INEFFECTIVE`와
  `NO_ACTION` 기준선은 추천할 수 없다.
- Phase 10-A 결정: 안전 후보가 있으면 `AVAILABLE`, 없으면 빈 `NO_SAFE_CANDIDATE` 결과를 만든다.
  추천에는 1차 Conflict 해소, 2차 Conflict 없음, 성능 가능 및 Rule 위반 없음의 긍정 근거를 모두
  보존한다.
- Phase 10-B 결정: `POC_RECOMMENDATION_V1`은 SAFE Action Candidate를 Cost Score, Delay,
  Path Extension, Candidate ID 오름차순으로 정렬하고 최대 3개를 표시한다. 가중 합산 점수나
  Callsign·군/민 Category 우대는 사용하지 않는다.
- Phase 10-C 결정: Read API는 Domain을 직접 노출하지 않고 고정 Maneuver 필드, Cost와 Safety
  Evidence를 JSON 호환 DTO로 변환한다. 조회 API에는 Accept/Modify/Reject 부작용을 포함하지 않는다.
- Phase 10-D 결정: `GET /api/v1/recommendations/current`만 제공하며 결과 없음은 204로 표현한다.
  모든 응답은 `Cache-Control: no-store`이고 Query나 다른 HTTP Method로 결정을 변경할 수 없다.
- Human-in-the-loop: Recommendation 생성은 Accept/Modify/Reject가 아니며 Aircraft Runtime을
  변경하지 않는다. 관제사 결정과 승인된 기동 적용은 별도 Domain/Application 단계다.
- 검증: Phase 10 Recommendation Domain 및 Ranking Service 테스트

### ASM-039 - Controller Decision Audit 경계

- 상태: `PROJECT_DECISION`
- 내용: `ACCEPT`만 원본 SAFE Candidate의 후속 적용을 허가한다. `MODIFY`는 Rationale과 실제로
  달라진 Action Maneuver를 기록하고 반드시 재검증하며, `REJECT`는 Rationale을 남기고 적용하지 않는다.
- Audit: Recommendation Set마다 최대 하나의 최종 Decision을 허용하고 Decision/Recommendation
  Identity, UTC, 비개인 Controller Position ID를 보존한다.
- Human-in-the-loop: Decision Audit Entry 생성과 실제 Aircraft Runtime 적용을 분리한다.
- 보안: Controller Position ID는 역할·석 식별자이며 실제 개인 이름이나 군 내부 식별자를 사용하지 않는다.
- 검증: Phase 11 Controller Decision Domain, Service, Command/API 및 HTTP Adapter 테스트

### ASM-040 - Golden Demo Runtime Composition 경계

- 상태: `PROJECT_DECISION`
- 내용: Phase 12-A Composition Root는 새 process-local Service와 Catalog를 조립하지만 Clock을 시작하거나
  계산 Pipeline을 실행하지 않는다.
- 격리: Factory 호출별 mutable Clock, Queue, Catalog와 Decision Service를 공유하지 않는다.
- Human-in-the-loop: `ACCEPT` 적용기와 `MODIFY` 재검증 실행기는 아직 Composition에 포함하지 않는다.
- Persistence: In-memory Recommendation Catalog는 재시작 복구나 영속 Audit을 제공하지 않는다.
- 검증: Phase 12 Runtime Composition 및 상태 격리 테스트

## 5. Phase별 확정 시점

| Phase | 반드시 확정할 Assumption |
|---|---|
| Phase 0 | ASM-001, 002, 005~009, 012, 014, 023, 025~029, 033 |
| Phase 1 | ASM-003, 004, 034 |
| Phase 2 | ASM-017 |
| Phase 3 | ASM-010, 013, 015 |
| Phase 4 | ASM-016, 022 |
| Phase 6 | ASM-018, 019 |
| Phase 7 | ASM-024, 035 |
| Phase 8 | ASM-036 |
| Phase 9 | ASM-027, 028, 037 |
| Phase 10 | ASM-028, 038 |
| Phase 11 | ASM-028, 033, 039 |
| Phase 12 | ASM-011, 021, 030, 032, 040 |

## 6. 변경 규칙

Assumption을 변경할 때는 다음을 함께 기록한다.

1. 변경 전 값
2. 변경 후 값
3. 변경 근거와 출처
4. 영향받는 Scenario, Config, 코드 및 테스트
5. 변경일과 문서 버전

`SOURCE_VERIFIED` 항목을 변경할 때는 반드시 새 공식 자료의 적용일과 원문 위치를 남긴다.
