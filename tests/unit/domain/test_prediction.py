from datetime import datetime, timedelta

import pytest

from sentry_atm.domain import PredictionRun, Trajectory, TrajectoryPoint, TrajectoryType
from sentry_atm.domain.time_policy import KST, UTC

INPUT_UTC = datetime(2026, 9, 1, 3, 0, tzinfo=UTC)


def _trajectory(
    aircraft_id: str = "CIV-A01",
    trajectory_type: TrajectoryType = TrajectoryType.PREDICTED,
) -> Trajectory:
    return Trajectory(
        aircraft_id=aircraft_id,
        trajectory_type=trajectory_type,
        points=(
            TrajectoryPoint(
                timestamp_utc=INPUT_UTC + timedelta(seconds=30),
                x_nm=1.0,
                y_nm=2.0,
                altitude_ft=8_000.0,
            ),
        ),
    )


def _run(**overrides: object) -> PredictionRun:
    values: dict[str, object] = {
        "prediction_run_id": "PRED-001",
        "input_timestamp_utc": datetime(2026, 9, 1, 12, 0, tzinfo=KST),
        "generated_at_utc": datetime(2026, 9, 1, 12, 0, 1, tzinfo=KST),
        "model_name": "constant-velocity",
        "model_version": "1.0.0",
        "horizons_seconds": (30, 60, 120),
        "trajectories": (_trajectory(),),
        "configuration_id": "BASELINE-V1",
    }
    values.update(overrides)
    return PredictionRun(**values)  # type: ignore[arg-type]


def test_prediction_run_normalizes_time_and_materializes_sequences() -> None:
    horizons = [30, 60, 120]
    trajectories = [_trajectory()]

    run = _run(horizons_seconds=horizons, trajectories=trajectories)
    horizons.append(180)
    trajectories.clear()

    assert run.input_timestamp_utc == INPUT_UTC
    assert run.horizons_seconds == (30, 60, 120)
    assert run.trajectories == (_trajectory(),)


@pytest.mark.parametrize(
    ("horizons", "error_type", "message"),
    [
        ((), ValueError, "must not be empty"),
        ((30, 30), ValueError, "strictly increasing"),
        ((60, 30), ValueError, "strictly increasing"),
        ((0, 30), ValueError, "positive"),
        ((True, 30), TypeError, "integers"),
        ((30.0, 60), TypeError, "integers"),
    ],
)
def test_prediction_run_rejects_invalid_horizons(
    horizons: tuple[object, ...],
    error_type: type[Exception],
    message: str,
) -> None:
    with pytest.raises(error_type, match=message):
        _run(horizons_seconds=horizons)


def test_prediction_run_rejects_non_predicted_trajectory() -> None:
    with pytest.raises(ValueError, match="must be PREDICTED"):
        _run(trajectories=(_trajectory(trajectory_type=TrajectoryType.ACTUAL),))


def test_prediction_run_rejects_duplicate_aircraft_trajectories() -> None:
    with pytest.raises(ValueError, match="at most one trajectory"):
        _run(trajectories=(_trajectory(), _trajectory()))


def test_prediction_run_rejects_invalid_trajectory_element() -> None:
    with pytest.raises(TypeError, match="Trajectory instances"):
        _run(trajectories=("CIV-A01",))
