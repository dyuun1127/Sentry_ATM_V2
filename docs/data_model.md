# SENTRY Domain Data Model

## 1. 목적

이 문서는 Phase 0-C에서 구현한 공통 Domain 정책과 최소 모델을 설명한다. 외부 CSV, OpenSky API, Scenario 파일 및 UI DTO는 먼저 이 Domain Model로 변환한 뒤 핵심 계산에 사용한다.

구현 위치:

```text
src/sentry_atm/domain/
├─ aircraft.py
├─ conflict.py
├─ enums.py
├─ flight.py
├─ performance.py
├─ prediction.py
├─ time_policy.py
├─ trajectory.py
├─ units.py
└─ validation.py
```

## 2. 공통 불변조건

### 2.1 시간

- 내부 저장 기준은 timezone-aware UTC다.
- KST 또는 다른 timezone의 입력은 UTC로 정규화한다.
- timezone이 없는 naive datetime은 거부한다.
- KST는 저장 필드가 아니라 화면 표시용 파생값이다.

### 2.2 단위

| 값 | 내부 단위 |
|---|---|
| Local x/y | NM |
| 수평거리 | NM |
| 고도 | ft |
| 수평속도 | kt |
| 수직속도 | ft/min |
| Heading | degree |

Heading은 `[0, 360)` 범위만 유효하다.

- 0도: North
- 90도: East
- 180도: South
- 270도: West

외부 입력을 자동으로 보정해 데이터 오류를 숨기지 않도록 `AircraftState`는 범위를 벗어난 Heading을 거부한다. 각도 Wrap이 필요한 계산에서는 `normalize_heading_deg`를 명시적으로 호출한다.

### 2.3 숫자

- Boolean은 숫자로 받지 않는다.
- NaN과 양·음의 Infinity를 거부한다.
- Ground Speed는 음수가 될 수 없다.
- x/y, Altitude 및 Vertical Speed는 방향과 부호가 의미 있으므로 유한값만 검사한다.

## 3. Enum

모든 Enum은 문자열 직렬화 값이 안정적인 `StrEnum`이다.

### 3.1 DataSource

- `OPENSKY`
- `SYNTHETIC`

### 3.2 AircraftCategory

- `AIRLINER`
- `FAST_JET`
- `TRANSPORT`
- `UNKNOWN`

이는 실제 군 기종이 아니라 비민감 성능 등급이다.

### 3.3 FlightPhase

- `UNKNOWN`
- `CLIMB`
- `LEVEL`
- `DESCENT`
- `APPROACH`
- `FINAL`

### 3.4 Emergency

`EmergencyStatus`:

- `NONE`
- `DECLARED`

`EmergencyType`:

- `PRIORITY_RETURN`
- `AIRCRAFT_CONDITION`

`DECLARED` 상태에는 Emergency Type이 반드시 필요하고, `NONE` 상태에는 Type을 지정할 수 없다.

### 3.5 TrajectoryType

- `PLANNED`
- `ACTUAL`
- `PREDICTED`

세 Trajectory는 같은 자료구조를 사용하지만 의미를 혼합하지 않는다.

### 3.6 Persistence 확장 Enum

`PerformanceDataSource`는 성능 Profile의 출처를 `SIMULATION_ASSUMPTION`,
`PUBLIC_REFERENCE`, `OPENAP`, `LICENSED_REFERENCE`로 구분한다. 실제 수치의 근거는
`source_reference`에 별도로 기록한다.

`FlightStatus`는 `PLANNED`, `ACTIVE`, `COMPLETED`, `CANCELLED`를 사용한다.

### 3.7 ConflictStatus

- `SAFE`: 설정된 Rule Profile의 수평·수직 조건을 동시에 위반하지 않음
- `PREDICTED`: 예측 최소 수평·수직 분리가 동시에 Profile 기준 미만임

## 4. AircraftMetadata

운동 상태보다 천천히 변하는 식별 및 분류 정보다.

| 필드 | 타입 | 설명 |
|---|---|---|
| `aircraft_id` | `str` | 시스템 내부의 필수 식별자 |
| `aircraft_type` | `str` | 공개 기종 또는 `UNKNOWN` |
| `category` | `AircraftCategory` | 비민감 성능 등급 |
| `callsign` | `str \| None` | 선택적 Callsign |
| `icao24` | `str \| None` | 선택적 6자리 16진수 주소 |
| `performance_class` | `str \| None` | 후속 성능 설정 연결 키 |

