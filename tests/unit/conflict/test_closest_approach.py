from datetime import UTC, datetime, timedelta

import pytest

from sentry_atm.conflict import (
    DEFAULT_CPA_HORIZON_SECONDS,
    ClosestApproachResult,
    ConstantVelocityClosestApproachCalculator,
)
from sentry_atm.domain import (
    AircraftState,
    ConflictPair,
    DataSource,
    SeparationMinimum,
)

NOW_UTC = datetime(2026, 9, 2, 3, 0, tzinfo=UTC)


def _state(
    aircraft_id: str,
    *,
    x_nm: float,
    y_nm: float,
    altitude_ft: float = 10_000.0,
    ground_speed_kt: float = 360.0,
    heading_deg: float,
    vertical_speed_fpm: float = 0.0,
    timestamp_utc: datetime = NOW_UTC,
) -> AircraftState:
    return AircraftState(
        aircraft_id=aircraft_id,
        timestamp_utc=timestamp_utc,
        x_nm=x_nm,
        y_nm=y_nm,
        altitude_ft=altitude_ft,
        ground_speed_kt=ground_speed_kt,
        heading_deg=heading_deg,
        vertical_speed_fpm=vertical_speed_fpm,
        source=DataSource.SYNTHETIC,
    )


def test_head_on_same_altitude_has_zero_cpa_at_expected_tcpa() -> None:
    calculator = ConstantVelocityClosestApproachCalculator(horizon_seconds=120)
    west = _state("CIV-A01", x_nm=-10.0, y_nm=0.0, heading_deg=90.0)
    east = _state("MIL-F01", x_nm=10.0, y_nm=0.0, heading_deg=270.0)

    result = calculator.calculate(west, east)

    assert result.pair.aircraft_ids == ("CIV-A01", "MIL-F01")
    assert result.evaluated_at_utc == NOW_UTC
    assert result.tcpa_seconds == pytest.approx(100.0)
    assert result.closest_approach_time_utc == NOW_UTC + timedelta(seconds=100)
    assert result.minimum_separation.horizontal_nm == pytest.approx(0.0, abs=1e-12)
    assert result.minimum_separation.vertical_ft == 0.0


def test_perpendicular_crossing_calculates_continuous_cpa_between_samples() -> None:
    calculator = ConstantVelocityClosestApproachCalculator(horizon_seconds=120)
    eastbound = _state("CIV-A01", x_nm=-10.0, y_nm=0.0, heading_deg=90.0)
    southbound = _state("CIV-A02", x_nm=0.0, y_nm=10.0, heading_deg=180.0)

    result = calculator.calculate(eastbound, southbound)

    assert result.tcpa_seconds == pytest.approx(100.0)
    assert result.minimum_separation.horizontal_nm == pytest.approx(0.0, abs=1e-12)


def test_vertical_separation_is_evaluated_at_horizontal_tcpa() -> None:
    calculator = ConstantVelocityClosestApproachCalculator(horizon_seconds=120)
    level = _state("CIV-A01", x_nm=-10.0, y_nm=0.0, heading_deg=90.0)
    descending = _state(
        "MIL-F01",
        x_nm=10.0,
        y_nm=0.0,
        altitude_ft=12_000.0,
        heading_deg=270.0,
        vertical_speed_fpm=-600.0,
    )

    result = calculator.calculate(level, descending)

    assert result.tcpa_seconds == pytest.approx(100.0)
    assert result.minimum_separation.vertical_ft == pytest.approx(1_000.0)


def test_parallel_equal_velocity_uses_current_separation_and_zero_tcpa() -> None:
    calculator = ConstantVelocityClosestApproachCalculator()
    first = _state("CIV-A01", x_nm=0.0, y_nm=0.0, heading_deg=0.0)
    second = _state("CIV-A02", x_nm=3.0, y_nm=4.0, heading_deg=0.0)

    result = calculator.calculate(first, second)

    assert calculator.horizon_seconds == DEFAULT_CPA_HORIZON_SECONDS
    assert result.tcpa_seconds == 0.0
    assert result.minimum_separation.horizontal_nm == pytest.approx(5.0)


