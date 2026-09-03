"""임무 소티 검증.

작전지역은 AIP ENR 5.2 고시 훈련공역에서만 온다. 지어낸 공역을 쓰면 "이 공역이
접근로 코앞에 있어 까다롭다"는 이 과제의 논지 자체가 성립하지 않는다.

단계 판정은 순서가 중요하다 — 거리로만 나누면 진출과 복귀가 구분되지 않는다.
"""

import pytest

from sentry_atm.regulation import data as sdata
from sentry_atm.regulation import mission
from sentry_atm.regulation import sector as sec
from sentry_atm.regulation.geo import vincenty_direct
from sentry_atm.regulation.mission import MissionKind, SortiePhase
from sentry_atm.regulation.state import AircraftState


@pytest.fixture(scope="module")
def ds():
    return sdata.load()


@pytest.fixture(scope="module")
def mb(ds):
    return mission.build(ds)


@pytest.fixture(scope="module")
def sm(ds):
    return sec.SectorModel.from_dataset(ds)


def state(lat, lon, alt, cs="ROKAF01", actype="F35A", t=0.0):
    return AircraftState(
        cs, lat, lon, alt, 232.4, 300.0, actype=actype, wake_cat="소형", t_s=t
    )


def sortie(mb, area_id="MOA 3A", kind=MissionKind.PATROL):
    return mission.Sortie(
        callsign="ROKAF01", actype="F35A", wake_cat="소형",
        kind=kind, area=mb.designate(area_id),
    )


class TestPublishedAreasOnly:
    def test_areas_come_from_aip_enr_52(self, ds, mb):
        published = {m["id"] for m in ds.airspace.raw["special_use"]["moa"]}
        assert set(mb.areas) == published

    def test_cheongju_has_five_training_areas(self, mb):
        assert set(mb.areas) == {"MOA 2H", "MOA 2L", "MOA 3A", "MOA 4", "MOA 11"}

    def test_designating_an_unpublished_area_is_refused(self, mb):
        with pytest.raises(KeyError):
            mb.designate("MOA 99")

    def test_altitude_blocks_are_resolved_to_amsl(self, ds, mb):
        """AGL·GND·FL 이 섞여 있으므로 하나로 환산되어야 한다."""
        elev = ds.procedures.raw["aerodrome"]["elev_ft"]
        assert mb.designate("MOA 2L").lower_ft == pytest.approx(elev + 3000.0)
        assert mb.designate("MOA 2H").upper_ft == 40000.0  # FL400

    def test_polygon_vertices_match_the_source(self, ds, mb):
        raw = next(m for m in ds.airspace.raw["special_use"]["moa"] if m["id"] == "MOA 4")
        assert len(mb.designate("MOA 4").volume.polygon) == len(raw["polygon"])


class TestApproachInterference:
    """어느 공역을 지정하느냐가 도착에 미치는 영향을 바꾼다."""

    def test_low_areas_overlap_the_arrival_ladder(self, mb):
        overlapping = {a.id for a in mb.areas_conflicting_with_approach()}
        assert "MOA 3A" in overlapping
        assert "MOA 2L" in overlapping

    def test_high_areas_do_not_overlap(self, mb):
        overlapping = {a.id for a in mb.areas_conflicting_with_approach()}
        assert "MOA 2H" not in overlapping  # 10,000ft 이상
        assert "MOA 11" not in overlapping  # 12,000ft 이상

    def test_overlap_test_is_symmetric_and_inclusive(self, mb):
        a = mb.designate("MOA 3A")
        assert a.overlaps_altitude(a.lower_ft, a.lower_ft)
        assert a.overlaps_altitude(a.upper_ft, a.upper_ft + 5000)
        assert not a.overlaps_altitude(a.upper_ft + 1, a.upper_ft + 5000)

    def test_nearest_area_to_the_field(self, ds, mb):
        near = mb.nearest_area(*ds.procedures.arp)
        assert near.id == "MOA 3A"


