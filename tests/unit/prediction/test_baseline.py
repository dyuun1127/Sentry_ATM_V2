from datetime import UTC, datetime, timedelta
from math import sqrt

import pytest

from sentry_atm.domain import AircraftState, DataSource, TrajectoryType
from sentry_atm.prediction import DEFAULT_HORIZONS_SECONDS, ConstantVelocityPredictor

INPUT_TIME_UTC = datetime(2026, 9, 1, 3, 0, tzinfo=UTC)


def _state(
    *,
    x_nm: float = 0.0,
    y_nm: float = 0.0,
    altitude_ft: float = 8_000.0,
    ground_speed_kt: float = 360.0,
    heading_deg: float = 90.0,
    vertical_speed_fpm: float = 600.0,
    source: DataSource = DataSource.SYNTHETIC,
) -> AircraftState:
    return AircraftState(
        aircraft_id="CIV-A01",
        timestamp_utc=INPUT_TIME_UTC,
        x_nm=x_nm,
        y_nm=y_nm,
        altitude_ft=altitude_ft,
        ground_speed_kt=ground_speed_kt,
        heading_deg=heading_deg,
        vertical_speed_fpm=vertical_speed_fpm,
        source=source,
    )


def test_default_predictor_generates_30_60_120_second_4dt() -> None:
    trajectory = ConstantVelocityPredictor().predict(_state())

    assert DEFAULT_HORIZONS_SECONDS == (30, 60, 120)
    assert trajectory.aircraft_id == "CIV-A01"
    assert trajectory.trajectory_type is TrajectoryType.PREDICTED
    assert tuple(point.timestamp_utc for point in trajectory.points) == tuple(
        INPUT_TIME_UTC + timedelta(seconds=seconds) for seconds in (30, 60, 120)
    )
    assert tuple(point.x_nm for point in trajectory.points) == pytest.approx((3.0, 6.0, 12.0))
    assert tuple(point.y_nm for point in trajectory.points) == pytest.approx(
        (0.0, 0.0, 0.0), abs=1e-12
    )
    assert tuple(point.altitude_ft for point in trajectory.points) == pytest.approx(
        (8_300.0, 8_600.0, 9_200.0)
    )


@pytest.mark.parametrize(
    ("heading_deg", "expected_x", "expected_y"),
    [
        (0.0, 0.0, 3.0),
        (90.0, 3.0, 0.0),
        (180.0, 0.0, -3.0),
        (270.0, -3.0, 0.0),
    ],
)
def test_predictor_uses_rktu_local_heading_axes(
    heading_deg: float,
    expected_x: float,
    expected_y: float,
) -> None:
    predictor = ConstantVelocityPredictor((30,))

    point = predictor.predict(_state(heading_deg=heading_deg, vertical_speed_fpm=0.0)).points[0]

    assert point.x_nm == pytest.approx(expected_x, abs=1e-12)
    assert point.y_nm == pytest.approx(expected_y, abs=1e-12)


def test_diagonal_projection_preserves_travel_distance() -> None:
    point = ConstantVelocityPredictor((30,)).predict(_state(heading_deg=45.0)).points[0]

    assert point.x_nm == pytest.approx(3.0 / sqrt(2.0))
    assert point.y_nm == pytest.approx(3.0 / sqrt(2.0))
    assert point.x_nm**2 + point.y_nm**2 == pytest.approx(9.0)


def test_predictor_supports_descent_and_opensky_state_without_mutation() -> None:
    state = _state(
        x_nm=2.0,
        y_nm=-1.0,
        ground_speed_kt=0.0,
        vertical_speed_fpm=-1_200.0,
        source=DataSource.OPENSKY,
    )

    first = ConstantVelocityPredictor((30, 60)).predict(state)
    second = ConstantVelocityPredictor((30, 60)).predict(state)

    assert first == second
    assert tuple(point.altitude_ft for point in first.points) == (7_400.0, 6_800.0)
    assert state == _state(
        x_nm=2.0,
        y_nm=-1.0,
        ground_speed_kt=0.0,
        vertical_speed_fpm=-1_200.0,
        source=DataSource.OPENSKY,
    )


def test_predictor_uses_explicit_reference_time_for_stale_playback_state() -> None:
    state = _state(ground_speed_kt=360.0, vertical_speed_fpm=0.0)
    reference_time = INPUT_TIME_UTC + timedelta(seconds=10)

    point = (
        ConstantVelocityPredictor((30,))
        .predict(
            state,
            reference_time_utc=reference_time,
        )
        .points[0]
    )

    assert point.timestamp_utc == INPUT_TIME_UTC + timedelta(seconds=40)
    assert point.x_nm == pytest.approx(4.0)


def test_predictor_rejects_reference_time_before_state() -> None:
    with pytest.raises(ValueError, match="must not be earlier"):
        ConstantVelocityPredictor().predict(
            _state(),
            reference_time_utc=INPUT_TIME_UTC - timedelta(seconds=1),
        )


def test_predictor_materializes_custom_horizons() -> None:
    horizons = [10, 20]
    predictor = ConstantVelocityPredictor(horizons)
    horizons.append(30)

    assert predictor.horizons_seconds == (10, 20)


@pytest.mark.parametrize(
    ("horizons", "error_type", "message"),
    [
        ((), ValueError, "must not be empty"),
        ((0, 30), ValueError, "positive"),
        ((30, 30), ValueError, "strictly increasing"),
        ((60, 30), ValueError, "strictly increasing"),
        ((True, 30), TypeError, "integers"),
        ((30.0, 60), TypeError, "integers"),
        ("30,60", TypeError, "iterable of integers"),
        (None, TypeError, "iterable of integers"),
    ],
)
def test_predictor_rejects_invalid_horizons(
    horizons: object,
    error_type: type[Exception],
    message: str,
) -> None:
    with pytest.raises(error_type, match=message):
        ConstantVelocityPredictor(horizons)  # type: ignore[arg-type]


def test_predictor_rejects_non_aircraft_state() -> None:
    with pytest.raises(TypeError, match="AircraftState"):
        ConstantVelocityPredictor().predict("CIV-A01")  # type: ignore[arg-type]
