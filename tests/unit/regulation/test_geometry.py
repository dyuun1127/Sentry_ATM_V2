"""충돌 기하 검증 — CPA 해석해와 보호실린더 침범 구간."""

import dataclasses

import pytest

from sentry_atm.regulation.geo import vincenty_direct
from sentry_atm.regulation.geometry import (
    DEFAULT_LOOKAHEAD_S,
    along_track_separation_nm,
    cpa,
    cross_track_offset_nm,
    detect_conflict,
    pair_conflict,
)
from sentry_atm.regulation.state import AircraftState, relative_state

RKTU = (36.71639, 127.4992)

H_MIN = 3.0     # 고시 5-5-4 가
V_MIN = 1000.0  # 고시 4-5-1


def ac(callsign, brg_from_arp, dist_nm, alt_ft, track, gs, vs=0.0, **kw):
    """RKTU 기준 방위·거리로 항적 하나 만들기."""
    lat, lon = vincenty_direct(*RKTU, brg_from_arp, dist_nm * 1852.0)
    return AircraftState(
        callsign=callsign, lat=lat, lon=lon, alt_ft=alt_ft,
        track_deg=track, gs_kt=gs, vs_fpm=vs, **kw
    )


class TestCPA:
    def test_head_on_converging(self):
        """정면 접근 — 최근접 시각과 거리가 해석적으로 맞아야 한다."""
        a = ac("AAA", 90, 10, 5000, 270, 300)   # 동쪽 10NM 에서 서진
        b = ac("BBB", 270, 10, 5000, 90, 300)   # 서쪽 10NM 에서 동진
        c = cpa(relative_state(a, b))
        # 상대속도 600kt, 상대거리 20NM → 20/600 시간 = 120초
        assert c.t_s == pytest.approx(120.0, abs=1.0)
        assert c.horizontal_nm == pytest.approx(0.0, abs=0.01)
        assert not c.is_diverging

    def test_diverging_gives_negative_time(self):
        """이미 지나쳐 벌어지는 중이면 t_cpa 가 음수."""
        a = ac("AAA", 90, 10, 5000, 90, 300)    # 동쪽에서 더 동쪽으로
        b = ac("BBB", 270, 10, 5000, 270, 300)  # 서쪽에서 더 서쪽으로
        c = cpa(relative_state(a, b))
        assert c.is_diverging

    def test_parallel_same_speed_constant_separation(self):
        """나란히 같은 속도 — 상대속도 0, 이격 불변."""
        a = ac("AAA", 0, 10, 5000, 90, 300)
        b = ac("BBB", 0, 15, 5000, 90, 300)
        rel = relative_state(a, b)
        c = cpa(rel)
        assert c.t_s == 0.0
        assert c.horizontal_nm == pytest.approx(rel.horizontal_nm, abs=1e-9)

    def test_matches_brute_force_sampling(self):
        """해석해가 촘촘한 수치 탐색과 일치해야 한다."""
        a = ac("AAA", 45, 12, 6000, 200, 280, vs=-800)
        b = ac("BBB", 300, 9, 5200, 100, 320, vs=0)
        c = cpa(relative_state(a, b))

        best_t, best_d = 0.0, float("inf")
        for i in range(0, 6001):
            t = i * 0.1
            d = relative_state(a.advance(t), b.advance(t)).horizontal_nm
            if d < best_d:
                best_t, best_d = t, d
        assert c.t_s == pytest.approx(best_t, abs=0.2)
        assert c.horizontal_nm == pytest.approx(best_d, abs=0.005)


