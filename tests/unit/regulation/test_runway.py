"""활주로 자원 모델 검증.

핵심은 **선행기가 무엇을 했느냐에 따라 근거 조항이 갈린다**는 점이다. 착륙 뒤
이륙은 활주로 개방(3-9-6 나), 이륙 뒤 이륙은 종단 통과 또는 후류 시간(3-9-6 가·바),
이륙 뒤 착륙은 시단 이격(3-10-3 가 2). 한 표로 뭉뚱그리면 틀린다.
"""

import math

import pytest

from sentry_atm.regulation import data as sdata
from sentry_atm.regulation import runway as rw
from sentry_atm.regulation.runway import Operation as Op


@pytest.fixture(scope="module")
def ds():
    return sdata.load()


@pytest.fixture(scope="module")
def sq(ds):
    return rw.build(ds)


def op(ds, cs, actype, kind, earliest=0.0, emergency=False):
    return rw.RunwayOp(
        cs, actype, ds.fleet.wake_cat(actype), kind,
        earliest_s=earliest, emergency=emergency,
    )


class TestSRSCategory:
    """고시 3-9-6 주기 가 — 청주는 군 공항 기준을 쓴다."""

    def test_every_fixed_wing_type_is_cat3_at_this_aerodrome(self, ds):
        """이 공항에서 SRS 범주는 기종을 구분하지 못한다 — 근거를 명시할 사항."""
        for actype, spec in ds.fleet.raw["types"].items():
            if spec.get("rotorcraft"):
                continue
            assert ds.fleet.srs_cat(actype) == "CAT_III", actype

    def test_rotorcraft_is_cat1(self, ds):
        """주기 가에 '모든 헬리콥터'가 CAT I 로 명시되어 있다."""
        assert ds.fleet.srs_cat("H60") == "CAT_I"

    def test_cat3_pair_uses_6000ft_not_the_civil_only_8000(self, ds, sq):
        """민간전용공항 기준(8,000ft)을 잘못 쓰면 간격이 33% 늘어난다."""
        d, _ = sq.rules.srs_distance_ft(
            op(ds, "a", "B738", Op.DEPARTURE), op(ds, "b", "F35A", Op.DEPARTURE)
        )
        assert d == 6000


class TestClauseSelection:
    """조합마다 다른 조항이 걸려야 한다."""

    def test_arrival_then_departure_waits_for_runway_exit(self, ds, sq):
        r = sq.rules.requirement(
            op(ds, "a", "B738", Op.ARRIVAL), op(ds, "b", "F35A", Op.DEPARTURE)
        )
        assert r.clauses == ("3-9-6 나",)
        assert r.binding == "활주로개방"
        assert r.seconds == ds.fleet.runway_occupancy_s("B738", "중형")

    def test_departure_then_arrival_uses_threshold_clearance(self, ds, sq):
        r = sq.rules.requirement(
            op(ds, "a", "B738", Op.DEPARTURE), op(ds, "b", "F35A", Op.ARRIVAL)
        )
        assert r.clauses == ("3-10-3 가 2)",)
        assert r.binding == "종단통과"

    def test_heavy_before_light_departure_is_wake_bound(self, ds, sq):
        """대형 뒤 소형은 거리가 아니라 후류 2분이 지배한다 (3-9-6 바 2)."""
        r = sq.rules.requirement(
            op(ds, "a", "KC30", Op.DEPARTURE), op(ds, "b", "F35A", Op.DEPARTURE)
        )
        assert r.binding == "이륙후류"
        assert r.seconds == 120.0

    def test_super_before_light_departure_is_three_minutes(self, ds, sq):
        r = sq.rules.requirement(
            op(ds, "a", "A388", Op.DEPARTURE), op(ds, "b", "F35A", Op.DEPARTURE)
        )
        assert r.seconds == 180.0

    def test_light_before_light_departure_is_distance_bound(self, ds, sq):
        """전투기끼리는 후류표에 없으므로 거리 기준만 남는다."""
        r = sq.rules.requirement(
            op(ds, "a", "F35A", Op.DEPARTURE), op(ds, "b", "KF16", Op.DEPARTURE)
        )
        assert r.binding == "종단통과"
        assert 0 < r.seconds < 120.0


