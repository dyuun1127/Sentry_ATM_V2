import math

import pytest

from sentry_atm.domain.units import (
    as_finite_float,
    as_heading_deg,
    feet_to_meters,
    fpm_to_ft_per_second,
    knots_to_nm_per_second,
    meters_to_feet,
    meters_to_nm,
    nm_to_meters,
    normalize_heading_deg,
)


def test_distance_conversions_round_trip() -> None:
    assert nm_to_meters(1.0) == 1_852.0
    assert meters_to_nm(1_852.0) == 1.0


def test_altitude_conversions_round_trip() -> None:
    altitude_ft = 10_000.0

    assert meters_to_feet(feet_to_meters(altitude_ft)) == pytest.approx(altitude_ft)


def test_speed_conversions_use_project_units() -> None:
    assert knots_to_nm_per_second(360.0) == pytest.approx(0.1)
    assert fpm_to_ft_per_second(-600.0) == pytest.approx(-10.0)


def test_heading_policy_rejects_out_of_range_values() -> None:
    assert as_heading_deg(359.9) == 359.9
    with pytest.raises(ValueError, match=r"\[0, 360\)"):
        as_heading_deg(360.0)


def test_heading_normalization_is_explicit() -> None:
    assert normalize_heading_deg(370.0) == 10.0
    assert normalize_heading_deg(-10.0) == 350.0


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_numeric_policy_rejects_non_finite_values(value: float) -> None:
    with pytest.raises(ValueError, match="finite"):
        as_finite_float(value, field_name="value")


def test_numeric_policy_rejects_boolean_values() -> None:
    with pytest.raises(TypeError, match="real number"):
        as_finite_float(True, field_name="value")