def test_diverging_pair_clamps_tcpa_to_current_time() -> None:
    calculator = ConstantVelocityClosestApproachCalculator(horizon_seconds=120)
    westbound = _state("CIV-A01", x_nm=-1.0, y_nm=0.0, heading_deg=270.0)
    eastbound = _state("CIV-A02", x_nm=1.0, y_nm=0.0, heading_deg=90.0)

    result = calculator.calculate(westbound, eastbound)

    assert result.tcpa_seconds == 0.0
    assert result.minimum_separation.horizontal_nm == pytest.approx(2.0)


def test_closest_approach_beyond_horizon_is_clamped_to_horizon_end() -> None:
    calculator = ConstantVelocityClosestApproachCalculator(horizon_seconds=30)
    west = _state(
        "CIV-A01",
        x_nm=-5.0,
        y_nm=0.0,
        ground_speed_kt=180.0,
        heading_deg=90.0,
    )
    east = _state(
        "CIV-A02",
        x_nm=5.0,
        y_nm=0.0,
        ground_speed_kt=180.0,
        heading_deg=270.0,
    )

    result = calculator.calculate(west, east)

    assert result.tcpa_seconds == 30.0
    assert result.closest_approach_time_utc == NOW_UTC + timedelta(seconds=30)
    assert result.minimum_separation.horizontal_nm == pytest.approx(7.0)


def test_calculation_is_symmetric_for_reversed_aircraft_input() -> None:
    calculator = ConstantVelocityClosestApproachCalculator(horizon_seconds=120)
    first = _state("MIL-F01", x_nm=-10.0, y_nm=0.0, heading_deg=90.0)
    second = _state("CIV-A02", x_nm=10.0, y_nm=0.0, heading_deg=270.0)

    forward = calculator.calculate(first, second)
    reversed_result = calculator.calculate(second, first)

    assert forward == reversed_result


@pytest.mark.parametrize("invalid_horizon", [0.0, -1.0, True, float("inf")])
def test_calculator_rejects_invalid_horizon(invalid_horizon: object) -> None:
    expected_error = TypeError if invalid_horizon is True else ValueError

    with pytest.raises(expected_error, match="horizon_seconds"):
        ConstantVelocityClosestApproachCalculator(
            horizon_seconds=invalid_horizon,  # type: ignore[arg-type]
        )


def test_calculator_requires_distinct_same_time_aircraft_states() -> None:
    calculator = ConstantVelocityClosestApproachCalculator()
    first = _state("CIV-A01", x_nm=0.0, y_nm=0.0, heading_deg=90.0)
    later = _state(
        "CIV-A02",
        x_nm=1.0,
        y_nm=0.0,
        heading_deg=90.0,
        timestamp_utc=NOW_UTC + timedelta(seconds=1),
    )
    duplicate = _state("CIV-A01", x_nm=1.0, y_nm=0.0, heading_deg=270.0)

    with pytest.raises(TypeError, match="AircraftState"):
        calculator.calculate(first, "state")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="same timestamp"):
        calculator.calculate(first, later)
    with pytest.raises(ValueError, match="distinct"):
        calculator.calculate(first, duplicate)


def test_closest_approach_result_rejects_invalid_components_or_time_range() -> None:
    pair = ConflictPair("CIV-A02", "CIV-A01")
    minimum = SeparationMinimum(1.0, 500.0)
    valid_values = {
        "pair": pair,
        "evaluated_at_utc": NOW_UTC,
        "closest_approach_time_utc": NOW_UTC + timedelta(seconds=30),
        "minimum_separation": minimum,
        "horizon_seconds": 120.0,
    }

    assert pair.aircraft_ids == ("CIV-A01", "CIV-A02")
    assert minimum.horizontal_nm == 1.0
    with pytest.raises(TypeError, match="ConflictPair"):
        ClosestApproachResult(**(valid_values | {"pair": "pair"}))
    with pytest.raises(TypeError, match="SeparationMinimum"):
        ClosestApproachResult(**(valid_values | {"minimum_separation": "minimum"}))
    with pytest.raises(ValueError, match="must not precede"):
        ClosestApproachResult(
            **(valid_values | {"closest_approach_time_utc": NOW_UTC - timedelta(seconds=1)})
        )
    with pytest.raises(ValueError, match="must not exceed"):
        ClosestApproachResult(
            **(valid_values | {"closest_approach_time_utc": NOW_UTC + timedelta(seconds=121)})
        )
