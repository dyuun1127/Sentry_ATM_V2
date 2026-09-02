"""Horizontal and vertical distance calculations for the SENTRY domain."""

from math import asin, cos, hypot, radians, sin, sqrt
from numbers import Real

from sentry_atm.domain.units import as_finite_float, as_non_negative_float
from sentry_atm.geo.coordinate import (
    MEAN_EARTH_RADIUS_NM,
    GeodeticPosition,
    LocalPosition,
)


def horizontal_distance_nm(start: LocalPosition, end: LocalPosition) -> float:
    """Return Euclidean horizontal distance between local positions in NM."""

    if not isinstance(start, LocalPosition) or not isinstance(end, LocalPosition):
        raise TypeError("start and end must be LocalPosition instances")
    return hypot(end.x_nm - start.x_nm, end.y_nm - start.y_nm)


def vertical_separation_ft(altitude_a_ft: Real, altitude_b_ft: Real) -> float:
    """Return absolute vertical separation between two altitudes in feet."""

    altitude_a = as_finite_float(altitude_a_ft, field_name="altitude_a_ft")
    altitude_b = as_finite_float(altitude_b_ft, field_name="altitude_b_ft")
    return abs(altitude_b - altitude_a)


def geodetic_distance_nm(
    start: GeodeticPosition,
    end: GeodeticPosition,
    *,
    earth_radius_nm: Real = MEAN_EARTH_RADIUS_NM,
) -> float:
    """Return spherical great-circle distance between geodetic positions in NM."""

    if not isinstance(start, GeodeticPosition) or not isinstance(end, GeodeticPosition):
        raise TypeError("start and end must be GeodeticPosition instances")

    radius = as_non_negative_float(earth_radius_nm, field_name="earth_radius_nm")
    if radius == 0.0:
        raise ValueError("earth_radius_nm must be greater than zero")

    start_latitude = radians(start.latitude_deg)
    end_latitude = radians(end.latitude_deg)
    latitude_delta = end_latitude - start_latitude
    longitude_delta = radians(end.longitude_deg - start.longitude_deg)

    haversine = (
        sin(latitude_delta / 2.0) ** 2
        + cos(start_latitude) * cos(end_latitude) * sin(longitude_delta / 2.0) ** 2
    )
    haversine = min(1.0, max(0.0, haversine))
    central_angle = 2.0 * asin(sqrt(haversine))
    return radius * central_angle
