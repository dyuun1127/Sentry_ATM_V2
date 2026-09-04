from math import pi

import pytest

from sentry_atm.geo import (
    MEAN_EARTH_RADIUS_NM,
    RKTU_ARP,
    GeodeticPosition,
    LocalPosition,
    geodetic_distance_nm,
    horizontal_distance_nm,
    rktu_local_to_geodetic,
    vertical_separation_ft,
)


def test_horizontal_distance_is_zero_for_same_position() -> None:
    position = LocalPosition(10.0, -5.0)

    assert horizontal_distance_nm(position, position) == 0.0


def test_horizontal_distance_uses_euclidean_geometry() -> None:
    start = LocalPosition(1.0, 2.0)
    end = LocalPosition(4.0, 6.0)

    assert horizontal_distance_nm(start, end) == pytest.approx(5.0)


def test_horizontal_distance_is_symmetric() -> None:
    start = LocalPosition(-10.0, 8.0)
    end = LocalPosition(15.0, -4.0)

    assert horizontal_distance_nm(start, end) == horizontal_distance_nm(end, start)


def test_horizontal_distance_rejects_incorrect_position_type() -> None:
    with pytest.raises(TypeError, match="LocalPosition"):
        horizontal_distance_nm(LocalPosition(0.0, 0.0), (3.0, 4.0))  # type: ignore[arg-type]


def test_vertical_separation_is_zero_at_same_altitude() -> None:
    assert vertical_separation_ft(8_000.0, 8_000.0) == 0.0


def test_vertical_separation_is_absolute_and_symmetric() -> None:
    assert vertical_separation_ft(7_500.0, 9_000.0) == 1_500.0
    assert vertical_separation_ft(9_000.0, 7_500.0) == 1_500.0


@pytest.mark.parametrize("invalid", [True, "8000", float("nan"), float("inf")])
def test_vertical_separation_rejects_invalid_altitude(invalid: object) -> None:
    expected_error = TypeError if isinstance(invalid, (bool, str)) else ValueError

    with pytest.raises(expected_error):
        vertical_separation_ft(invalid, 8_000.0)  # type: ignore[arg-type]


def test_default_distance_uses_the_wgs84_ellipsoid() -> None:
    """기본값이 타원체다 — AIP 좌표와 대조하므로 AIP 가 쓰는 도형이어야 한다."""
    start = GeodeticPosition(latitude_deg=36.7164, longitude_deg=127.4992)
    end = GeodeticPosition(latitude_deg=36.7164, longitude_deg=128.0)

    wgs84 = geodetic_distance_nm(start, end)
    sphere = geodetic_distance_nm(start, end, earth_radius_nm=MEAN_EARTH_RADIUS_NM)

    # 이 위도의 동서 방향에서 구면 근사는 약 0.23% 짧다.
    assert wgs84 > sphere
    assert (wgs84 - sphere) / wgs84 == pytest.approx(0.0023, abs=3e-4)


def test_one_degree_latitude_matches_known_spherical_arc() -> None:
    start = GeodeticPosition(0.0, 127.0)
    end = GeodeticPosition(1.0, 127.0)

    expected_nm = MEAN_EARTH_RADIUS_NM * pi / 180.0

    assert geodetic_distance_nm(
        start, end, earth_radius_nm=MEAN_EARTH_RADIUS_NM
    ) == pytest.approx(expected_nm)


def test_geodetic_distance_is_zero_and_symmetric() -> None:
    other = GeodeticPosition(36.9, 127.7)

    assert geodetic_distance_nm(RKTU_ARP, RKTU_ARP) == 0.0
    assert geodetic_distance_nm(RKTU_ARP, other) == pytest.approx(
        geodetic_distance_nm(other, RKTU_ARP)
    )


def test_antipodal_geodetic_distance_is_half_circumference() -> None:
    start = GeodeticPosition(0.0, 0.0)
    end = GeodeticPosition(0.0, 180.0)

    assert geodetic_distance_nm(
        start, end, earth_radius_nm=MEAN_EARTH_RADIUS_NM
    ) == pytest.approx(pi * MEAN_EARTH_RADIUS_NM)


def test_geodetic_distance_accepts_custom_positive_radius() -> None:
    start = GeodeticPosition(0.0, 0.0)
    end = GeodeticPosition(90.0, 0.0)

    assert geodetic_distance_nm(start, end, earth_radius_nm=1.0) == pytest.approx(pi / 2.0)


@pytest.mark.parametrize("invalid_radius", [0.0, -1.0, float("nan"), True])
def test_geodetic_distance_rejects_invalid_radius(invalid_radius: object) -> None:
    expected_error = TypeError if isinstance(invalid_radius, bool) else ValueError

    with pytest.raises(expected_error):
        geodetic_distance_nm(
            RKTU_ARP,
            RKTU_ARP,
            earth_radius_nm=invalid_radius,  # type: ignore[arg-type]
        )


def test_geodetic_distance_rejects_incorrect_position_type() -> None:
    with pytest.raises(TypeError, match="GeodeticPosition"):
        geodetic_distance_nm(RKTU_ARP, LocalPosition(0.0, 0.0))  # type: ignore[arg-type]


def test_local_and_geodetic_distance_agree_within_terminal_envelope() -> None:
    local_origin = LocalPosition(0.0, 0.0)
    local_target = LocalPosition(30.0, 0.0)
    geodetic_target = rktu_local_to_geodetic(local_target.x_nm, local_target.y_nm)

    local_distance = horizontal_distance_nm(local_origin, local_target)
    surface_distance = geodetic_distance_nm(RKTU_ARP, geodetic_target)

    assert local_distance == pytest.approx(30.0)
    assert abs(surface_distance - local_distance) < 0.001