class TestLineUpAndWait:
    """고시 3-9-6 라 — 후류 간격을 활주로 위에서 소진할 수 없다."""

    def test_prohibited_behind_heavy_and_super(self, ds, sq):
        for lead in ("KC30", "A388"):
            r = sq.rules.requirement(
                op(ds, "a", lead, Op.DEPARTURE), op(ds, "b", "F35A", Op.DEPARTURE)
            )
            assert r.luaw_prohibited, lead

    def test_not_prohibited_between_light_aircraft(self, ds, sq):
        r = sq.rules.requirement(
            op(ds, "a", "F35A", Op.DEPARTURE), op(ds, "b", "KF16", Op.DEPARTURE)
        )
        assert not r.luaw_prohibited


class TestRollModel:
    """이륙활주는 등가속으로 본다 — 등속 가정보다 안전 측이다."""

    def test_uniform_acceleration_is_slower_than_uniform_speed(self, ds, sq):
        """등속이면 6,000/9,003 = 67% 시점, 등가속이면 √(0.67) = 82% 시점이다."""
        a = op(ds, "a", "B738", Op.DEPARTURE)
        roll = ds.fleet.departure_roll_s("B738", "중형")
        t = sq.rules.time_to_roll_distance_s(a, 6000.0)
        uniform = roll * 6000.0 / sq.rules._length_ft
        assert t > uniform
        assert t == pytest.approx(roll * math.sqrt(6000.0 / sq.rules._length_ft))

    def test_distance_beyond_runway_end_caps_at_full_roll(self, ds, sq):
        a = op(ds, "a", "B738", Op.DEPARTURE)
        assert sq.rules.time_to_roll_distance_s(a, 99_999.0) == ds.fleet.departure_roll_s(
            "B738", "중형"
        )

    def test_runway_length_comes_from_aip(self, ds, sq):
        """길이를 코드에 박지 않는다 — AIP 전사값에서 온다."""
        aip_m = ds.procedures.runways["24R"].length_m
        assert sq.rules._length_ft == pytest.approx(aip_m / 0.3048)


class TestLayout:
    def test_no_slot_moves_earlier_than_it_can_be_ready(self, ds, sq):
        ops = [
            op(ds, "AC0", "B738", Op.ARRIVAL, earliest=0),
            op(ds, "AC1", "F35A", Op.DEPARTURE, earliest=30),
            op(ds, "AC2", "A321", Op.ARRIVAL, earliest=60),
        ]
        sched = sq.lay_out(ops)
        for s in sched.slots:
            assert s.time_s >= s.op.earliest_s - 1e-6

    def test_every_gap_meets_its_requirement(self, ds, sq):
        ops = [
            op(ds, "AC0", "KC30", Op.DEPARTURE, earliest=0),
            op(ds, "AC1", "F35A", Op.DEPARTURE, earliest=10),
            op(ds, "AC2", "B738", Op.ARRIVAL, earliest=20),
            op(ds, "AC3", "KF16", Op.DEPARTURE, earliest=30),
        ]
        sched = sq.lay_out(ops)
        for a, b in zip(sched.slots, sched.slots[1:]):
            assert b.time_s - a.time_s >= b.requirement.seconds - 1e-6

    def test_first_slot_has_no_requirement(self, ds, sq):
        sched = sq.lay_out([op(ds, "AC0", "B738", Op.ARRIVAL)])
        assert sched.slots[0].requirement is None

    def test_first_come_first_served_orders_by_readiness(self, ds, sq):
        ops = [
            op(ds, "LATE", "B738", Op.ARRIVAL, earliest=300),
            op(ds, "EARLY", "F35A", Op.DEPARTURE, earliest=10),
        ]
        assert sq.first_come_first_served(ops).order == ["EARLY", "LATE"]


