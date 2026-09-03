"""출발 항적 생성 검증.

도착과 달리 출발은 **AIP 가 고시한 SID 를 따라야 한다.** 상승률을 지어내면
구간 고도제약(AT / AT_OR_ABOVE)을 물리적으로 못 맞추는 항적이 나오고, 그 항적으로
학습하면 예측기가 절차를 벗어난 상승을 정상으로 배운다.
"""

import math
import random

import pytest

from sentry_atm.regulation import data as sdata
from sentry_atm.regulation import synth
from sentry_atm.regulation.geo import separation_distance_nm, vincenty_direct
from sentry_atm.regulation.rules import RuleBook

TRANSITIONS = ["GUKDO", "OLMEN", "BULTI"]


@pytest.fixture(scope="module")
def ds():
    return sdata.load()


@pytest.fixture(scope="module")
def gen(ds):
    return synth.build(ds)


@pytest.fixture(scope="module")
def calm(ds):
    """무풍·무잡음 — 절차 준수만 보고 싶을 때."""
    return synth.TrajectorySynthesizer(
        ds=ds,
        wind=synth.WindField(
            surface_speed_kt=0.0, shear_kt_per_1000ft=0.0, spatial_amp_kt=0.0
        ),
        radar_noise_nm=0.0,
    )


def depart(s, ds, actype="F35A", transition="GUKDO", cruise=14000.0, seed=7):
    rng = random.Random(seed)
    intent = synth.DepartureIntent(
        "DEP", actype, ds.fleet.wake_cat(actype), "UPTIL1", transition,
        cruise, synth.PilotTechnique(),
    )
    return s.fly_departure(intent, rng)


def leg_index_at(sample, pts, start):
    """이 표본이 아직 통과하지 않은 첫 픽스."""
    leg = start
    while leg < len(pts) - 1 and separation_distance_nm(sample.lat, sample.lon, *pts[leg]) <= 1.0:
        leg += 1
    return leg


class TestLiftoffPoint:
    """지상 활주는 항적에 넣지 않는다 — 활주로 위는 레이더 분리 문제가 아니다."""

    def test_first_sample_is_at_the_departure_end_of_the_runway(self, ds, calm):
        tj = depart(calm, ds)
        rwy = ds.procedures.runways["24R"]
        end = vincenty_direct(rwy.thr_lat, rwy.thr_lon, rwy.true_brg, rwy.length_m)
        d = separation_distance_nm(tj.samples[0].lat, tj.samples[0].lon, *end)
        assert d < 0.1, f"부양 지점이 이륙 종단에서 {d:.2f}NM 떨어져 있다"

    def test_first_sample_is_already_airborne(self, ds, calm):
        tj = depart(calm, ds)
        rwy = ds.procedures.runways["24R"]
        assert tj.samples[0].alt_ft > rwy.thr_elev_ft

    def test_first_sample_is_moving_near_rotation_speed(self, ds, calm):
        tj = depart(calm, ds, actype="B738")
        vref = ds.fleet.final_gs_kt("B738", "중형")
        assert tj.samples[0].gs_kt == pytest.approx(1.15 * vref, rel=0.05)


class TestProcedureCompliance:
    @pytest.mark.parametrize("transition", TRANSITIONS)
    @pytest.mark.parametrize("actype", ["F35A", "B738", "KC30"])
    def test_at_altitude_constraints_are_met(self, ds, calm, transition, actype):
        """AT 제약은 그 고도로 지나야 한다 — 초과하면 절차 위반이다."""
        tj = depart(calm, ds, actype=actype, transition=transition)
        pts, cons = calm.sid_route("UPTIL1", transition)
        for (lat, lon), c in zip(pts, cons):
            if c.get("alt_cons") != "AT":
                continue
            near = min(tj.samples, key=lambda x: separation_distance_nm(x.lat, x.lon, lat, lon))
            assert near.alt_ft == pytest.approx(c["alt_ft"], abs=300), (
                f"{c['wpt']} AT {c['alt_ft']}ft 인데 {near.alt_ft:.0f}ft"
            )

    @pytest.mark.parametrize("transition", TRANSITIONS)
    def test_at_or_above_constraints_are_met(self, ds, calm, transition):
        tj = depart(calm, ds, transition=transition)
        pts, cons = calm.sid_route("UPTIL1", transition)
        for (lat, lon), c in zip(pts, cons):
            if c.get("alt_cons") != "AT_OR_ABOVE":
                continue
            near = min(tj.samples, key=lambda x: separation_distance_nm(x.lat, x.lon, lat, lon))
            assert near.alt_ft >= c["alt_ft"] - 50

    @pytest.mark.parametrize("actype", ["F35A", "B738"])
    def test_leg_speed_limits_are_respected(self, ds, calm, actype):
        """UPTIL·TU521 구간은 220kt 제한이다. 무풍이므로 대지속도로 확인한다."""
        tj = depart(calm, ds, actype=actype)
        pts, cons = calm.sid_route("UPTIL1", "GUKDO")
        leg = 0
        for x in tj.samples:
            leg = leg_index_at(x, pts, leg)
            limit = cons[leg].get("speed_max_kt")
            if limit:
                assert x.gs_kt <= limit + 2, f"{cons[leg]['wpt']} 구간에서 {x.gs_kt:.0f}kt"

    def test_route_passes_every_published_fix(self, ds, calm):
        tj = depart(calm, ds)
        pts, cons = calm.sid_route("UPTIL1", "GUKDO")
        for (lat, lon), c in zip(pts, cons):
            d = min(separation_distance_nm(x.lat, x.lon, lat, lon) for x in tj.samples)
            assert d < 1.5, f"{c['wpt']} 를 {d:.1f}NM 빗겨갔다"


