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

## 10. Phase 6-A Conflict Domain

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

## 11. 의도적으로 제외한 모델

다음은 현재 Phase의 책임이 아니므로 아직 구현하지 않는다.

- Risk와 Priority: Phase 7
- ResolutionCandidate와 Recommendation: Phase 9~11
- API DTO와 UI State: Phase 12

외부 데이터 Schema를 Domain Model에 직접 추가하지 않고 각 Adapter에서 명시적으로 변환한다.
