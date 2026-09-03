"""규정 엔진 검증.

고시의 수치뿐 아니라 **조항에 붙은 조건**이 구현되어 있는지를 본다.
표만 맞고 조건이 빠지면 안전필수 판정에서 조용히 틀린다.
"""

import pytest

from sentry_atm.regulation import data as sdata
from sentry_atm.regulation.geo import vincenty_direct
from sentry_atm.regulation.rules import FT_PER_NM, RuleBook
from sentry_atm.regulation.state import AircraftState

RKTU = (36.71639, 127.4992)
FINAL_COURSE = 232.43  # RWY 24R 진방위 (AD 2.12)


@pytest.fixture(scope="module")
def rb():
    return RuleBook(sdata.load())


def on_final(callsign, dist_from_thr_nm, alt_ft, wake_cat, offset_nm=0.0, **kw):
    """RWY 24R 연장 중심선 위 지점에 항적 배치.

    dist_from_thr_nm 이 작을수록 활주로에 가깝다 — 즉 **선행기**다.
    3° 활공로상에서는 활주로에 가까울수록 고도가 낮다.
    offset_nm 은 우측이 양수.
    """
    lat, lon = vincenty_direct(*RKTU, (FINAL_COURSE + 180) % 360, dist_from_thr_nm * 1852.0)
    if offset_nm:
        lat, lon = vincenty_direct(lat, lon, (FINAL_COURSE + 90) % 360, offset_nm * 1852.0)
    return AircraftState(
        callsign=callsign, lat=lat, lon=lon, alt_ft=alt_ft,
        track_deg=FINAL_COURSE, gs_kt=150, wake_cat=wake_cat, **kw
    )


class TestSeparationStandard:
    def test_default_is_3nm_and_1000ft(self, rb):
        """T17 은 ASR 40마일 미만이므로 3NM (고시 5-5-4 가), 수직 1,000ft (4-5-1)."""
        a = on_final("AAA", 12, 4000, "중형")
        b = on_final("BBB", 8, 3000, "중형")
        std = rb.separation_standard(a, b)
        assert std.horizontal_nm == 3.0
        assert std.vertical_ft == 1000.0
        assert "5-5-4 가" in std.clauses and "4-5-1" in std.clauses

    def test_reduced_final_disabled_by_default(self, rb):
        """2.5NM 감축(5-5-4 차)은 활주로 점유시간 조건이 미확인이라 꺼져 있어야 한다."""
        a = on_final("AAA", 6, 2200, "소형")
        b = on_final("BBB", 3, 1300, "대형")
        std = rb.separation_standard(a, b, on_final_within_10nm=True)
        assert std.horizontal_nm == 3.0, "미확인 조건 위에서 분리를 줄이면 안 된다"

    def test_reduced_final_respects_weight_class_condition(self, rb):
        """감축을 켜더라도 선행기 중량등급이 후행기 이하일 때만 적용된다 (5-5-4 차 1)."""
        cfg = rb.ds.airspace.raw["separation"]["reduced_final"]
        cfg["enabled"] = True
        try:
            # 선행 소형 → 후행 대형: 조건 충족
            ok = rb.separation_standard(
                on_final("L", 6, 2200, "소형"), on_final("F", 3, 1300, "대형"),
                on_final_within_10nm=True,
            )
            assert ok.horizontal_nm == 2.5
            # 선행 대형 → 후행 소형: 조건 불충족
            ng = rb.separation_standard(
                on_final("L", 6, 2200, "대형"), on_final("F", 3, 1300, "소형"),
                on_final_within_10nm=True,
            )
            assert ng.horizontal_nm == 3.0
        finally:
            cfg["enabled"] = False