class TestClimbModel:
    def test_never_descends_on_the_sid(self, ds, calm):
        """SID 구간에서 강하하면 아래 항적과의 수직분리 전제가 깨진다."""
        for tr in TRANSITIONS:
            tj = depart(calm, ds, transition=tr)
            assert all(x.vs_fpm >= 0.0 for x in tj.samples), tr

    def test_altitude_is_monotone(self, ds, calm):
        tj = depart(calm, ds)
        alts = [x.alt_ft for x in tj.samples]
        assert all(b >= a - 1e-6 for a, b in zip(alts, alts[1:]))

    def test_climb_rate_follows_the_published_gradient(self, ds, calm):
        """상승률은 값을 두지 않고 AIP 구배 × 대지속도로 낸다."""
        sid = ds.procedures.sid("UPTIL1")
        gradient = sid["climb_gradient_ft_per_nm"]
        tj = depart(calm, ds, actype="B738")
        climbing = [x for x in tj.samples if x.vs_fpm > 50.0]
        assert climbing
        for x in climbing[:20]:
            expected = gradient * x.gs_kt / 60.0
            assert x.vs_fpm <= expected * 1.5 + 1.0

    def test_levels_off_at_cruise_altitude(self, ds, calm):
        tj = depart(calm, ds, actype="B738", transition="OLMEN", cruise=8000.0)
        assert max(x.alt_ft for x in tj.samples) <= 8000.0 + 100.0


class TestCruiseAltitudeRule:
    """고시 4-5-2 — 순항고도를 지어내지 않는다."""

    def test_eastbound_gets_odd_thousands(self, ds):
        rb = RuleBook(ds)
        alt = rb.cruise_altitude_ft(36.24, 6500)  # 자침 45°
        assert (alt // 1000) % 2 == 1

    def test_westbound_gets_even_thousands(self, ds):
        rb = RuleBook(ds)
        alt = rb.cruise_altitude_ft(285.29, 6500)  # 자침 294°
        assert (alt // 1000) % 2 == 0

    def test_result_is_never_below_the_floor(self, ds):
        rb = RuleBook(ds)
        for trk in range(0, 360, 15):
            assert rb.cruise_altitude_ft(float(trk), 6500) >= 6500

    def test_generated_departures_comply(self, ds, gen):
        rng = random.Random(11)
        for i in range(20):
            intent = gen.departure_intent(rng, f"D{i}", 0.0)
            legs = ds.procedures.sid("UPTIL1")["transitions"][intent.transition]
            mag = (legs[-1]["course_true"] + ds.procedures.mag_var) % 360.0
            odd = (int(intent.cruise_alt_ft) // 1000) % 2 == 1
            assert odd == (mag < 180.0)


class TestGenerator:
    def test_generates_the_requested_count(self, gen):
        assert len(gen.departures(8, seed=1)) == 8

    def test_is_deterministic_for_a_seed(self, gen):
        a = gen.departures(4, seed=5)
        b = gen.departures(4, seed=5)
        assert [x.callsign for x in a] == [x.callsign for x in b]
        assert a[0].samples[10].lat == b[0].samples[10].lat

    def test_only_published_transitions_are_used(self, ds, gen):
        rng = random.Random(3)
        published = set(ds.procedures.sid("UPTIL1")["transitions"])
        for i in range(30):
            assert gen.departure_intent(rng, f"D{i}", 0.0).transition in published

    def test_mixed_civil_and_military(self, gen):
        rng = random.Random(2)
        kinds = {gen.departure_intent(rng, f"D{i}", 0.0).actype for i in range(40)}
        assert kinds & set(synth.MILITARY_TYPES)
        assert kinds & set(synth.CIVIL_TYPES)