class TestPhaseMachine:
    def test_before_takeoff_is_ground(self, mb, sm):
        s = sortie(mb)
        ac = state(*ds_arp(mb), 0.0)
        assert mb.phase_at(s, ac, sm) is SortiePhase.GROUND

    def test_inside_the_area_is_on_station(self, mb, sm):
        s = sortie(mb)
        s.takeoff_s = 0.0
        c = s.area.centroid
        ac = state(c[0], c[1], (s.area.lower_ft + s.area.upper_ft) / 2)
        assert mb.phase_at(s, ac, sm) is SortiePhase.ON_STATION

    def test_outbound_under_control_is_climbout(self, ds, mb, sm):
        s = sortie(mb)
        s.takeoff_s = 0.0
        thr = ds.procedures.runways["24R"]
        ac = state(thr.thr_lat, thr.thr_lon, 4000.0)
        assert mb.phase_at(s, ac, sm) is SortiePhase.CLIMBOUT

    def test_after_recovery_declared_the_same_position_reads_as_approach(self, ds, mb, sm):
        """거리로만 나누면 진출과 복귀가 구분되지 않는다 — 선언이 상태를 가른다."""
        s = sortie(mb)
        s.takeoff_s = 0.0
        thr = ds.procedures.runways["24R"]
        ac = state(thr.thr_lat, thr.thr_lon, 4000.0)
        assert mb.phase_at(s, ac, sm) is SortiePhase.CLIMBOUT
        mb.declare_recovery(s, 600.0)
        assert mb.phase_at(s, ac, sm) is SortiePhase.APPROACH

    def test_recovery_outside_controlled_airspace_is_recovery_not_approach(self, mb, sm):
        s = sortie(mb)
        s.takeoff_s = 0.0
        mb.declare_recovery(s, 600.0)
        far = vincenty_direct(*s.area.centroid, 90.0, 40 * 1852.0)
        ac = state(far[0], far[1], 20000.0)
        assert mb.phase_at(s, ac, sm) is SortiePhase.RECOVERY

    def test_landed_is_terminal(self, mb, sm):
        s = sortie(mb)
        s.takeoff_s, s.landed_s = 0.0, 900.0
        c = s.area.centroid
        ac = state(c[0], c[1], (s.area.lower_ft + s.area.upper_ft) / 2)
        assert mb.phase_at(s, ac, sm) is SortiePhase.LANDED


class TestTransitionTimestamps:
    def test_advance_records_arrival_on_station(self, mb, sm):
        s = sortie(mb)
        s.takeoff_s = 0.0
        c = s.area.centroid
        ac = state(c[0], c[1], (s.area.lower_ft + s.area.upper_ft) / 2)
        mb.advance(s, ac, sm, 300.0)
        assert s.on_station_s == 300.0

    def test_advance_records_departure_from_station(self, ds, mb, sm):
        s = sortie(mb)
        s.takeoff_s = 0.0
        c = s.area.centroid
        inside = state(c[0], c[1], (s.area.lower_ft + s.area.upper_ft) / 2)
        mb.advance(s, inside, sm, 300.0)
        mb.declare_recovery(s, 900.0)
        thr = ds.procedures.runways["24R"]
        mb.advance(s, state(thr.thr_lat, thr.thr_lon, 4000.0), sm, 950.0)
        assert s.off_station_s == 950.0
        assert s.time_on_station_s() == pytest.approx(650.0)

    def test_time_on_station_is_none_until_both_ends_are_known(self, mb):
        s = sortie(mb)
        assert s.time_on_station_s() is None
        s.on_station_s = 100.0
        assert s.time_on_station_s() is None


class TestMissionKind:
    def test_scramble_and_patrol_are_distinguished(self, mb):
        patrol = sortie(mb, kind=MissionKind.PATROL)
        scramble = sortie(mb, kind=MissionKind.SCRAMBLE)
        assert patrol.kind is not scramble.kind
        assert "초계" in patrol.describe()
        assert "비상출격" in scramble.describe()

    def test_emergency_flag_is_set_by_declaration(self, mb):
        s = sortie(mb)
        mb.declare_recovery(s, 100.0, emergency=True)
        assert s.emergency
        assert s.recovery_declared_s == 100.0

    def test_ordinary_recovery_is_not_an_emergency(self, mb):
        s = sortie(mb)
        mb.declare_recovery(s, 100.0)
        assert not s.emergency


def ds_arp(mb):
    """작전지역 판정에 쓸 공항 기준점 — 픽스처 밖에서 쓰기 위한 헬퍼."""
    a = mb.ds.procedures.arp
    return a[0], a[1]
