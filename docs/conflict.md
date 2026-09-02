# Predictive Conflict Domain Contract

## 1. 범위

Phase 6-A는 미래 충돌 계산 결과를 표현하는 불변 Domain 계약과 교체 가능한 분리 Rule을 정의한다.
Phase 6-B는 같은 UTC Snapshot의 Aircraft 두 대에 대해 Constant-Velocity 수평 CPA/TCPA를
연속시간으로 계산한다. Phase 6-C는 Snapshot의 모든 고유 Pair를 평가한다. Risk, Priority와 대응
후보 생성은 포함하지 않는다.

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

### 5.3 후속 단계

- Phase 6-D: Rolling Prediction Scheduler 연결
- Phase 6-E: Golden Demo의 `MIL-F01`/`CIV-A02` 미래 충돌 재현
