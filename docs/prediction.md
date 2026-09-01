# Baseline Trajectory Predictor

## 1. 목적과 범위

Phase 4-A는 현재 `AircraftState` 하나에서 `+30`, `+60`, `+120초`의 Local 4DT를
결정론적으로 생성한다. 출력은 Actual State를 변경하지 않는 별도의 `PREDICTED Trajectory`다.

구현 위치:

```text
src/sentry_atm/prediction/baseline.py
```

## 2. 운동 가정

초기 Baseline은 예측 구간 동안 다음 값이 일정하다고 가정한다.

- Ground Speed
- Heading
- Vertical Speed

계산식:

```text
distance_nm = ground_speed_kt × horizon_seconds / 3600
x = current_x + distance_nm × sin(heading)
y = current_y + distance_nm × cos(heading)
altitude = current_altitude + vertical_speed_fpm × horizon_seconds / 60
```

Heading은 RKTU Local 좌표 정책과 동일하게 `0°=North`, `90°=East`다. 입력 State의
timezone-aware UTC 시각에 각 Horizon을 더해 예측시각을 만든다.

## 3. Public API

```python
from sentry_atm.prediction import ConstantVelocityPredictor

predictor = ConstantVelocityPredictor()
predicted_trajectory = predictor.predict(current_aircraft_state)
```

기본 Horizon은 `(30, 60, 120)`이며, 양의 정수가 엄격히 증가하는 형태로 교체할 수 있다.

## 4. 재현성과 경계

- 실제 현재시각이나 Simulation Clock을 직접 읽지 않는다.
- 같은 `AircraftState`와 Horizon은 항상 같은 `Trajectory`를 생성한다.
- `SYNTHETIC`과 `OPENSKY` State에 동일한 Domain 계산을 적용한다.
- Runtime, Aircraft State 및 Planned/Actual Trajectory를 변경하지 않는다.
- 모델 식별자는 `constant-velocity`, 버전은 `1.0.0`, 설정 ID는 `BASELINE-CV-V1`이다.

## 5. 현재 제한사항

- 선회, 가감속, 목표 고도 Capture 및 경로 Waypoint를 반영하지 않는다.
- Aircraft Performance Profile의 Envelope를 아직 적용하지 않는다.
- 풍향·풍속과 불확실성 구간을 반영하지 않는다.
- Horizon 사이의 조밀한 중간점을 생성하지 않는다.
- Prediction 저장 Adapter는 아직 결합하지 않는다.

따라서 이 결과는 충돌 예측 파이프라인을 검증하기 위한 Baseline이며 실제 항공기 성능 예측이나
운항 판단에 사용할 수 없다.

## 6. Multi-Aircraft Prediction Run

Phase 4-B의 `PredictionRunService`는 하나의 `TrafficSnapshot`에 포함된 모든 활성 State를
등록 순서대로 예측하고 하나의 `PredictionRun`으로 묶는다.

```python
from sentry_atm.prediction import ConstantVelocityPredictor, PredictionRunService

service = PredictionRunService(ConstantVelocityPredictor())
run = service.run(
    traffic_snapshot,
    prediction_run_id="RUN-0001",
    generated_at_utc=generated_at_utc,
)
```

- `input_timestamp_utc`: Snapshot 시각
- `generated_at_utc`: 호출자가 전달한 timezone-aware 생성시각
- `trajectories`: Snapshot의 Aircraft 순서를 보존한 예측 결과
- 모델 정보: Predictor의 이름·버전·설정 ID

Playback의 Zero-order Hold State는 기록시각이 Snapshot보다 과거일 수 있다. 이 경우 마지막
기록 위치에서 먼저 Snapshot 시각까지 동일 운동으로 전파한 뒤, Snapshot 기준 `+30/+60/+120초`
시각의 위치를 계산한다. Snapshot보다 미래인 State는 입력 오류로 거부한다.

자동 UUID나 실제 시스템 시각을 내부에서 생성하지 않는다. 호출자가 Run ID와 생성시각을
명시하므로 같은 입력으로 완전히 동일한 `PredictionRun`을 재현할 수 있다.

## 7. Deterministic Rolling Prediction Scheduler

Phase 4-C의 `RollingPredictionScheduler`는 기본 5초 Simulation Time 구간마다 최대 하나의
`PredictionRun`을 생성한다. Scheduler는 Clock을 진행시키지 않으며, Engine에서 얻은 현재
Snapshot을 전달받아 실행 여부만 판단한다.

```python
from sentry_atm.prediction import RollingPredictionScheduler

scheduler = RollingPredictionScheduler(clock=clock, service=service)
prediction_run = scheduler.run_if_due(traffic_snapshot)
```

실행 규칙:

1. Clock이 `RUNNING`일 때만 실행한다.
2. T+0부터 시작해 기본 5초 구간마다 한 번만 실행한다.
3. 같은 구간에서 반복 호출하면 `None`을 반환한다.
4. 큰 Tick 이동으로 경계를 건너뛰면 과거 Run을 만들지 않고 현재 Snapshot으로 한 번만 실행한다.
5. Pause 중에는 실행하지 않고 Resume 후 현재 구간이 아직 실행되지 않았으면 실행한다.
6. Clock Reset을 자동 인식해 T+0부터 같은 Run ID와 결과를 재현한다.

Run ID는 `<prefix>-<tick_count 12자리>` 형식이며 기본 Prefix는 `PRED`다. 생성시각도
Snapshot의 Simulation UTC를 사용하므로 wall clock, sleep, UUID 및 난수에 의존하지 않는다.
