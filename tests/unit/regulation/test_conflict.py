"""통합 충돌 탐지 검증 — 기하 + 규정 + 공역."""

import pytest

from sentry_atm.regulation import conflict as cf
from sentry_atm.regulation import data as sdata
from sentry_atm.regulation.geo import vincenty_direct
from sentry_atm.regulation.state import AircraftState

RKTU = (36.71639, 127.4992)
FINAL_COURSE = 232.43


@pytest.fixture(scope="module")
def det():
    return cf.build(sdata.load())


def on_final(callsign, dist_from_thr_nm, wake_cat="중형", alt_ft=None, gs_kt=150, **kw):
    """RWY 24R 연장 중심선 위. 거리가 작을수록 활주로에 가깝다(선행기).

    고도를 생략하면 3° 활공로 위에 올린다 — TCH 59ft, THR 표고 185.4ft.
    """
    if alt_ft is None:
        alt_ft = dist_from_thr_nm * 6076.115 * 0.0524078 + 59 + 185.4
    lat, lon = vincenty_direct(*RKTU, (FINAL_COURSE + 180) % 360, dist_from_thr_nm * 1852.0)
    return AircraftState(
        callsign=callsign, lat=lat, lon=lon, alt_ft=alt_ft,
        track_deg=FINAL_COURSE, gs_kt=gs_kt, wake_cat=wake_cat, **kw
    )


class TestResponsibility:
    def test_only_scans_aircraft_under_control(self, det, monkeypatch):
        """인접 기관 관할 항적은 분리 대상이 아니다 (고시 2-1-15)."""
        # TURTU 부근(중원 APP)에 서로 붙은 두 기를 놓아도 우리 책임이 아니다
        ds = sdata.load()
        turtu = ds.procedures.fix("TURTU")
        a = AircraftState("JNG1", turtu.lat, turtu.lon, 3700, FINAL_COURSE, 200)
        b = AircraftState("JNG2", turtu.lat + 0.005, turtu.lon, 3700, FINAL_COURSE, 200)
        assert det.scan([a, b]) == []

    def test_scans_aircraft_inside_terminal_area(self, det):
        a = on_final("AAA", 7.0)
        b = on_final("BBB", 8.0)
        assert det.sector.is_under_control(a)
        assert det.sector.is_under_control(b)


class TestRadarConflict:
    def test_in_trail_too_close_is_violation(self, det):
        """종렬 1NM — 수평 3NM 미만이고 활공로상 고도차도 1,000ft 미만."""
        a = on_final("AAA", 7.0)
        b = on_final("BBB", 8.0)
        c = det.check_radar(a, b)
        assert c is not None and c.is_active
        assert c.kind is cf.ConflictKind.RADAR
        assert "5-5-4 가" in c.clauses and "4-5-1" in c.clauses

    def test_adequately_spaced_is_clear(self, det):
        """종렬 4NM 이면 수평 최저치 3NM 확보."""
        assert det.check_radar(on_final("AAA", 6.0), on_final("BBB", 10.0)) is None

    def test_vertical_separation_resolves(self, det):
        """수평이 가까워도 1,000ft 수직분리가 있으면 위반이 아니다."""
        a = on_final("AAA", 7.0, alt_ft=3000)
        b = on_final("BBB", 8.0, alt_ft=4000)
        assert det.check_radar(a, b) is None

    def test_describe_mentions_clause_and_cpa(self, det):
        c = det.check_radar(on_final("AAA", 7.0), on_final("BBB", 8.0))
        text = c.describe()
        assert "CPA" in text and "5-5-4 가" in text and "AAA" in text


