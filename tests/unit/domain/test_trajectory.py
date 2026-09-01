from datetime import datetime, timedelta

import pytest

from sentry_atm.domain.enums import TrajectoryType
from sentry_atm.domain.time_policy import UTC
from sentry_atm.domain.trajectory import Trajectory, TrajectoryPoint

BASE_TIME = datetime(2026, 9, 1, 3, 0, tzinfo=UTC)


def _point(seconds: int) -> TrajectoryPoint:
    return TrajectoryPoint(
        timestamp_utc=BASE_TIME + timedelta(seconds=seconds),
        x_nm=float(seconds),
        y_nm=0.0,
        altitude_ft=7_000.0,
    )


def test_trajectory_is_immutable_and_time_ordered() -> None:
    source_points = [_point(0), _point(30), _point(60)]

    trajectory = Trajectory.from_points(
        aircraft_id="CIV-A02",
        trajectory_type=TrajectoryType.PREDICTED,
        points=source_points,
    )
    source_points.append(_point(90))

    assert trajectory.points == (_point(0), _point(30), _point(60))
    assert trajectory.start_time_utc == BASE_TIME
    assert trajectory.end_time_utc == BASE_TIME + timedelta(seconds=60)
    assert trajectory.duration_seconds == 60.0


def test_trajectory_rejects_empty_points() -> None:
    with pytest.raises(ValueError, match="at least one point"):
        Trajectory(
            aircraft_id="CIV-A02",
            trajectory_type=TrajectoryType.ACTUAL,
            points=(),
        )


@pytest.mark.parametrize("seconds", [[0, 0], [30, 20]])
def test_trajectory_requires_strictly_increasing_time(seconds: list[int]) -> None:
    with pytest.raises(ValueError, match="strictly increasing"):
        Trajectory(
            aircraft_id="CIV-A02",
            trajectory_type=TrajectoryType.PLANNED,
            points=tuple(_point(second) for second in seconds),
        )


def test_trajectory_rejects_non_point_values() -> None:
    with pytest.raises(TypeError, match="TrajectoryPoint"):
        Trajectory(
            aircraft_id="CIV-A02",
            trajectory_type=TrajectoryType.ACTUAL,
            points=("not-a-point",),  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("aircraft_id", ["", "  "])
def test_trajectory_rejects_blank_aircraft_id(aircraft_id: str) -> None:
    with pytest.raises(ValueError, match="must not be blank"):
        Trajectory(
            aircraft_id=aircraft_id,
            trajectory_type=TrajectoryType.ACTUAL,
            points=(_point(0),),
        )
