"""체공(홀딩) 검증.

가장 중요한 것은 **장주를 지어내지 않는다**는 점이다. 청주에는 AIP 에 공고된
체공장주가 IKAPO·COWON 두 곳뿐이고, 공고되지 않은 픽스에 세우는 지시는
고시 4-6-1 나 2)의 "AS PUBLISHED" 로 낼 수 없다.

수용량도 실제 제약이다. 두 장주에 쌓을 수 있는 층수가 곧 도착 흐름을 붙들 수
있는 상한이고, 넘으면 체공이 아닌 다른 수단으로 풀어야 한다.
"""

import math

import pytest

from sentry_atm.regulation import data as sdata
from sentry_atm.regulation import hold


@pytest.fixture(scope="module")
def ds():
    return sdata.load()


@pytest.fixture(scope="module")
def hb(ds):
    return hold.build(ds)


class TestPublishedPatternsOnly:
    def test_patterns_come_from_the_aip(self, ds, hb):
        published = {h["fix"] for h in ds.procedures.iap("RNP_24R")["holdings"]}
        assert {p.fix for p in hb.patterns} == published

    def test_cheongju_publishes_ikapo_and_cowon(self, hb):
        assert {p.fix for p in hb.patterns} == {"IKAPO", "COWON"}

    def test_unpublished_fix_is_refused(self, hb):
        """TURTU 는 접근 픽스이지 체공장주가 아니다."""
        with pytest.raises(KeyError):
            hb.pattern("TURTU")

    def test_pattern_values_match_the_chart(self, ds, hb):
        for h in ds.procedures.iap("RNP_24R")["holdings"]:
            p = hb.pattern(h["fix"])
            assert p.inbound_course_true == h["inbound_course_true"]
            assert p.leg_nm == h["leg_nm"]
            assert p.alt_ft == h["alt_ft"]

    def test_fix_coordinates_come_from_transcribed_waypoints(self, ds, hb):
        for p in hb.patterns:
            w = ds.procedures.fix(p.fix)
            assert (p.lat, p.lon) == (w.lat, w.lon)


class TestCircuitTime:
    def test_a_circuit_is_two_legs_and_two_half_turns(self, hb):
        p = hb.pattern("COWON")
        gs = 200.0
        t = hb.circuit_time_s(p, gs)
        leg_s = p.leg_nm / gs * 3600.0
        rate = p.turn_rate_deg_per_s(gs, 3.0, 25.0)
        assert t == pytest.approx(2 * leg_s + 2 * (180.0 / rate))

    def test_faster_aircraft_take_longer_where_no_speed_limit_is_published(self, hb):
        """뱅크각 한계가 먼저 걸리므로 빠를수록 선회가 느려진다."""
        p = hb.pattern("COWON")
        assert hb.circuit_time_s(p, 300.0) > hb.circuit_time_s(p, 230.0)

    def test_published_speed_limit_caps_the_circuit(self, hb):
        """IKAPO 는 230kt 제한이 공고되어 있어 그 위로는 같아진다."""
        p = hb.pattern("IKAPO")
        assert p.speed_max_kt == 230
        assert hb.circuit_time_s(p, 300.0) == pytest.approx(hb.circuit_time_s(p, 230.0))

    def test_turn_rate_is_the_slower_of_standard_and_bank_limited(self, hb):
        p = hb.pattern("COWON")
        assert p.turn_rate_deg_per_s(120.0, 3.0, 25.0) == pytest.approx(3.0)
        assert p.turn_rate_deg_per_s(300.0, 3.0, 25.0) < 3.0

    def test_circuit_is_a_few_minutes_not_seconds(self, hb):
        """규모 확인 — 장주 한 바퀴는 4~6분 정도여야 한다."""
        for p in hb.patterns:
            t = hb.circuit_time_s(p, 230.0)
            assert 240.0 < t < 400.0, f"{p.fix} {t:.0f}s"


class TestStackLevels:
    def test_levels_step_by_the_vertical_minimum(self, ds, hb):
        step = ds.airspace.raw["holding"]["level_step_ft"]
        assert step == ds.airspace.raw["separation"]["vertical"]["below_fl410_ft"]
        lv = hb.levels(hb.pattern("IKAPO"))
        assert all(b - a == step for a, b in zip(lv, lv[1:]))

    def test_levels_start_at_the_published_altitude(self, hb):
        for p in hb.patterns:
            assert hb.levels(p)[0] == p.alt_ft

    def test_levels_stop_at_the_published_ceiling(self, hb):
        for p in hb.patterns:
            assert hb.levels(p)[-1] <= p.max_alt_ft

    def test_capacity_is_the_sum_of_all_levels(self, hb):
        assert hb.capacity == sum(len(hb.levels(p)) for p in hb.patterns)
        assert hb.capacity == 9  # IKAPO 7~10 (4) + COWON 6~10 (5)