`icao24`는 제공된 경우 소문자로 정규화하며 정확히 6자리 16진수여야 한다.

## 5. AircraftState

특정 UTC 시각의 불변 Kinematic State다.

| 필드 | 내부 단위/타입 | 설명 |
|---|---|---|
| `aircraft_id` | `str` | Metadata와 연결되는 식별자 |
| `timestamp_utc` | aware `datetime` | UTC로 정규화된 관측시각 |
| `x_nm` | NM | RKTU 원점 기준 East/West 위치 |
| `y_nm` | NM | RKTU 원점 기준 North/South 위치 |
| `altitude_ft` | ft | 고도 |
| `ground_speed_kt` | kt | 음수가 아닌 지상속도 |
| `heading_deg` | degree | `[0, 360)` Heading |
| `vertical_speed_fpm` | ft/min | 상승 양수, 강하 음수 |
| `source` | `DataSource` | 상태의 출처 |
| `flight_phase` | `FlightPhase` | 파생 또는 Scenario 비행단계 |
| `emergency_status` | `EmergencyStatus` | 비상 선언 상태 |
| `emergency_type` | `EmergencyType \| None` | 추상화된 비상 종류 |

`timestamp_kst`는 `timestamp_utc`에서 계산하는 읽기 전용 Property다.

## 6. TrajectoryPoint

하나의 4DT 지점이다.

| 필드 | 내부 단위/타입 |
|---|---|
| `timestamp_utc` | aware UTC `datetime` |
| `x_nm` | NM |
| `y_nm` | NM |
| `altitude_ft` | ft |

Phase 1에서 `GeodeticPosition`, `LocalPosition`과 RKTU Local Tangent Plane 변환을 추가했다. 핵심 Trajectory 계산은 Local x/y를 사용하고, 위경도는 Geo Adapter 경계에서 변환한다. 자세한 내용은 `docs/coordinate_system.md`를 참조한다.

## 7. Trajectory

| 필드 | 타입 | 설명 |
|---|---|---|
| `aircraft_id` | `str` | 소유 항공기 |
| `trajectory_type` | `TrajectoryType` | Planned, Actual 또는 Predicted |
| `points` | `tuple[TrajectoryPoint, ...]` | 변경 불가능한 4DT 점 목록 |

불변조건:

1. 최소 한 개의 Point가 필요하다.
2. 모든 요소는 `TrajectoryPoint`여야 한다.
3. Timestamp는 엄격하게 증가해야 한다.
4. 같은 Timestamp의 중복 Point를 허용하지 않는다.
5. 입력 List를 전달해도 내부에서는 Tuple로 복사한다.

파생값:

- `start_time_utc`
- `end_time_utc`
- `duration_seconds`

## 8. 사용 예시

```python
from datetime import UTC, datetime

from sentry_atm.domain import (
    AircraftState,
    DataSource,
    FlightPhase,
    Trajectory,
    TrajectoryPoint,
    TrajectoryType,
)

state = AircraftState(
    aircraft_id="MIL-F01",
    timestamp_utc=datetime(2026, 9, 1, 3, 0, tzinfo=UTC),
    x_nm=-8.0,
    y_nm=2.0,
    altitude_ft=7_400.0,
    ground_speed_kt=320.0,
    heading_deg=210.0,
    vertical_speed_fpm=-1_200.0,
    source=DataSource.SYNTHETIC,
    flight_phase=FlightPhase.DESCENT,
)

trajectory = Trajectory(
    aircraft_id=state.aircraft_id,
    trajectory_type=TrajectoryType.ACTUAL,
    points=(
        TrajectoryPoint(
            timestamp_utc=state.timestamp_utc,
            x_nm=state.x_nm,
            y_nm=state.y_nm,
            altitude_ft=state.altitude_ft,
        ),
    ),
)
```

## 9. Persistence 준비 Domain

SQLite를 포함한 영속성 구현과 독립적으로 다음 Domain 객체를 추가했다.

- `AircraftType`: 공개 기종 코드와 비민감 Category
- `AircraftPerformanceProfile`: 속도·상승/강하·선회·고도 Envelope와 출처
- `Flight`: 한 항공기의 계획 시간 구간과 상태
- `PredictionRun`: 입력시각, 모델 버전, Horizon 및 Predicted Trajectory Aggregate

Repository 계약과 논리 Schema는 `docs/persistence.md`를 참조한다.

## 10. Scenario State Anchor

