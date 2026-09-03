"""착륙순서 최적화 검증.

가장 중요한 것은 **단조 개선 보장**이다. 탐욕법으로 처음부터 재배열하면
앞쪽에서 제약을 다 써버려 결과가 선착순보다 나빠질 수 있다(이전 구현의 실패).
선착순에서 출발해 개선되는 교환만 받아들이면 그 일이 구조적으로 불가능하다.
"""

import random

import pytest

from sentry_atm.regulation import conflict as cf
from sentry_atm.regulation import data as sdata
from sentry_atm.regulation import sequencing as seq
from sentry_atm.regulation.geo import vincenty_direct
from sentry_atm.regulation.state import AircraftState

TYPES = ["B738", "A321", "F35A", "KC30", "C130", "KF16", "FA50", "B77W", "A320", "F15K"]


@pytest.fixture(scope="module")
def ds():
    return sdata.load()


@pytest.fixture(scope="module")
def sq(ds):
    return seq.build(ds)


@pytest.fixture(scope="module")
def det(ds):
    return cf.build(ds)


def traffic(sq, ds, n, seed, emergency=None):
    rng = random.Random(seed)
    out = []
    d = 10.0
    for i in range(n):
        ty = rng.choice(TYPES)
        cat = ds.fleet.wake_cat(ty)
        lat, lon = vincenty_direct(
            *sq.thr, (sq.final_course_deg + 180.0) % 360.0, d * 1852.0
        )
        out.append(
            AircraftState(
                f"AC{i:02d}", lat, lon, sq.glidepath_altitude_ft(d),
                sq.final_course_deg, ds.fleet.final_gs_kt(ty, cat),
                actype=ty, wake_cat=cat, emergency=(f"AC{i:02d}" == emergency),
            )
        )
        d += rng.uniform(1.8, 3.2)
    return out


class TestMonotoneImprovement:
    """선착순보다 나빠질 수 없어야 한다 — 이전 구현이 실패한 지점."""

    @pytest.mark.parametrize("seed", [1, 2, 3, 4, 5, 6, 7, 8])
    def test_never_worse_than_first_come_first_served(self, sq, ds, seed):
        t = traffic(sq, ds, 14, seed)
        for k in (1, 2, 3):
            r = seq.optimize_order(sq, t, max_shift=k)
            assert r.completion_s <= r.baseline_completion_s + 1e-6, (
                f"제한 ±{k} 에서 선착순보다 나빠졌다"
            )
            assert r.improvement >= 0.0

    @pytest.mark.parametrize("seed", [11, 12, 13, 14])
    def test_larger_limit_is_never_worse(self, sq, ds, seed):
        """제한을 늘리면 탐색 공간이 커지므로 결과가 나빠지면 안 된다."""
        t = traffic(sq, ds, 14, seed)
        prev = None
        for k in (0, 1, 2, 3):
            r = seq.optimize_order(sq, t, max_shift=k)
            if prev is not None:
                assert r.completion_s <= prev + 1e-6
            prev = r.completion_s

    def test_zero_shift_returns_first_come_first_served(self, sq, ds):
        t = traffic(sq, ds, 12, seed=21)
        r = seq.optimize_order(sq, t, max_shift=0)
        assert r.order == r.baseline_order
        assert r.swaps == 0
        assert r.improvement == 0.0


class TestConstraint:
    """순번 이동 제한 — 고시 2-1-4 선착순 원칙을 지키기 위한 장치."""

    @pytest.mark.parametrize("k", [1, 2, 3])
    def test_no_aircraft_moves_beyond_the_limit(self, sq, ds, k):
        t = traffic(sq, ds, 16, seed=31)
        r = seq.optimize_order(sq, t, max_shift=k)
        for cs, shift in r.shifts().items():
            assert abs(shift) <= k, f"{cs} 가 {shift}자리 이동 (제한 ±{k})"

    def test_order_is_a_permutation(self, sq, ds):
        t = traffic(sq, ds, 16, seed=32)
        r = seq.optimize_order(sq, t, max_shift=2)
        assert sorted(r.order) == sorted(r.baseline_order)
        assert len(set(r.order)) == len(r.order)

    def test_emergency_is_not_pushed_back(self, sq, ds):
        """고시 2-1-4 가 — 조난 항공기의 순번은 최적화 대상이 아니다."""
        t = traffic(sq, ds, 14, seed=33, emergency="AC09")
        r = seq.optimize_order(sq, t, max_shift=3)
        base = r.baseline_order.index("AC09")
        after = r.order.index("AC09")
        assert after <= base, "비상기가 뒤로 밀렸다"