class TestAssignment:
    def test_circuits_round_up_to_whole_laps(self, hb):
        """반 바퀴에서 빠져나오는 지시는 규정 용어에 없다."""
        a = hb.assign("AC1", 230.0, 60.0, fix="COWON")
        assert a.circuits == 1
        assert a.delay_s >= 60.0

    def test_more_need_means_more_circuits(self, hb):
        one = hb.assign("AC1", 230.0, 60.0, fix="COWON")
        many = hb.assign("AC1", 230.0, 900.0, fix="COWON")
        assert many.circuits > one.circuits
        assert many.delay_s >= 900.0

    def test_zero_need_gets_no_hold(self, hb):
        assert hb.assign("AC1", 230.0, 0.0, fix="COWON") is None

    def test_occupied_levels_are_not_reused(self, hb):
        taken = {"COWON": {6000.0, 7000.0}}
        a = hb.assign("AC1", 230.0, 60.0, fix="COWON", occupied_levels=taken)
        assert a.level_ft == 8000.0

    def test_full_pattern_returns_none_rather_than_overlapping(self, hb):
        """자리가 없으면 지어낸 고도에 세우지 않는다."""
        full = {"COWON": set(hb.levels(hb.pattern("COWON")))}
        assert hb.assign("AC1", 230.0, 60.0, fix="COWON", occupied_levels=full) is None

    def test_nearest_picks_a_published_pattern(self, ds, hb):
        w = ds.procedures.fix("IKAPO")
        assert hb.nearest(w.lat, w.lon).fix == "IKAPO"


class TestDelayInformation:
    """고시 4-6-3 나 — 30분 이상이면 지연정보 발부."""

    def test_threshold_comes_from_data(self, ds, hb):
        assert ds.airspace.raw["holding"]["delay_info_threshold_min"] == 30

    def test_short_delay_needs_no_efc(self, hb):
        a = hb.assign("AC1", 230.0, 60.0, fix="COWON")
        assert not hb.needs_delay_info(a.delay_s)
        assert a.efc_s is None

    def test_long_delay_carries_an_efc(self, hb):
        a = hb.assign("AC1", 230.0, 40 * 60.0, fix="COWON", now_s=0.0)
        assert hb.needs_delay_info(a.delay_s)
        assert a.efc_s is not None and a.efc_s >= a.delay_s


class TestPhraseology:
    """고시 4-6-1 나 2) — 공고 장주는 'AS PUBLISHED' 로 지시한다."""

    def test_uses_as_published(self, hb):
        a = hb.assign("KAL123", 230.0, 60.0, fix="IKAPO")
        assert "AS PUBLISHED" in a.phraseology()
        assert "IKAPO" in a.phraseology()

    def test_right_turns_are_not_spoken(self, hb):
        """4-6-4 마 — 좌선회일 때만 선회방향을 발부한다."""
        a = hb.assign("KAL123", 230.0, 60.0, fix="IKAPO")
        assert "LEFT TURNS" not in a.phraseology()

    def test_efc_appears_only_when_required(self, hb):
        short = hb.assign("A", 230.0, 60.0, fix="COWON")
        long = hb.assign("B", 230.0, 40 * 60.0, fix="COWON")
        assert "EXPECT FURTHER CLEARANCE" not in short.phraseology()
        assert "EXPECT FURTHER CLEARANCE" in long.phraseology()


class TestStacking:
    def test_fills_across_patterns_when_no_fix_is_given(self, hb):
        reqs = [(f"AC{i}", 230.0, 60.0) for i in range(6)]
        placed, refused = hb.stack(reqs)
        assert not refused
        assert len({(a.pattern.fix, a.level_ft) for a in placed}) == 6
        assert len({a.pattern.fix for a in placed}) == 2

    def test_no_two_aircraft_share_a_level_at_the_same_fix(self, hb):
        placed, _ = hb.stack([(f"AC{i}", 230.0, 60.0) for i in range(9)])
        seen = {(a.pattern.fix, a.level_ft) for a in placed}
        assert len(seen) == len(placed)

    def test_beyond_capacity_is_refused_not_squeezed(self, hb):
        reqs = [(f"AC{i}", 230.0, 60.0) for i in range(hb.capacity + 3)]
        placed, refused = hb.stack(reqs)
        assert len(placed) == hb.capacity
        assert len(refused) == 3

    def test_single_fix_stacking_respects_that_pattern_only(self, hb):
        placed, refused = hb.stack(
            [(f"AC{i}", 230.0, 60.0) for i in range(6)], fix="IKAPO"
        )
        assert {a.pattern.fix for a in placed} == {"IKAPO"}
        assert len(placed) == len(hb.levels(hb.pattern("IKAPO")))
        assert len(refused) == 6 - len(placed)
