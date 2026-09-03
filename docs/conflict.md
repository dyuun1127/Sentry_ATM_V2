# Predictive Conflict Domain Contract

## 1. 범위

Phase 6-A는 미래 충돌 계산 결과를 표현하는 불변 Domain 계약과 교체 가능한 분리 Rule을 정의한다.
Phase 6-B는 같은 UTC Snapshot의 Aircraft 두 대에 대해 Constant-Velocity 수평 CPA/TCPA를
연속시간으로 계산한다. Phase 6-C는 Snapshot의 모든 고유 Pair를 평가하고 Phase 6-D는 이를
Simulation Clock 기반으로 반복한다. Phase 6-E는 Golden Demo의 실제 상태 전환을 이 계산 경로로
검증한다. Risk, Priority와 대응 후보 생성은 포함하지 않는다.

## 2. Domain 객체

| 객체 | 책임 |
|---|---|
| `ConflictPair` | 서로 다른 두 Aircraft ID를 사전순으로 정규화한다. |
| `SeparationMinimum` | 최근접점의 수평거리 NM와 수직거리 ft를 보존한다. |
| `SeparationRuleProfile` | 출처가 명시된 수평·수직 임계값으로 최소분리를 분류한다. |
| `ConflictEvent` | Pair, 평가시각, 최근접 예상시각, 최소분리와 사용 Rule을 보존한다. |
| `ConflictStatus` | `SAFE` 또는 `PREDICTED` 결과만 표현한다. |

Pair의 입력 순서가 달라도 같은 Pair Key가 만들어진다.

```text
ConflictPair(MIL-F01, CIV-A02)
ConflictPair(CIV-A02, MIL-F01)
→ (CIV-A02, MIL-F01)
```

## 3. Rule Profile

기본 `POC_TERMINAL_V1`은 `ASM-018`에 기록된 잠정 PoC 시작값이다.

| 값 | 기준 |
|---|---:|
| 수평 | 5 NM |
| 수직 | 1,000 ft |

판정식은 다음과 같다.

```text
PREDICTED = horizontal_nm < horizontal_threshold_nm
            AND vertical_ft < vertical_threshold_ft
```

두 조건이 같은 예측시각에 모두 성립해야 한다. 어느 한 값이라도 기준 이상이면 `SAFE`이며, 정확한
경계값도 `SAFE`로 취급한다. 이는 공식적인 보편 관제 분리기준이 아니며 Detector에는 다른
`SeparationRuleProfile`을 주입할 수 있어야 한다.

## 4. 시간과 재현성

- 모든 시각은 timezone-aware UTC로 정규화한다.
- 최근접 예상시각은 평가시각보다 이를 수 없다.
- TCPA는 `(closest_approach_time_utc - evaluated_at_utc)`에서 초 단위로 계산한다.
- 결과에는 적용한 `rule_profile_id`를 남겨 동일 조건으로 재현할 수 있게 한다.

## 5. 다음 단계 경계

### 5.1 Phase 6-B 상대운동 계산

Heading 0도를 North, 90도를 East로 두고 각 Aircraft의 수평속도를 Local x/y NM/s로 변환한다.

```text
r = position_second - position_first
v = velocity_second - velocity_first
unbounded_tcpa = -(r · v) / |v|²
tcpa = clamp(unbounded_tcpa, 0, horizon_seconds)
```

- 상대 수평속도가 0이면 현재 분리가 Horizon 전체에서 동일하므로 TCPA를 0초로 고정한다.
- 이미 발산 중이면 TCPA를 0초로 제한한다.
- 최근접점이 Horizon 밖이면 Horizon 종료시각으로 제한한다.
- 수직분리는 수평 CPA가 발생하는 동일 시각에 Constant Vertical Rate로 계산한다.
- 기본 Horizon은 `ASM-016`과 맞춘 120초이며 생성자에서 교체할 수 있다.
- 입력 State는 같은 UTC Snapshot이어야 하고 서로 다른 Aircraft ID를 가져야 한다.

이는 수평 최근접점 계산이다. 수직분리만 별도로 최소화하거나 서로 다른 시각의 최소 수평·수직 값을
결합하지 않는다. 실제 Conflict는 같은 시각의 분리를 Rule Profile로 평가해야 한다.

### 5.2 Phase 6-C Pairwise Detector

