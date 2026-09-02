# Resolution Candidate Contract

## 1. 범위

Phase 9는 하나의 Conflict Exception에 대해 제한된 대응 후보를 생성하고, 원본 Runtime을 변경하지
않는 격리 State에서 안전성을 계산한다. 추천 순위와 관제사 승인 적용은 아직 포함하지 않는다.

```text
Conflict Exception
        ↓
ResolutionCandidateBatch
        ├─ ResolutionCandidate + typed Maneuver
        ├─ ResolutionCandidate + typed Maneuver
        └─ NO_ACTION baseline
```

Candidate가 존재한다는 사실은 안전하거나 실행 가능하다는 뜻이 아니다. 모든 Candidate는 후속
Safety Validation을 통과하기 전까지 `unvalidated proposal`이다.

## 2. 제한된 Maneuver Primitive

`ASM-027`에 따라 자유형 3D 경로 대신 다음 Primitive만 허용한다.

| Maneuver | Canonical 값 | 기본 Objective |
|---|---|---|
| `HEADING` | 절대 목표 침로 degree `[0, 360)` | `LATERAL_SEPARATION` |
| `ALTITUDE` | 절대 목표 고도 ft | `VERTICAL_SEPARATION` |
| `SPEED` | 양수 목표 지상속도 kt | `TIME_SEPARATION` |
| `ENTRY_DELAY` | 양수 지연시간 sec | `TIME_SEPARATION` |
| `SEQUENCE_CHANGE` | 1부터 시작하는 목표 순번 | `SEQUENCE_MANAGEMENT` |
| `NO_ACTION` | 별도 값 없음 | `BASELINE_COMPARISON` |

`NO_ACTION`은 개입 Primitive가 아니라 후보 적용 전후를 같은 계산으로 비교하기 위한 기준선이다.
상대 표현인 우측 20도, 30 kt 감속 또는 1,000 ft 추가 강하는 Generator가 생성시점 Aircraft State를
사용해 절대 목표값으로 변환한다. 이 변환은 Phase 9-B 책임이다.

## 3. Candidate

`ResolutionCandidate`는 다음을 보존한다.

- 안정적인 Candidate ID
- 대상 Aircraft ID
- 타입이 구분된 Maneuver
- Maneuver와 일치하는 단일 Primary Objective
- timezone-aware UTC 적용 시작시각
- 예상 지연 sec, 경로 연장 NM, 0~100 Operational Cost Score

Cost는 후보 비교를 위한 PoC 값이며 정밀 연료소모량이나 공식 운항비용을 의미하지 않는다.
`NO_ACTION`은 대상 Aircraft가 없고 예상 Cost가 모두 0이어야 한다. 다른 Maneuver는 반드시 대상
Aircraft가 있어야 한다.

## 4. Candidate Batch

`ResolutionCandidateBatch`는 한 Source Exception과 Conflict Pair에 대한 생성 결과다.

- Batch, Source Exception, Source Conflict와 Generator Profile ID
- Conflict Pair
- 생성 UTC
- Candidate ID 순으로 정렬된 불변 Candidate Tuple
- 정확히 하나의 `NO_ACTION` 기준선

모든 Action Candidate 대상은 Conflict Pair에 속해야 하고 적용시각은 Batch 생성시각보다 이를 수
없다. Candidate ID는 Batch 안에서 고유해야 한다. `actionable_candidates`와 `baseline_candidate`는
원본 Tuple을 변경하지 않는 파생 View다.

## 5. Golden Demo Mapping

시나리오의 `CAND-A`부터 `CAND-E`는 다음 타입으로 표현한다.

| ID | Target | Domain Maneuver |
|---|---|---|
| `CAND-A` | `MIL-F01` | `AltitudeManeuver(target_altitude_ft=9000)` |
| `CAND-B` | `MIL-F01` | 생성시점 침로에서 우측 20도를 계산한 `HeadingManeuver` |
| `CAND-C` | `CIV-A02` | 생성시점 속도에서 30 kt를 뺀 `SpeedManeuver` |
| `CAND-D` | `CIV-A02` | 생성시점 고도에서 1,000 ft를 뺀 `AltitudeManeuver` |
| `CAND-E` | 없음 | `NoActionManeuver` |

Phase 9-A 테스트는 이 다섯 Candidate가 하나의 결정론적 Batch로 표현됨을 확인하지만 SAFE, UNSAFE,
INEFFECTIVE 결과는 하드코딩하지 않는다.

## 6. 안전 및 Human-in-the-loop 경계

