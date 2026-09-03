"""충돌 회피 검증.

두 가지를 중점적으로 본다.
1. 회피안이 **실제로** 충돌을 해소하고 2차 충돌을 만들지 않는가 (전파해서 확인).
2. 도착 흐름 디컨플릭션이 **발산하지 않는가** — 오프셋 누적이 발산했던 실패의 재발 방지.
"""

import math

import pytest

from sentry_atm.regulation import conflict as cf
from sentry_atm.regulation import data as sdata
from sentry_atm.regulation import resolution as res
from sentry_atm.regulation import sequencing as seq
from sentry_atm.regulation.geo import separation_distance_nm, vincenty_direct
from sentry_atm.regulation.state import AircraftState

RKTU = (36.71639, 127.4992)
H_MIN, V_MIN = 3.0, 1000.0


@pytest.fixture(scope="module")
def ds():
    return sdata.load()


@pytest.fixture(scope="module")
def resolver(ds):
    return res.build(ds)


@pytest.fixture(scope="module")
def sq(ds):
    return seq.build(ds)


def near_field(callsign, brg, dist_nm, alt_ft, track, gs, vs=0.0, **kw):
    """RKTU 기준 방위·거리로 배치 — 청주 GCA 담당 공역 안쪽."""
    lat, lon = vincenty_direct(*RKTU, brg, dist_nm * 1852.0)
    return AircraftState(callsign, lat, lon, alt_ft, track, gs, vs_fpm=vs, **kw)


def on_final(callsign, dist_from_thr_nm, alt_ft, track, gs, **kw):
    """RWY 24R 연장 중심선 위."""
    from sentry_atm.regulation.geo import vincenty_direct as vd
    thr = sdata.load().procedures.runways["24R"]
    lat, lon = vd(thr.thr_lat, thr.thr_lon, (thr.true_brg + 180) % 360,
                  dist_from_thr_nm * 1852.0)
    return AircraftState(callsign, lat, lon, alt_ft, track, gs, **kw)


class TestLevelOff:
    """수평면 유지 — 고도 회피 평가의 전제."""

    def test_altitude_stops_at_target(self):
        ac = near_field("A", 0, 5, 4000, 90, 250, vs=1000.0)
        ac = ac.__class__(**{**ac.__dict__, "target_alt_ft": 5000.0})
        assert ac.altitude_at(30) == pytest.approx(4500)
        assert ac.altitude_at(60) == pytest.approx(5000)
        assert ac.altitude_at(600) == pytest.approx(5000), "목표에서 멈춰야 한다"

    def test_level_off_time(self):
        ac = near_field("A", 0, 5, 4000, 90, 250, vs=1000.0)
        ac = ac.__class__(**{**ac.__dict__, "target_alt_ft": 5000.0})
        assert ac.level_off_time_s == pytest.approx(60.0)

    def test_advance_clears_rate_after_level_off(self):
        ac = near_field("A", 0, 5, 4000, 90, 250, vs=1000.0)
        ac = ac.__class__(**{**ac.__dict__, "target_alt_ft": 5000.0})
        assert ac.advance(120).vs_fpm == 0.0
        assert ac.advance(120).alt_ft == pytest.approx(5000)

    def test_conflict_uses_piecewise_vertical(self, resolver):
        """1,000ft 상승 지시가 지평 끝까지 상승하는 것으로 계산되면 안 된다.

        같은 고도로 정면 접근하는 두 기. 한 기를 1,000ft 상승시키면
        수직분리가 딱 1,000ft 확보되어 해소된다. 등속 외삽이면 10,000ft 가 되어
        해소 폭을 과대평가한다 — 결과는 같지만 근거가 틀린다.
        """
        a = near_field("AAA", 90, 6, 4000, 270, 250)
        b = near_field("BBB", 270, 6, 4000, 90, 250)
        assert resolver.detector.check_radar(a, b) is not None

        climbed = res.Maneuver("AAA", "ALTITUDE", 1000.0).apply(a)
        assert climbed.target_alt_ft == 5000.0
        assert climbed.altitude_at(600) == 5000.0
        assert resolver.detector.check_radar(climbed, b) is None


