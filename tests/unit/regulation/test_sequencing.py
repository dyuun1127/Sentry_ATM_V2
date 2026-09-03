"""도착 시퀀싱 검증.

핵심은 "만들어진 스케줄이 실제로 비행 가능한가"다. 슬롯 시각만 그럴듯하고
그대로 날렸을 때 분리위반이 나면 아무 의미가 없으므로, 스케줄대로 항적을
중심선에 배치해 분리·후류를 다시 검사하는 테스트를 둔다.
"""

import math

import pytest

from sentry_atm.regulation import conflict as cf
from sentry_atm.regulation import data as sdata
from sentry_atm.regulation import sequencing as seq
from sentry_atm.regulation.geo import separation_distance_nm, vincenty_direct
from sentry_atm.regulation.state import AircraftState

FT_PER_NM = 6076.11548556


@pytest.fixture(scope="module")
def ds():
    return sdata.load()


@pytest.fixture(scope="module")
def sq(ds):
    return seq.build(ds)


@pytest.fixture(scope="module")
def det(ds):
    return cf.build(ds)


def inbound(sq, callsign, dist_nm, actype, *, offset_nm=0.0, gs_kt=None, emergency=False):
    """연장 중심선 위 dist_nm 지점에 활공로 고도로 배치."""
    ds = sq.ds
    cat = ds.fleet.wake_cat(actype)
    gs = gs_kt if gs_kt is not None else ds.fleet.final_gs_kt(actype, cat)
    lat, lon = vincenty_direct(
        *sq.thr, (sq.final_course_deg + 180.0) % 360.0, dist_nm * 1852.0
    )
    if offset_nm:
        lat, lon = vincenty_direct(lat, lon, (sq.final_course_deg + 90.0) % 360.0,
                                   offset_nm * 1852.0)
    return AircraftState(
        callsign=callsign, lat=lat, lon=lon,
        alt_ft=sq.glidepath_altitude_ft(dist_nm),
        track_deg=sq.final_course_deg, gs_kt=gs,
        actype=actype, wake_cat=cat, emergency=emergency,
    )


def fly_schedule(sq, arrivals, schedule, at_time_s):
    """스케줄대로 날았을 때 at_time_s 시점의 항적 배치를 만든다.

    각 기체는 자기 슬롯 시각에 시단을 통과하도록 중심선 위에 놓인다.
    """
    by_cs = {ac.callsign: ac for ac in arrivals}
    out = []
    for slot in schedule.slots:
        ac = by_cs[slot.callsign]
        v = sq.final_gs_kt(ac)
        remaining_nm = (slot.threshold_time_s - at_time_s) / 3600.0 * v
        if remaining_nm <= 0:
            continue  # 이미 착륙
        lat, lon = vincenty_direct(
            *sq.thr, (sq.final_course_deg + 180.0) % 360.0, remaining_nm * 1852.0
        )
        out.append(
            AircraftState(
                callsign=ac.callsign, lat=lat, lon=lon,
                alt_ft=sq.glidepath_altitude_ft(remaining_nm),
                track_deg=sq.final_course_deg, gs_kt=v,
                actype=ac.actype, wake_cat=ac.wake_cat,
            )
        )
    return out


class TestGeometry:
    def test_join_point_defaults_to_the_if(self, sq, ds):
        """합류점 기본값은 절차의 IF(TURTU) — 여기서부터 최종접근진로에 정렬된다."""
        turtu = ds.procedures.fix("TURTU")
        assert sq.join_dist_nm == pytest.approx(
            separation_distance_nm(turtu.lat, turtu.lon, *sq.thr), abs=0.01
        )
        assert sq.join_dist_nm == pytest.approx(13.03, abs=0.05)

    def test_join_point_is_on_the_extended_centreline(self, sq):
        jlat, jlon = sq.join_point
        ac = AircraftState("J", jlat, jlon, 3700, sq.final_course_deg, 200)
        assert sq.centreline_offset_nm(ac) == pytest.approx(0.0, abs=0.001)

    def test_glidepath_altitude_matches_published_faf(self, sq, ds):
        """3° 활공로가 FAF 고시고도를 재현해야 한다 (Phase 1 교차확인의 재확인)."""
        alt = sq.glidepath_altitude_ft(sq.faf_dist_nm)
        assert alt == pytest.approx(2100, abs=15)

    def test_established_requires_alignment_and_proximity(self, sq):
        aligned = inbound(sq, "AAA", 10.0, "B738")
        assert sq.is_established(aligned)

        offset = inbound(sq, "BBB", 10.0, "B738", offset_nm=1.5)
        assert not sq.is_established(offset), "중심선에서 1.5NM 벗어남"

        far = inbound(sq, "CCC", 20.0, "B738")
        assert not sq.is_established(far), "합류점 바깥"

    def test_offset_sign_is_right_positive(self, sq):
        right = inbound(sq, "R", 10.0, "B738", offset_nm=1.0)
        assert sq.centreline_offset_nm(right) == pytest.approx(1.0, abs=0.02)


