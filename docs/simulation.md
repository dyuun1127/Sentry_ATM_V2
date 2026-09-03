# Simulation Time and Aircraft Runtimes

## 1. 목적

SENTRY의 Playback Aircraft, Synthetic Aircraft 및 후속 Rolling Prediction이 같은 재현 가능한 UTC Simulation Time을 사용하도록 한다. Phase 2-A는 공통 Clock을, Phase 2-B는 OPENSKY Playback Runtime을, Phase 2-C는 기초 Synthetic Runtime을, Phase 3-A는 다중 항공기 Traffic Engine을 제공한다.

구현 위치:

```text
src/sentry_atm/simulation/clock.py
src/sentry_atm/simulation/engine.py
src/sentry_atm/simulation/playback.py
src/sentry_atm/simulation/synthetic.py
```

## 2. 시간 모델

- 생성 시 timezone-aware 시작 시각을 반드시 전달한다.
- 시작 시각은 내부에서 UTC로 정규화한다.
- 기본 Tick은 `1.0초`다 (`ASM-017`).
- 현재 시각은 `시작 시각 + Tick 횟수 × Tick 간격`으로 계산한다.
- 실제 시스템 시각, `datetime.now()` 또는 `sleep()`에 의존하지 않는다.

이 구조를 사용하면 테스트와 데모를 같은 입력 순서로 실행했을 때 같은 시각과 결과를 재현할 수 있다.

## 3. 상태 전이

| 현재 상태 | 명령 | 다음 상태 | 시간 변화 |
|---|---|---|---|
| `READY` | `play()` | `RUNNING` | 없음 |
| `RUNNING` | `tick()` | `RUNNING` | 지정 Tick만큼 증가 |
| `RUNNING` | `pause()` | `PAUSED` | 없음 |
| `PAUSED` | `tick()` | `PAUSED` | 없음 |
| `PAUSED` | `play()` | `RUNNING` | 없음 |
| 모든 상태 | `reset()` | `READY` | 시작 시각으로 복원 |

`READY`에서 `pause()`를 호출하면 `READY`를 유지한다. `READY` 또는 `PAUSED` 상태의 `tick()`은 현재 시각을 반환하지만 시간을 증가시키지 않는다.

## 4. Public API

```python
from datetime import UTC, datetime

from sentry_atm.simulation import SimulationClock

clock = SimulationClock(
    start_time_utc=datetime(2026, 9, 1, 3, 0, tzinfo=UTC),
)
clock.play()
clock.tick(steps=5)

assert clock.elapsed_seconds == 5.0
```

## 5. 유효성 정책

- Naive datetime과 datetime이 아닌 시작값을 거부한다.
- Tick 간격은 유한한 양수여야 한다.
- `steps`는 bool이 아닌 양의 정수여야 한다.
- 상태 변경은 시뮬레이션 시각을 암묵적으로 증가시키지 않는다.

## 6. Playback Aircraft Runtime

`PlaybackAircraftRuntime`은 한 항공기의 시간순 OPENSKY `AircraftState` 기록과 `SimulationClock`을 결합한다.

```python
from sentry_atm.simulation import PlaybackAircraftRuntime

runtime = PlaybackAircraftRuntime(clock=clock, states=recorded_states)
state = runtime.current_state
```

선택 규칙:

1. Clock 시각과 같은 기록이 있으면 그 상태를 반환한다.
2. 기록 사이에서는 현재 시각보다 이전인 가장 최신 상태를 유지한다.
3. 첫 기록 이전에는 `None`을 반환한다.
4. 마지막 기록 이후에는 마지막 상태를 유지한다.
5. 입력 순서를 자동 정렬하지 않고 엄격한 시간 오름차순을 요구한다.

이 방식은 Zero-order Hold이며 원본 기록을 수정하거나 새 상태를 생성하지 않는다. Playback과 Synthetic Runtime의 책임 분리를 위해 `source=OPENSKY` 상태만 허용한다.

## 7. Synthetic Aircraft Runtime

`SyntheticAircraftRuntime`은 초기 `source=SYNTHETIC` 상태와 선택적인 미래 상태 Anchor를 사용해
Clock 현재 시각의 상태를 계산한다. 각 Anchor 사이에서는 속도, Heading 및 수직속도가 유지되는
구간별 Constant Motion을 적용한다.

```text
distance_nm = ground_speed_kt × elapsed_seconds / 3600
x = initial_x + distance_nm × sin(heading)
y = initial_y + distance_nm × cos(heading)
altitude = initial_altitude + vertical_speed_fpm × elapsed_seconds / 60
```

