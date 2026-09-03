"""관제 이양 사슬 검증.

경계 고도를 코드에 두지 않는다 — 관제권(CTR)과 공역 블록(T17, T17_UPPER)의
전사 상한을 그대로 읽어야 한다. 사슬에 상수를 박으면 AIP 개정 때 조용히 틀린다.

측방 이양은 수직 사슬과 **별개 경로**다. 고도만 보면 남동측으로 벗어난 항적을
계속 상위 섹터로 표시하게 되어 이양 시점을 놓친다.
"""

import random

import pytest

from sentry_atm.regulation import data as sdata
from sentry_atm.regulation import handoff, synth
from sentry_atm.regulation.geo import parse_latlon, vincenty_direct
from sentry_atm.regulation.handoff import HandoffDirection
from sentry_atm.regulation.state import AircraftState

M = 1852.0


@pytest.fixture(scope="module")
def ds():
    return sdata.load()


@pytest.fixture(scope="module")
def hc(ds):
    return handoff.build(ds)


def at(ds, alt, *, nm_from_field=0.0, brg=60.0, cs="ROKAF01", t=0.0):
    """관제권 중심 기준 좌표. 수직 사슬 시험에는 `in_corridor` 를 쓴다."""
    c = ds.airspace.raw["ctr"]["center"]
    lat0, lon0 = parse_latlon(c["lat"]), parse_latlon(c["lon"])
    lat, lon = (
        vincenty_direct(lat0, lon0, brg, nm_from_field * M) if nm_from_field else (lat0, lon0)
    )
    return AircraftState(
        cs, lat, lon, alt, brg, 250.0, actype="F35A", wake_cat="소형", t_s=t
    )


def in_corridor(ds, alt, *, cs="ROKAF01", t=0.0):
    """T17 회랑 안의 좌표.

    수직 사슬(GCA → OSAN APP → ACC)은 회랑 안에서만 성립한다. 회랑 밖으로
    나가면 측방 이양이 먼저 걸려 다른 기관이 잡으므로, 고도 경계를 시험하려면
    반드시 회랑 안이어야 한다.
    """
    poly = ds.airspace.sector_polygon
    lat = sum(p[0] for p in poly) / len(poly)
    lon = sum(p[1] for p in poly) / len(poly)
    return AircraftState(
        cs, lat, lon, alt, 60.0, 250.0, actype="F35A", wake_cat="소형", t_s=t
    )


class TestChainFromData:
    def test_four_steps_in_order(self, hc):
        assert [s.unit for s in hc.steps] == [
            "CHEONGJU TWR", "CHEONGJU GCA", "OSAN APP", "ACC"
        ]

    def test_boundaries_come_from_transcribed_blocks(self, ds, hc):
        blocks = {b["id"]: b for b in ds.airspace.raw["tma"]["blocks"]}
        gca = next(s for s in hc.steps if s.unit == "CHEONGJU GCA")
        assert gca.upper_ft == blocks["T17"]["upper"]["ft"]
        osan = next(s for s in hc.steps if s.unit == "OSAN APP")
        assert osan.lower_ft == blocks["T17_UPPER"]["lower"]["ft"]
        assert osan.upper_ft == blocks["T17_UPPER"]["upper"]["fl"] * 100.0

    def test_tower_ceiling_comes_from_the_control_zone(self, ds, hc):
        elev = ds.procedures.raw["aerodrome"]["elev_ft"]
        twr = hc.steps[0]
        assert twr.upper_ft == pytest.approx(elev + ds.airspace.raw["ctr"]["upper"]["ft"])

    def test_acc_starts_where_the_upper_sector_ends(self, hc):
        osan = next(s for s in hc.steps if s.unit == "OSAN APP")
        acc = next(s for s in hc.steps if s.unit == "ACC")
        assert acc.lower_ft == osan.upper_ft
        assert acc.upper_ft == float("inf")

    def test_lateral_unit_is_jungwon(self, hc):
        assert hc.lateral_unit == "JUNGWON APP"


class TestUnitAtAltitude:
    @pytest.mark.parametrize(
        "alt,expected",
        [
            (1000.0, "CHEONGJU TWR"),
            (6000.0, "CHEONGJU GCA"),
            (10000.0, "OSAN APP"),
            (20000.0, "ACC"),
        ],
    )
    def test_altitude_maps_to_the_expected_unit(self, hc, alt, expected):
        assert hc.unit_at(alt) == expected

    def test_boundaries_are_lower_inclusive(self, hc):
        osan = next(s for s in hc.steps if s.unit == "OSAN APP")
        assert hc.unit_at(osan.lower_ft) == "OSAN APP"
        assert hc.unit_at(osan.lower_ft - 1.0) != "OSAN APP"