class TestGapRequirement:
    def test_heavy_ahead_of_small_uses_landing_minimum(self, sq):
        """대형 뒤 소형 → 6NM (고시 5-5-4 아)."""
        leader = inbound(sq, "HVY", 6.0, "KC30")     # 대형
        follower = inbound(sq, "SML", 12.0, "F35A")  # 소형
        g = sq.gap_requirement(leader, follower)
        assert g.required_nm == 6.0
        assert "5-5-4 아" in g.clauses
        # 6NM ÷ F-35A 150kt = 144초
        assert g.seconds == pytest.approx(6.0 / 150.0 * 3600.0, abs=0.5)
        assert g.driver == "후류"

    def test_gap_uses_follower_speed_not_leader(self, sq):
        """같은 선행기·같은 등급이라도 후행기 속도가 다르면 간격 시간이 다르다."""
        leader = inbound(sq, "HVY", 6.0, "KC30")
        fast = sq.gap_requirement(leader, inbound(sq, "F", 12.0, "KF16"))   # 소형 155kt
        slow = sq.gap_requirement(leader, inbound(sq, "S", 12.0, "FA50"))   # 소형 145kt
        assert fast.required_nm == slow.required_nm == 6.0, "같은 등급 조합"
        assert fast.seconds < slow.seconds, "빠른 후행기가 같은 거리를 더 빨리 소화한다"
        assert fast.seconds == pytest.approx(6.0 / 155.0 * 3600.0, abs=0.5)
        assert slow.seconds == pytest.approx(6.0 / 145.0 * 3600.0, abs=0.5)

    def test_wake_category_alone_does_not_fix_the_gap(self, sq):
        """같은 후행 등급이어도 기종이 다르면 간격이 다르다 — 등급별 고정값이면 안 되는 이유."""
        leader = inbound(sq, "MED", 5.0, "B738")
        g_f35 = sq.gap_requirement(leader, inbound(sq, "A", 10.0, "F35A"))
        g_fa50 = sq.gap_requirement(leader, inbound(sq, "B", 10.0, "FA50"))
        assert g_f35.required_nm == g_fa50.required_nm == 4.0
        assert g_f35.seconds != g_fa50.seconds

    def test_in_trail_distance_governs_not_runway_occupancy(self, sq):
        """청주 접근속도 대역에서는 종렬 거리 요건이 항상 활주로 점유를 넘는다.

        3NM ÷ 140kt = 77초 > 활주로 점유 60초 + 여유 10초. 활주로 점유가 지배하려면
        후행기 최종접근속도가 180kt 를 넘어야 하는데 그런 기종이 없다.
        즉 시퀀싱의 지렛대는 전적으로 종렬 거리(후류·레이더)에 있다.
        """
        leader = inbound(sq, "AAA", 5.0, "B738")
        follower = inbound(sq, "BBB", 9.0, "B738")
        g = sq.gap_requirement(leader, follower)
        assert g.required_nm == 3.0          # 레이더 최저치 (후류 추가분리 불요)
        assert g.driver == "레이더"
        assert g.seconds == pytest.approx(3.0 / 140.0 * 3600.0, abs=0.5)
        assert g.seconds > 60 + 10

    def test_fast_leader_binds_at_the_join_not_the_threshold(self, sq):
        """선행기가 더 빠르면 최소 이격이 시단이 아니라 합류부에서 나온다.

        F-35A(150kt) 뒤 B737(140kt). 시단 통과 시점만 3NM 으로 맞추면
        합류부에서는 2.6NM 밖에 안 된다 — 고시 5-5-4 가 위반이다.
        간격 요건은 두 지점을 모두 만족해야 한다.
        """
        leader = inbound(sq, "F35", 5.0, "F35A")    # 150kt
        follower = inbound(sq, "B73", 10.0, "B738")  # 140kt
        g = sq.gap_requirement(leader, follower)
        assert g.binding == "합류부"
        assert g.seconds > 3.0 / 140.0 * 3600.0, "시단 기준만으로는 부족하다"

        # 이 간격으로 날았을 때 합류부에서 실제로 3NM 이 확보되는지 확인
        v_l, v_f, d = 150.0, 140.0, sq.join_dist_nm
        sep_at_join = d * (1 - v_l / v_f) + v_l * g.seconds / 3600.0
        assert sep_at_join >= 3.0 - 1e-6

    def test_slow_leader_binds_at_the_threshold(self, sq):
        """후행기가 더 빠르면(압축) 최소 이격은 시단에서 나온다 — 통상적인 경우."""
        leader = inbound(sq, "B73", 5.0, "B738")     # 140kt
        follower = inbound(sq, "F35", 10.0, "F35A")  # 150kt
        g = sq.gap_requirement(leader, follower)
        assert g.binding == "시단"
        assert g.seconds == pytest.approx(g.required_nm / 150.0 * 3600.0, abs=0.5)

    def test_fighter_behind_airliner_is_the_awkward_case(self, sq):
        """전투기(소형)가 민항기(중형) 뒤 — 등급은 가볍지만 접근속도는 더 빠르다.

        민항 전용 공항의 '가벼우면 느리다' 전제가 깨지는 지점이다.
        """
        airliner = inbound(sq, "KAL", 5.0, "B738")   # 중형 140kt
        fighter = inbound(sq, "MIG", 10.0, "F35A")   # 소형 150kt
        assert sq.final_gs_kt(fighter) > sq.final_gs_kt(airliner)
        g = sq.gap_requirement(airliner, fighter)
        assert g.required_nm == 4.0           # 중형 뒤 소형, 착륙 (5-5-4 아)
        assert "5-5-4 아" in g.clauses