Heading은 Domain 정책과 동일하게 `0°=North`, `90°=East`다. 현재 시각 이전의 가장 최신 Anchor를
선택하고 그 Anchor와 Clock 시각으로 매번 다시 계산하므로 Reset과 반복 실행 결과가 동일하다.
Anchor는 같은 Aircraft ID와 `SYNTHETIC` Source를 사용하며 초기 State 뒤에 엄격한 시간순으로
배치해야 한다.

Phase 12-E부터 `apply_state_anchor()`는 현재 `RUNNING` Clock 시각과 일치하는 승인 State를 현재 Run의
동적 Anchor로 한 번 추가할 수 있다. ID와 Source가 Runtime과 같아야 하며 기존 Scenario/승인 Anchor와
같은 시각을 덮어쓸 수 없다. 동적 Anchor는 Clock Reset 시 제거되고 사전 Scenario Anchor는 유지된다.
이 저수준 Runtime 명령 자체는 승인 권한을 판단하지 않으며, Application Orchestrator가 감사된
`ACCEPT`를 먼저 검증한다.

초기 상태 시각 이전에는 `None`을 반환하며, 정확히 초기 시각이면 원래 상태를 반환한다. 이후 상태는 기존 식별자, 운동 값, 비행단계 및 비상 상태를 보존한다.

이 Runtime은 현재 Clock 시각의 단일 Actual State만 계산한다. 미래 시점 목록이나 `PREDICTED` Trajectory를 생성하지 않으므로 Phase 4 Predictor 책임과 분리된다.

## 8. Traffic Simulation Engine

`TrafficSimulationEngine`은 동일한 `SimulationClock`을 공유하는 Playback/Synthetic Runtime을 등록 순서대로 관리한다. 중복 Aircraft ID와 다른 Clock을 사용하는 Runtime은 거부한다.

```python
from sentry_atm.simulation import TrafficSimulationEngine

engine = TrafficSimulationEngine(
    clock=clock,
    runtimes=(civil_playback, military_synthetic),
)
clock.play()
snapshot = engine.tick()
```

`TrafficSnapshot`은 조회한 Simulation UTC 시각과 그 시각에 활성화된 Aircraft State들을 불변 tuple로 보존한다. 아직 시작하지 않은 Runtime은 제외된다. Playback은 Zero-order Hold를 사용하므로 개별 상태의 기록 시각이 Snapshot 시각보다 과거일 수 있으며, 두 시각을 동일한 의미로 취급하지 않는다.

Engine의 `tick()`은 Clock을 진행한 뒤 Snapshot을 반환한다. Clock이 `READY` 또는 `PAUSED`라면 시간이 증가하지 않은 Snapshot을 반환한다.

## 9. Rolling 계산 통합

`TrafficSimulationEngine`은 Predictor나 Conflict Detector를 직접 호출하지 않는다. Phase 4-C의
`RollingPredictionScheduler`와 Phase 6-D의 `RollingConflictScheduler`가 현재 Snapshot을 받아
각자의 기본 5초 Simulation Time 구간에 독립적으로 실행된다. 이 구조로 Simulation 진행, 미래
Trajectory 생성과 Conflict 판정을 분리한다.

## 10. 현재 제한사항

- 종료 시각과 `FINISHED` 상태는 아직 없다.
- 재생 배속과 실제 화면 Frame Rate를 연결하지 않는다.
- 기록 사이 위치·고도 보간은 아직 수행하지 않는다.
- CSV와 OpenSky 원본 자료를 `AircraftState`로 변환하는 Adapter는 아직 없다.
- Synthetic 운동은 각 State Anchor 사이에서만 Constant Speed, Constant Heading, Constant Vertical Rate를 지원한다.
- 선회율, 가감속, 목표 고도 Capture 및 Aircraft Performance 제한은 아직 없다.
- 범용 관제 명령 적용은 아직 없다. 동적 State Anchor 적용은 Golden Demo의 감사된 Altitude
  `ACCEPT` 한 건으로 제한한다.
- Runtime 동적 추가·제거는 아직 지원하지 않는다.
- 외부 Scenario 파일 Loader는 아직 없으며, 현재는 코드 기반 Golden Scenario Builder만 제공한다.
- Engine은 Predictor, Conflict Detector 또는 Rule Engine을 직접 호출하지 않는다.