class TestEmergencyInsertion:
    """고시 2-1-4 가 — 순번이 아니라 물리적 최단 도달시각 기준."""

    def test_emergency_lands_no_later_than_it_physically_can(self, ds, sq):
        ops = [op(ds, f"AC{i}", "B738", Op.ARRIVAL, earliest=i * 90.0) for i in range(6)]
        ops.append(op(ds, "EMG", "F35A", Op.ARRIVAL, earliest=200.0, emergency=True))
        sched = sq.insert_emergency(ops, "EMG")
        assert sched.by_callsign("EMG").time_s == pytest.approx(200.0, abs=1.0)

    def test_emergency_insertion_does_not_leave_the_runway_idle(self, ds, sq):
        """순번으로 밀어넣으면 활주로가 비는데, 도달시각 기준이면 그렇지 않다."""
        ops = [op(ds, f"AC{i}", "B738", Op.ARRIVAL, earliest=i * 90.0) for i in range(8)]
        base = sq.first_come_first_served(ops)
        ops.append(op(ds, "EMG", "F35A", Op.ARRIVAL, earliest=250.0, emergency=True))
        after = sq.insert_emergency(ops, "EMG")
        assert after.max_gap_s() <= base.max_gap_s() + 1.0

    def test_all_aircraft_still_scheduled_after_insertion(self, ds, sq):
        ops = [op(ds, f"AC{i}", "A321", Op.ARRIVAL, earliest=i * 100.0) for i in range(5)]
        ops.append(op(ds, "EMG", "KF16", Op.ARRIVAL, earliest=150.0, emergency=True))
        sched = sq.insert_emergency(ops, "EMG")
        assert sorted(sched.order) == sorted(o.callsign for o in ops)


class TestMixedOperations:
    def test_departures_and_arrivals_are_both_reported(self, ds, sq):
        ops = [
            op(ds, "D1", "F35A", Op.DEPARTURE),
            op(ds, "A1", "B738", Op.ARRIVAL, earliest=100),
            op(ds, "D2", "KF16", Op.DEPARTURE, earliest=200),
        ]
        sched = sq.lay_out(ops)
        assert [s.op.callsign for s in sched.departures()] == ["D1", "D2"]
        assert [s.op.callsign for s in sched.arrivals()] == ["A1"]

    def test_interleaving_a_departure_costs_runway_time_when_the_stream_is_tight(
        self, ds, sq
    ):
        """출발을 끼우면 도착 흐름이 밀린다 — 이 비용이 보여야 시연 의미가 있다.

        단, 도착 간격에 여유가 있으면 비용이 흡수된다. 점유시간과 같은 간격으로
        붙여 두어야 경합이 실제로 드러난다.
        """
        rot = ds.fleet.runway_occupancy_s("B738", "중형")
        arrivals = [op(ds, f"A{i}", "B738", Op.ARRIVAL, earliest=i * rot) for i in range(5)]
        without = sq.lay_out(arrivals)
        mixed = list(arrivals)
        mixed.insert(2, op(ds, "DEP", "KC30", Op.DEPARTURE, earliest=2 * rot))
        with_dep = sq.lay_out(mixed)
        assert with_dep.slots[-1].time_s > without.slots[-1].time_s

    def test_slack_in_the_arrival_stream_absorbs_a_departure(self, ds, sq):
        """반대 경우도 성립해야 한다 — 여유가 있으면 출발이 공짜로 들어간다."""
        arrivals = [op(ds, f"A{i}", "B738", Op.ARRIVAL, earliest=i * 240.0) for i in range(4)]
        without = sq.lay_out(arrivals)
        mixed = list(arrivals)
        mixed.insert(2, op(ds, "DEP", "F35A", Op.DEPARTURE, earliest=300.0))
        with_dep = sq.lay_out(mixed)
        assert with_dep.slots[-1].time_s == pytest.approx(without.slots[-1].time_s)