class TestWakeConflict:
    def test_heavy_ahead_of_small_needs_six_miles_on_landing(self, det):
        """대형 뒤 소형, 동일 활주로 착륙 → 6NM (고시 5-5-4 아)."""
        leader = on_final("HVY", 5.0, "대형")
        follower = on_final("SML", 10.0, "소형")   # 5NM 종렬
        c = det.check_wake(leader, follower, FINAL_COURSE, same_landing_runway=True)
        assert c is not None
        assert c.required_nm == 6.0
        assert c.actual_nm == pytest.approx(5.0, abs=0.02)
        assert "5-5-4 아" in c.clauses

    def test_sufficient_wake_spacing_is_clear(self, det):
        leader = on_final("HVY", 4.0, "대형")
        follower = on_final("SML", 11.0, "소형")   # 7NM 종렬
        assert det.check_wake(leader, follower, FINAL_COURSE,
                              same_landing_runway=True) is None

    def test_medium_pair_has_no_wake_requirement(self, det):
        """중형 뒤 중형은 항적난기류 추가분리 불요 — 레이더 최저치만."""
        leader = on_final("AAA", 5.0, "중형")
        follower = on_final("BBB", 8.5, "중형")
        assert det.check_wake(leader, follower, FINAL_COURSE,
                              same_landing_runway=True) is None


class TestScan:
    def test_sorts_active_violations_first(self, det):
        """이미 위반인 쌍이 예상 위반보다 앞에 온다."""
        traffic = [
            on_final("NEAR1", 6.0),
            on_final("NEAR2", 6.8),                    # 0.8NM — 이미 위반
            on_final("FAR1", 9.0, gs_kt=130),
            on_final("FAR2", 13.0, gs_kt=210),         # 접근 중 — 예상 위반
        ]
        found = det.scan(traffic)
        assert found, "충돌이 하나도 안 잡혔다"
        assert found[0].is_active
        assert found[0].pair == ("NEAR1", "NEAR2")

    def test_clean_sequence_has_no_conflicts(self, det):
        """4NM 간격 중형 4대 — 레이더·후류 모두 확보."""
        traffic = [on_final(f"KAL{i}", 4.0 + 4.0 * i, "중형") for i in range(4)]
        assert det.scan(traffic, final_course_deg=FINAL_COURSE) == []

    def test_wake_scan_uses_landing_sequence(self, det):
        """착륙 순서를 주면 인접 순번만 종렬 판정한다."""
        traffic = [
            on_final("HVY", 4.0, "대형"),
            on_final("SML", 8.0, "소형"),    # 4NM 종렬, 요건 6NM → 위반
            on_final("MED", 14.0, "중형"),
        ]
        found = det.scan(
            traffic, final_course_deg=FINAL_COURSE,
            landing_sequence=["HVY", "SML", "MED"],
        )
        wake = [c for c in found if c.kind is cf.ConflictKind.WAKE]
        assert len(wake) == 1
        assert wake[0].pair == ("HVY", "SML")

    def test_wake_scan_infers_order_without_sequence(self, det):
        """순서를 안 줘도 진로 앞뒤로 선후를 정한다."""
        traffic = [on_final("SML", 8.0, "소형"), on_final("HVY", 4.0, "대형")]
        found = det.scan(traffic, final_course_deg=FINAL_COURSE)
        wake = [c for c in found if c.kind is cf.ConflictKind.WAKE]
        assert len(wake) == 1
        assert wake[0].first == "HVY", "활주로에 가까운 대형기가 선행기여야 한다"


class TestReverification:
    def test_candidate_clear_when_well_separated(self, det):
        others = [on_final("AAA", 5.0), on_final("BBB", 13.0)]
        assert det.is_clear(on_final("NEW", 9.0), others)

    def test_candidate_rejected_on_secondary_conflict(self, det):
        """회피안이 다른 항적과 새 충돌을 만들면 통과시키지 않는다."""
        others = [on_final("AAA", 5.0), on_final("BBB", 9.5)]
        assert not det.is_clear(on_final("NEW", 9.0), others)

    def test_candidate_rejected_on_wake(self, det):
        """레이더 분리는 되지만 항적난기류 종렬이 부족한 경우."""
        others = [on_final("HVY", 5.0, "대형")]
        candidate = on_final("SML", 8.5, "소형")   # 3.5NM — 레이더 OK, 후류 6NM 부족
        assert det.check_radar(candidate, others[0]) is None
        assert not det.is_clear(candidate, others, final_course_deg=FINAL_COURSE)

    def test_ignores_aircraft_outside_responsibility(self, det):
        ds = sdata.load()
        turtu = ds.procedures.fix("TURTU")
        outside = AircraftState("JNG1", turtu.lat, turtu.lon, 3700, FINAL_COURSE, 200)
        assert det.is_clear(on_final("NEW", 9.0), [outside])