class TestManeuver:
    def test_heading_rotates_track(self):
        ac = near_field("A", 0, 5, 4000, 90, 250)
        assert res.Maneuver("A", "HEADING", 30).apply(ac).track_deg == pytest.approx(120)
        assert res.Maneuver("A", "HEADING", -30).apply(ac).track_deg == pytest.approx(60)

    def test_speed_never_goes_below_floor(self):
        ac = near_field("A", 0, 5, 4000, 90, 70)
        assert res.Maneuver("A", "SPEED", -40).apply(ac).gs_kt == 60.0

    def test_instruction_uses_magnetic_heading(self, ds):
        """관제 문구는 자방위로 낸다 — 조종사가 듣는 값이다. RKTU VAR 9°W."""
        ac = near_field("KAL1", 0, 5, 4000, 231.0, 150)
        text = res.Maneuver("KAL1", "HEADING", 20).apply
        m = res.Maneuver("KAL1", "HEADING", 20)
        s = m.instruction(ac, ds.procedures.mag_var)
        assert s == "KAL1, 우선회 침로 260"   # (231+20+9) % 360
        assert text is not None

    def test_altitude_instruction(self):
        ac = near_field("KAL1", 0, 5, 4000, 232, 150)
        m = res.Maneuver("KAL1", "ALTITUDE", 1000)
        assert m.instruction(ac) == "KAL1, 상승 고도 5,000피트 유지"

    def test_speed_instruction(self):
        ac = near_field("KAL1", 0, 5, 4000, 232, 160)
        assert res.Maneuver("KAL1", "SPEED", -20).instruction(ac) == \
            "KAL1, 속도 140노트 유지"


class TestCandidates:
    def test_all_options_are_atc_units(self, resolver):
        """후보는 전부 관제 지시로 읽을 수 있는 이산값이어야 한다."""
        ac = near_field("A", 0, 5, 4000, 90, 250)
        cands = resolver.all_candidates(ac)
        headings = {abs(m.delta) for m in cands if m.kind == "HEADING"}
        alts = {abs(m.delta) for m in cands if m.kind == "ALTITUDE"}
        speeds = {abs(m.delta) for m in cands if m.kind == "SPEED"}
        assert headings == {10.0, 20.0, 30.0}
        assert alts == {1000.0, 2000.0}
        assert speeds == {20.0, 40.0}
        assert len(cands) == 14   # 침로 6 + 고도 4 + 속도 4


