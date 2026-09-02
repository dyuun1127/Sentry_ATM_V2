"""RKTU-centered spherical local tangent-plane coordinate conversion."""

from dataclasses import dataclass
from math import atan2, cos, degrees, hypot, radians, sin, sqrt

from sentry_atm.domain.units import as_finite_float, as_non_negative_float

MEAN_EARTH_RADIUS_NM = 3_440.065

RKTU_ARP_LATITUDE_DEG = 36 + 42 / 60 + 59 / 3_600
RKTU_ARP_LONGITUDE_DEG = 127 + 29 / 60 + 57 / 3_600


def _as_latitude_deg(value: float, *, field_name: str = "latitude_deg") -> float:
    latitude = as_finite_float(value, field_name=field_name)
    if not -90.0 <= latitude <= 90.0:
        raise ValueError(f"{field_name} must be in [-90, 90]")
    return latitude


def _as_longitude_deg(value: float, *, field_name: str = "longitude_deg") -> float:
    longitude = as_finite_float(value, field_name=field_name)
    if not -180.0 <= longitude <= 180.0:
        raise ValueError(f"{field_name} must be in [-180, 180]")
    return longitude


def _normalize_longitude_deg(value: float) -> float:
    return (value + 180.0) % 360.0 - 180.0


@dataclass(frozen=True, slots=True)
class GeodeticPosition:
    """A validated latitude/longitude pair in decimal degrees."""

    latitude_deg: float
    longitude_deg: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "latitude_deg", _as_latitude_deg(self.latitude_deg))
        object.__setattr__(self, "longitude_deg", _as_longitude_deg(self.longitude_deg))


@dataclass(frozen=True, slots=True)
class LocalPosition:
    """A local horizontal position where East is +x and North is +y."""

    x_nm: float
    y_nm: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "x_nm", as_finite_float(self.x_nm, field_name="x_nm"))
        object.__setattr__(self, "y_nm", as_finite_float(self.y_nm, field_name="y_nm"))


@dataclass(frozen=True, slots=True)
class LocalTangentPlane:
    """Spherical East-North tangent plane centered on a geodetic origin."""

    origin: GeodeticPosition
    earth_radius_nm: float = MEAN_EARTH_RADIUS_NM

    def __post_init__(self) -> None:
        if not isinstance(self.origin, GeodeticPosition):
            raise TypeError("origin must be a GeodeticPosition")
        radius = as_non_negative_float(self.earth_radius_nm, field_name="earth_radius_nm")
        if radius == 0.0:
            raise ValueError("earth_radius_nm must be greater than zero")
        object.__setattr__(self, "earth_radius_nm", radius)

    def to_local(self, position: GeodeticPosition) -> LocalPosition:
        """Project a nearby surface position onto the origin's ENU plane."""

        if not isinstance(position, GeodeticPosition):
            raise TypeError("position must be a GeodeticPosition")

        origin_up, origin_east, origin_north = self._origin_basis()
        point_up = _surface_unit_vector(position)
        near_side_projection = _dot(point_up, origin_up)
        if near_side_projection <= 0.0:
            raise ValueError("position must be within 90 degrees of the tangent-plane origin")

        delta = tuple(
            self.earth_radius_nm * (point_component - origin_component)
            for point_component, origin_component in zip(point_up, origin_up, strict=True)
        )
        return LocalPosition(
            x_nm=_dot(delta, origin_east),
            y_nm=_dot(delta, origin_north),
        )

    def to_geodetic(self, position: LocalPosition) -> GeodeticPosition:
        """Recover the near-side surface position from local ENU coordinates."""

        if not isinstance(position, LocalPosition):
            raise TypeError("position must be a LocalPosition")

        horizontal_squared = position.x_nm**2 + position.y_nm**2
        radius_squared = self.earth_radius_nm**2
        if horizontal_squared >= radius_squared:
            raise ValueError("local position lies outside the invertible tangent-plane hemisphere")

        origin_up, origin_east, origin_north = self._origin_basis()
        up_component = sqrt(radius_squared - horizontal_squared)
        point_ecef = tuple(
            position.x_nm * east + position.y_nm * north + up_component * up
            for east, north, up in zip(
                origin_east,
                origin_north,
                origin_up,
                strict=True,
            )
        )

        latitude_deg = degrees(atan2(point_ecef[2], hypot(point_ecef[0], point_ecef[1])))
        longitude_deg = _normalize_longitude_deg(degrees(atan2(point_ecef[1], point_ecef[0])))
        return GeodeticPosition(
            latitude_deg=latitude_deg,
            longitude_deg=longitude_deg,
        )

    def _origin_basis(
        self,
    ) -> tuple[
        tuple[float, float, float],
        tuple[float, float, float],
        tuple[float, float, float],
    ]:
        latitude_rad = radians(self.origin.latitude_deg)
        longitude_rad = radians(self.origin.longitude_deg)
        sin_latitude = sin(latitude_rad)
        cos_latitude = cos(latitude_rad)
        sin_longitude = sin(longitude_rad)
        cos_longitude = cos(longitude_rad)

        up = (
            cos_latitude * cos_longitude,
            cos_latitude * sin_longitude,
            sin_latitude,
        )
        east = (-sin_longitude, cos_longitude, 0.0)
        north = (
            -sin_latitude * cos_longitude,
            -sin_latitude * sin_longitude,
            cos_latitude,
        )
        return up, east, north


def _surface_unit_vector(position: GeodeticPosition) -> tuple[float, float, float]:
    latitude_rad = radians(position.latitude_deg)
    longitude_rad = radians(position.longitude_deg)
    cos_latitude = cos(latitude_rad)
    return (
        cos_latitude * cos(longitude_rad),
        cos_latitude * sin(longitude_rad),
        sin(latitude_rad),
    )


def _dot(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    return sum(
        left_component * right_component
        for left_component, right_component in zip(left, right, strict=True)
    )


RKTU_ARP = GeodeticPosition(
    latitude_deg=RKTU_ARP_LATITUDE_DEG,
    longitude_deg=RKTU_ARP_LONGITUDE_DEG,
)
RKTU_LOCAL_FRAME = LocalTangentPlane(origin=RKTU_ARP)


def rktu_geodetic_to_local(latitude_deg: float, longitude_deg: float) -> LocalPosition:
    """Convert WGS84-style decimal degrees to RKTU-centered local x/y NM."""

    return RKTU_LOCAL_FRAME.to_local(
        GeodeticPosition(
            latitude_deg=latitude_deg,
            longitude_deg=longitude_deg,
        )
    )


def rktu_local_to_geodetic(x_nm: float, y_nm: float) -> GeodeticPosition:
    """Convert RKTU-centered local x/y NM to decimal degrees."""

    return RKTU_LOCAL_FRAME.to_geodetic(LocalPosition(x_nm=x_nm, y_nm=y_nm))