class TestAltitudeLadder:
    def test_ladder_assigned_by_sequence_order(self, sq):
        arrivals = [inbound(sq, f"AC{i}", 12.0 + 6.0 * i, "B738") for i in range(3)]
        s = sq.build(arrivals)
        assert [x.assigned_alt_ft for x in s.slots] == [4000, 5000, 6000]
        assert not any(x.holding_above for x in s.slots)

    def test_adjacent_orders_have_vertical_separation(self, sq, ds):
        """인접 순번 간 1,000ft 확보 — 고시 4-5-1 이 구조적으로 만족된다."""
        arrivals = [inbound(sq, f"AC{i}", 12.0 + 6.0 * i, "B738") for i in range(3)]
        alts = [x.assigned_alt_ft for x in sq.build(arrivals).slots]
        for lo, hi in zip(alts, alts[1:]):
            assert hi - lo >= ds.airspace.sep_vertical_ft

    def test_ladder_exhaustion_is_flagged(self, sq):
        """4번째부터는 사다리를 넘어 상위 섹터 대기 대상이 된다 (T17 상한 6,500ft)."""
        arrivals = [inbound(sq, f"AC{i}", 12.0 + 6.0 * i, "B738") for i in range(5)]
        s = sq.build(arrivals)
        assert [x.holding_above for x in s.slots] == [False, False, False, True, True]
        assert max(x.assigned_alt_ft for x in s.slots) == 6000


