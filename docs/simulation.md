# Simulation Time and Playback Runtime

## 1. 목적

SENTRY의 Playback Aircraft, Synthetic Aircraft 및 후속 Rolling Prediction이 같은 재현 가능한 UTC Simulation Time을 사용하도록 한다. Phase 2-A는 공통 Clock을, Phase 2-B는 기록된 OPENSKY 상태를 Clock에 맞춰 조회하는 Playback Runtime을 제공한다.

구현 위치:

```text
src/sentry_atm/simulation/clock.py
src/sentry_atm/simulation/playback.py
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

## 7. 현재 제한사항

- 종료 시각과 `FINISHED` 상태는 아직 없다.
- 재생 배속과 실제 화면 Frame Rate를 연결하지 않는다.
- 5초 Rolling Prediction 갱신 스케줄은 Predictor 구현 단계에서 추가한다.
- 기록 사이 위치·고도 보간은 아직 수행하지 않는다.
- CSV와 OpenSky 원본 자료를 `AircraftState`로 변환하는 Adapter는 아직 없다.
- Synthetic Aircraft Runtime은 후속 Phase에서 별도로 구현한다.
