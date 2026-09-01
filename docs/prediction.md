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
- 다중 Aircraft 실행 주기와 `PredictionRun` 생성은 후속 Phase에서 결합한다.

따라서 이 결과는 충돌 예측 파이프라인을 검증하기 위한 Baseline이며 실제 항공기 성능 예측이나
운항 판단에 사용할 수 없다.
