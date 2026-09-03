"""공역 포함 판정 검증 — 담당 구역 합집합, 고도 밴드, 관제이양.

핵심은 "T17 회랑 하나로는 최종접근이 덮이지 않는다"는 점이다. AIP 를 그대로
읽으면 청주 GCA 담당은 T17 ∪ 터미널 Class C(관제권 + 확장 + 5~10NM 링) 이고,
RWY 24R 최종접근은 회랑이 아니라 관제권 북동 확장과 링이 담당한다.
"""

import pytest

from sentry_atm.regulation import data as sdata
from sentry_atm.regulation.geo import distance_nm
from sentry_atm.regulation.sector import (
    CircleVolume,
    PolygonVolume,
    SectorModel,
    point_in_polygon,
    resolve_altitude_ft,
)
from sentry_atm.regulation.state import AircraftState

RKTU_LAT, RKTU_LON = 36.71639, 127.4992


@pytest.fixture(scope="module")
def ds():
    return sdata.load()


@pytest.fixture(scope="module")
def sm(ds):
    return SectorModel.from_dataset(ds)


def at(lat, lon, alt_ft, callsign="TST"):
    return AircraftState(callsign, lat, lon, alt_ft, track_deg=52.43, gs_kt=200)


def fix_at(ds, name, alt_ft):
    w = ds.procedures.fix(name)
    return at(w.lat, w.lon, alt_ft, name)


class TestAltitudeResolution:
    def test_amsl_passthrough(self):
        assert resolve_altitude_ft({"ft": 6500, "ref": "AMSL"}, 192) == 6500

    def test_agl_adds_aerodrome_elevation(self):
        """T17 하한 1,000ft AGL → 공항 표고 192ft 기준 1,192ft AMSL."""
        assert resolve_altitude_ft({"ft": 1000, "ref": "AGL"}, 192) == 1192

    def test_surface_references(self):
        assert resolve_altitude_ft({"ref": "GND"}, 192) == 192
        assert resolve_altitude_ft({"ref": "SFC"}, 192) == 192

    def test_flight_level(self):
        assert resolve_altitude_ft({"fl": 145}, 192) == 14500

    def test_rejects_unknown_reference(self):
        with pytest.raises(ValueError, match="고도 기준"):
            resolve_altitude_ft({"ft": 100, "ref": "QFE"}, 192)


class TestPointInPolygon:
    SQUARE = [(0.0, 0.0), (0.0, 10.0), (10.0, 10.0), (10.0, 0.0)]

    def test_inside_and_outside(self):
        assert point_in_polygon(5.0, 5.0, self.SQUARE)
        assert not point_in_polygon(15.0, 5.0, self.SQUARE)
        assert not point_in_polygon(5.0, 15.0, self.SQUARE)

    def test_degenerate_polygon(self):
        assert not point_in_polygon(1.0, 1.0, [(0.0, 0.0), (1.0, 1.0)])

    def test_concave_polygon(self):
        """ㄷ 자 모양 — 오목한 부분은 바깥이어야 한다."""
        c = [(0.0, 0.0), (0.0, 10.0), (10.0, 10.0), (10.0, 7.0),
             (3.0, 7.0), (3.0, 3.0), (10.0, 3.0), (10.0, 0.0)]
        assert point_in_polygon(1.0, 5.0, c)
        assert not point_in_polygon(6.0, 5.0, c)