Phase 6-C의 `PairwiseConflictDetector`는 입력을 Aircraft ID로 정렬한 후 중복 없는 모든 조합을
계산한다. 항공기 수가 `n`이면 Assessment 수는 `n(n-1)/2`다.

- `assess(states)`: `SAFE`와 `PREDICTED`를 포함한 모든 `ConflictEvent` 반환
- `detect(states)`: 전체 Assessment 중 `PREDICTED`만 반환
- 입력 순서와 관계없이 Pair 순서, Conflict ID와 결과가 동일함
- 모든 입력 State는 같은 UTC Snapshot과 고유한 Aircraft ID를 가져야 함
- 빈 입력 또는 Aircraft 한 대는 유효하며 빈 결과를 반환함
- 각 결과에는 평가시각, Pair와 적용한 Rule Profile ID가 포함됨

`SAFE` 결과도 보존할 수 있어 특정 Pair가 왜 탐지되지 않았는지 최소분리와 적용 Rule을 통해 설명할
수 있다. Detector는 Risk 또는 Priority를 계산하지 않으며 Aircraft Runtime도 변경하지 않는다.

### 5.3 Phase 6-D Rolling Conflict Integration

`ConflictAssessmentService`는 `TrafficSnapshot`을 하나의 불변 `ConflictAssessmentRun`으로
변환한다. Run은 다음 값을 보존한다.

- 결정론적 Assessment Run ID
- 입력 Snapshot UTC
- CPA Look-ahead Horizon
- 적용한 Separation Rule Profile ID
- Pair 순서가 고정된 전체 `ConflictEvent`
- `PREDICTED`만 반환하는 `predicted_events` 파생값

Playback의 Zero-order Hold State는 기록시각이 Snapshot보다 과거일 수 있다. Service는 해당 State를
Constant Speed·Heading·Vertical Rate로 Snapshot UTC까지 먼저 전파한다. Snapshot보다 미래인
State는 입력 오류로 거부한다.

`RollingConflictScheduler`는 기본 5초 Simulation Time 구간마다 최대 한 번 현재 Snapshot을
평가한다.

1. Clock이 `RUNNING`일 때만 실행한다.
2. 동일 구간의 중복 호출은 `None`을 반환한다.
3. Pause 중에는 실행하지 않고 Resume 후 아직 평가하지 않은 현재 구간을 실행한다.
4. 큰 Tick 이동은 과거 Run을 소급 생성하지 않고 현재 Snapshot 한 건만 평가한다.
5. Clock Reset을 인식해 T+0의 동일 Run ID와 결과를 재현한다.

Scheduler와 Service는 Clock이나 Aircraft Runtime을 변경하지 않는다. Simulation Engine도 Conflict
구현을 직접 참조하지 않으며 현재 Snapshot만 제공한다.

### 5.4 Phase 6-E Golden Demo Calibration

Golden Scenario는 `MIL-F01`에 T+60 실제 State Anchor를 둔다. 이 값은 T+60 계획 상태와 비교해
고도 7,400 ft, 수평 이탈 2.1 NM이며 이벤트 방출과 같은 Clock 시각에 활성화된다.

기존 `SyntheticAircraftRuntime` → `TrafficSnapshot` → `ConflictAssessmentService` →
`PairwiseConflictDetector` → CPA Calculator 경로를 그대로 사용한 결과는 다음과 같다.

| 평가시각 | Pair | TCPA | 수평 최소분리 | 수직 최소분리 | 판정 |
|---|---|---:|---:|---:|---|
| T+0 | 전체 28 Pair | - | - | - | `PREDICTED` 0건 |
| T+60 | `CIV-A02` / `MIL-F01` | 100초 | 2.3 NM | 500 ft | `PREDICTED` |
| T+70 | `CIV-A02` / `MIL-F01` | 90초 | 2.3 NM | 500 ft | `PREDICTED` |

T+60의 현재 수평분리는 약 6.16 NM, T+70은 약 5.63 NM이므로 두 평가시각의 현재 상태는 안전하다.
최근접 예상시각은 T+160으로 동일하다. Detector와 Rule Profile에는 Aircraft ID, 시나리오 시각,
목표 분리값을 위한 전용 분기를 추가하지 않았다. Clock Reset 후에도 이벤트와 Assessment가 동일하게
재생된다.

### 5.5 후속 단계

- Phase 7-B: Conflict Risk와 운항 Priority의 결정론적 Evaluator