class TestFeasibility:
    """낼 수 없는 지시를 상신하면 관제사가 곧바로 신뢰를 거둔다."""

    def test_speed_cannot_go_below_final_approach_speed(self, resolver):
        """B737-800 을 최종접근에서 125kt 로 늦추라는 안은 성능상 불가능하다."""
        b738 = near_field("KAL1", 52, 7, 2500, 232.43, 140, actype="B738")
        ok, why = resolver.is_feasible(b738, res.Maneuver("KAL1", "SPEED", -20))
        assert not ok
        assert "최종접근속도" in why and "140" in why

        assert resolver.is_feasible(b738, res.Maneuver("KAL1", "SPEED", +20))[0]

    def test_speed_cannot_exceed_procedure_limit(self, resolver):
        """AIP RNP RWY 24R 의 Max 230 kt IAS."""
        fast = near_field("RKF1", 52, 7, 3000, 232.43, 220, actype="F35A", wake_cat="소형")
        ok, why = resolver.is_feasible(fast, res.Maneuver("RKF1", "SPEED", +40))
        assert not ok and "230" in why
        assert resolver.procedure_speed_max_kt == 230.0

    def test_altitude_cannot_exceed_sector_ceiling(self, resolver):
        """T17 상한 6,500ft 를 넘기면 상위 섹터 협의 사항이다 (고시 2-1-15)."""
        high = near_field("A", 0, 4, 6000, 232.43, 200)
        ok, why = resolver.is_feasible(high, res.Maneuver("A", "ALTITUDE", +1000))
        assert not ok
        assert "6500" in why.replace(",", "") and "OSAN APP" in why

    def test_altitude_cannot_leave_controlled_airspace_downward(self, resolver):
        """최종접근 중 2,000ft 강하하면 5~10NM 링 하한(1,000ft AGL) 아래로 나간다."""
        low = on_final("A", 7.0, 2500, 232.43, 145)
        assert resolver.detector.sector.volume_of(low) == "RING_5_10"
        ok, why = resolver.is_feasible(low, res.Maneuver("A", "ALTITUDE", -2000))
        assert not ok and "담당 공역" in why

    def test_altitude_descent_allowed_when_it_stays_inside(self, resolver):
        high = on_final("A", 7.0, 4500, 232.43, 145)
        assert resolver.is_feasible(high, res.Maneuver("A", "ALTITUDE", -1000))[0]

    def test_heading_is_always_feasible(self, resolver):
        ac = near_field("A", 0, 5, 4000, 90, 250)
        for d in (10, -10, 30, -30):
            assert resolver.is_feasible(ac, res.Maneuver("A", "HEADING", d))[0]

    def test_candidates_are_filtered(self, resolver):
        """생성된 후보에는 불가능한 지시가 없어야 한다."""
        ac = near_field("KAL1", 52, 7, 2500, 232.43, 140, actype="B738")
        assert len(resolver.candidates(ac)) < len(resolver.all_candidates(ac))
        for m in resolver.candidates(ac):
            assert resolver.is_feasible(ac, m)[0]

    def test_resolutions_are_all_feasible(self, resolver):
        a = near_field("AAA", 45, 7, 4000, 225, 250)
        b = near_field("BBB", 225, 7, 4000, 45, 250)
        traffic = [a, b]
        c = resolver.detector.check_radar(a, b)
        by_cs = {x.callsign: x for x in traffic}
        for r in resolver.resolve(c, traffic):
            subject = by_cs[r.maneuver.callsign]
            assert resolver.is_feasible(subject, r.maneuver)[0]

    def test_cost_ordering_prefers_speed_then_heading_then_altitude(self, resolver):
        """접근관제에서 관제사가 실제로 선호하는 순서."""
        c_spd = resolver.cost(res.Maneuver("A", "SPEED", 20))
        c_hdg = resolver.cost(res.Maneuver("A", "HEADING", 20))
        c_alt = resolver.cost(res.Maneuver("A", "ALTITUDE", 1000))
        assert c_spd < c_hdg < c_alt

    def test_larger_magnitude_costs_more(self, resolver):
        assert resolver.cost(res.Maneuver("A", "HEADING", 30)) > \
            resolver.cost(res.Maneuver("A", "HEADING", 10))