class TestWakeInFlight:
    """고시 5-5-4 사 — 비행 중 종렬. 기하 조건이 붙는다."""

    def test_heavy_ahead_of_small_is_5nm_in_flight(self, rb):
        """비행 중에는 대형 뒤 소형이 5마일 (착륙 시 6마일과 다르다)."""
        leader = on_final("HVY", 8, 2700, "대형")
        follower = on_final("SML", 12, 3300, "소형")
        req = rb.wake_in_trail(leader, follower)
        assert req.applies and req.required_nm == 5.0
        assert "5-5-4 사" in req.clauses

    def test_heavy_ahead_of_small_is_6nm_on_landing(self, rb):
        """동일 활주로 착륙 시에는 아항이 부가되어 6마일."""
        leader = on_final("HVY", 8, 2700, "대형")
        follower = on_final("SML", 12, 3300, "소형")
        req = rb.wake_in_trail(leader, follower, same_landing_runway=True)
        assert req.required_nm == 6.0
        assert "5-5-4 아" in req.clauses

    def test_medium_ahead_of_small_only_applies_on_landing(self, rb):
        """중형 뒤 소형은 사항 표에 없고 아항(착륙)에만 4마일이 있다."""
        leader = on_final("MED", 8, 2700, "중형")
        follower = on_final("SML", 12, 3300, "소형")
        assert not rb.wake_in_trail(leader, follower).applies
        assert rb.wake_in_trail(leader, follower, same_landing_runway=True).required_nm == 4.0

    @pytest.mark.parametrize(
        "leader_cat,follower_cat,expected",
        [("초대형", "대형", 5.0), ("초대형", "중형", 7.0), ("초대형", "소형", 8.0),
         ("대형", "대형", 4.0), ("대형", "중형", 5.0)],
    )
    def test_in_flight_table(self, rb, leader_cat, follower_cat, expected):
        leader = on_final("L", 8, 2700, leader_cat)
        follower = on_final("F", 12, 3300, follower_cat)
        assert rb.wake_in_trail(leader, follower).required_nm == expected

    def test_lateral_gate_2500ft(self, rb):
        """측방 2,500ft 를 벗어나면 항적난기류 분리 불요 (5-5-4 사 1)."""
        leader = on_final("HVY", 8, 2700, "대형")
        gate_nm = 2500.0 / FT_PER_NM

        inside = on_final("A", 12, 3300, "소형", offset_nm=gate_nm * 0.9)
        assert rb.wake_in_trail(leader, inside).applies

        outside = on_final("B", 12, 3300, "소형", offset_nm=gate_nm * 1.5)
        req = rb.wake_in_trail(leader, outside)
        assert not req.applies
        assert "측방" in req.rationale and "5-5-4 사" in req.rationale

    def test_below_gate_1000ft(self, rb):
        """후행기가 선행기보다 1,000ft 이상 아래일 때만 불요 (5-5-4 사 1)."""
        leader = on_final("HVY", 8, 5000, "대형")

        just_below = on_final("A", 12, 4200, "소형")   # 800ft 아래 — 적용
        assert rb.wake_in_trail(leader, just_below).applies

        well_below = on_final("B", 12, 3800, "소형")   # 1,200ft 아래 — 불요
        req = rb.wake_in_trail(leader, well_below)
        assert not req.applies and "아래" in req.rationale

    def test_follower_above_leader_still_applies(self, rb):
        """후행기가 선행기보다 높아도 적용된다.

        고시는 "아래로 1,000피트 **미만**"만 배제하므로, 위에 있는 경우는
        조건을 만족한다. 3° 활공로에서 후행기는 항상 선행기보다 높으므로
        이걸 배제하면 정상 접근 시퀀스에 후류 분리가 전혀 안 걸린다.
        """
        leader = on_final("HVY", 8, 2700, "대형")
        above = on_final("SML", 12, 3800, "소형")   # 1,100ft 위
        assert rb.wake_in_trail(leader, above).applies

    def test_wake_violation_detects_too_close(self, rb):
        leader = on_final("HVY", 7, 2500, "대형")
        follower = on_final("SML", 10, 3000, "소형")  # 3NM 종렬, 요건 5NM
        violated, req, actual = rb.wake_violation(
            leader, follower, FINAL_COURSE
        )
        assert violated
        assert actual == pytest.approx(3.0, abs=0.01)
        assert req.required_nm == 5.0

    def test_wake_violation_clear_when_spaced(self, rb):
        leader = on_final("HVY", 6, 2200, "대형")
        follower = on_final("SML", 12, 3300, "소형")  # 6NM 종렬
        violated, _, actual = rb.wake_violation(leader, follower, FINAL_COURSE)
        assert not violated and actual == pytest.approx(6.0, abs=0.01)


