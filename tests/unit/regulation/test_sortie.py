"""시간표와 소티 시나리오 검증.

**합성을 실측처럼 보이게 하면 안 된다.** 실제 시간표가 없을 때는 합성으로
떨어지되, 그 사실이 결과에 남아야 한다. 발표에서 "이 숫자가 어디서 왔는가"에
답할 수 없는 값은 쓰지 않는다.

시나리오는 규정을 다시 해석하지 않는다 — 각 모듈이 낸 값을 순서대로 엮을 뿐이고,
그래서 시나리오를 바꿔도 분리 최저치가 흔들리지 않는다.
"""

import json
import shutil
from pathlib import Path

import pytest

from sentry_atm.regulation import data as sdata
from sentry_atm.regulation import schedule, sortie
from sentry_atm.regulation.runway import Operation


@pytest.fixture(scope="module")
def ds():
    return sdata.load()


@pytest.fixture(scope="module")
def tt(ds):
    return schedule.build(ds, window=("09:00", "10:00"), seed=4)


@pytest.fixture
def workdir():
    """저장소 안의 임시 디렉터리.

    pytest 의 `tmp_path` 를 쓰지 않는다 — 이 기계에서는 TMPDIR 이 목록 조회가
    막힌 경로를 가리켜 픽스처가 실패한다. 시험이 개발 기계의 환경 변수에
    의존하지 않도록 저장소 안에 만들고 지운다.
    """
    d = Path(__file__).parent / ".tmp"
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True, exist_ok=True)
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def sc(ds, tt):
    s = sortie.build(ds, tt)
    s.build()
    return s


class TestTimetableProvenance:
    def test_synthetic_is_labelled(self, tt):
        assert tt.synthetic
        assert "실제 운항 시간표가 아니다" in tt.provenance()

    def test_synthetic_respects_the_slot_constraint(self, ds, tt):
        """청주는 활주로 공용 구조상 시간당 7~8회로 제한된다."""
        assert 6.0 <= tt.movements_per_hour() <= 9.0

    def test_flights_are_time_ordered(self, tt):
        ts = [f.scheduled_s for f in tt.flights]
        assert ts == sorted(ts)

    def test_flights_fall_inside_the_window(self, tt):
        for f in tt.flights:
            assert tt.window_from_s <= f.scheduled_s <= tt.window_to_s

    def test_both_directions_are_present(self, tt):
        assert tt.arrivals and tt.departures

    def test_deterministic_for_a_seed(self, ds):
        a = schedule.build(ds, window=("09:00", "10:00"), seed=9)
        b = schedule.build(ds, window=("09:00", "10:00"), seed=9)
        assert [f.callsign for f in a.flights] == [f.callsign for f in b.flights]


class TestTimetableLoading:
    def test_a_real_file_is_read_and_marked_real(self, ds, workdir):
        p = workdir / "schedule.json"
        p.write_text(json.dumps({
            "date": "2026-07-04",
            "window": {"from": "09:00", "to": "10:00"},
            "source": "실제 운항 시간표",
            "flights": [
                {"callsign": "KAL1401", "actype": "B738",
                 "operation": "도착", "scheduled": "09:15", "other_end": "ICN"},
                {"callsign": "TWB702", "actype": "A321",
                 "operation": "출발", "scheduled": "09:40", "other_end": "CJU"},
            ],
        }, ensure_ascii=False), encoding="utf-8")
        t = schedule.build(ds, path=p)
        assert not t.synthetic
        assert "실제 시간표" in t.provenance()
        assert [f.callsign for f in t.flights] == ["KAL1401", "TWB702"]
        assert t.flights[0].operation is Operation.ARRIVAL
        assert t.flights[1].operation is Operation.DEPARTURE

    def test_english_operation_words_are_accepted(self, ds, workdir):
        p = workdir / "s.json"
        p.write_text(json.dumps({
            "window": {"from": "09:00", "to": "10:00"},
            "flights": [{"callsign": "X1", "actype": "B738",
                         "operation": "arrival", "scheduled": "09:10"}],
        }), encoding="utf-8")
        assert schedule.build(ds, path=p).flights[0].operation is Operation.ARRIVAL

    def test_missing_file_falls_back_to_synthetic(self, ds, workdir):
        t = schedule.build(ds, path=workdir / "absent.json")
        assert t.synthetic

    def test_scheduled_time_becomes_the_earliest_runway_time(self, ds, tt):
        ops = tt.to_runway_ops(ds.fleet)
        for op, f in zip(ops, tt.flights):
            assert op.earliest_s == f.scheduled_s
            assert op.callsign == f.callsign


