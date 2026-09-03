"""도착 시퀀싱 데모 — 혼재 교통 20대와 비상기 우선권.

    python tools/demo_sequencing.py

브리프 7장의 1막(평시)·3막(비상기)에 해당하는 결정론 부분을 눈으로 확인한다.
학습(Phase 5)과 HMI(Phase 6)가 붙기 전이므로 숫자와 표로만 낸다.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sentry_atm.regulation import conflict as cf  # noqa: E402
from sentry_atm.regulation import data as sdata  # noqa: E402
from sentry_atm.regulation import sequencing as seq  # noqa: E402
from sentry_atm.regulation.geo import vincenty_direct  # noqa: E402
from sentry_atm.regulation.state import AircraftState  # noqa: E402

# 청주 혼재 교통 — 민항(제주항공·티웨이·진에어 등)과 17전투비행단·6탐색구조전대
TRAFFIC = [
    ("KAL1201", "B738"), ("TWB302", "A321"), ("ROKAF11", "F35A"),
    ("JJA1105", "B738"), ("ROKAF21", "KC30"), ("ROKAF12", "F35A"),
    ("ABL401", "B738"), ("TWB308", "A321"), ("ROKAF13", "F35A"),
    ("JJA1109", "B738"), ("ROKAF22", "C130"), ("ROKAF14", "KF16"),
    ("KAL1205", "B738"), ("TWB312", "A321"), ("ROKAF15", "F35A"),
    ("JJA1113", "B738"), ("ROKAF23", "KC30"), ("ROKAF16", "FA50"),
    ("ABL405", "B738"), ("ROKAF17", "F35A"),
]


def inbound(sq, callsign, actype, dist_nm):
    ds = sq.ds
    cat = ds.fleet.wake_cat(actype)
    lat, lon = vincenty_direct(
        *sq.thr, (sq.final_course_deg + 180.0) % 360.0, dist_nm * 1852.0
    )
    return AircraftState(
        callsign=callsign, lat=lat, lon=lon,
        alt_ft=sq.glidepath_altitude_ft(dist_nm),
        track_deg=sq.final_course_deg,
        gs_kt=ds.fleet.final_gs_kt(actype, cat),
        actype=actype, wake_cat=cat,
    )


def mmss(seconds: float) -> str:
    return f"{int(seconds) // 60:2d}:{int(seconds) % 60:02d}"


def act1_normal(sq, det, arrivals):
    print("=" * 78)
    print("1막 — 평시 도착 시퀀스 20대")
    print("=" * 78)
    schedule = sq.build(arrivals)
    by_type = {ac.callsign: ac.actype for ac in arrivals}

    print(f"{'순':>3} {'콜사인':<9}{'기종':<6}{'등급':<5}{'착륙':>7}{'지연':>7}"
          f"{'배정고도':>9}  간격 요건")
    print("-" * 78)
    for s in schedule.slots:
        alt = f"{s.assigned_alt_ft:,}ft" + ("*" if s.holding_above else "")
        gap = "-"
        if s.gap:
            gap = (f"{s.gap.seconds:5.0f}s  {s.gap.required_nm:g}NM "
                   f"[{s.gap.driver}/{s.gap.binding}]")
        print(f"{s.order + 1:>3} {s.callsign:<9}{by_type[s.callsign]:<6}"
              f"{next(a.wake_cat for a in arrivals if a.callsign == s.callsign):<5}"
              f"{mmss(s.threshold_time_s):>7}{s.delay_s:6.0f}s{alt:>9}  {gap}")

    print("-" * 78)
    print("* 사다리 초과 — 상위 섹터(OSAN APP) 대기 대상")
    print(f"평균 착륙 간격 {schedule.mean_gap_s:.0f}초, "
          f"총 소요 {mmss(schedule.makespan_s)}, 총 지연 {schedule.total_delay_s / 60:.1f}분")
    print("  ※ 이 간격은 항적난기류·레이더 분리만으로 결정되는 종렬 하한이다.")
    print("     출발 혼합·활주로 점유·민군 조정을 포함한 공항 수용량과는 다른 값이므로")
    print("     청주의 시간당 슬롯 제약(7~8회)과 직접 비교하지 않는다.")

    from sentry_atm.regulation.geo import separation_distance_nm
    violations, min_sep = 0, 99.0
    for t in range(0, int(schedule.makespan_s) + 1, 10):
        traffic = fly(sq, arrivals, schedule, t)
        violations += len(det.scan(traffic, final_course_deg=sq.final_course_deg,
                                   landing_sequence=schedule.order))
        mine = [x for x in traffic if det.sector.is_under_control(x)]
        for i, x in enumerate(mine):
            for y in mine[i + 1:]:
                min_sep = min(min_sep, separation_distance_nm(x.lat, x.lon, y.lat, y.lon))
    print(f"전 구간 10초 간격 재검사 — 분리·후류 위반 {violations}건, "
          f"최소 이격 {min_sep:.2f} NM (최저치 3.00 NM)")
    return schedule


def fly(sq, arrivals, schedule, t):
    by_cs = {ac.callsign: ac for ac in arrivals}
    out = []
    for slot in schedule.slots:
        ac = by_cs[slot.callsign]
        v = sq.final_gs_kt(ac)
        rem = (slot.threshold_time_s - t) / 3600.0 * v
        if rem <= 0:
            continue
        lat, lon = vincenty_direct(
            *sq.thr, (sq.final_course_deg + 180.0) % 360.0, rem * 1852.0
        )
        out.append(AircraftState(
            callsign=ac.callsign, lat=lat, lon=lon,
            alt_ft=sq.glidepath_altitude_ft(rem),
            track_deg=sq.final_course_deg, gs_kt=v,
            actype=ac.actype, wake_cat=ac.wake_cat,
        ))
    return out


def act3_emergency(sq, det, arrivals, baseline, subject):
    print()
    print("=" * 78)
    print(f"3막 — {subject} 비상 선언 (고시 2-1-4 가, 조난 항공기 최우선 통행권)")
    print("=" * 78)

    after = sq.insert_priority(arrivals, subject)
    cmp_ = seq.compare(baseline, after, subject)

    b = baseline.by_callsign(subject)
    print(f"{'항목':<22}{'기준':>14}{'SENTRY':>14}")
    print("-" * 78)
    print(f"{'비상기 착륙 순번':<22}{cmp_.order_before + 1:>11} 위"
          f"{cmp_.order_after + 1:>11} 위")
    print(f"{'비상기 착륙 시각':<22}{mmss(cmp_.time_before_s):>14}"
          f"{mmss(cmp_.time_after_s):>14}")
    print(f"{'단축':<22}{'—':>14}{cmp_.time_saved_s / 60:>11.1f} 분")
    print(f"{'물리적 최단 도달':<22}{'—':>14}{mmss(b.earliest_time_s):>14}")
    print(f"{'소산 항적':<22}{'—':>14}{len(cmp_.displaced):>11} 대")
    print(f"{'평균 추가지연':<22}{'—':>14}"
          f"{cmp_.mean_added_delay_s / 60:>11.1f} 분")

    def max_gap(s):
        return max((y.threshold_time_s - x.threshold_time_s
                    for x, y in zip(s.slots, s.slots[1:], strict=False)), default=0.0)

    print(f"{'최대 슬롯 간격':<22}{max_gap(baseline):>11.0f} 초"
          f"{max_gap(after):>11.0f} 초")
    print(f"{'평균 착륙 간격':<22}{baseline.mean_gap_s:>11.0f} 초"
          f"{after.mean_gap_s:>11.0f} 초")

    emg = [ac if ac.callsign != subject else
           AircraftState(**{**ac.__dict__, "emergency": True}) for ac in arrivals]
    violations = 0
    min_sep = 99.0
    for t in range(0, int(after.makespan_s) + 1, 10):
        traffic = fly(sq, emg, after, t)
        violations += len(det.scan(traffic, final_course_deg=sq.final_course_deg,
                                   landing_sequence=after.order))
        from sentry_atm.regulation.geo import separation_distance_nm
        mine = [x for x in traffic if det.sector.is_under_control(x)]
        for i, x in enumerate(mine):
            for y in mine[i + 1:]:
                min_sep = min(min_sep, separation_distance_nm(x.lat, x.lon, y.lat, y.lon))
    print("-" * 78)
    print(f"전 구간 10초 간격 재검사 — 분리·후류 위반 {violations}건, "
          f"최소 이격 {min_sep:.2f} NM (최저치 3.00 NM)")
    print(f"소산 항적: {', '.join(cmp_.displaced) if cmp_.displaced else '없음'}")


def main() -> int:
    ds = sdata.load()
    sq = seq.build(ds)
    det = cf.build(ds)

    print()
    print(f"청주(RKTU) RWY {sq.runway} / {sq.approach}")
    print(f"최종접근진로 {sq.final_course_deg}°T, FAF {sq.faf_dist_nm:.2f} NM, "
          f"합류점 {sq.join_dist_nm:.2f} NM")
    print()

    # 2.6NM 간격으로 밀려 들어오는 혼잡 시간대
    arrivals = [
        inbound(sq, cs, at, 10.0 + 2.6 * i)
        for i, (cs, at) in enumerate(TRAFFIC)
    ]

    baseline = act1_normal(sq, det, arrivals)
    act3_emergency(sq, det, arrivals, baseline, "ROKAF17")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