`ScenarioAircraft`는 안정적인 `AircraftMetadata`, Scenario 시작시각의 `initial_state`, 선택적인
`scheduled_states`를 묶는다. `scheduled_states`는 같은 Aircraft ID와 `SYNTHETIC` Source를
사용하고 초기 State 뒤에 엄격한 UTC 시간순으로 배치되는 불변 State Anchor다. 이는 Golden Demo
Truth를 재현하기 위한 입력이며 관제 명령이나 Conflict 결과가 아니다.

## 11. Phase 6-A Conflict Domain

- `ConflictPair`: 서로 다른 두 Aircraft ID를 사전순으로 정규화한 안정적인 Pair Key
- `SeparationMinimum`: 예측 최근접점의 수평분리 NM와 수직분리 ft
- `SeparationRuleProfile`: 출처를 기록한 교체 가능한 수평·수직 판정 기준
- `ConflictEvent`: 평가시각, 최근접 예상시각, 최소분리, Rule Profile ID와 판정 결과
- `ConflictAssessmentRun`: 한 Snapshot의 실행 ID, Horizon, Rule과 전체 Pair 결과 Aggregate

`ConflictEvent.tcpa_seconds`는 평가시각과 최근접 예상시각의 차이에서 계산하므로 중복된 시간 상태를
저장하지 않는다. `POC_TERMINAL_V1`의 5 NM/1,000 ft는 `ASM-018`의 잠정 PoC 값이며 공식적인
보편 분리기준이 아니다. Phase 6-B의 CPA/TCPA 계산 결과를 이 계약으로 전달하고, Phase 6-C의
Pairwise Detector가 전체 Assessment와 탐지 결과를 생성한다.
Phase 6-D의 Rolling Scheduler는 `ConflictAssessmentRun`을 기본 5초 Simulation Time 구간마다
최대 한 번 생성한다.

## 12. Phase 7-A Risk와 Operational Priority Domain

- `RiskPolicyProfile`: TCPA와 분리비율의 잠정 Risk 입력 및 출처
- `ConflictRiskAssessment`: Pair 단위 Risk Score, Level, 비율, 이유와 정책 ID
- `OperationalPriorityPolicyProfile`: Scenario Event별 Priority Score와 Level 매핑
- `OperationalPriorityAssessment`: Aircraft 단위 Priority Score, Level, 이유와 Source Event ID

Risk와 Priority는 별도 결과이며 `ConflictEvent`도 변경하지 않는다. Score는 0~100 범위로 제한하고
모든 평가시각은 UTC로 정규화한다. Phase 7-B의 `ConflictRiskEvaluator`와
`OperationalPriorityEvaluator`가 정책 Profile을 사용해 이 결과를 생성한다. 자세한 계약은
`docs/risk_priority.md`를 참조한다.

## 13. Phase 8-A Exception Queue Domain

- `ConflictExceptionItem`: 하나의 `ConflictRiskAssessment`를 참조하는 Pair Exception
- `OperationalPriorityExceptionItem`: 하나의 `OperationalPriorityAssessment`를 참조하는 Aircraft Exception
- `ExceptionQueuePolicy`: Risk/Priority 교차 Rank와 완전한 결정론적 정렬 키
- `ExceptionQueueSnapshot`: 한 UTC 시각의 고유하고 정렬된 불변 Exception 집합

Phase 8-B의 `ExceptionQueueService`는 Conflict Aircraft Pair 또는 Priority Aircraft ID 기반 Stable
ID로 최신 Item과 Snapshot Revision을 관리한다. 새 LOW/ROUTINE은 제외하며 Lifecycle은
`OPEN → ACKNOWLEDGED → RESOLVED`이고 해결 뒤 위험이 재상승하면 새 Open 시각으로 재개한다.
상세 계약과 잠정 Rank는 `docs/exception_queue.md`를 참조한다.

Phase 8-C의 `ConflictExceptionReadModel`, `OperationalPriorityExceptionReadModel`과
`ExceptionQueueSnapshotReadModel`은 Domain을 JSON 호환 표현으로 변환한다. Read Model은 파생된
표시 데이터이며 Domain Source of Truth 또는 별도 Persistence Aggregate가 아니다.

## 14. Phase 9-A Resolution Candidate Domain

