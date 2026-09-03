"""데모 시나리오 4막 구성 — 본선 시연용.

    python tools/build_demo.py

브리프 7장의 구성을 그대로 만든다.

    1막 평시    정상 접근, 배정고도 사다리 운용, 관제사 개입 0
    2막 예외    위험 상신(회피안 제시) / 주의는 화면 강조만 (미상신)
    3막 비상기  TCAS 미장착 전투기 연료부족 → 우선권 판단 → 승인
                → 간섭 항적 소산 → 분리 확보 확인 → 재시퀀싱
    4막 마무리  결정 로그 + 4DT 프로파일

**시나리오는 지어내지 않는다.** 후보 시드를 훑어 4막 구조가 뚜렷한 것을 고를
뿐이며, 고른 뒤에는 파이프라인이 실제로 낸 결과를 그대로 쓴다. 몇 개 중에서
골랐는지도 함께 기록한다.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# 참조 데이터는 패키지 안에 있고(저장소 배치와 무관), 산출물은 artifacts/ 로 모은다.
REFERENCE = ROOT / "src" / "sentry_atm" / "regulation" / "reference"
ARTIFACTS = ROOT / "artifacts"
ARTIFACTS.mkdir(exist_ok=True)

import export_scenario as ex  # noqa: E402

from sentry_atm.regulation import conflict as cf  # noqa: E402
from sentry_atm.regulation import data as sdata  # noqa: E402
from sentry_atm.regulation import (  # noqa: E402
    mbe,  # noqa: E402
    synth,  # noqa: E402
)
from sentry_atm.regulation import resolution as res  # noqa: E402
from sentry_atm.regulation import sequencing as seq  # noqa: E402
from sentry_atm.regulation.geo import separation_distance_nm  # noqa: E402

# 비상기는 TCAS 미장착 전투기로 둔다 — 기획서 1.3 의 논지를 화면에서 확인할 수 있다.
EMERGENCY_TYPE = "F35A"


def score_candidate(payload) -> tuple[float, dict]:
    """4막 구조가 얼마나 뚜렷한지."""
    exs = payload["exceptions"]
    danger = [e for e in exs if e["level"] in ("위험", "비상")]
    predictive = [e for e in danger if e["state"] == "예측"]
    with_opts = [e for e in predictive if len(e["options"]) >= 3]
    caution = {
        r["key"] for f in payload["frames"] for r in f["pairs"] if r["level"] == "주의"
    }
    t1 = payload["meta"]["t1"]
    first = min((e["raised_t"] for e in danger), default=t1)

    stats = {
        "danger": len(danger), "predictive": len(predictive),
        "with_options": len(with_opts), "caution": len(caution),
        "first_exception_t": first,
    }
    # 1막이 충분히 길고(개입 0 구간), 2막에 회피안을 갖춘 예측 상신이 있고,
    # 주의가 2건 이상이면 좋은 후보다.
    s = 0.0
    s += min(first / 600.0, 1.5) * 2.0          # 평시 구간 길이
    s += min(len(with_opts), 2) * 3.0           # 회피안 있는 예측 상신
    s += min(len(caution), 3) * 1.5             # 화면 강조용 주의
    s -= max(0, len(danger) - 4) * 1.0          # 예외가 너무 많으면 산만
    return s, stats


def build_acts(payload, priority):
    """막 경계를 데이터에서 정한다."""
    t1 = payload["meta"]["t1"]
    danger = [e for e in payload["exceptions"] if e["level"] in ("위험", "비상")]
    first_exc = min((e["raised_t"] for e in danger), default=t1 * 0.4)
    declared = priority["declared_t"]

    return [
        {
            "n": 1, "name": "평시",
            "t0": 0.0, "t1": round(first_exc, 1),
            "headline": "정상 항적은 시스템이 자율 유지한다",
            "text": "배정고도 사다리로 순번 간 1,000ft 수직분리가 구조적으로 확보되고, "
                    "관제사에게 올라가는 건이 없다. 오버레이를 끄면 현행 ASR 화면과 같다.",
        },
        {
            "n": 2, "name": "예외",
            "t0": round(first_exc, 1), "t1": round(declared, 1),
            "headline": "판단이 필요한 것만 근거와 함께 상신한다",
            "text": "위험 단계만 회피안과 함께 상신하고, 주의 단계는 화면에만 강조하고 "
                    "올리지 않는다. 근거에는 CPA·예지시간·충돌확률·예측 σ 와 근거 조항이 붙는다.",
        },
        {
            "n": 3, "name": "비상기 우선권",
            "t0": round(declared, 1),
            "t1": round(min(priority["after"]["t"] + 120.0, t1), 1),
            "headline": "고시 2-1-4 — 조난 항공기 최우선 통행권",
            "text": "순번이 아니라 물리적 최단 도달시각을 기준으로 삽입한다. "
                    "순번으로 밀어넣으면 활주로가 비고 뒤 항적 전체가 무너진다. "
                    "시단 16NM 안쪽 확정 항적은 건드리지 않는다.",
        },
        {
            "n": 4, "name": "마무리",
            "t0": round(min(priority["after"]["t"] + 120.0, t1), 1),
            "t1": round(t1, 1),
            "headline": "결정 로그와 4DT 프로파일",
            "text": "AI 추천·관제사 승인·결과가 모두 기록되어 리플레이할 수 있다. "
                    "관제사 교육·훈련 자료로 쓰인다.",
        },
    ]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--flights", type=int, default=22)
    ap.add_argument("--seeds", type=int, default=14, help="훑어볼 후보 시드 개수")
    ap.add_argument("--buffer", type=float, default=1.5,
                    help="슬롯 계획 여유. 너무 크면 대기열이 없어 우선권 이득이 "
                         "드러나지 않고, 너무 작으면 예외가 위반 후에 잡힌다.")
    ap.add_argument("--out", default=str(ARTIFACTS / "scenario.json"))
    args = ap.parse_args()

    ds = sdata.load()
    det = cf.build(ds)
    sq = seq.build(ds)
    resolver = res.build(ds)
    gen = synth.build(ds)
    unc = mbe.build_uncertainty_from_checkpoint(str(ROOT / "models" / "predictor.pt"))
    resolver.uncertainty = unc

    print(f"후보 시드 {args.seeds}개를 훑어 4막 구조가 뚜렷한 것을 고른다…")
    print("  1·2막(예외 구성)과 3막(우선권 이득)을 함께 평가한다 —")
    print("  둘 중 하나만 보면 다른 막이 밋밋해진다.")
    best = None
    for i in range(args.seeds):
        seed = 11 + i * 10
        payload = run_pipeline(ds, det, sq, resolver, gen, unc,
                               args.flights, seed, args.buffer)
        s, stats = score_candidate(payload)
        priority = build_priority(ds, sq, det, gen, args.flights, seed, args.buffer)

        if priority is None:
            print(f"  seed {seed:3d}  제외 — 대기열이 없어 3막(우선권)이 성립하지 않음")
            continue

        total = (s
                 + min(priority["saved_s"] / 60.0, 6.0) * 2.0
                 + min(len(priority["frozen"]), 5) * 0.6)
        mark = ""
        if best is None or total > best[0]:
            best = (total, seed, payload, stats, priority)
            mark = "  ← 최선"
        print(f"  seed {seed:3d}  점수 {total:5.2f}  "
              f"위험 {stats['danger']}(예측 {stats['predictive']}, "
              f"회피안 {stats['with_options']}) 주의 {stats['caution']}  "
              f"1막 {stats['first_exception_t']/60:.0f}분  "
              f"3막 {priority['saved_s']/60:+.1f}분/확정 {len(priority['frozen'])}대{mark}")

    if best is None:
        raise SystemExit("4막 구조를 만족하는 시나리오를 찾지 못했다 — --buffer 를 낮출 것")

    _, seed, payload, stats, priority = best
    print(f"\n선정 — seed {seed} (후보 {args.seeds}개 중)")
    payload["priority"] = priority
    payload["acts"] = build_acts(payload, priority)
    payload["meta"]["demo"] = {
        "candidates": args.seeds, "seed": seed, "buffer": args.buffer,
        "note": "후보 시드를 훑어 4막 구조가 뚜렷한 것을 골랐다. "
                "고른 뒤의 수치는 파이프라인이 실제로 낸 결과다.",
    }
    payload["meta"]["emergency_type"] = EMERGENCY_TYPE
    payload["meta"]["emergency_tcas"] = ds.fleet.has_tcas(EMERGENCY_TYPE)

    print("\n막 구성")
    for a in payload["acts"]:
        print(f"  {a['n']}막 {a['name']:<10} {a['t0']/60:5.1f}~{a['t1']/60:5.1f}분  "
              f"{a['headline']}")

    print("\n3막 — 비상기 우선권")
    p = priority
    print(f"  {p['callsign']} ({p['actype']}, TCAS "
          f"{'장착' if p['tcas'] else '미장착'}) {p['declared_t']/60:.1f}분에 비상 선언")
    print(f"  착륙 순번 {p['before']['order']}위 → {p['after']['order']}위")
    print(f"  착륙 시각 {p['before']['t']/60:.1f}분 → {p['after']['t']/60:.1f}분 "
          f"({p['saved_s']/60:+.1f}분)")
    print(f"  확정 항적 {len(p['frozen'])}대 슬롯 유지, 소산 {len(p['displaced'])}대 "
          f"(평균 추가지연 {p['mean_added_delay_s']/60:.1f}분)")
    print(f"  최대 슬롯 간격 {p['max_gap_before_s']:.0f}s → {p['max_gap_after_s']:.0f}s "
          f"(활주로 공백 없음)")
    print(f"  전 구간 재검사 — 분리·후류 위반 {p['violations']}건, "
          f"최소 이격 {p['min_sep_nm']:.2f} NM")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                   encoding="utf-8")
    print(f"\n저장 — {out.name} ({out.stat().st_size/1024:.0f} KB)")
    return 0


def run_pipeline(ds, det, sq, resolver, gen, unc, flights, seed, buffer):
    """export_scenario 의 본체를 후보 평가용으로 재사용한다."""
    import contextlib
    import io

    argv = sys.argv
    sys.argv = [
        "export_scenario", "--flights", str(flights), "--seed", str(seed),
        "--buffer", str(buffer), "--out", str(ARTIFACTS / "_cand.json"),
    ]
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            ex.main()
    finally:
        sys.argv = argv
    path = ARTIFACTS / "_cand.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    path.unlink(missing_ok=True)
    return payload


def build_priority(ds, sq, det, gen, flights, seed, buffer):
    """3막 — 비상기 우선권 삽입 결과를 실제 시퀀서로 계산한다."""
    trajectories = gen.sequenced_arrivals(flights, sq, seed=seed, spacing_buffer=buffer)
    shift = -min(tr.samples[0].t_s for tr in trajectories)
    trajectories = [
        synth.Trajectory(
            tr.callsign, tr.actype, tr.wake_cat,
            [replace(s, t_s=s.t_s + shift) for s in tr.samples], tr.dt_s,
        )
        for tr in trajectories
    ]

    # 비상 선언 시점과 대상 기체를 정한다.
    #
    # 우선권의 논지는 "순번을 앞당기되 이미 접근이 확정된 항적은 건드리지 않는다"이다.
    # 그것이 드러나려면 (가) 비상기가 대기열 뒤쪽에 밀려 있고 (나) 시단 16NM 안쪽에
    # 확정 항적이 여럿 있어야 한다. 대기열 중간의 기체를 고르면 우선권으로 얻을 것이
    # 없어 순번·시각이 그대로 나온다.
    cat = ds.fleet.wake_cat(EMERGENCY_TYPE)

    def snapshot(t, emergency_cs=None):
        out = []
        for tr in trajectories:
            s0 = tr.at(t)
            if s0 is None:
                continue
            if tr.callsign == emergency_cs:
                s0 = replace(s0, actype=EMERGENCY_TYPE, wake_cat=cat)
            out.append(s0)
        return out

    t_end = max(tr.samples[-1].t_s for tr in trajectories)
    best = None
    t = 0.0
    while t <= t_end:
        states0 = snapshot(t)
        if len(states0) < 8:
            t += 60.0
            continue
        frozen0 = [x for x in states0 if sq.distance_to_threshold_nm(x) <= 16.0]
        if len(frozen0) < 2:
            t += 60.0
            continue
        base = sq.build(states0, t)
        # 대기열 뒤쪽에서 아직 멀리 있는 후보들만 시험한다
        for slot in base.slots[len(base.slots) // 2:]:
            ac = next(x for x in states0 if x.callsign == slot.callsign)
            if sq.distance_to_threshold_nm(ac) < 25.0:
                continue
            trial_states = snapshot(t, ac.callsign)
            trial_before = sq.build(trial_states, t)
            trial_after = sq.insert_priority(trial_states, ac.callsign, now_s=t)
            saved = (trial_before.by_callsign(ac.callsign).threshold_time_s
                     - trial_after.by_callsign(ac.callsign).threshold_time_s)
            if saved <= 0:
                continue
            score = saved + len(frozen0) * 30.0
            if best is None or score > best[0]:
                best = (score, t, ac.callsign)
        t += 60.0

    if best is None:
        return None   # 이 시나리오에는 대기열이 없어 우선권 이득이 드러나지 않는다

    _, declared, subject_cs = best
    subject = next(tr for tr in trajectories if tr.callsign == subject_cs)

    # **선언 시점의 실제 상태**로 계산한다. 진입 시점 스냅샷으로 하면
    # 확정 항적이 하나도 없고 착륙 시각이 데모 타임라인과 어긋난다.
    states = snapshot(declared, subject_cs)

    before = sq.build(states, declared)
    after = sq.insert_priority(states, subject.callsign, now_s=declared)
    cmp_ = seq.compare(before, after, subject.callsign)

    def max_gap(sch):
        return max((b.threshold_time_s - a.threshold_time_s
                    for a, b in zip(sch.slots, sch.slots[1:], strict=False)), default=0.0)

    frozen = [
        s.callsign for s in before.slots
        if sq.distance_to_threshold_nm(
            next(x for x in states if x.callsign == s.callsign)) <= 16.0
    ]

    # 우선권 적용 스케줄을 실제로 날려 검증한다
    from sentry_atm.regulation.geo import vincenty_direct

    by = {x.callsign: x for x in states}
    violations, min_sep = 0, 99.0
    t = declared
    while t <= declared + after.makespan_s:
        flown = []
        for slot in after.slots:
            ac = by[slot.callsign]
            v = sq.final_gs_kt(ac)
            rem = (slot.threshold_time_s - t) / 3600.0 * v
            if rem <= 0:
                continue
            lat, lon = vincenty_direct(
                *sq.thr, (sq.final_course_deg + 180.0) % 360.0, rem * 1852.0)
            flown.append(replace(
                ac, lat=lat, lon=lon, alt_ft=sq.glidepath_altitude_ft(rem),
                track_deg=sq.final_course_deg, gs_kt=v, vs_fpm=0.0, target_alt_ft=None))
        violations += len(det.scan(flown, final_course_deg=sq.final_course_deg,
                                   landing_sequence=after.order))
        mine = [x for x in flown if det.sector.is_under_control(x)]
        for i, x in enumerate(mine):
            for y in mine[i + 1:]:
                min_sep = min(min_sep, separation_distance_nm(x.lat, x.lon, y.lat, y.lon))
        t += 20.0

    b = before.by_callsign(subject.callsign)
    a = after.by_callsign(subject.callsign)

    return {
        "airborne": len(states),
        "callsign": subject.callsign,
        "actype": EMERGENCY_TYPE,
        "tcas": ds.fleet.has_tcas(EMERGENCY_TYPE),
        "declared_t": round(declared, 1),
        "before": {"order": b.order + 1, "t": round(b.threshold_time_s, 1)},
        "after": {"order": a.order + 1, "t": round(a.threshold_time_s, 1)},
        "earliest_t": round(a.earliest_time_s, 1),
        "saved_s": round(cmp_.time_saved_s, 1),
        "displaced": cmp_.displaced,
        "mean_added_delay_s": round(cmp_.mean_added_delay_s, 1),
        "frozen": frozen,
        "max_gap_before_s": round(max_gap(before), 1),
        "max_gap_after_s": round(max_gap(after), 1),
        "violations": violations,
        "min_sep_nm": round(min_sep, 2),
        "order_before": before.order,
        "order_after": after.order,
        "clause": "2-1-4 가 — 조난 항공기 최우선 통행권",
    }


if __name__ == "__main__":
    raise SystemExit(main())
