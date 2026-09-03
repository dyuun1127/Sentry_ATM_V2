"""측지 계산 검증."""

import math
import random

import pytest

from sentry_atm.regulation.geo import (
    LocalFrame,
    angular_diff,
    enu_offset_nm,
    bearing_true,
    distance_nm,
    magnetic_to_true,
    parse_latlon,
    separation_distance_nm,
    true_to_magnetic,
    vincenty_direct,
    vincenty_inverse,
)


class TestParse:
    def test_packed_format(self):
        """AD 2.12 붙여쓰기 표기."""
        assert parse_latlon("364330.38N") == pytest.approx(36 + 43 / 60 + 30.38 / 3600)
        assert parse_latlon("1273040.05E") == pytest.approx(127 + 30 / 60 + 40.05 / 3600)

    def test_symbol_format(self):
        """차트 도분초 기호 표기."""
        assert parse_latlon("36°47'03.7\"N") == pytest.approx(36 + 47 / 60 + 3.7 / 3600)
        assert parse_latlon("127°36'25.0\"E") == pytest.approx(127 + 36 / 60 + 25.0 / 3600)

    def test_no_decimal_seconds(self):
        assert parse_latlon("36°43'05\"N") == pytest.approx(36 + 43 / 60 + 5 / 3600)

    def test_southern_western_negative(self):
        assert parse_latlon("364330.38S") < 0
        assert parse_latlon("1273040.05W") < 0

    def test_rejects_garbage(self):
        with pytest.raises(ValueError):
            parse_latlon("not a coordinate")


class TestVincenty:
    def test_runway_matches_aip(self):
        """AD 2.12 가 별도로 고시한 활주로 길이·진방위를 좌표로 재현한다."""
        thr24r = (36 + 43 / 60 + 30.38 / 3600, 127 + 30 / 60 + 40.05 / 3600)
        thr06l = (36 + 42 / 60 + 36.10 / 3600, 127 + 29 / 60 + 12.46 / 3600)
        d, brg, _ = vincenty_inverse(*thr24r, *thr06l)
        assert d == pytest.approx(2744, abs=2)      # AIP 2744 m
        assert brg == pytest.approx(232.43, abs=0.02)  # AIP TRUE BRG 232.43

    def test_direct_inverse_roundtrip(self):
        lat, lon = 36.71639, 127.4992
        for brg in (0, 45, 137, 232.43, 359):
            for dist_m in (500.0, 18520.0, 55560.0):
                lat2, lon2 = vincenty_direct(lat, lon, brg, dist_m)
                d, b, _ = vincenty_inverse(lat, lon, lat2, lon2)
                assert d == pytest.approx(dist_m, abs=0.01)
                assert angular_diff(b, brg) == pytest.approx(0.0, abs=1e-6)

    def test_zero_distance(self):
        assert vincenty_inverse(36.7, 127.5, 36.7, 127.5) == (0.0, 0.0, 0.0)