class TestResolve:
    @pytest.fixture
    def head_on(self):
        a = near_field("AAA", 45, 7, 4000, 225, 250)
        b = near_field("BBB", 225, 7, 4000, 45, 250)
        return [a, b]

    def test_finds_resolutions(self, resolver, head_on):
        c = resolver.detector.check_radar(*head_on)
        assert c is not None
        options = resolver.resolve(c, head_on)
        assert options, "회피안을 하나도 못 찾았다"
        assert len(options) <= 3

    def test_every_resolution_actually_clears_the_conflict(self, resolver, head_on):
        """제시된 회피안은 전부 실제로 충돌을 해소해야 한다."""
        by_cs = {ac.callsign: ac for ac in head_on}
        c = resolver.detector.check_radar(*head_on)
        for r in resolver.resolve(c, head_on):
            subject = by_cs[r.maneuver.callsign]
            other_cs = c.second if r.maneuver.callsign == c.first else c.first
            moved = r.maneuver.apply(subject)
            assert resolver.detector.check_radar(moved, by_cs[other_cs]) is None

    def test_resolution_maintains_separation_when_propagated(self, resolver, head_on):
        """전파해서 확인 — 지평 전 구간에서 최저치를 지켜야 한다."""
        by_cs = {ac.callsign: ac for ac in head_on}
        c = resolver.detector.check_radar(*head_on)
        r = resolver.resolve(c, head_on)[0]
        subject = by_cs[r.maneuver.callsign]
        other = by_cs[c.second if r.maneuver.callsign == c.first else c.first]
        moved = r.maneuver.apply(subject)

        worst = math.inf
        for t in range(0, 601, 5):
            p, q = moved.advance(t), other.advance(t)
            h = separation_distance_nm(p.lat, p.lon, q.lat, q.lon)
            v = abs(p.alt_ft - q.alt_ft)
            if v < V_MIN:
                worst = min(worst, h)
        assert worst >= H_MIN - 1e-3, f"전파 중 최소 이격 {worst:.2f}NM"

    def test_rejects_candidates_causing_secondary_conflict(self, resolver):
        """회피가 제3의 항적과 새 충돌을 만들면 채택하지 않는다."""
        a = near_field("AAA", 45, 7, 4000, 225, 250)
        b = near_field("BBB", 225, 7, 4000, 45, 250)
        # AAA 의 좌측에 제3기를 두어 좌선회 회피를 막는다
        blocker = near_field("CCC", 30, 7, 4000, 225, 250)
        traffic = [a, b, blocker]

        c = resolver.detector.check_radar(a, b)
        for r in resolver.resolve(c, traffic):
            subject = next(x for x in traffic if x.callsign == r.maneuver.callsign)
            others = [x for x in traffic if x.callsign != r.maneuver.callsign]
            assert resolver.detector.is_clear(r.maneuver.apply(subject), others)

    def test_returns_empty_for_unknown_callsigns(self, resolver, head_on):
        c = resolver.detector.check_radar(*head_on)
        assert resolver.resolve(c, []) == []

    def test_options_are_sorted_by_cost(self, resolver, head_on):
        c = resolver.detector.check_radar(*head_on)
        options = resolver.resolve(c, head_on)
        costs = [(r.collision_probability, r.cost) for r in options]
        assert costs == sorted(costs)


class TestCollisionProbability:
    def test_deterministic_model_gives_zero_or_one(self, resolver):
        a = near_field("AAA", 90, 6, 4000, 270, 250)
        b = near_field("BBB", 270, 6, 4000, 90, 250)
        p = res.collision_probability(
            a, b, H_MIN, V_MIN, res.UncertaintyModel(), 600.0
        )
        assert p == 1.0

        far = near_field("CCC", 270, 25, 4000, 90, 250)
        p = res.collision_probability(
            a, far, H_MIN, V_MIN, res.UncertaintyModel(), 60.0
        )
        assert p == 0.0

    def test_uncertainty_raises_probability_for_near_miss(self):
        """최저치를 아슬아슬하게 넘긴 조우는 σ 가 커지면 확률이 올라간다."""
        a = near_field("AAA", 90, 8, 4000, 270, 250)
        # AAA 의 3.6NM 북쪽에 나란히 — 최저치를 아슬아슬하게 넘긴 상태
        blat, blon = vincenty_direct(a.lat, a.lon, 0.0, 3.6 * 1852.0)
        b = AircraftState("BBB", blat, blon, 4000, 270, 250)
        sep = separation_distance_nm(a.lat, a.lon, b.lat, b.lon)
        assert H_MIN < sep < H_MIN + 1.5

        low = res.collision_probability(
            a, b, H_MIN, V_MIN,
            res.UncertaintyModel(horizontal_nm_per_s=0.0005), 300.0, samples=200
        )
        high = res.collision_probability(
            a, b, H_MIN, V_MIN,
            res.UncertaintyModel(horizontal_nm_per_s=0.005), 300.0, samples=200
        )
        assert 0.0 <= low <= high <= 1.0
        assert high > low

    def test_is_reproducible(self):
        a = near_field("AAA", 90, 8, 4000, 270, 250)
        b = near_field("BBB", 88, 8, 4000, 270, 250)
        u = res.UncertaintyModel(horizontal_nm_per_s=0.003)
        p1 = res.collision_probability(a, b, H_MIN, V_MIN, u, 300.0, samples=150)
        p2 = res.collision_probability(a, b, H_MIN, V_MIN, u, 300.0, samples=150)
        assert p1 == p2


