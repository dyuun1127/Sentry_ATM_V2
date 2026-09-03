"""데이터 계층 검증 — 로더가 AIP 값을 정확히 노출하는지, 규정 상수가 맞는지."""

import pytest

from sentry_atm.regulation import data as sdata


@pytest.fixture(scope="module")
def ds():
    return sdata.load()


class TestProcedures:
    def test_all_waypoints_parse(self, ds):
        """모든 픽스가 청주 주변(위도 36~38, 경도 126~129) 안에 있어야 한다."""
        wpts = ds.procedures.waypoints
        assert len(wpts) >= 22
        for name, w in wpts.items():
            assert 36.0 < w.lat < 38.0, f"{name} 위도 이상: {w.lat}"
            assert 126.0 < w.lon < 129.0, f"{name} 경도 이상: {w.lon}"

    def test_faf_is_apaki(self, ds):
        """RNP RWY 24R 의 FAF 는 APAKI, 고시고도 2,100 ft."""
        iap = ds.procedures.iap("RNP_24R")
        assert iap["faf"] == "APAKI"
        faf_leg = next(l for l in iap["final"] if l.get("role") == "FAF")
        assert faf_leg["alt_ft"] == 2100

    def test_runway_24r(self, ds):
        rwy = ds.procedures.runways["24R"]
        assert rwy.true_brg == pytest.approx(232.43)
        assert rwy.length_m == 2744

    def test_mag_var(self, ds):
        assert ds.procedures.mag_var == 9.0


class TestAirspace:
    def test_target_sector_is_t17(self, ds):
        """대상 섹터는 청주 GCA 가 운용하는 T17."""
        t17 = ds.airspace.target_sector
        assert t17["id"] == "T17"
        assert t17["unit"] == "CHEONGJU GCA"
        assert t17["upper"] == {"ft": 6500, "ref": "AMSL"}
        assert t17["ifr_vfr_separation"] is False  # Class D

    def test_sector_polygon_closed_shape(self, ds):
        poly = ds.airspace.sector_polygon
        assert len(poly) == 4
        for lat, lon in poly:
            assert 36.0 < lat < 38.0 and 126.0 < lon < 129.0

    def test_separation_minima_match_regulation(self, ds):
        """고시 5-5-4 / 4-5-1 값."""
        a = ds.airspace
        assert a.sep_horizontal_nm == 3.0     # ASR 40마일 미만
        assert a.sep_final_nm == 2.5          # 최종접근 10NM 이내
        assert a.sep_vertical_ft == 1000      # FL410 이하

    def test_altitude_ladder_fits_under_t17_ceiling(self, ds):
        """배정고도 사다리는 전부 T17 상한(6,500ft) 아래여야 한다."""
        ladder = ds.airspace.altitude_ladder_ft
        assert ladder == [4000, 5000, 6000]
        assert max(ladder) < ds.airspace.handoff_alt_ft

    def test_wake_tables_are_split_by_clause(self, ds):
        """고시 5-5-4 사(비행 중)와 아(착륙)는 별개 표다.

        하나로 합치면 '대형 뒤 소형' 이 5마일(사)인지 6마일(아)인지 구분이 사라진다.
        적용 조건 판정은 rules.RuleBook 이 담당한다.
        """
        in_flight = ds.airspace.wake_table("in_flight")
        landing = ds.airspace.wake_table("landing")
        assert in_flight["대형|소형"] == 5.0
        assert landing["대형|소형"] == 6.0
        assert "중형|소형" not in in_flight
        assert landing["중형|소형"] == 4.0

    def test_reduced_final_is_disabled(self, ds):
        """2.5NM 감축은 활주로 점유시간 조건이 미확인이라 꺼져 있어야 한다."""
        cfg = ds.airspace.raw["separation"]["reduced_final"]
        assert cfg["enabled"] is False
        assert cfg["value_nm"] == 2.5

    def test_handoff_upper_unit_is_osan(self, ds):
        """ENR 2.1 은 T17 상층(6,500ft~FL145)을 OSAN APP 에 배정한다."""
        assert ds.airspace.raw["handoff"]["upper_unit"] == "OSAN APP"
        assert ds.airspace.raw["handoff"]["lateral_unit"] == "JUNGWON APP"

    def test_terminal_class_c(self, ds):
        """AD 2.17 (AMDT 1/26) — 관제권이 Class D 에서 Class C 로 변경."""
        assert ds.airspace.raw["ctr"]["class"] == "C"
        assert ds.airspace.raw["cheongju_terminal"]["provides_ifr_vfr_separation"] is True


def test_frame_centered_on_arp(ds):
    x, y = ds.frame.to_xy(*ds.procedures.arp)
    assert x == pytest.approx(0.0, abs=1e-9)
    assert y == pytest.approx(0.0, abs=1e-9)
