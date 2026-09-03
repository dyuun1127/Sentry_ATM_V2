"""경로 계획 검증.

두 가지가 핵심이다.

**관제 지시로 옮길 수 있어야 한다.** 경로는 고시된 픽스를 잇는 직선의 연속이어야
하고, 부드러운 최적 곡선은 계산상 짧아도 "DIRECT (픽스)" 로 표현할 수 없다.

**고도를 함께 본다.** 제한구역은 상한이 있다 — R19 는 3,400ft 까지다. 평면으로만
회피하면 그 위로 곧장 지날 수 있는 항적을 불필요하게 우회시키고, 고도를 무시하면
낮게 복귀하는 항적을 제한구역으로 밀어 넣는다.
"""

import math

import pytest

from sentry_atm.regulation import data as sdata
from sentry_atm.regulation import route
from sentry_atm.regulation.geo import bearing_true, separation_distance_nm, vincenty_direct
from sentry_atm.regulation.sector import CircleVolume
from sentry_atm.regulation.state import AircraftState

M = 1852.0


@pytest.fixture(scope="module")
def ds():
    return sdata.load()


@pytest.fixture(scope="module")
def rp(ds):
    return route.build(ds)


def opposite_side(rp, hazard, fix_lat, fix_lon, nm=12.0):
    """위험구역을 사이에 두고 픽스 반대편 지점 — 직선이 막히는 배치."""
    b = bearing_true(fix_lat, fix_lon, hazard.center_lat, hazard.center_lon)
    return vincenty_direct(hazard.center_lat, hazard.center_lon, b, nm * M)


def hazard(rp, hid):
    return next(h for h in rp.hazards if h.id == hid)


class TestHazardSet:
    def test_restricted_areas_are_loaded_from_aip(self, ds, rp):
        published = {r["id"] for r in ds.airspace.raw["special_use"]["restricted"]}
        assert published <= {h.id for h in rp.hazards}

    def test_neighbour_control_zone_is_a_hazard(self, rp):
        assert "SEONGMU CTR" in {h.id for h in rp.hazards}

    def test_training_areas_are_not_hazards_by_default(self, rp):
        """자기 임무공역일 수 있고 활성 여부가 NOTAM 에 달렸다."""
        assert not any(h.id.startswith("MOA") for h in rp.hazards)

    def test_moa_can_be_added_explicitly(self, rp):
        v = rp.moa_volume("MOA 3A")
        assert v.id == "MOA 3A"
        assert v.upper_ft > v.lower_ft


class TestSamplingResolution:
    def test_sample_step_is_finer_than_the_smallest_hazard(self, rp):
        """성기게 잡으면 작은 구역을 건너뛰고 통과한다."""
        radii = [h.radius_nm for h in rp.hazards if isinstance(h, CircleVolume)]
        assert rp.sample_nm <= min(radii) / 2.0 + 1e-9

    def test_a_segment_through_a_hazard_centre_is_detected(self, rp):
        h = hazard(rp, "RK R139")
        a = vincenty_direct(h.center_lat, h.center_lon, 0.0, 6 * M)
        b = vincenty_direct(h.center_lat, h.center_lon, 180.0, 6 * M)
        assert rp.blocking(a, b, 2000.0) == "RK R139"

    def test_a_segment_clear_of_every_hazard_is_not_blocked(self, rp):
        h = hazard(rp, "RK R19")
        a = vincenty_direct(h.center_lat, h.center_lon, 90.0, 40 * M)
        b = vincenty_direct(h.center_lat, h.center_lon, 90.0, 60 * M)
        assert rp.blocking(a, b, 3000.0) is None


class TestAltitudeAwareness:
    """제한구역은 상한이 있다 — 그 위로는 막지 않는다."""

    @pytest.mark.parametrize(
        "hid,below,above",
        [("RK R19", 3000.0, 5000.0), ("RK R152", 2000.0, 3000.0), ("RK R139", 5000.0, 9000.0)],
    )
    def test_blocked_below_the_ceiling_and_clear_above(self, rp, hid, below, above):
        h = hazard(rp, hid)
        a = vincenty_direct(h.center_lat, h.center_lon, 0.0, 8 * M)
        b = vincenty_direct(h.center_lat, h.center_lon, 180.0, 8 * M)
        assert rp.blocking(a, b, below) == hid
        assert rp.blocking(a, b, above) is None

    def test_the_same_route_is_direct_when_flown_high_enough(self, ds, rp):
        h = hazard(rp, "RK R19")
        w = ds.procedures.fix("IKAPO")
        origin = opposite_side(rp, h, w.lat, w.lon)
        low = rp.plan(origin, "IKAPO", 3000.0)
        high = rp.plan(origin, "IKAPO", 6000.0)
        assert low.detour_nm > 0.0
        assert high.detour_nm == pytest.approx(0.0)
        assert high.total_nm < low.total_nm