class TestController:
    def test_over_the_field_at_low_altitude_is_the_tower(self, ds, hc):
        assert hc.controller(at(ds, 2000.0)) == "CHEONGJU TWR"

    def test_outside_the_control_zone_is_approach_not_tower(self, ds, hc):
        """관제권은 반경 5NM 이다 — 그 밖은 낮아도 관제탑이 아니다."""
        radius = ds.airspace.raw["ctr"]["radius_nm"]
        assert hc.controller(at(ds, 2000.0, nm_from_field=radius + 3.0)) == "CHEONGJU GCA"

    def test_above_the_sector_ceiling_is_the_upper_unit(self, ds, hc):
        assert hc.controller(in_corridor(ds, 9000.0)) == "OSAN APP"

    def test_above_the_upper_sector_is_the_area_control_centre(self, ds, hc):
        assert hc.controller(in_corridor(ds, 15000.0)) == "ACC"

    def test_lateral_departure_beats_the_vertical_chain(self, ds, hc):
        """T19 로 벗어나면 고도와 무관하게 중원 APP 이 잡는다."""
        t19 = next(b for b in ds.airspace.raw["tma"]["blocks"] if b["id"] == "T19")
        pts = [(parse_latlon(n["lat"]), parse_latlon(n["lon"])) for n in t19["polygon"]]
        lat = sum(p[0] for p in pts) / len(pts)
        lon = sum(p[1] for p in pts) / len(pts)
        ac = AircraftState(
            "R1", lat, lon, 9000.0, 140.0, 300.0, actype="F35A", wake_cat="소형"
        )
        assert hc.controller(ac) == "JUNGWON APP"


class TestTransferEvents:
    def test_no_event_when_the_unit_does_not_change(self, ds, hc):
        a = at(ds, 3000.0)
        b = at(ds, 3200.0, t=10.0)
        assert hc.transfer(a, b) is None

    def test_climbing_through_the_ceiling_is_a_climb_handoff(self, ds, hc):
        a = in_corridor(ds, 6400.0)
        b = in_corridor(ds, 6600.0, t=10.0)
        ev = hc.transfer(a, b)
        assert ev is not None
        assert ev.direction is HandoffDirection.CLIMB
        assert (ev.from_unit, ev.to_unit) == ("CHEONGJU GCA", "OSAN APP")

    def test_descending_through_the_ceiling_is_an_inbound_handoff(self, ds, hc):
        a = in_corridor(ds, 6600.0)
        b = in_corridor(ds, 6400.0, t=10.0)
        ev = hc.transfer(a, b)
        assert ev.direction is HandoffDirection.DESCEND
        assert (ev.from_unit, ev.to_unit) == ("OSAN APP", "CHEONGJU GCA")

    def test_unresolved_conflict_marks_the_handoff_as_held(self, ds, hc):
        """고시 2-1-15 — 충돌요인 제거 후 이양한다."""
        a = in_corridor(ds, 6400.0)
        b = in_corridor(ds, 6600.0, t=10.0)
        ev = hc.transfer(a, b, conflicts_pending=True)
        assert not ev.conditions_met
        assert "2-1-15" in ev.blocking_reason
        assert "보류" in ev.describe()

    def test_clean_handoff_is_not_marked(self, ds, hc):
        a = in_corridor(ds, 6400.0)
        b = in_corridor(ds, 6600.0, t=10.0)
        ev = hc.transfer(a, b)
        assert ev.conditions_met
        assert "보류" not in ev.describe()


class TestScanOnRealTrajectory:
    @pytest.fixture(scope="class")
    def track(self, ds):
        gen = synth.build(ds)
        rng = random.Random(5)
        intent = synth.DepartureIntent(
            "ROKAF01", "F35A", "소형", "UPTIL1", "GUKDO", 14000.0,
            synth.PilotTechnique(),
        )
        return gen.synth.fly_departure(intent, rng).samples

    def test_a_departure_climbs_through_the_chain_in_order(self, hc, track):
        evs = hc.scan(track)
        assert evs
        units = [evs[0].from_unit] + [e.to_unit for e in evs]
        order = [s.unit for s in hc.steps]
        idx = [order.index(u) for u in units if u in order]
        assert idx == sorted(idx), units

    def test_departure_starts_with_the_tower(self, hc, track):
        assert hc.controller(track[0]) == "CHEONGJU TWR"

    def test_every_event_is_a_real_unit_change(self, hc, track):
        for e in hc.scan(track):
            assert e.from_unit != e.to_unit

    def test_events_are_time_ordered(self, hc, track):
        ts = [e.t_s for e in hc.scan(track)]
        assert ts == sorted(ts)