- `HeadingManeuver`, `AltitudeManeuver`, `SpeedManeuver`: 절대 목표값 기반 기동
- `EntryDelayManeuver`, `SequenceChangeManeuver`: 시간·순서 관리 기동
- `NoActionManeuver`: 적용 전후 비교 기준선
- `CandidateCostEstimate`: 지연 sec, 경로 연장 NM와 0~100 PoC Cost
- `ResolutionCandidate`: 대상, Maneuver, Objective, 적용시각과 Cost
- `ResolutionCandidateBatch`: 하나의 Conflict Exception에 대한 결정론적 Candidate 집합

Candidate는 아직 안전성이나 실행 가능성이 검증되지 않은 제안이며 Aircraft State를 변경하지 않는다.
자세한 계약은 `docs/resolution.md`를 참조한다.

Phase 9-B의 `ResolutionCandidateGenerationProfile`은 Candidate Template, 기동 크기, 비용과 출처를
보존한다. `DeterministicResolutionCandidateGenerator`는 활성 Conflict Exception과 Pair State를 이
Profile에 적용해 Batch를 생성하지만 Domain Candidate에 Safety 결과를 추가하거나 Runtime을 변경하지
않는다.

Phase 9-C는 `SafetyRuleViolation`, `CandidateSafetyValidationResult`와
`ResolutionSafetyValidationRun`으로 Primary/Secondary Conflict, Performance 가능 여부, Rule 증거와
SAFE/UNSAFE/INEFFECTIVE 판정을 분리해 보존한다. Reason Code와 증거가 일치하지 않는 Result는 생성할
수 없다.

Phase 9-D의 `ResolutionSafetyValidationProfile`은 Horizon, 명령 실행시간, 잠정 최저고도와 허용
속도변화 입력 및 출처를 보존한다. `IsolatedResolutionSafetyValidator`는 Candidate별 복제 State에
기동을 적용하고 전체 Traffic Pair를 재평가해 Phase 9-C Aggregate를 생성한다. 이는 Application
Service이며 원본 Runtime이나 Domain Aggregate를 변경하지 않는다.

## 15. Phase 10-A Resolution Recommendation Domain

- `ResolutionRecommendation`: SAFE Action Candidate, 동일 Candidate의 Validation Evidence, Rank,
  긍정 근거와 설명문
- `ResolutionRecommendationSet`: Exception/Candidate Batch/Validation Run 출처와 결정론적 추천 순서
- `RecommendationAvailability`: `AVAILABLE` 또는 명시적인 `NO_SAFE_CANDIDATE`

`UNSAFE`, `INEFFECTIVE`와 `NO_ACTION`은 Recommendation을 생성할 수 없다. Recommendation 생성은
Aircraft Runtime 또는 Candidate를 변경하지 않으며 관제사 결정과도 구분된다. 자세한 계약은
`docs/recommendation.md`를 참조한다.

Phase 10-B의 `RecommendationRankingProfile`은 표시할 최대 추천 수와 정책 출처를 보존한다.
`DeterministicRecommendationRankingService`는 완전한 Validation Run의 SAFE Action Candidate만
Cost Score, Delay, Path Extension, Candidate ID 순으로 정렬해 Recommendation Set을 생성한다.

Phase 10-C의 Recommendation Read Model은 Set, Candidate Maneuver/Cost와 Safety Evidence를 JSON
호환 값으로 변환한다. `RecommendationSetSource`와 `RecommendationApiContract`는 현재 결과의
생명주기와 전송 Adapter를 Domain에서 분리하며 Read Model 자체를 별도 Aggregate로 저장하지 않는다.

Phase 10-D의 `RecommendationWsgiApp`은 현재 Read Model을 `GET
/api/v1/recommendations/current`로 제공하는 읽기 전용 전송 Adapter다. HTTP 응답은 Domain Model이나
별도 Persistence Aggregate가 아니며 Controller Decision Command를 포함하지 않는다.

## 16. Phase 11-A Controller Decision Audit Domain

- `ControllerDecisionAuditEntry`: SAFE Recommendation에 대한 `ACCEPT`, `MODIFY`, `REJECT`와 UTC,
  Controller Position, Rationale 및 변경 Maneuver
- `ControllerDecisionAuditLog`: Recommendation Set당 한 Decision을 시간순으로 보존하고 1부터 증가하는
  Revision을 포함하는 불변 Snapshot