class TestEffect:
    def test_reordering_actually_helps_on_mixed_traffic(self, sq, ds):
        """기종이 섞이면 순서에 따라 총 소요가 달라진다 (고시 5-5-4 사·아항)."""
        gains = []
        for seed in range(40, 60):
            t = traffic(sq, ds, 18, seed)
            gains.append(seq.optimize_order(sq, t, max_shift=1).gap_improvement)
        assert sum(gains) / len(gains) > 0.005, "혼재 교통에서 개선이 거의 없다"

    def test_uniform_fleet_has_little_to_gain(self, sq, ds):
        """같은 기종만 있으면 순서를 바꿀 이유가 없다 — 이득의 출처 확인."""
        rng = random.Random(99)
        out = []
        d = 10.0
        for i in range(14):
            lat, lon = vincenty_direct(
                *sq.thr, (sq.final_course_deg + 180.0) % 360.0, d * 1852.0
            )
            out.append(
                AircraftState(
                    f"AC{i:02d}", lat, lon, sq.glidepath_altitude_ft(d),
                    sq.final_course_deg, ds.fleet.final_gs_kt("B738", "중형"),
                    actype="B738", wake_cat="중형",
                )
            )
            d += rng.uniform(1.8, 3.2)
        r = seq.optimize_order(sq, out, max_shift=3)
        assert r.gap_improvement < 0.005

    def test_swaps_are_reported(self, sq, ds):
        t = traffic(sq, ds, 16, seed=41)
        r = seq.optimize_order(sq, t, max_shift=2)
        assert r.swaps >= 0
        assert r.iterations >= 1
        if r.swaps == 0:
            assert r.order == r.baseline_order


class TestFlyable:
    def test_optimized_schedule_has_no_violations(self, sq, ds, det):
        """순서를 바꿔도 분리·후류가 유지되어야 한다 — 간격 요건이 재계산되므로."""
        for seed in (51, 52, 53):
            t = traffic(sq, ds, 14, seed)
            r = seq.optimize_order(sq, t, max_shift=2)
            by = {ac.callsign: ac for ac in t}
            schedule = sq._lay_out([by[cs] for cs in r.order], 0.0)
            for at_t in range(0, int(schedule.makespan_s) + 1, 30):
                flown = []
                for slot in schedule.slots:
                    ac = by[slot.callsign]
                    v = sq.final_gs_kt(ac)
                    rem = (slot.threshold_time_s - at_t) / 3600.0 * v
                    if rem <= 0:
                        continue
                    lat, lon = vincenty_direct(
                        *sq.thr, (sq.final_course_deg + 180.0) % 360.0, rem * 1852.0
                    )
                    flown.append(
                        AircraftState(
                            ac.callsign, lat, lon, sq.glidepath_altitude_ft(rem),
                            sq.final_course_deg, v,
                            actype=ac.actype, wake_cat=ac.wake_cat,
                        )
                    )
                found = det.scan(
                    flown, final_course_deg=sq.final_course_deg,
                    landing_sequence=schedule.order,
                )
                assert found == [], "\n".join(c.describe() for c in found)

    def test_no_slot_lands_before_it_can_arrive(self, sq, ds):
        t = traffic(sq, ds, 14, seed=61)
        r = seq.optimize_order(sq, t, max_shift=2)
        by = {ac.callsign: ac for ac in t}
        schedule = sq._lay_out([by[cs] for cs in r.order], 0.0)
        for slot in schedule.slots:
            assert slot.threshold_time_s >= slot.earliest_time_s - 1e-6