class TestSeparationDistance:
    """분리 판정용 거리 — 안전필수 경로이므로 정확도를 명시적으로 못박는다."""

    def test_accurate_at_separation_minimum(self):
        """수평 분리 최저치(3NM) 규모에서 측지선과 1 cm 이내로 일치해야 한다."""
        random.seed(20260902)
        lat0, lon0 = 36.71639, 127.4992  # RKTU ARP
        worst = 0.0
        for _ in range(2000):
            p1 = vincenty_direct(lat0, lon0, random.uniform(0, 360),
                                 random.uniform(0, 30) * 1852.0)
            p2 = vincenty_direct(p1[0], p1[1], random.uniform(0, 360),
                                 random.uniform(0.2, 3.0) * 1852.0)
            got = separation_distance_nm(*p1, *p2)
            truth = vincenty_inverse(*p1, *p2)[0] / 1852.0
            worst = max(worst, abs(got - truth))
        assert worst * 1852.0 < 0.01, f"분리거리 오차 {worst * 1852:.4f} m"

    def test_accurate_across_whole_tma(self):
        """섹터 전역(이격 30NM 까지) 에서도 0.5 m 이내."""
        random.seed(20260902)
        lat0, lon0 = 36.71639, 127.4992
        worst = 0.0
        for _ in range(2000):
            p1 = vincenty_direct(lat0, lon0, random.uniform(0, 360),
                                 random.uniform(0, 30) * 1852.0)
            p2 = vincenty_direct(p1[0], p1[1], random.uniform(0, 360),
                                 random.uniform(0.2, 30.0) * 1852.0)
            worst = max(worst, abs(separation_distance_nm(*p1, *p2)
                                   - vincenty_inverse(*p1, *p2)[0] / 1852.0))
        assert worst * 1852.0 < 0.5, f"분리거리 오차 {worst * 1852:.3f} m"

    def test_enu_offset_directions(self):
        """동/북 부호 규약."""
        east, north = enu_offset_nm(36.7, 127.5, 36.8, 127.6)
        assert east > 0 and north > 0
        east, north = enu_offset_nm(36.7, 127.5, 36.6, 127.4)
        assert east < 0 and north < 0


class TestLocalFrame:
    def test_display_accuracy_is_documented(self):
        """표출용 프레임의 실제 정확도를 고정한다 — 30NM 에서 0.04NM 이내.

        이 값이 분리 최저치(3NM)의 1% 를 넘으므로, 분리 판정에는 쓰지 않고
        separation_distance_nm 을 쓴다는 설계를 회귀 테스트로 못박는다.
        """
        lat0, lon0 = 36.71639, 127.4992  # RKTU ARP
        frame = LocalFrame(lat0, lon0)
        worst = 0.0
        for brg in range(0, 360, 15):
            for dist_nm in (5.0, 15.0, 30.0):
                lat, lon = vincenty_direct(lat0, lon0, brg, dist_nm * 1852.0)
                x, y = frame.to_xy(lat, lon)
                worst = max(worst, abs(math.hypot(x, y) - dist_nm))
        assert 0.03 < worst < 0.04, f"표출 프레임 오차가 예상 범위를 벗어남: {worst:.4f} NM"

    def test_roundtrip(self):
        frame = LocalFrame(36.71639, 127.4992)
        for x, y in [(0, 0), (10, -20), (-25, 8), (30, 30)]:
            lat, lon = frame.to_latlon(x, y)
            x2, y2 = frame.to_xy(lat, lon)
            assert x2 == pytest.approx(x, abs=1e-9)
            assert y2 == pytest.approx(y, abs=1e-9)


class TestMagVar:
    def test_rktu_runway_true_to_magnetic(self):
        """RWY 24R 진방위 232.43° 는 자방위 약 240° (VAR 9°W) — 활주로 명칭과 일치."""
        assert true_to_magnetic(232.43, 9.0) == pytest.approx(241.43)
        assert magnetic_to_true(240.0, 9.0) == pytest.approx(231.0)

    def test_roundtrip(self):
        for t in (0.0, 90.0, 232.43, 355.0):
            assert magnetic_to_true(true_to_magnetic(t, 9.0), 9.0) == pytest.approx(t)


class TestAngularDiff:
    @pytest.mark.parametrize(
        "a,b,expected",
        [(10, 350, 20), (350, 10, -20), (0, 180, -180), (90, 90, 0), (232.5, 232.4, 0.1)],
    )
    def test_wraps(self, a, b, expected):
        assert angular_diff(a, b) == pytest.approx(expected, abs=1e-9)


def test_distance_and_bearing_helpers():
    a = (36.7, 127.4)
    b = (36.8, 127.6)
    assert distance_nm(*a, *b) == pytest.approx(vincenty_inverse(*a, *b)[0] / 1852.0)
    assert bearing_true(*a, *b) == pytest.approx(vincenty_inverse(*a, *b)[1])
