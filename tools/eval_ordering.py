"""착륙순서 최적화 평가 — 순번 이동 제한별 효과.

    python tools/eval_ordering.py [--trials 400] [--aircraft 20]

같은 항공기 집합이라도 순서에 따라 총 소요가 달라진다. 항적난기류 요건이
선행·후행 등급 조합으로 정해지기 때문이다(고시 5-5-4 사·아항). 그 차이만
회수하며, 선착순 원칙(고시 2-1-4)을 지키기 위해 순번 이동을 제한한다.
"""

from __future__ import annotations

import argparse
import random
import statistics as st
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sentry_atm.regulation import conflict as cf  # noqa: E402
from sentry_atm.regulation import data as sdata  # noqa: E402
from sentry_atm.regulation import sequencing as seq  # noqa: E402
from sentry_atm.regulation.geo import vincenty_direct  # noqa: E402
from sentry_atm.regulation.state import AircraftState  # noqa: E402

# 청주 혼재 교통 구성. 민항 중형이 다수이고 전투기(소형)와 수송기(대형)가 섞인다.
TYPE_MIX = (
    ["B738"] * 6 + ["A321"] * 3 + ["B38M"] * 2 + ["A320"] * 2   # 민항 중형
    + ["B77W", "A333"]                                          # 민항 대형
    + ["F35A"] * 4 + ["KF16"] * 2 + ["FA50"] * 2                # 전투기 소형
    + ["F15K"]                                                   # 전투기 중형
    + ["KC30", "C130"]                                           # 수송 대형
)


def make_traffic(sq, ds, rng, n):
    out = []
    d = rng.uniform(8.0, 12.0)
    for i in range(n):
        ty = rng.choice(TYPE_MIX)
        cat = ds.fleet.wake_cat(ty)
        lat, lon = vincenty_direct(
            *sq.thr, (sq.final_course_deg + 180.0) % 360.0, d * 1852.0
        )
        out.append(
            AircraftState(
                f"AC{i:02d}", lat, lon, sq.glidepath_altitude_ft(d),
                sq.final_course_deg, ds.fleet.final_gs_kt(ty, cat),
                actype=ty, wake_cat=cat,
            )
        )
        d += rng.uniform(1.6, 3.4)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=400)
    ap.add_argument("--aircraft", type=int, default=20)
    ap.add_argument("--seed", type=int, default=20260903)
    args = ap.parse_args()

    ds = sdata.load()
    sq = seq.build(ds)
    det = cf.build(ds)
    rng = random.Random(args.seed)

    shifts = [0, 1, 2, 3, 4]
    gaps: dict[int, list[float]] = {k: [] for k in shifts}
    worse = 0
    swap_counts: dict[int, list[int]] = {k: [] for k in shifts}

    print(f"항공기 {args.aircraft}대 × {args.trials}회 시행")
    traffics = [make_traffic(sq, ds, rng, args.aircraft) for _ in range(args.trials)]

    for traffic in traffics:
        base = None
        for k in shifts:
            r = seq.optimize_order(sq, traffic, max_shift=k)
            gaps[k].append(r.mean_gap_s)
            swap_counts[k].append(r.swaps)
            if k == 0:
                base = r.mean_gap_s
            elif r.mean_gap_s > base + 1e-9:
                worse += 1

    fcfs = st.mean(gaps[0])
    print()
    print(f"{'순번 이동 제한':<16}{'평균 착륙간격':>14}{'선착순 대비':>12}{'평균 교환':>11}")
    print("-" * 55)
    for k in shifts:
        m = st.mean(gaps[k])
        label = "선착순 (현행)" if k == 0 else f"±{k}"
        imp = (fcfs - m) / fcfs
        print(f"{label:<16}{m:13.1f}초{imp:12.2%}{st.mean(swap_counts[k]):11.1f}")
    print("-" * 55)

    best = st.mean(gaps[max(shifts)])
    one = st.mean(gaps[1])
    if fcfs > best:
        captured = (fcfs - one) / (fcfs - best)
        print(f"  ±1 이 전체 이득의 {captured:.0%} 를 확보한다 —")
        print("  선착순 원칙(고시 2-1-4)을 사실상 훼손하지 않으면서 간격을 줄일 수 있다.")

    print(f"\n  선착순보다 나빠진 시행 {worse}건 / {args.trials * (len(shifts) - 1)}건")
    print("  선착순에서 출발해 개선되는 교환만 받아들이므로 단조 개선이 보장된다.")

    # 최적화된 순서가 실제로 비행 가능한지 확인
    checked = violations = 0
    for traffic in traffics[:40]:
        r = seq.optimize_order(sq, traffic, max_shift=1)
        by = {ac.callsign: ac for ac in traffic}
        schedule = sq._lay_out([by[cs] for cs in r.order], 0.0)
        for t in range(0, int(schedule.makespan_s) + 1, 20):
            flown = _project(sq, traffic, schedule, t)
            violations += len(
                det.scan(flown, final_course_deg=sq.final_course_deg,
                         landing_sequence=schedule.order)
            )
        checked += 1
    print(f"\n  ±1 최적화 스케줄 {checked}건 재검사 — 분리·후류 위반 {violations}건")

    print()
    print("  [주의] 여기서 측정한 값은 항적난기류·레이더 분리로 결정되는 착륙 간격이다.")
    print("         활주로 점유, 출발 혼합, 민·군 조정을 포함한 공항 전체 수용량과는")
    print("         다른 값이므로 청주의 시간당 슬롯 제약(7~8회)과 연결하지 않는다.")
    return 0


def _project(sq, traffic, schedule, t):
    by = {ac.callsign: ac for ac in traffic}
    out = []
    for slot in schedule.slots:
        ac = by[slot.callsign]
        v = sq.final_gs_kt(ac)
        rem = (slot.threshold_time_s - t) / 3600.0 * v
        if rem <= 0:
            continue
        lat, lon = vincenty_direct(
            *sq.thr, (sq.final_course_deg + 180.0) % 360.0, rem * 1852.0
        )
        out.append(
            AircraftState(
                ac.callsign, lat, lon, sq.glidepath_altitude_ft(rem),
                sq.final_course_deg, v, actype=ac.actype, wake_cat=ac.wake_cat,
            )
        )
    return out


if __name__ == "__main__":
    raise SystemExit(main())