- Candidate 생성만으로 Aircraft Runtime을 변경하지 않는다 (`ASM-028`).
- Performance Envelope, 공역, 최저고도와 2차 충돌은 후속 Validator가 검사한다.
- Candidate Generation과 Safety Validation 구현을 분리한다.
- 추천 순위는 검증 결과와 비용이 준비된 이후에만 계산한다.
- 관제사의 Accept/Modify/Reject 이전에는 후보를 실제 State에 적용하지 않는다.

## 7. Deterministic Candidate Generator

Phase 9-B의 `DeterministicResolutionCandidateGenerator`는 다음 입력만 사용한다.

- 활성 `ConflictExceptionItem`
- Conflict Pair 두 대의 같은 UTC 시각 `AircraftState`
- Aircraft ID별 `AircraftPerformanceProfile`
- Pair에 속하는 명시적인 Preferred Target Aircraft ID
- 선택적인 Preferred Target Altitude Hint
- 교체 가능한 `ResolutionCandidateGenerationProfile`

Generator는 Callsign, 군/민 Category 또는 Scenario ID를 분기 조건으로 사용하지 않는다. Preferred
Target은 진입 조건 이탈과 같은 상위 Application 판단에서 명시적으로 전달해야 한다. 입력 Iterable과
Mapping 순서를 바꿔도 동일 Batch를 생성한다.

### 7.1 `POC_RESOLUTION_V1` 생성 입력

| 값 | 입력 |
|---|---:|
| 우측 Heading 변화 | 20 deg |
| Altitude 변화 | 1,000 ft |
| Speed 감소 | 30 kt |
| Entry Delay | 30 sec |
| Sequence Position | 1 |

Golden Profile의 Template은 Preferred Altitude, Preferred Heading, Other Speed, Other Altitude 순서이며
마지막에 `NO_ACTION`을 추가한다. Preferred Altitude Hint가 있으면 해당 절대 고도를 사용한다. Hint가
없으면 Preferred는 1,000 ft 상승하되 Ceiling을 넘지 않고, Other Altitude 후보는 1,000 ft 하강하되
0 ft 아래로 내려가지 않는다. Speed 후보는 Profile Min Speed보다 낮아지지 않는다.

비용은 `ASM-027 POC GENERATION INPUTS`에 기록된 비교용 잠정값이며 실제 연료 또는 운항비용이
아니다. 생성 Profile을 교체하면 Template, 기동 크기와 비용 입력을 함께 바꿀 수 있다.

### 7.2 Golden Demo 계산 결과

실제 Simulation T+70 HIGH Conflict와 T+75 State를 입력하면 다음 값이 계산된다.

| ID | 계산 결과 |
|---|---|
| `CAND-A` | `MIL-F01`, Target Altitude 9,000 ft Hint |
| `CAND-B` | `MIL-F01`, Heading 180° + 20° = 200° |
| `CAND-C` | `CIV-A02`, Speed 250 − 30 = 220 kt |
| `CAND-D` | `CIV-A02`, Altitude 8,125 − 1,000 = 7,125 ft |
| `CAND-E` | `NO_ACTION` |

이 결과는 후보 값만 계산한 것이며 Scenario 문서의 SAFE/UNSAFE/INEFFECTIVE 판정을 의미하지 않는다.

## 8. Safety Validation Domain

Phase 9-C는 실제 Validator 계산 전에 결과와 증거의 타입 안전한 계약을 정의한다.

### 8.1 Verdict

| Verdict | 필수 의미 |
|---|---|
| `SAFE` | 1차 Conflict 해소, 2차 Conflict·성능·Rule 실패 없음 |
| `INEFFECTIVE` | Action 적용 후 다른 실패 없이 1차 Conflict만 지속 |
| `UNSAFE` | 2차 Conflict, 성능 또는 Rule 실패가 있거나 무조작 기준선이 Conflict를 유지 |

`NO_ACTION` 기준선이 자연스럽게 Conflict를 해소하고 다른 실패가 없다면 `SAFE`도 가능하다. Verdict는
Candidate 종류만으로 정하지 않고 재시뮬레이션 증거와 함께 결정한다.

### 8.2 Evidence

`CandidateSafetyValidationResult`는 다음을 함께 보존한다.

- Candidate와 Validation Result ID
- 평가 UTC와 Validation Profile ID
- Candidate 적용 후 Primary `ConflictEvent`
- 모든 Secondary `PREDICTED` Conflict
- Performance Envelope 가능 여부
- 출처가 있는 `SafetyRuleViolation`
- Verdict를 설명하는 안정적인 Reason Code