class TestScheduleOrder:
    def test_first_come_first_served(self, sq):
        """고시 2-1-4 — 도달시각 순."""
        arrivals = [
            inbound(sq, "FAR", 30.0, "B738"),
            inbound(sq, "NEAR", 8.0, "B738"),
            inbound(sq, "MID", 18.0, "B738"),
        ]
        assert sq.build(arrivals).order == ["NEAR", "MID", "FAR"]

    def test_slots_respect_gap_requirements(self, sq):
        arrivals = [
            inbound(sq, "HVY", 8.0, "KC30"),
            inbound(sq, "SML", 14.0, "F35A"),
            inbound(sq, "MED", 22.0, "B738"),
        ]
        s = sq.build(arrivals)
        for a, b in zip(s.slots, s.slots[1:]):
            assert b.threshold_time_s - a.threshold_time_s >= b.gap.seconds - 1e-6

    def test_no_delay_when_naturally_spaced(self, sq):
        """이미 충분히 벌어져 있으면 슬롯을 밀 필요가 없다."""
        arrivals = [inbound(sq, f"AC{i}", 8.0 + 10.0 * i, "B738") for i in range(3)]
        s = sq.build(arrivals)
        assert s.total_delay_s == pytest.approx(0.0, abs=1.0)

    def test_bunched_arrivals_incur_delay(self, sq):
        arrivals = [inbound(sq, f"AC{i}", 8.0 + 0.5 * i, "B738") for i in range(4)]
        s = sq.build(arrivals)
        assert s.total_delay_s > 60.0


class TestScheduleIsFlyable:
    """스케줄대로 날렸을 때 실제로 분리가 유지되는가 — 이게 진짜 검증이다."""

    @pytest.mark.parametrize("t", [0.0, 120.0, 300.0, 600.0])
    def test_mixed_fleet_sequence_has_no_violations(self, sq, det, t):
        arrivals = [
            inbound(sq, "KAL101", 10.0, "B738"),
            inbound(sq, "TWB202", 14.0, "A321"),
            inbound(sq, "ROKAF1", 19.0, "F35A"),
            inbound(sq, "ROKAF2", 24.0, "KC30"),
            inbound(sq, "JJA303", 29.0, "B738"),
            inbound(sq, "ROKAF3", 34.0, "C130"),
        ]
        schedule = sq.build(arrivals)
        traffic = fly_schedule(sq, arrivals, schedule, t)
        found = det.scan(traffic, final_course_deg=sq.final_course_deg,
                         landing_sequence=schedule.order)
        assert found == [], "\n".join(c.describe() for c in found)

    def test_bunched_arrivals_are_resolved_by_scheduling(self, sq, det):
        """거의 겹쳐 들어오는 항적도 슬롯을 밀면 분리가 확보된다."""
        arrivals = [
            inbound(sq, "A1", 12.0, "KC30"),
            inbound(sq, "A2", 12.6, "F35A"),
            inbound(sq, "A3", 13.1, "B738"),
            inbound(sq, "A4", 13.7, "F35A"),
        ]
        schedule = sq.build(arrivals)
        for t in (0.0, 60.0, 150.0, 300.0):
            traffic = fly_schedule(sq, arrivals, schedule, t)
            found = det.scan(traffic, final_course_deg=sq.final_course_deg,
                             landing_sequence=schedule.order)
            assert found == [], f"t={t}: " + "\n".join(c.describe() for c in found)

    def test_all_aircraft_are_established_on_centreline(self, sq):
        """스케줄대로 날면 합류점 안쪽에서 전부 중심선에 정렬되어 있어야 한다.

        측방 이격이 아니라 종렬 거리만으로 분리가 성립하는 근거다.
        """
        arrivals = [inbound(sq, f"AC{i}", 10.0 + 5.0 * i, "B738") for i in range(4)]
        schedule = sq.build(arrivals)
        traffic = fly_schedule(sq, arrivals, schedule, 200.0)
        inside = [ac for ac in traffic
                  if sq.distance_to_threshold_nm(ac) <= sq.join_dist_nm]
        assert inside
        for ac in inside:
            assert sq.is_established(ac), f"{ac.callsign} 미정렬"


