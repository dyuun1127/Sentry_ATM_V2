"""Internal unit conversions and numeric validation helpers."""

from math import isfinite
from numbers import Real

METERS_PER_NM = 1_852.0
FEET_PER_METER = 3.280_839_895_013_123
SECONDS_PER_HOUR = 3_600.0
SECONDS_PER_MINUTE = 60.0


def as_finite_float(value: Real, *, field_name: str) -> float:
    """Convert a real number to float and reject booleans, NaN, and infinity."""

    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{field_name} must be a real number")
    numeric = float(value)
    if not isfinite(numeric):
        raise ValueError(f"{field_name} must be finite")
    return numeric


def as_non_negative_float(value: Real, *, field_name: str) -> float:
    """Validate a finite value that cannot be negative."""

    numeric = as_finite_float(value, field_name=field_name)
    if numeric < 0.0:
        raise ValueError(f"{field_name} must be non-negative")
    return numeric


def as_heading_deg(value: Real, *, field_name: str = "heading_deg") -> float:
    """Validate a heading in the canonical half-open range [0, 360)."""

    heading = as_finite_float(value, field_name=field_name)
    if not 0.0 <= heading < 360.0:
        raise ValueError(f"{field_name} must be in [0, 360)")
    return heading


def normalize_heading_deg(value: Real) -> float:
    """Normalize a finite angle to the canonical heading range [0, 360)."""

    return as_finite_float(value, field_name="heading_deg") % 360.0


def nm_to_meters(distance_nm: Real) -> float:
    """Convert nautical miles to meters."""

    return as_finite_float(distance_nm, field_name="distance_nm") * METERS_PER_NM


def meters_to_nm(distance_m: Real) -> float:
    """Convert meters to nautical miles."""

    return as_finite_float(distance_m, field_name="distance_m") / METERS_PER_NM


def feet_to_meters(altitude_ft: Real) -> float:
    """Convert feet to meters."""

    return as_finite_float(altitude_ft, field_name="altitude_ft") / FEET_PER_METER


def meters_to_feet(altitude_m: Real) -> float:
    """Convert meters to feet."""

    return as_finite_float(altitude_m, field_name="altitude_m") * FEET_PER_METER


def knots_to_nm_per_second(speed_kt: Real) -> float:
    """Convert knots to nautical miles per second."""

    return as_non_negative_float(speed_kt, field_name="speed_kt") / SECONDS_PER_HOUR


def fpm_to_ft_per_second(vertical_speed_fpm: Real) -> float:
    """Convert signed feet per minute to signed feet per second."""

    return (
        as_finite_float(
            vertical_speed_fpm,
            field_name="vertical_speed_fpm",
        )
        / SECONDS_PER_MINUTE
    )