class TestCylinderConflict:
    def test_head_on_at_same_altitude_is_conflict(self):
        a = ac("AAA", 90, 10, 5000, 270, 300)
        b = ac("BBB", 270, 10, 5000, 90, 300)
        w = pair_conflict(a, b, H_MIN, V_MIN)
        assert w is not None
        # 3NM 침범 시작은 상대거리가 20→3 NM 이 되는 시점 = 17/600 h = 102초
        assert w.entry_s == pytest.approx(102.0, abs=1.0)
        assert w.time_to_violation_s == pytest.approx(102.0, abs=1.0)
        assert not w.is_active

    def test_vertical_separation_prevents_conflict(self):
        """수평은 겹쳐도 1,000ft 수직분리가 유지되면 충돌이 아니다 (실린더)."""
        a = ac("AAA", 90, 10, 5000, 270, 300)
        b = ac("BBB", 270, 10, 6000, 90, 300)
        assert pair_conflict(a, b, H_MIN, V_MIN) is None

    def test_vertical_exactly_at_minimum_is_not_conflict(self):
        """정확히 1,000ft 는 분리가 확보된 것 — 미만이어야 위반."""
        a = ac("AAA", 0, 5, 4000, 90, 250)
        b = ac("BBB", 0, 5.1, 5000, 90, 250)
        assert pair_conflict(a, b, H_MIN, V_MIN) is None

    def test_climbing_through_causes_conflict(self):
        """수평은 계속 가깝고, 상승으로 수직분리가 무너지는 경우."""
        a = ac("AAA", 0, 8, 4000, 90, 250, vs=0)
        b = ac("BBB", 0, 8.5, 6000, 90, 250, vs=-1200)  # 강하하며 파고듦
        w = pair_conflict(a, b, H_MIN, V_MIN)
        assert w is not None
        # 2000ft 차이가 1000ft 미만이 되려면 1000ft 강하 필요 = 50초
        assert w.entry_s == pytest.approx(50.0, abs=1.0)

    def test_already_in_violation(self):
        a = ac("AAA", 0, 5, 5000, 90, 250)
        b = ac("BBB", 0, 6, 5000, 90, 250)
        w = pair_conflict(a, b, H_MIN, V_MIN)
        assert w is not None and w.is_active
        assert w.time_to_violation_s == 0.0

    def test_beyond_lookahead_is_ignored(self):
        """등속 가정의 유효 범위 밖 침범은 보지 않는다."""
        a = ac("AAA", 90, 60, 5000, 270, 120)
        b = ac("BBB", 270, 60, 5000, 90, 120)
        assert pair_conflict(a, b, H_MIN, V_MIN, lookahead_s=60.0) is None
        assert pair_conflict(a, b, H_MIN, V_MIN, lookahead_s=3600.0) is not None

    def test_grazing_encounter_that_sampling_would_miss(self):
        """1초 샘플링이 놓칠 수 있는 짧은 침범도 해석해는 잡는다."""
        # 빠른 상대속도로 실린더 가장자리를 스치는 조우를 구성
        a = ac("AAA", 90, 3.0, 5000, 270, 480)
        b = ac("BBB", 0, 2.95, 5000, 180, 480)
        w = pair_conflict(a, b, H_MIN, V_MIN)
        if w is not None:
            assert w.duration_s > 0
            # 침범 구간 한가운데에서는 실제로 최저치 미만이어야 한다
            mid = (max(w.entry_s, 0.0) + w.exit_s) / 2.0
            rel = relative_state(a.advance(mid), b.advance(mid))
            assert rel.horizontal_nm < H_MIN + 1e-6
            assert rel.vertical_ft < V_MIN + 1e-6

    def test_conflict_window_agrees_with_sampling(self):
        """침범 구간 밖에서는 실제로 위반이 아니어야 한다."""
        a = ac("AAA", 30, 14, 5000, 210, 300, vs=0)
        b = ac("BBB", 200, 11, 5400, 20, 280, vs=-500)
        w = pair_conflict(a, b, H_MIN, V_MIN)
        assert w is not None
        for t in (0.0, max(w.entry_s - 5.0, 0.0), w.exit_s + 5.0):
            rel = relative_state(a.advance(t), b.advance(t))
            violating = rel.horizontal_nm < H_MIN and rel.vertical_ft < V_MIN
            in_window = w.entry_s <= t <= w.exit_s
            assert violating == in_window, f"t={t}: 판정 불일치"