class TestVolumes:
    def test_circle_volume(self):
        v = CircleVolume("C", 0.0, 5000.0, RKTU_LAT, RKTU_LON, radius_nm=5.0)
        assert v.contains(RKTU_LAT, RKTU_LON, 2000)
        assert not v.contains(RKTU_LAT, RKTU_LON, 6000)   # 고도 밖

    def test_annulus_excludes_core(self):
        """5~10NM 링은 중심 5NM 을 포함하지 않는다."""
        v = CircleVolume("R", 1192.0, 5192.0, RKTU_LAT, RKTU_LON,
                         radius_nm=10.0, inner_nm=5.0)
        assert not v.contains_position(RKTU_LAT, RKTU_LON)  # 중심
        from sentry_atm.regulation.geo import vincenty_direct
        lat, lon = vincenty_direct(RKTU_LAT, RKTU_LON, 52.0, 7.0 * 1852.0)
        assert v.contains_position(lat, lon)
        lat, lon = vincenty_direct(RKTU_LAT, RKTU_LON, 52.0, 12.0 * 1852.0)
        assert not v.contains_position(lat, lon)

    def test_polygon_volume(self, ds):
        t17 = ds.airspace.target_sector
        v = PolygonVolume("T17", 1192.0, 6500.0,
                          tuple(ds.airspace.sector_polygon))
        assert v.contains(RKTU_LAT, RKTU_LON, 4000)
        assert not v.contains(RKTU_LAT, RKTU_LON, 7000)
        assert t17["id"] == "T17"


class TestT17Corridor:
    def test_corridor_band(self, sm):
        """1,000ft AGL(=1,192ft AMSL) ~ 6,500ft AMSL."""
        assert sm.corridor.lower_ft == pytest.approx(1192.0)
        assert sm.corridor.upper_ft == 6500.0

    def test_airport_inside_corridor(self, sm):
        assert sm.corridor.contains_position(RKTU_LAT, RKTU_LON)

    def test_final_approach_fixes_are_outside_the_corridor(self, ds, sm):
        """회랑의 남동측 경계가 공항을 스치고 지나가 최종접근이 밖으로 나온다.

        이 사실이 곧 '회랑만으로 모델링하면 안 되는' 이유다.
        """
        for name in ("TURTU", "TU743", "APAKI", "TU746"):
            w = ds.procedures.fix(name)
            assert not sm.corridor.contains_position(w.lat, w.lon), (
                f"{name} 이 T17 회랑 안 — 공역 데이터가 바뀌었는지 확인 필요"
            )

    def test_corridor_is_class_d_no_ifr_vfr_separation(self, sm):
        assert sm.corridor_provides_ifr_vfr_separation is False


class TestCheongjuGcaArea:
    """청주 GCA 담당 = T17 ∪ 터미널 Class C."""

    def test_terminal_is_class_c(self, sm):
        """AD 2.17 (AMDT 1/26) 에서 Class D → Class C 로 변경 — IFR-VFR 분리 제공."""
        assert sm.gca.airspace_class == "C"
        assert sm.provides_ifr_vfr_separation is True

    @pytest.mark.parametrize(
        "name,alt_ft,expected_volume",
        [
            ("TU743", 2500, "RING_5_10"),    # 8.3NM — 5~10NM 링
            ("APAKI", 2100, "CTR_EXT_NE"),   # FAF 6.6NM — 관제권 북동 확장
            ("TU746", 1200, "CTR_CORE"),     # 3.8NM — 관제권
            ("SURAX", 620, "CTR_CORE"),      # MAPt 1.6NM
            ("HYEIN", 6000, "T17"),          # IAF — 회랑
            ("COWON", 6000, "T17"),          # 실패접근 대기
        ],
    )
    def test_approach_path_is_covered(self, ds, sm, name, alt_ft, expected_volume):
        """최종접근 전 구간이 청주 GCA 담당 공역 안에 있어야 한다."""
        ac = fix_at(ds, name, alt_ft)
        assert sm.is_under_control(ac), f"{name} 이 청주 GCA 담당 밖"
        assert sm.volume_of(ac) == expected_volume

    def test_faf_altitude_fits_inside_terminal_band(self, ds, sm):
        """FAF 고시고도 2,100ft 가 관제권 상한(5,000ft AGL) 안에 들어야 한다."""
        faf = ds.procedures.iap("RNP_24R")["faf"]
        ac = fix_at(ds, faf, 2100)
        assert sm.is_under_control(ac)
        # 5,000ft AGL 위로 올리면 담당 밖 (회랑에도 안 들어감)
        high = fix_at(ds, faf, 6000)
        assert not sm.is_under_control(high)

    def test_seongmu_class_d_is_excluded(self, sm, ds):
        """성무 Class D 중첩구역은 청주 Class C 에서 제외된다 (ENR 2.1)."""
        from sentry_atm.regulation.geo import parse_latlon

        e = ds.airspace.raw["cheongju_terminal"]["excludes"][0]
        lat = parse_latlon(e["center"]["lat"])
        lon = parse_latlon(e["center"]["lon"])
        # 성무 중심이 청주 ARP 로부터 10NM 이내여야 중첩이 의미 있다
        assert distance_nm(RKTU_LAT, RKTU_LON, lat, lon) < 12.0
        assert not sm.gca.contains(lat, lon, 2000)