class TestScenarioShape:
    def test_thirteen_steps_in_order(self, sc):
        assert [s.n for s in sc.steps] == list(range(1, 14))

    def test_steps_are_time_ordered(self, sc):
        ts = [s.t_s for s in sc.steps]
        assert ts == sorted(ts)

    def test_every_step_has_detail(self, sc):
        for s in sc.steps:
            assert s.detail.strip()

    def test_regulatory_steps_cite_clauses(self, sc):
        by_n = {s.n: s for s in sc.steps}
        assert "2-1-4 가" in by_n[7].clauses      # 비상 선언
        assert "2-1-4 가" in by_n[11].clauses     # 우선 착륙
        assert "4-6-1" in by_n[10].clauses        # 체공
        assert "2-1-15" in by_n[5].clauses        # 이양
        assert "3-9-6" in by_n[3].clauses         # 활주로


class TestMilitaryTraffic:
    def test_patrol_sorties_use_the_runway_twice(self, ds, tt):
        s = sortie.build(ds, tt, patrol_sorties=3)
        ops = s._patrol_ops()
        assert len(ops) == 6
        assert sum(1 for o in ops if o.is_departure) == 3
        assert sum(1 for o in ops if not o.is_departure) == 3

    def test_patrol_callsigns_are_unique(self, ds, tt):
        s = sortie.build(ds, tt, patrol_sorties=3)
        names = [o.callsign for o in s._patrol_ops()]
        assert len(set(names)) == len(names)

    def test_zero_patrol_is_a_civil_only_aerodrome(self, ds, tt):
        s = sortie.build(ds, tt, patrol_sorties=0)
        assert s._patrol_ops() == []
        s.build()
        assert "순찰 소티 0회" in s.steps[0].detail

    def test_military_traffic_raises_the_movement_rate(self, ds, tt):
        civil_only = sortie.build(ds, tt, patrol_sorties=0)
        civil_only.build()
        mixed = sortie.build(ds, tt, patrol_sorties=3)
        mixed.build()
        assert len(mixed.baseline.slots) > len(civil_only.baseline.slots)


class TestEmergencyHandling:
    def test_emergency_is_declared_and_recorded(self, sc):
        assert sc.sortie.emergency
        assert sc.sortie.recovery_declared_s is not None

    def test_fighter_lands_no_later_than_it_physically_can(self, sc):
        """고시 2-1-4 가 — 순번이 아니라 물리적 최단 도달시각."""
        landed = sc.final.by_callsign(sc.fighter_callsign)
        assert landed.time_s == pytest.approx(landed.op.earliest_s, abs=1.0)

    def test_recovery_route_ends_at_a_published_iaf(self, sc):
        assert sc.recovery_route is not None
        assert sc.recovery_route.fixes[-1] in sc.router.approach_entries()

    def test_holds_use_published_patterns_only(self, sc):
        published = {p.fix for p in sc.holding.patterns}
        for h in sc.holds:
            assert h.pattern.fix in published

    def test_held_aircraft_do_not_share_a_level(self, sc):
        seen = {(h.pattern.fix, h.level_ft) for h in sc.holds}
        assert len(seen) == len(sc.holds)

    def test_refused_holds_are_reported_not_hidden(self, sc):
        """자리가 없으면 겹쳐 세우지 않고 남는다 — 벡터·순서조정 대상."""
        assert isinstance(sc.hold_refused, list)
        assert set(sc.hold_refused).isdisjoint({h.callsign for h in sc.holds})


class TestScheduleIntegrity:
    def test_final_schedule_meets_every_runway_requirement(self, sc):
        for a, b in zip(sc.final.slots, sc.final.slots[1:]):
            assert b.time_s - a.time_s >= b.requirement.seconds - 1e-6

    def test_no_slot_precedes_its_earliest_time(self, sc):
        for s in sc.final.slots:
            assert s.time_s >= s.op.earliest_s - 1e-6

    def test_every_aircraft_keeps_a_slot(self, sc):
        assert len(set(sc.final.order)) == len(sc.final.order)

    def test_inserting_the_sortie_never_loses_a_flight(self, sc):
        base = {s.op.callsign for s in sc.baseline.slots}
        after = {s.op.callsign for s in sc.with_sortie.slots}
        assert base <= after
        assert sc.fighter_callsign in after
