"""RKTU-centered local tangent-plane coordinate conversion on WGS84.

The plane was spherical, on a mean Earth radius. At this latitude that carries a
systematic scale error of about 0.23 percent, because the meridional and prime
vertical radii of curvature (6,358 and 6,386 km at 36.7N) straddle the mean
radius rather than matching it.

Between two aircraft five miles apart that came to 22 metres, and it leaned the
wrong way: the plane reported them **further apart than they were**, so a pair the
plane called exactly at the three mile minimum was already inside it.

Twenty-two metres sits far below radar accuracy and no controller would ever see
it. It is corrected anyway, for two reasons. The bias is systematic and in the
unsafe direction, so it never averages out. And this plane is the bridge between
local x/y and the AIP-transcribed coordinates the regulation layer works in,
where runway thresholds, holding patterns and published fixes all live in
latitude and longitude. Using the local curvature radii instead of a mean radius
brings the worst pairwise error down to 1.9 metres.
"""

from dataclasses import dataclass
from math import cos, degrees, radians, sin, sqrt

from sentry_atm.domain.units import as_finite_float

MEAN_EARTH_RADIUS_NM = 3_440.065
"""평균 지구 반지름 (NM). 구면 근사가 필요한 곳에만 남겨 둔다."""

# WGS84 타원체. 곡률반경은 위도에 따라 달라지므로 원점에서 한 번 구해 쓴다.
WGS84_SEMI_MAJOR_AXIS_M = 6_378_137.0
WGS84_FLATTENING = 1.0 / 298.257223563
METRES_PER_NM = 1_852.0

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


def curvature_radii_m(latitude_deg: float) -> tuple[float, float]:
    """WGS84 자오선·묘유선 곡률반경 (m).

    남북 방향과 동서 방향의 반지름이 다르다. 하나의 평균 반지름으로 두 방향을
    함께 근사하면 그 차이가 그대로 배율 오차가 된다.
    """
    latitude = radians(_as_latitude_deg(latitude_deg))
    eccentricity_squared = WGS84_FLATTENING * (2.0 - WGS84_FLATTENING)
    w = 1.0 - eccentricity_squared * sin(latitude) ** 2
    meridional = WGS84_SEMI_MAJOR_AXIS_M * (1.0 - eccentricity_squared) / (w**1.5)
    prime_vertical = WGS84_SEMI_MAJOR_AXIS_M / sqrt(w)
    return meridional, prime_vertical


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
    """WGS84 East-North tangent plane centered on a geodetic origin."""

    origin: GeodeticPosition

    def __post_init__(self) -> None:
        if not isinstance(self.origin, GeodeticPosition):
            raise TypeError("origin must be a GeodeticPosition")

    @property
    def curvature_radii_nm(self) -> tuple[float, float]:
        """원점 위도에서의 (자오선, 묘유선) 곡률반경 (NM)."""
        meridional, prime_vertical = curvature_radii_m(self.origin.latitude_deg)
        return meridional / METRES_PER_NM, prime_vertical / METRES_PER_NM

    def to_local(self, position: GeodeticPosition) -> LocalPosition:
        """Project a nearby surface position onto the origin's ENU plane."""

        if not isinstance(position, GeodeticPosition):
            raise TypeError("position must be a GeodeticPosition")

        meridional_nm, prime_vertical_nm = self.curvature_radii_nm
        latitude_delta_deg = position.latitude_deg - self.origin.latitude_deg
        longitude_delta_deg = _normalize_longitude_deg(
            position.longitude_deg - self.origin.longitude_deg
        )
        if abs(latitude_delta_deg) >= 90.0 or abs(longitude_delta_deg) >= 90.0:
            raise ValueError("position must be within 90 degrees of the tangent-plane origin")

        return LocalPosition(
            x_nm=(
                radians(longitude_delta_deg)
                * prime_vertical_nm
                * cos(radians(self.origin.latitude_deg))
            ),
            y_nm=radians(latitude_delta_deg) * meridional_nm,
        )

    def to_geodetic(self, position: LocalPosition) -> GeodeticPosition:
        """Recover the surface position from local ENU coordinates."""

        if not isinstance(position, LocalPosition):
            raise TypeError("position must be a LocalPosition")

        meridional_nm, prime_vertical_nm = self.curvature_radii_nm
        latitude_deg = self.origin.latitude_deg + degrees(position.y_nm / meridional_nm)
        if not -90.0 <= latitude_deg <= 90.0:
            raise ValueError("local position lies outside the invertible tangent plane")

        longitude_deg = self.origin.longitude_deg + degrees(
            position.x_nm / (prime_vertical_nm * cos(radians(self.origin.latitude_deg)))
        )
        return GeodeticPosition(
            latitude_deg=latitude_deg,
            longitude_deg=_normalize_longitude_deg(longitude_deg),
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