class TestNeighbours:
    def test_initial_segments_belong_to_jungwon(self, ds, sm):
        """IAF/IF 중 IKAPO·MENOL·TURTU 는 T19 — 중원 APP 관할."""
        for name, alt_ft in (("IKAPO", 7000), ("MENOL", 6000), ("TURTU", 3700)):
            assert sm.owner(fix_at(ds, name, alt_ft)) == "JUNGWON APP"

    def test_above_corridor_is_osan_not_jungwon(self, sm):
        """T17 상한 위는 OSAN APP 이다 — 브리프의 '중원 APP' 은 ENR 2.1 과 다르다."""
        assert sm.upper_unit == "OSAN APP"
        assert sm.owner(at(RKTU_LAT, RKTU_LON, 7000)) == "OSAN APP"

    def test_lateral_neighbour_is_jungwon(self, sm):
        assert sm.lateral_unit == "JUNGWON APP"

    def test_far_away_is_outside(self, sm):
        assert sm.owner(at(35.9, 128.6, 4000)) == "OUTSIDE"


class TestHandoff:
    def test_ownership_by_altitude_over_the_field(self, sm):
        assert sm.owner(at(RKTU_LAT, RKTU_LON, 4000)) == "CHEONGJU GCA"
        assert sm.owner(at(RKTU_LAT, RKTU_LON, 7000)) == "OSAN APP"

    def test_inbound_handoff_on_descent(self, sm):
        assert sm.crosses_handoff(at(RKTU_LAT, RKTU_LON, 6600),
                                  at(RKTU_LAT, RKTU_LON, 6400)) == "INBOUND"

    def test_outbound_handoff_on_climb(self, sm):
        assert sm.crosses_handoff(at(RKTU_LAT, RKTU_LON, 6400),
                                  at(RKTU_LAT, RKTU_LON, 6600)) == "OUTBOUND"

    def test_no_crossing(self, sm):
        assert sm.crosses_handoff(at(RKTU_LAT, RKTU_LON, 4000),
                                  at(RKTU_LAT, RKTU_LON, 5000)) is None

    def test_transfer_event_on_arrival(self, ds, sm):
        """도착기는 TURTU(중원 APP) 에서 TU743(청주 GCA) 사이에 인수된다."""
        before = fix_at(ds, "TURTU", 3700)
        after = fix_at(ds, "TU743", 2500)
        assert sm.transfer_event(before, after) == ("JUNGWON APP", "CHEONGJU GCA")

    def test_no_transfer_event_within_same_unit(self, ds, sm):
        assert sm.transfer_event(fix_at(ds, "TU743", 2500),
                                 fix_at(ds, "APAKI", 2100)) is None

    def test_iaf_altitudes_straddle_the_boundary(self, ds, sm):
        """RNP 24R 의 두 IAF 가 관제이양 경계를 사이에 둔다.

        HYEIN 6,000ft 는 T17 안(청주 GCA), IKAPO 7,000ft 는 그 위.
        """
        iap = ds.procedures.iap("RNP_24R")
        hyein = iap["transitions"]["HYEIN"][0]["alt_ft"]
        ikapo = iap["transitions"]["IKAPO"][0]["alt_ft"]
        assert hyein < sm.handoff_alt_ft < ikapo
        assert sm.owner(fix_at(ds, "HYEIN", hyein)) == "CHEONGJU GCA"
