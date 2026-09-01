from dataclasses import FrozenInstanceError
from math import degrees

import pytest

from sentry_atm.geo.coordinate import (
    MEAN_EARTH_RADIUS_NM,
    RKTU_ARP,
    RKTU_ARP_LATITUDE_DEG,
    RKTU_ARP_LONGITUDE_DEG,
    GeodeticPosition,
    LocalPosition,
    LocalTangentPlane,
    rktu_geodetic_to_local,
    rktu_local_to_geodetic,
)


def test_rktu_arp_constants_match_published_dms_coordinates() -> None:
    assert RKTU_ARP_LATITUDE_DEG == pytest.approx(36.716_388_888_9)
    assert RKTU_ARP_LONGITUDE_DEG == pytest.approx(127.499_166_666_7)


def test_rktu_arp_maps_to_local_origin() -> None:
    local = rktu_geodetic_to_local(
        RKTU_ARP.latitude_deg,
        RKTU_ARP.longitude_deg,
    )

    assert local.x_nm == pytest.approx(0.0, abs=1e-12)
    assert local.y_nm == pytest.approx(0.0, abs=1e-12)


def test_north_is_positive_y() -> None:
    one_nm_in_degrees = degrees(1.0 / MEAN_EARTH_RADIUS_NM)

    local = rktu_geodetic_to_local(
        RKTU_ARP.latitude_deg + one_nm_in_degrees,
        RKTU_ARP.longitude_deg,
    )

    assert local.x_nm == pytest.approx(0.0, abs=1e-10)
    assert local.y_nm == pytest.approx(1.0, abs=1e-6)


def test_east_is_positive_x() -> None:
    local = rktu_geodetic_to_local(
        RKTU_ARP.latitude_deg,
        RKTU_ARP.longitude_deg + 0.01,
    )

    assert local.x_nm > 0.0
    assert abs(local.y_nm) < 0.001


def test_west_and_south_use_negative_axes() -> None:
    west = rktu_geodetic_to_local(
        RKTU_ARP.latitude_deg,
        RKTU_ARP.longitude_deg - 0.01,
    )
    south = rktu_geodetic_to_local(
        RKTU_ARP.latitude_deg - 0.01,
        RKTU_ARP.longitude_deg,
    )

    assert west.x_nm < 0.0
    assert south.y_nm < 0.0


@pytest.mark.parametrize(
    ("latitude_deg", "longitude_deg"),
    [
        (36.65, 127.55),
        (36.85, 127.30),
        (36.50, 127.70),
    ],
)
def test_geodetic_round_trip_within_terminal_region(
    latitude_deg: float,
    longitude_deg: float,
) -> None:
    source = GeodeticPosition(latitude_deg, longitude_deg)

    local = rktu_geodetic_to_local(latitude_deg, longitude_deg)
    restored = rktu_local_to_geodetic(local.x_nm, local.y_nm)

    assert restored.latitude_deg == pytest.approx(source.latitude_deg, abs=1e-10)
    assert restored.longitude_deg == pytest.approx(source.longitude_deg, abs=1e-10)


@pytest.mark.parametrize(
    ("x_nm", "y_nm"),
    [(-20.0, -10.0), (0.0, 0.0), (25.0, 15.0)],
)
def test_local_round_trip_within_simulation_envelope(x_nm: float, y_nm: float) -> None:
    source = LocalPosition(x_nm=x_nm, y_nm=y_nm)

    geodetic = rktu_local_to_geodetic(source.x_nm, source.y_nm)
    restored = rktu_geodetic_to_local(geodetic.latitude_deg, geodetic.longitude_deg)

    assert restored.x_nm == pytest.approx(source.x_nm, abs=1e-10)
    assert restored.y_nm == pytest.approx(source.y_nm, abs=1e-10)


@pytest.mark.parametrize(
    ("latitude_deg", "longitude_deg", "message"),
    [
        (91.0, 127.0, r"\[-90, 90\]"),
        (36.0, 181.0, r"\[-180, 180\]"),
    ],
)
def test_geodetic_position_rejects_out_of_range_values(
    latitude_deg: float,
    longitude_deg: float,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        GeodeticPosition(latitude_deg, longitude_deg)


def test_local_inverse_rejects_position_outside_hemisphere() -> None:
    with pytest.raises(ValueError, match="outside the invertible"):
        rktu_local_to_geodetic(MEAN_EARTH_RADIUS_NM, 0.0)


def test_forward_projection_rejects_far_side_of_earth() -> None:
    frame = LocalTangentPlane(origin=GeodeticPosition(0.0, 0.0))

    with pytest.raises(ValueError, match="within 90 degrees"):
        frame.to_local(GeodeticPosition(0.0, 180.0))


def test_tangent_plane_requires_a_valid_origin_and_radius() -> None:
    with pytest.raises(TypeError, match="GeodeticPosition"):
        LocalTangentPlane(origin="RKTU")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="greater than zero"):
        LocalTangentPlane(origin=RKTU_ARP, earth_radius_nm=0.0)


def test_tangent_plane_rejects_incorrect_position_types() -> None:
    frame = LocalTangentPlane(origin=RKTU_ARP)

    with pytest.raises(TypeError, match="GeodeticPosition"):
        frame.to_local(LocalPosition(0.0, 0.0))  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="LocalPosition"):
        frame.to_geodetic(RKTU_ARP)  # type: ignore[arg-type]


def test_coordinate_models_are_immutable() -> None:
    position = LocalPosition(1.0, 2.0)

    with pytest.raises(FrozenInstanceError):
        position.x_nm = 3.0  # type: ignore[misc]