Reason Code와 실제 증거는 양방향으로 일치해야 한다. 예를 들어 Secondary Conflict가 있으면
`SECONDARY_CONFLICT_DETECTED`가 반드시 존재하고, 해당 Reason만 있고 Conflict가 없는 결과도
거부한다. Secondary Pair는 Primary Pair와 달라야 하며 ID와 Pair가 모두 고유해야 한다.

Rule 위반은 `MINIMUM_ALTITUDE`, `AIRSPACE`, `PROCEDURE`, `OTHER`로 구분하고 Rule ID, 대상 Aircraft,
설명과 Source Reference를 남긴다. Performance Envelope 실패는 Rule 위반과 별도 증거로 유지한다.

### 8.3 Validation Run

`ResolutionSafetyValidationRun`은 하나의 Candidate Batch에 대한 같은 UTC·Horizon·Profile의 결과를
Candidate ID 순으로 보존한다. Result ID와 Candidate ID는 각각 고유하며 `safe_results`는 원본을
변경하지 않는 파생 View다.

Phase 9-C는 Result를 직접 만들어 Golden 판정을 하드코딩하지 않는다. 실제 Candidate State 적용,
재예측과 Conflict 탐지는 Phase 9-D Validator의 책임이다.

## 9. Isolated Resolution Safety Validator

Phase 9-D의 `IsolatedResolutionSafetyValidator`는 Candidate마다 Aircraft State Mapping을 복제하고
다음 순서로 검증한다.

1. Candidate 대상 State에 기동을 적용한다.
2. 같은 120초 Horizon의 Continuous Relative-Motion CPA 계산으로 모든 Traffic Pair를 재평가한다.
3. Source Conflict Pair를 1차 Conflict로, 나머지 `PREDICTED` Pair를 2차 Conflict로 분리한다.
4. 대상 Aircraft Performance Profile과 잠정 최저고도 Rule을 검사한다.
5. 계산 증거를 Phase 9-C의 `CandidateSafetyValidationResult`와
   `ResolutionSafetyValidationRun`으로 조립한다.

Generator와 Validator는 별도 서비스다. Validator는 원본 State, Candidate Batch 또는 실제 Aircraft
Runtime을 변경하지 않는다 (`ASM-028`). 입력 State는 동일한 UTC 시각이어야 하며 Batch 생성시각과
Candidate 적용시각도 이 시각과 일치해야 한다.

### 9.1 기동 적용 모델

현재 PoC는 `ASM-037`의 단순화된 즉시 목표 모델을 사용한다.

| Maneuver | 격리 State 적용 |
|---|---|
| Heading | 목표 침로로 교체 |
| Altitude | 목표 고도로 교체하고 수직속도 0으로 유지 |
| Speed | 목표 지상속도로 교체 |
| Entry Delay | 현재 속도·침로·수직속도 방향의 이동량만큼 State를 뒤로 이동 |
| Sequence Change | 운동학적 State 변경 없음 |
| No Action | State 변경 없음 |

Performance 검사는 60초 명령 실행시간을 기준으로 최소/최대 속도, Ceiling, 상승·강하율, 선회율과
한 번의 최대 속도 변화 50 kt를 확인한다. 잠정 최저고도 7,500 ft는 `AltitudeManeuver`의 목표값에만
적용하며 현재 Traffic 전체에 대한 공식 최저고도로 해석하지 않는다.

### 9.2 Golden Demo 실제 계산 결과

T+70 Conflict, T+75 Candidate와 전체 8대 Traffic State를 입력하면 현재 계산은 다음 결과를 만든다.

| Candidate | 계산 판정 | 핵심 증거 |
|---|---|---|
| `CAND-A` | `SAFE` | 1차 Conflict 해소, 추가 실패 없음 |
| `CAND-B` | `INEFFECTIVE` | 현재 즉시 목표 침로 모델에서는 1차 Conflict 지속 |
| `CAND-C` | `INEFFECTIVE` | 감속 후에도 1차 Conflict 지속 |
| `CAND-D` | `UNSAFE` | 7,125 ft 목표가 잠정 최저고도 Rule 위반 |
| `CAND-E` | `UNSAFE` | 조작 없음 기준선에서 1차 Conflict 지속 |

Scenario Contract는 `CAND-B`가 1차 Conflict를 해소한 뒤 `MIL-F02`와 2차 근접을 만드는 것을 목표로
한다. 현재 결과는 이를 아직 재현하지 못하므로 판정을 하드코딩하지 않고, 후속 Golden Resolution
Calibration에서 Aircraft 초기조건 또는 기동 실행 모델을 조정한다.

## 10. 다음 단계

Golden Resolution Calibration으로 Scenario Contract와 계산 결과를 정합시킨 뒤, 안전한 Candidate만
대상으로 결정론적 Recommendation 순위를 계산한다.