class TestPriorityInsertion:
    """고시 2-1-4 가 — 조난 항공기 최우선 통행권."""

    @pytest.fixture
    def scenario(self, sq):
        """정상 접근 20대.

        2.6NM 간격 — 140kt 에서 자연 간격 67초로, 요구 간격(77~150초)보다 좁다.
        따라서 대기열이 생기고 슬롯이 밀린다. 실제 혼잡 시간대의 상황이다.
        """
        types = ["B738", "A321", "F35A", "B738", "KC30", "F35A"]
        return [
            inbound(sq, f"AC{i:02d}", 10.0 + 2.6 * i, types[i % len(types)])
            for i in range(20)
        ]

    def test_emergency_moves_up_without_emptying_the_runway(self, sq, scenario):
        """비상기를 앞으로 당기되 활주로 공백을 만들지 않는다.

        순번 1번으로 밀어넣으면 비상기가 도달할 때까지 활주로가 비고
        뒤 항적 전체가 그만큼 밀린다. 물리적 최단 도달시각 기준 삽입은
        그 공백을 만들지 않는다.
        """
        before = sq.build(scenario)
        after = sq.insert_priority(scenario, "AC19")

        cmp_ = seq.compare(before, after, "AC19")
        assert cmp_.order_after < cmp_.order_before, "순번이 앞당겨져야 한다"
        assert cmp_.time_saved_s > 0, "착륙 시각이 단축되어야 한다"

        # 활주로 공백 검사: 최대 슬롯 간격이 기준 대비 크게 벌어지면 안 된다
        def max_gap(s):
            return max(
                (b.threshold_time_s - a.threshold_time_s
                 for a, b in zip(s.slots, s.slots[1:])), default=0.0
            )
        assert max_gap(after) <= max_gap(before) + 60.0, "활주로 공백이 생겼다"

    def test_emergency_never_lands_before_it_can_physically_arrive(self, sq, scenario):
        after = sq.insert_priority(scenario, "AC19")
        slot = after.by_callsign("AC19")
        assert slot.threshold_time_s >= slot.earliest_time_s - 1e-6

    def test_established_traffic_is_not_disturbed(self, sq, scenario):
        """시단 16NM 안쪽 항적은 이미 접근이 확정된 것으로 보고 건드리지 않는다."""
        before = sq.build(scenario)
        after = sq.insert_priority(scenario, "AC19")
        for ac in scenario:
            if sq.distance_to_threshold_nm(ac) <= 16.0:
                assert after.by_callsign(ac.callsign).threshold_time_s == pytest.approx(
                    before.by_callsign(ac.callsign).threshold_time_s, abs=1.0
                ), f"{ac.callsign} 확정 항적인데 슬롯이 움직였다"

    def test_priority_schedule_is_still_flyable(self, sq, det, scenario):
        """우선권을 적용한 스케줄도 분리위반이 없어야 한다."""
        after = sq.insert_priority(scenario, "AC19")
        emergency = [
            ac if ac.callsign != "AC19" else
            AircraftState(**{**ac.__dict__, "emergency": True})
            for ac in scenario
        ]
        for t in (0.0, 300.0, 900.0, 1800.0):
            traffic = fly_schedule(sq, emergency, after, t)
            found = det.scan(traffic, final_course_deg=sq.final_course_deg,
                             landing_sequence=after.order)
            assert found == [], f"t={t}: " + "\n".join(c.describe() for c in found)

    def test_comparison_reports_displaced_traffic(self, sq, scenario):
        before = sq.build(scenario)
        after = sq.insert_priority(scenario, "AC19")
        cmp_ = seq.compare(before, after, "AC19")
        assert isinstance(cmp_.displaced, list)
        if cmp_.displaced:
            assert cmp_.mean_added_delay_s > 0


class TestScheduleMetrics:
    def test_mean_gap_and_makespan(self, sq):
        arrivals = [inbound(sq, f"AC{i}", 8.0 + 4.0 * i, "B738") for i in range(5)]
        s = sq.build(arrivals)
        assert s.mean_gap_s > 0
        assert s.makespan_s == pytest.approx(
            s.slots[-1].threshold_time_s - s.slots[0].threshold_time_s
        )

    def test_by_callsign_raises_for_unknown(self, sq):
        s = sq.build([inbound(sq, "AAA", 10.0, "B738")])
        with pytest.raises(KeyError):
            s.by_callsign("NOPE")