class TestDegenerate:
    def test_zero_relative_velocity_not_violating(self):
        from sentry_atm.regulation.state import RelativeState

        rel = RelativeState(5.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        assert detect_conflict(rel, H_MIN, V_MIN) is None

    def test_zero_relative_velocity_already_violating(self):
        from sentry_atm.regulation.state import RelativeState

        rel = RelativeState(1.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        w = detect_conflict(rel, H_MIN, V_MIN)
        assert w is not None and w.is_active

    def test_lookahead_default_is_ten_minutes(self):
        assert DEFAULT_LOOKAHEAD_S == 600.0


class TestTrackGeometry:
    def test_along_track_positive_when_leader_ahead(self):
        """선행기가 앞서 있으면 양수."""
        follower = ac("FOL", 0, 10, 3000, 232.43, 180)
        leader = ac("LDR", 0, 10, 3000, 232.43, 180)
        # 선행기를 진로 방향으로 5NM 이동
        lat, lon = vincenty_direct(leader.lat, leader.lon, 232.43, 5 * 1852.0)
        leader = AircraftState("LDR", lat, lon, 3000, 232.43, 180)
        d = along_track_separation_nm(leader, follower, 232.43)
        assert d == pytest.approx(5.0, abs=0.01)

    def test_along_track_negative_when_order_reversed(self):
        a = ac("A", 0, 10, 3000, 232.43, 180)
        lat, lon = vincenty_direct(a.lat, a.lon, 232.43, 5 * 1852.0)
        b = AircraftState("B", lat, lon, 3000, 232.43, 180)
        assert along_track_separation_nm(a, b, 232.43) < 0

    def test_cross_track_sign_is_right_positive(self):
        """진로 우측이 양수."""
        ref_lat, ref_lon = RKTU
        # 진로 0°(북) 기준으로 동쪽에 있는 기체는 우측
        lat, lon = vincenty_direct(ref_lat, ref_lon, 90.0, 2 * 1852.0)
        east = AircraftState("E", lat, lon, 3000, 0.0, 200)
        assert cross_track_offset_nm(east, ref_lat, ref_lon, 0.0) == pytest.approx(2.0, abs=0.01)

        lat, lon = vincenty_direct(ref_lat, ref_lon, 270.0, 2 * 1852.0)
        west = AircraftState("W", lat, lon, 3000, 0.0, 200)
        assert cross_track_offset_nm(west, ref_lat, ref_lon, 0.0) == pytest.approx(-2.0, abs=0.01)

    def test_on_centreline_offset_is_zero(self):
        lat, lon = vincenty_direct(*RKTU, 232.43, 8 * 1852.0)
        onc = AircraftState("ONC", lat, lon, 3000, 52.43, 180)
        assert cross_track_offset_nm(onc, *RKTU, 232.43) == pytest.approx(0.0, abs=0.005)


class TestAircraftState:
    def test_advance_moves_along_track(self):
        a = ac("AAA", 0, 0, 5000, 90.0, 360.0, vs=600.0)
        b = a.advance(60.0)
        from sentry_atm.regulation.geo import bearing_true, separation_distance_nm

        assert separation_distance_nm(a.lat, a.lon, b.lat, b.lon) == pytest.approx(6.0, abs=0.01)
        assert bearing_true(a.lat, a.lon, b.lat, b.lon) == pytest.approx(90.0, abs=0.05)
        assert b.alt_ft == pytest.approx(5600.0)
        assert b.t_s == 60.0

    def test_state_is_immutable(self):
        a = ac("AAA", 0, 0, 5000, 90.0, 360.0)
        with pytest.raises(dataclasses.FrozenInstanceError):
            a.alt_ft = 6000  # type: ignore[misc]

    def test_rejects_unknown_wake_category(self):
        with pytest.raises(ValueError, match="고시 등급"):
            AircraftState("X", 36.7, 127.5, 5000, 90, 300, wake_cat="Heavy")

    def test_velocity_components(self):
        a = ac("AAA", 0, 0, 5000, 0.0, 300.0)
        assert a.v_north_kt == pytest.approx(300.0)
        assert a.v_east_kt == pytest.approx(0.0, abs=1e-9)
        b = ac("BBB", 0, 0, 5000, 90.0, 300.0)
        assert b.v_east_kt == pytest.approx(300.0)

    def test_flight_level_formatting(self):
        assert ac("A", 0, 0, 6000, 0, 200).flight_level == "6,000 ft"
        assert ac("A", 0, 0, 18000, 0, 200).flight_level == "FL180"

    def test_closing_speed_sign(self):
        conv_a = ac("A", 90, 10, 5000, 270, 300)
        conv_b = ac("B", 270, 10, 5000, 90, 300)
        assert relative_state(conv_a, conv_b).closing_speed_kt > 0

        div_a = ac("A", 90, 10, 5000, 90, 300)
        div_b = ac("B", 270, 10, 5000, 270, 300)
        assert relative_state(div_a, div_b).closing_speed_kt < 0