`ACCEPT`는 후속 적용을 허가하지만 Entry 생성만으로 Runtime을 변경하지 않는다. `MODIFY`는 변경
Maneuver의 재검증이 필수이고 `REJECT`는 적용을 허가하지 않는다. 자세한 계약은
`docs/controller_decision.md`를 참조한다. Phase 11-B Service는 성공한 Decision에만 Revision을 할당하고
동일 Set의 중복 최종 결정을 원자적으로 거부한다.

Phase 11-C의 Command/API DTO는 Domain이나 Persistence 모델이 아니다. 입력은 ID, Decision Type,
timezone-aware UTC 및 고정 Maneuver Schema로 제한하고, 출력은 Audit Identity와 Human-in-the-loop
상태를 JSON 호환 Read Model로 표현한다.

Phase 11-D의 WSGI Request/Response와 오류 Payload는 Transport 모델이며 Domain 또는 Audit Persistence
모델이 아니다. HTTP Decision 성공도 그 자체로 Aircraft Runtime 적용을 의미하지 않는다.

## 17. Phase 12-A Runtime Composition

`GoldenDemoRuntime`은 Domain/Persistence 모델이 아니라 process-local Composition Container다.
`InMemoryRecommendationCatalog` 역시 Recommendation Set을 Read API와 Decision Lookup에 연결하기 위한
휘발성 Application State이며 영속 Audit 저장소가 아니다. Composition 생성은 어떠한 Runtime 기동도
적용하지 않는다.

Phase 12-B의 `GoldenDemoStepResult`는 한 Simulation Tick에서 계산된 Traffic, Event, Prediction,
Conflict, Risk, Priority 및 Exception Queue 결과를 함께 참조하는 불변 Application Snapshot이다.
Domain Aggregate를 합치거나 복제하는 Persistence 모델이 아니다.

Phase 12-C의 `GoldenDemoResolutionResult`는 하나의 Source Step/Conflict Exception, Candidate Batch,
Safety Validation Run과 게시된 Recommendation Set을 연결하는 불변 Application 결과다. 성능 Profile은
Domain 전용 `reference_data`에서 공급하며 SQLite Seed도 같은 객체를 재사용한다. Resolution Result 자체는
새 Domain Aggregate나 Persistence 모델이 아니며 Controller Decision 또는 Aircraft State를 포함하지
않는다.

Phase 12-D의 `GoldenDemoControllerDecisionResult`는 T+90 Step, T+75 Resolution, 선택한
Recommendation과 기존 `ControllerDecisionAuditEntry/Log`를 연결하는 불변 Application 결과다.
`ACCEPT`의 `authorizes_application`은 후속 적용 권한이며 적용 완료 상태가 아니다. 따라서 이 Result에도
적용 후 Aircraft State나 Conflict 해소 판정을 저장하지 않는다.

Phase 12-E의 `GoldenDemoApprovedManeuverApplicationResult`는 승인 전후 Actual State, 적용 후 Traffic
Snapshot, 새 Prediction/Conflict Run, Risk/Priority, Exception Queue와 원 Pair의 재검증 결과를 연결한다.
`SyntheticAircraftRuntime.applied_states`는 현재 Clock Run에만 존재하는 승인 State Anchor이며 Reset 시
제거된다. Application Result는 process-local 실행 증거이고 아직 영속 Audit Aggregate는 아니다.

## 18. Phase 13-A Golden Demo Session Read Model

- `GoldenDemoAircraftReadModel`: Metadata와 현재 Actual State를 합친 지도·표시용 DTO
- `GoldenDemoRevalidationReadModel`: 승인 적용 전후 고도, 재계산 Run Identity와 원 Conflict 해소 요약
- `GoldenDemoSessionReadModel`: 현재 Run/Stage, Traffic 및 기존 Queue·Recommendation·Decision DTO를
  조합한 JSON 호환 응답

Session Stage는 저장되는 Domain 상태가 아니라 완료된 Application Evidence에서 파생된다. Session
Read Model은 `to_dict()`에서 Enum, tuple 및 중첩 DTO를 JSON Primitive로 변환하며 Clock이나 Runtime을
진행하지 않는다.

## 19. 의도적으로 제외한 모델

다음은 현재 Phase의 책임이 아니므로 아직 구현하지 않는다.

- Golden Demo Session Command와 HTTP Adapter: Phase 13-B 이후
- UI State와 화면 구현: Session Command/HTTP 계약 완성 이후
- Session 및 Application Audit Persistence: 현재 process-local PoC 범위 이후

외부 데이터 Schema를 Domain Model에 직접 추가하지 않고 각 Adapter에서 명시적으로 변환한다.