class TestArrivalStreamDeconfliction:
    """도착 흐름은 회피 기동이 아니라 슬롯 재배정으로 푼다."""

    def inbound(self, sq, cs, actype, dist_nm):
        cat = sq.ds.fleet.wake_cat(actype)
        lat, lon = vincenty_direct(
            *sq.thr, (sq.final_course_deg + 180.0) % 360.0, dist_nm * 1852.0
        )
        return AircraftState(
            cs, lat, lon, sq.glidepath_altitude_ft(dist_nm),
            sq.final_course_deg, sq.ds.fleet.final_gs_kt(actype, cat),
            actype=actype, wake_cat=cat,
        )

    def test_converges_without_divergence(self, resolver, sq):
        """오프셋 누적은 발산했다. 슬롯 재배정은 수렴해야 한다."""
        traffic = [
            self.inbound(sq, f"AC{i:02d}", t, 10.0 + 2.0 * i)
            for i, t in enumerate(
                ["KC30", "F35A", "B738", "F35A", "C130", "B738",
                 "KF16", "A321", "KC30", "F35A", "B738", "FA50"]
            )
        ]
        schedule, log, rounds = resolver.deconflict_arrival_stream(traffic, sq)
        assert rounds < 20, f"수렴 실패: {log}"

        flown = res._project_onto_schedule(sq, traffic, schedule, 0.0)
        found = resolver.detector.scan(
            flown, final_course_deg=sq.final_course_deg,
            landing_sequence=schedule.order,
        )
        assert found == [], "\n".join(c.describe() for c in found)

    def test_violation_count_never_increases(self, resolver, sq):
        """반복할수록 위반이 늘어나면 발산이다. 단조 비증가여야 한다."""
        traffic = [
            self.inbound(sq, f"AC{i:02d}", t, 10.0 + 1.6 * i)
            for i, t in enumerate(
                ["KC30", "F35A", "B738", "F35A", "C130",
                 "B738", "KF16", "A321", "KC30", "F35A"]
            )
        ]
        schedule = sq.build(traffic)
        counts = []
        for _ in range(8):
            flown = res._project_onto_schedule(sq, traffic, schedule, 0.0)
            found = resolver.detector.scan(
                flown, final_course_deg=sq.final_course_deg,
                landing_sequence=schedule.order,
            )
            counts.append(len(found))
            if not found:
                break
            schedule = res._push_slot(sq, schedule, found[0], traffic, 0.0)

        for prev, nxt in zip(counts, counts[1:]):
            assert nxt <= prev, f"위반이 늘었다 (발산): {counts}"

    def test_schedule_stays_feasible_after_pushing(self, resolver, sq):
        """슬롯을 밀어도 물리적 최단 도달시각보다 이르게 착륙시키지 않는다."""
        traffic = [
            self.inbound(sq, f"AC{i:02d}", "B738", 10.0 + 2.0 * i) for i in range(6)
        ]
        schedule, _, _ = resolver.deconflict_arrival_stream(traffic, sq)
        for s in schedule.slots:
            assert s.threshold_time_s >= s.earliest_time_s - 1e-6
