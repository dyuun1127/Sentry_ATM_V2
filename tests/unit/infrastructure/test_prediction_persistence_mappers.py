from datetime import UTC, datetime, timedelta

import pytest

from sentry_atm.domain import PredictionRun, Trajectory, TrajectoryPoint, TrajectoryType
from sentry_atm.infrastructure.persistence.mappers import (
    prediction_run_from_row,
    prediction_run_to_row,
    trajectory_from_rows,
    trajectory_point_from_row,
    trajectory_point_to_row,
    trajectory_to_row,
)

INPUT_UTC = datetime(2026, 9, 2, 3, 0, tzinfo=UTC)


def _trajectory(
    aircraft_id: str = "CIV-A01",
    trajectory_type: TrajectoryType = TrajectoryType.PREDICTED,
) -> Trajectory:
    return Trajectory(
        aircraft_id=aircraft_id,
        trajectory_type=trajectory_type,
        points=tuple(
            TrajectoryPoint(
                timestamp_utc=INPUT_UTC + timedelta(seconds=seconds),
                x_nm=float(seconds) / 10.0,
                y_nm=1.0,
                altitude_ft=8_000.0 + seconds,
            )
            for seconds in (30, 60, 120)
        ),
    )


def _prediction_run() -> PredictionRun:
    return PredictionRun(
        prediction_run_id="PRED-000000000005",
        input_timestamp_utc=INPUT_UTC,
        generated_at_utc=INPUT_UTC,
        model_name="constant-velocity",
        model_version="1.0.0",
        horizons_seconds=(30, 60, 120),
        trajectories=(_trajectory(), _trajectory("MIL-F01")),
        configuration_id="BASELINE-CV-V1",
    )


def test_prediction_aggregate_mappers_round_trip_all_fields_and_order() -> None:
    prediction_run = _prediction_run()
    run_row = prediction_run_to_row(prediction_run)
    restored_trajectories = []

    for trajectory_index, trajectory in enumerate(prediction_run.trajectories, start=1):
        trajectory_row = trajectory_to_row(
            trajectory,
            prediction_run_id=prediction_run.prediction_run_id,
            sequence_index=trajectory_index - 1,
        )
        trajectory_row.trajectory_id = trajectory_index
        point_rows = tuple(
            trajectory_point_to_row(
                point,
                trajectory_id=trajectory_index,
                sequence_index=point_index,
            )
            for point_index, point in enumerate(trajectory.points)
        )
        restored_trajectories.append(trajectory_from_rows(trajectory_row, point_rows))

    restored = prediction_run_from_row(run_row, tuple(restored_trajectories))

    assert run_row.horizons_seconds_json == "[30,60,120]"
    assert restored == prediction_run


def test_trajectory_point_mapper_round_trip() -> None:
    point = _trajectory().points[0]

    row = trajectory_point_to_row(point, trajectory_id=7, sequence_index=0)

    assert row.trajectory_id == 7
    assert trajectory_point_from_row(row) == point


def test_prediction_trajectory_mapper_rejects_non_predicted_trajectory() -> None:
    with pytest.raises(ValueError, match="PREDICTED"):
        trajectory_to_row(
            _trajectory(trajectory_type=TrajectoryType.ACTUAL),
            prediction_run_id="RUN-001",
            sequence_index=0,
        )


def test_prediction_mappers_reject_wrong_types() -> None:
    with pytest.raises(TypeError, match="PredictionRun"):
        prediction_run_to_row("run")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="PredictionRunRow"):
        prediction_run_from_row("row", ())  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="tuple of Trajectory"):
        prediction_run_from_row(prediction_run_to_row(_prediction_run()), [])  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="trajectory must be Trajectory"):
        trajectory_to_row("trajectory", prediction_run_id="RUN", sequence_index=0)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="TrajectoryRow"):
        trajectory_from_rows("row", ())  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="tuple of TrajectoryPointRow"):
        row = trajectory_to_row(_trajectory(), prediction_run_id="RUN", sequence_index=0)
        trajectory_from_rows(row, [])  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="point must be TrajectoryPoint"):
        trajectory_point_to_row("point", trajectory_id=1, sequence_index=0)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="TrajectoryPointRow"):
        trajectory_point_from_row("row")  # type: ignore[arg-type]