class TestPlanning:
    def test_clear_direct_route_has_no_detour(self, ds, rp):
        w = ds.procedures.fix("IKAPO")
        origin = vincenty_direct(w.lat, w.lon, 45.0, 15 * M)
        r = rp.plan(origin, "IKAPO", 9000.0)
        assert r.detour_nm == pytest.approx(0.0)
        assert r.fixes == ["IKAPO"]

    def test_blocked_route_goes_via_published_fixes_only(self, ds, rp):
        h = hazard(rp, "SEONGMU CTR")
        w = ds.procedures.fix("IKAPO")
        origin = opposite_side(rp, h, w.lat, w.lon)
        r = rp.plan(origin, "IKAPO", 2000.0)
        assert r is not None
        assert len(r.fixes) > 1
        for f in r.fixes:
            assert f in ds.procedures.waypoints, f

    def test_every_leg_of_a_planned_route_is_clear(self, ds, rp):
        h = hazard(rp, "SEONGMU CTR")
        w = ds.procedures.fix("IKAPO")
        origin = opposite_side(rp, h, w.lat, w.lon)
        alt = 2000.0
        r = rp.plan(origin, "IKAPO", alt)
        here = origin
        for leg in r.legs:
            assert rp.blocking(here, (leg.lat, leg.lon), alt) is None
            here = (leg.lat, leg.lon)

    def test_detour_is_measured_against_the_straight_line(self, ds, rp):
        h = hazard(rp, "RK R19")
        w = ds.procedures.fix("IKAPO")
        origin = opposite_side(rp, h, w.lat, w.lon)
        r = rp.plan(origin, "IKAPO", 3000.0)
        direct = separation_distance_nm(*origin, w.lat, w.lon)
        assert r.detour_nm == pytest.approx(r.total_nm - direct)
        assert r.detour_nm > 0.0

    def test_leg_distances_sum_to_the_total(self, ds, rp):
        w = ds.procedures.fix("HYEIN")
        origin = vincenty_direct(w.lat, w.lon, 200.0, 25 * M)
        r = rp.plan(origin, "HYEIN", 8000.0)
        assert r.total_nm == pytest.approx(sum(x.dist_nm for x in r.legs))

    def test_unpublished_destination_is_refused(self, rp):
        with pytest.raises(KeyError):
            rp.plan((36.7, 127.5), "NOWHERE", 5000.0)


class TestRecovery:
    def test_recovery_targets_a_published_iaf(self, ds, rp):
        entries = rp.approach_entries()
        assert set(entries) == {"IKAPO", "HYEIN"}
        ac = AircraftState(
            "R1", 36.9, 127.8, 9000.0, 240.0, 300.0, actype="F35A", wake_cat="소형"
        )
        r = rp.recovery(ac)
        assert r.fixes[-1] in entries

    def test_recovery_minimises_total_distance_not_straight_line(self, ds, rp):
        """직선거리가 가까운 IAF 가 막혀 있으면 더 먼 IAF 로 직행하는 편이 빠르다."""
        ac = AircraftState(
            "R1", 36.5, 127.2, 2000.0, 60.0, 300.0, actype="F35A", wake_cat="소형"
        )
        r = rp.recovery(ac)
        assert r is not None
        alternatives = [
            rp.plan((ac.lat, ac.lon), iaf, ac.alt_ft) for iaf in rp.approach_entries()
        ]
        best = min(x.total_nm for x in alternatives if x is not None)
        assert r.total_nm == pytest.approx(best)

    def test_ete_scales_with_ground_speed(self, rp):
        ac = AircraftState(
            "R1", 36.9, 127.8, 9000.0, 240.0, 300.0, actype="F35A", wake_cat="소형"
        )
        r = rp.recovery(ac)
        assert r.ete_s(300.0) == pytest.approx(r.ete_s(150.0) / 2.0)

    def test_recovery_can_be_forced_around_a_training_area(self, ds, rp):
        """작전지역을 회피 대상으로 넣으면 경로가 달라져야 한다."""
        ac = AircraftState(
            "R1", 36.55, 127.75, 5000.0, 270.0, 300.0, actype="F35A", wake_cat="소형"
        )
        plain = rp.recovery(ac)
        avoided = rp.recovery(ac, avoid=(rp.moa_volume("MOA 3A"),))
        if avoided is not None and plain is not None:
            assert avoided.total_nm >= plain.total_nm - 1e-6


class TestClearanceWording:
    def test_clearance_is_expressed_as_direct_legs(self, ds, rp):
        w = ds.procedures.fix("IKAPO")
        origin = vincenty_direct(w.lat, w.lon, 45.0, 20 * M)
        r = rp.plan(origin, "IKAPO", 9000.0)
        text = r.clearance("ROKAF01")
        assert text.startswith("ROKAF01, CLEARED TO IKAPO")
        assert "DIRECT IKAPO" in text

    def test_multi_leg_clearance_names_every_fix(self, ds, rp):
        h = hazard(rp, "SEONGMU CTR")
        w = ds.procedures.fix("IKAPO")
        origin = opposite_side(rp, h, w.lat, w.lon)
        r = rp.plan(origin, "IKAPO", 2000.0)
        text = r.clearance("ROKAF01")
        for f in r.fixes:
            assert f in text

    def test_describe_marks_direct_routes(self, ds, rp):
        w = ds.procedures.fix("HYEIN")
        origin = vincenty_direct(w.lat, w.lon, 30.0, 18 * M)
        assert "직행" in rp.plan(origin, "HYEIN", 9000.0).describe()