class TestPriority:
    def test_emergency_outranks_normal(self, rb):
        """고시 2-1-4 가 — 조난 항공기 최우선 통행권."""
        emerg = on_final("EMG", 20, 6000, "소형", emergency=True)
        normal = on_final("NRM", 8, 3000, "중형")
        assert rb.priority_rank(emerg)[0] < rb.priority_rank(normal)[0]
        assert "2-1-4" in rb.priority_rank(emerg)[1]

    def test_normal_traffic_is_first_come_first_served(self, rb):
        a = on_final("AAA", 20, 6000, "중형")
        b = on_final("BBB", 8, 3000, "대형")
        assert rb.priority_rank(a)[0] == rb.priority_rank(b)[0]


class TestAltitudeAssignment:
    def test_ladder_is_three_layers_under_t17_ceiling(self, rb):
        assert rb.altitude_ladder_ft == [4000, 5000, 6000]
        assert max(rb.altitude_ladder_ft) < rb.ds.airspace.handoff_alt_ft

    def test_later_sequence_gets_higher_altitude(self, rb):
        """순번이 뒤일수록 높은 고도 — 인접 순번 간 1,000ft 가 구조적으로 확보된다."""
        alts = [rb.assigned_altitude_ft(i) for i in range(3)]
        assert alts == [4000, 5000, 6000]
        for lo, hi in zip(alts, alts[1:], strict=False):
            assert hi - lo >= rb.ds.airspace.sep_vertical_ft

    def test_ladder_exhaustion_flagged(self, rb):
        assert not rb.ladder_exhausted(2)
        assert rb.ladder_exhausted(3)
        assert rb.assigned_altitude_ft(9) == 6000

    def test_direction_of_flight_rule(self, rb):
        """4-5-2 — 자침 0~179° 홀수, 180~359° 짝수."""
        east = AircraftState("E", *RKTU, 7000, track_deg=81.0, gs_kt=300)   # 자침 90
        ok, why = rb.direction_of_flight_altitude_ok(east)
        assert ok and "홀수" in why

        west = AircraftState("W", *RKTU, 8000, track_deg=261.0, gs_kt=300)  # 자침 270
        ok, why = rb.direction_of_flight_altitude_ok(west)
        assert ok and "짝수" in why

        wrong = AircraftState("X", *RKTU, 8000, track_deg=81.0, gs_kt=300)
        assert not rb.direction_of_flight_altitude_ok(wrong)[0]


class TestFormation:
    def test_formation_adds_separation(self, rb):
        """고시 5-5-8 — 군 운용 공역에서 실제로 발생하는 편대비행 추가분리."""
        from dataclasses import dataclass

        @dataclass(frozen=True)
        class FormationState(AircraftState):
            is_formation: bool = False

        lead = FormationState("FMN1", *RKTU, 5000, 232.43, 300, is_formation=True)
        solo = on_final("SOLO", 8, 5000, "중형")
        assert rb.separation_standard(lead, solo).horizontal_nm == 4.0   # 3 + 1

        lead2 = FormationState("FMN2", *RKTU, 5000, 232.43, 300, is_formation=True)
        assert rb.separation_standard(lead, lead2).horizontal_nm == 5.0  # 3 + 2


class TestAdjacentAirspace:
    def test_boundary_buffer(self, rb):
        """고시 5-5-10 — 협의 없으면 인접공역 경계에서 1.5NM."""
        assert rb.adjacent_boundary_buffer_nm == 1.5
