"""충돌 회피(CD&R) 데모.

    python tools/demo_cdr.py

세 가지를 보인다.
1. 조우 탐지 → 회피 후보 생성 → 2차 충돌 재검증 → 관제 지시 문구
2. 예측 불확실성(σ)에 따른 충돌확률 변화 — Phase 5 가 σ 를 학습으로 채운다
3. 도착 흐름 디컨플릭션이 발산하지 않고 수렴하는 것
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sentry_atm.regulation import data as sdata  # noqa: E402
from sentry_atm.regulation import resolution as res  # noqa: E402
from sentry_atm.regulation import sequencing as seq  # noqa: E402
from sentry_atm.regulation.geo import separation_distance_nm, vincenty_direct  # noqa: E402
from sentry_atm.regulation.state import AircraftState  # noqa: E402

RKTU = (36.71639, 127.4992)


def at(callsign, brg, dist_nm, alt_ft, track, gs, actype="B738", wake="중형"):
    lat, lon = vincenty_direct(*RKTU, brg, dist_nm * 1852.0)
    return AircraftState(callsign, lat, lon, alt_ft, track, gs,
                         actype=actype, wake_cat=wake)


def min_separation(a, b, horizon_s=600, step=5):
    """전파해서 실제 최소 이격을 잰다 — 수직분리가 없는 동안만."""
    worst = math.inf
    for t in range(0, horizon_s + 1, step):
        p, q = a.advance(t), b.advance(t)
        if abs(p.alt_ft - q.alt_ft) < 1000.0:
            worst = min(worst, separation_distance_nm(p.lat, p.lon, q.lat, q.lon))
    return worst


def act2_exception(ds, resolver):
    print("=" * 78)
    print("2막 — 조우 탐지와 회피안 상신")
    print("=" * 78)

    # 최종접근 중인 민항기(시단 7NM)와 공역을 가로지르는 전투기
    thr = ds.procedures.runways["24R"]
    lat, lon = vincenty_direct(
        thr.thr_lat, thr.thr_lon, (thr.true_brg + 180) % 360, 7 * 1852.0
    )
    kal = AircraftState("KAL1201", lat, lon, 2500, thr.true_brg, 145,
                        actype="B738", wake_cat="중형")
    rokaf = at("ROKAF11", 235, 8, 2500, 70.0, 300, "F35A", "소형")
    traffic = [kal, rokaf]

    for ac in traffic:
        print(f"  {ac.callsign:<9}{ac.actype:<6}{ac.wake_cat:<5}"
              f"{ac.alt_ft:6.0f}ft  침로 {ac.track_deg:5.1f}°T  {ac.gs_kt:3.0f}kt  "
              f"담당 {resolver.detector.sector.owner(ac)}"
              f"/{resolver.detector.sector.volume_of(ac)}")
    print()

    c = resolver.detector.check_radar(kal, rokaf)
    if c is None:
        print("조우 없음")
        return
    print(f"탐지: {c.describe()}")
    print(f"      TCAS: KAL1201 {'장착' if ds.fleet.has_tcas('B738') else '미장착'} / "
          f"ROKAF11 {'장착' if ds.fleet.has_tcas('F35A') else '미장착'}")
    print(f"      전파 실측 최소 이격 {min_separation(kal, rokaf):.2f} NM")
    print()

    options = resolver.resolve(c, traffic)
    raw = sum(len(resolver.all_candidates(x)) for x in traffic)
    feasible = sum(len(resolver.candidates(x)) for x in traffic)
    print(f"회피 후보 {raw}개 (두 기 × 침로 6 / 고도 4 / 속도 4)")
    print(f"  → 성능·절차 한계 통과 {feasible}개")
    for x in traffic:
        for m in resolver.all_candidates(x):
            ok, why = resolver.is_feasible(x, m)
            if not ok:
                print(f"     제외: {m}  — {why}")
                break
    print(f"  → 충돌 해소 + 2차 충돌 없음: 상위 {len(options)}개 상신")
    print("-" * 78)
    by_cs = {a.callsign: a for a in traffic}
    for i, r in enumerate(options, 1):
        subject = by_cs[r.maneuver.callsign]
        moved = r.maneuver.apply(subject)
        other = by_cs[c.second if r.maneuver.callsign == c.first else c.first]
        print(f"  {i}. {r.maneuver.instruction(subject, ds.procedures.mag_var)}")
        print(f"     비용 {r.cost:.2f}, 회피 후 최소 이격 "
              f"{min_separation(moved, other):.2f} NM, 2차 충돌 없음")
    print("-" * 78)
    print("  ※ 최종 결정은 관제사 (고시 2-1-2, human-on-the-loop).")
    print("     시스템은 근거와 후보를 제시할 뿐 조종사에게 직접 지시하지 않는다.")


def act_uncertainty(resolver):
    print()
    print("=" * 78)
    print("예측 불확실성과 충돌확률 — Phase 5 연결 지점")
    print("=" * 78)

    a = at("AAA", 90, 8, 4000, 270, 250)
    blat, blon = vincenty_direct(a.lat, a.lon, 0.0, 3.6 * 1852.0)
    b = AircraftState("BBB", blat, blon, 4000, 270, 250)
    sep = separation_distance_nm(a.lat, a.lon, b.lat, b.lon)

    print(f"나란히 비행 중인 두 기, 현재 이격 {sep:.2f} NM (최저치 3.00 NM)")
    print("결정론 판정으로는 '위반 아님'이지만, 예측이 틀릴 수 있다면 얘기가 다르다.")
    print()
    print(f"{'10분 지평 σ':>14}{'충돌확률':>12}")
    print("-" * 30)
    for sigma_10min in (0.0, 0.5, 1.0, 2.0, 4.0):
        u = res.UncertaintyModel(horizontal_nm_per_s=sigma_10min / 600.0)
        p = res.collision_probability(a, b, 3.0, 1000.0, u, 300.0, samples=600)
        label = "0 (결정론)" if sigma_10min == 0 else f"{sigma_10min:.1f} NM"
        print(f"{label:>14}{p:>11.1%}")
    print("-" * 30)
    print("  ※ σ 는 지어내지 않는다. 기본값 0 은 '불확실성을 가정하지 않음'이며,")
    print("     Phase 5 의 항적예측이 산출하는 지평별 σ 로 대체된다.")


def act_deconfliction(ds, resolver, sq):
    print()
    print("=" * 78)
    print("도착 흐름 디컨플릭션 — 슬롯 재배정 (측방 오프셋 아님)")
    print("=" * 78)

    types = ["KC30", "F35A", "B738", "F35A", "C130", "B738",
             "KF16", "A321", "KC30", "F35A", "B738", "FA50"]
    traffic = []
    for i, t in enumerate(types):
        cat = ds.fleet.wake_cat(t)
        d = 10.0 + 1.8 * i
        lat, lon = vincenty_direct(
            *sq.thr, (sq.final_course_deg + 180.0) % 360.0, d * 1852.0
        )
        traffic.append(AircraftState(
            f"AC{i:02d}", lat, lon, sq.glidepath_altitude_ft(d),
            sq.final_course_deg, ds.fleet.final_gs_kt(t, cat),
            actype=t, wake_cat=cat,
        ))

    print(f"1.8NM 간격으로 몰려 들어온 혼재 교통 {len(traffic)}대")
    print()

    base = sq.build_unsequenced(traffic)
    initial = resolver.scan_schedule(sq, traffic, base)
    print(f"[기준선] 간격 조정 없이 도달 순서대로 — 위반 {len(initial)}쌍")
    for c, t in initial[:3]:
        print(f"    t={t:5.0f}s  {c.describe()}")
    if len(initial) > 3:
        print(f"    ... 외 {len(initial) - 3}쌍")
    print()

    schedule, log, rounds = resolver.deconflict_arrival_stream(
        traffic, sq, initial=base
    )
    print("[SENTRY] 슬롯 재배정")
    for line in log:
        print(f"    {line}")

    remaining = resolver.scan_schedule(sq, traffic, schedule)
    worst = 99.0
    t = 0.0
    while t <= schedule.makespan_s:
        flown = res._project_onto_schedule(sq, traffic, schedule, t)
        mine = [x for x in flown if resolver.detector.sector.is_under_control(x)]
        for i, x in enumerate(mine):
            for y in mine[i + 1:]:
                worst = min(worst, separation_distance_nm(x.lat, x.lon, y.lat, y.lon))
        t += 10.0

    print("-" * 78)
    print(f"{'항목':<20}{'기준선':>14}{'SENTRY':>14}")
    print(f"{'위반 쌍':<20}{len(initial):>11} 쌍{len(remaining):>11} 쌍")
    print(f"{'평균 착륙 간격':<20}{base.mean_gap_s:>11.0f} 초{schedule.mean_gap_s:>11.0f} 초")
    print(f"{'총 지연':<20}{base.total_delay_s / 60:>11.1f} 분"
          f"{schedule.total_delay_s / 60:>11.1f} 분")
    print(f"{'재배정 횟수':<20}{'—':>14}{rounds:>11} 회")
    print(f"{'최소 이격':<20}{'—':>14}{worst:>11.2f} NM")
    print("  ※ 측방 오프셋을 주지 않는다. 오프셋은 준 기체가 옆 기체와 새 충돌을")
    print("     만들고 그걸 또 오프셋으로 풀면서 발산한다.")


def main() -> int:
    ds = sdata.load()
    resolver = res.build(ds)
    sq = seq.build(ds)

    print()
    act2_exception(ds, resolver)
    act_uncertainty(resolver)
    act_deconfliction(ds, resolver, sq)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
