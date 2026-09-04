"""시나리오 내보내기 — HMI 콘솔이 읽을 JSON 을 만든다.

    python tools/export_scenario.py [--out hmi/scenario.json]

전체 파이프라인을 시간축으로 돌려 프레임마다 항적·예외·근거·추천안을 기록한다.
콘솔은 이 파일만 읽으므로 브라우저에서 파이썬이 필요 없고, 외부 네트워크도
필요 없다 — 폐쇄망 반입 가능성의 근거다.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# 참조 데이터는 패키지 안에 있고(저장소 배치와 무관), 산출물은 artifacts/ 로 모은다.
REFERENCE = ROOT / "src" / "sentry_atm" / "regulation" / "reference"
ARTIFACTS = ROOT / "artifacts"
ARTIFACTS.mkdir(exist_ok=True)

from sentry_atm.api import geometry as api_geometry  # noqa: E402
from sentry_atm.regulation import conflict as cf  # noqa: E402
from sentry_atm.regulation import data as sdata  # noqa: E402
from sentry_atm.regulation import (  # noqa: E402
    mbe,  # noqa: E402
    synth,  # noqa: E402
)
from sentry_atm.regulation import resolution as res  # noqa: E402
from sentry_atm.regulation import sequencing as seq  # noqa: E402
from sentry_atm.regulation.geo import (  # noqa: E402
    bearing_true,
    separation_distance_nm,
)

FRAME_S = 10.0


def load_scorer(path):
    """학습된 예외 판정 모델. 없으면 None (콘솔이 규칙 판정으로 표시)."""
    import os
    import pickle

    if not os.path.exists(path):
        return None, None
    with open(path, "rb") as fh:
        blob = pickle.load(fh)
    return mbe.Scorer(blob["boosting"], "부스팅"), blob["thresholds"]


def airspace_geometry(ds, sq):
    """콘솔이 그릴 공역 형상 — 라이브러리와 같은 것을 쓴다.

    여기에 한 벌을 더 두면 정적 산출물과 실시간 콘솔이 서로 다른 공역을 그리게
    되고, 둘 다 그럴듯해서 어긋난 사실이 드러나지 않는다.
    """
    return api_geometry.airspace_geometry(ds, sq)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--flights", type=int, default=22)
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--buffer", type=float, default=1.9,
                    help="슬롯 계획 여유. 크면 예외가 예측 단계에서 잡힌다.")
    ap.add_argument("--emergency", default=None,
                    help="비상 선언 콜사인. 생략하면 마지막에서 세 번째 항적.")
    ap.add_argument("--mbe", default=str(ROOT / "models" / "mbe.pkl"))
    ap.add_argument("--predictor", default=str(ROOT / "models" / "predictor.pt"))
    ap.add_argument("--out", default=str(ARTIFACTS / "scenario.json"))
    args = ap.parse_args()

    ds = sdata.load()
    det = cf.build(ds)
    sq = seq.build(ds)
    resolver = res.build(ds)
    gen = synth.build(ds)

    unc = mbe.build_uncertainty_from_checkpoint(args.predictor)
    resolver.uncertainty = unc
    scorer, thresholds = load_scorer(args.mbe)
    fb = mbe.FeatureBuilder(det, unc)

    print(f"항적 {args.flights}대 생성 중…")
    trajectories = gen.sequenced_arrivals(
        args.flights, sq, seed=args.seed, spacing_buffer=args.buffer)
    {tr.callsign: tr for tr in trajectories}

    emergency_cs = args.emergency or trajectories[-3].callsign
    print(f"비상 선언 항적 — {emergency_cs}")

    # 시간축을 0 부터 시작하도록 정규화한다 — 콘솔 슬라이더가 읽기 쉬워진다
    shift = -min(tr.samples[0].t_s for tr in trajectories)
    trajectories = [
        synth.Trajectory(
            tr.callsign, tr.actype, tr.wake_cat,
            [__import__("dataclasses").replace(s_, t_s=s_.t_s + shift)
             for s_ in tr.samples],
            tr.dt_s,
        )
        for tr in trajectories
    ]
    {tr.callsign: tr for tr in trajectories}

    t0 = min(tr.samples[0].t_s for tr in trajectories)
    t1 = max(tr.samples[-1].t_s for tr in trajectories)
    print(f"시간축 {t0:.0f}s ~ {t1:.0f}s ({(t1 - t0) / 60:.0f}분), "
          f"프레임 {int((t1 - t0) / FRAME_S) + 1}개")

    frames = []
    exceptions: dict[str, dict] = {}
    events: list[dict] = []
    prev_owner: dict[str, str] = {}

    t = t0
    while t <= t1:
        live = []
        for tr in trajectories:
            s = tr.at(t)
            if s is not None:
                live.append(s)

        mine = [a for a in live if det.sector.is_under_control(a)]

        # --- 관제이양 이벤트 (고시 2-1-15) ---
        for a in live:
            owner = det.sector.owner(a)
            if prev_owner.get(a.callsign) not in (None, owner):
                events.append({
                    "t": round(t, 1), "kind": "HANDOFF", "callsign": a.callsign,
                    "text": f"{a.callsign} {prev_owner[a.callsign]} → {owner}",
                    "alt_ft": round(a.alt_ft),
                })
            prev_owner[a.callsign] = owner

        # --- 예외 판정 ---
        levels: dict[str, str] = {}
        pair_rows = []
        for i, a in enumerate(mine):
            for b in mine[i + 1:]:
                std = det.rules.separation_standard(a, b)
                f = fb.build(a, b)
                score = scorer.score([f])[0] if scorer else f[0]
                level = (
                    thresholds.level(score, a.emergency or b.emergency)
                    if thresholds
                    else ("위험" if score > 0.5 else "정상")
                )
                if level == "정상":
                    continue

                window = cf.pair_conflict(a, b, std.horizontal_nm, std.vertical_ft,
                                          det.lookahead_s)
                key = f"{min(a.callsign, b.callsign)}|{max(a.callsign, b.callsign)}"
                row = {
                    "key": key,
                    "pair": [a.callsign, b.callsign],
                    "level": level,
                    "score": round(score, 4),
                    "evidence": {
                        "sep_nm": round(separation_distance_nm(a.lat, a.lon, b.lat, b.lon), 2),
                        "sep_ft": round(abs(a.alt_ft - b.alt_ft)),
                        "cpa_nm": round(f[1], 2),
                        "cpa_ft": round(f[2]),
                        "t_cpa_s": round(f[3]),
                        "ttv_s": round(f[7]) if f[7] < 9000 else None,
                        "collision_prob": round(f[0], 3),
                        "sigma_nm": round(unc.sigma_at(min(f[3], 600.0))[0], 2),
                        "h_min_nm": std.horizontal_nm,
                        "v_min_ft": std.vertical_ft,
                    },
                    "clauses": list(std.clauses),
                }
                pair_rows.append(row)
                for cs in (a.callsign, b.callsign):
                    if levels.get(cs) != "비상":
                        levels[cs] = (
                            "위험" if level == "위험" or levels.get(cs) == "위험"
                            else level
                        )

                # 위험 단계만 회피안을 만들어 상신한다
                if level in ("위험", "비상") and key not in exceptions:
                    options = []
                    for r in resolver.resolve(window and row and cf.Conflict(
                        kind=cf.ConflictKind.RADAR, first=a.callsign, second=b.callsign,
                        clauses=std.clauses, rationale=std.rationale, window=window,
                    ), mine, final_course_deg=sq.final_course_deg) if window else []:
                        subject = a if r.maneuver.callsign == a.callsign else b
                        options.append({
                            "callsign": r.maneuver.callsign,
                            "kind": r.maneuver.kind,
                            "delta": r.maneuver.delta,
                            "instruction": r.maneuver.instruction(
                                subject, ds.procedures.mag_var),
                            "cost": round(r.cost, 2),
                            "rationale": r.rationale,
                        })
                    violating = (
                        row["evidence"]["sep_nm"] < std.horizontal_nm
                        and row["evidence"]["sep_ft"] < std.vertical_ft
                    )
                    exceptions[key] = {
                        "key": key, "raised_t": round(t, 1), "pair": row["pair"],
                        "level": level, "score": row["score"],
                        "evidence": row["evidence"], "clauses": row["clauses"],
                        "options": options,
                        "state": "위반 중" if violating else "예측",
                        "lead_s": (
                            None if violating else row["evidence"]["ttv_s"]
                        ),
                        "no_option_reason": (
                            None if options else (
                                "이미 분리위반 상태 — 단일 관제 지시로 해소되지 않는다. "
                                "슬롯 재배정 또는 관제사 직접 판단이 필요하다."
                                if violating else
                                "성능·절차 한계와 2차 충돌 재검증을 통과하는 안이 없다."
                            )
                        ),
                    }

        frames.append({
            "t": round(t, 1),
            "aircraft": [
                {
                    "cs": a.callsign,
                    "lat": round(a.lat, 6),
                    "lon": round(a.lon, 6),
                    "alt": round(a.alt_ft),
                    "gs": round(a.gs_kt),
                    "trk": round(a.track_deg, 1),
                    "vs": round(a.vs_fpm),
                    "type": a.actype,
                    "wake": a.wake_cat,
                    "dist": round(separation_distance_nm(a.lat, a.lon, *sq.thr), 2),
                    "brg": round(bearing_true(*sq.thr, a.lat, a.lon), 1),
                    "mine": det.sector.is_under_control(a),
                    "owner": det.sector.owner(a),
                    "level": ("비상" if a.callsign == emergency_cs
                              else levels.get(a.callsign, "정상")),
                }
                for a in live
            ],
            "pairs": pair_rows,
        })
        t += FRAME_S

    # --- 착륙 순서 ---
    # 항적이 실제로 시단을 통과하는 시각으로 순서를 만든다. 마지막 샘플만 모아
    # sq.build 를 돌리면 전부 시단 근처라 도달시각이 0 부근으로 뭉쳐, 데모
    # 타임라인과 전혀 다른 표가 나온다.
    landing = sorted(trajectories, key=lambda tr: tr.samples[-1].t_s)
    # --- 착륙순서 최적화 (순번 이동 제한별 효과) ---
    #
    # 같은 항공기 집합이라도 순서에 따라 총 소요가 달라진다 — 항적난기류 요건이
    # 선행·후행 등급 조합으로 정해지기 때문이다(고시 5-5-4 사·아항).
    # 가장 붐비는 시점의 도착 흐름을 잡아 제한별로 계산한다.
    busiest_t, busiest = None, []
    tt = t0
    while tt <= t1:
        alive = [x for x in (tr.at(tt) for tr in trajectories) if x is not None]
        if len(alive) > len(busiest):
            busiest, busiest_t = alive, tt
        tt += FRAME_S

    # --- 도착 흐름 디컨플릭션 (슬롯 재배정) ---
    #
    # 1막의 평온함은 공짜가 아니다. 간격 조정이 없으면 같은 항적 집합이
    # 여러 쌍에서 분리위반을 낸다. 그것을 **측방 오프셋이 아니라 슬롯 재배정**으로
    # 푸는 것이 이 체계의 설계다 — 오프셋은 국소 조치라 준 기체가 옆 기체와
    # 새 충돌을 만들며 발산한다.
    deconfliction = None
    if len(busiest) >= 5:
        naive = sq.build_unsequenced(busiest, busiest_t)
        before_pairs = resolver.scan_schedule(sq, busiest, naive, busiest_t)
        fixed, log, rounds = resolver.deconflict_arrival_stream(
            busiest, sq, now_s=busiest_t, initial=naive
        )
        after_pairs = resolver.scan_schedule(sq, busiest, fixed, busiest_t)
        deconfliction = {
            "t": round(busiest_t, 1),
            "n_aircraft": len(busiest),
            "before_violations": len(before_pairs),
            "after_violations": len(after_pairs),
            "rounds": rounds,
            "before_mean_gap_s": round(naive.mean_gap_s, 1),
            "after_mean_gap_s": round(fixed.mean_gap_s, 1),
            "before_delay_min": round(naive.total_delay_s / 60.0, 1),
            "after_delay_min": round(fixed.total_delay_s / 60.0, 1),
            "samples": [
                {"t": round(t_, 1), "text": c.describe()}
                for c, t_ in before_pairs[:3]
            ],
            "log": log,
        }

    ordering = None
    if len(busiest) >= 4:
        rows = []
        base_gap = None
        shift_map = {}
        for k in (0, 1, 2, 3):
            r = seq.optimize_order(sq, busiest, max_shift=k, now_s=busiest_t)
            if k == 0:
                base_gap = r.mean_gap_s
            if k == 1:
                shift_map = {cs: v for cs, v in r.shifts().items() if v}
            rows.append({
                "max_shift": k,
                "mean_gap_s": round(r.mean_gap_s, 1),
                "completion_s": round(r.completion_s, 1),
                "swaps": r.swaps,
                "gain": round((base_gap - r.mean_gap_s) / base_gap, 4) if base_gap else 0.0,
                "order": r.order,
            })
        best = rows[-1]["mean_gap_s"]
        one = rows[1]["mean_gap_s"]
        ordering = {
            "t": round(busiest_t, 1),
            "n_aircraft": len(busiest),
            "rows": rows,
            "captured_by_one": (
                round((base_gap - one) / (base_gap - best), 3)
                if base_gap and base_gap > best else None
            ),
            "shifts": shift_map,
            "clause": "5-5-4 사·아항 (등급 조합별 종렬), 2-1-4 (선착순 원칙)",
        }

    schedule_rows = []
    prev = None
    for i, tr in enumerate(landing):
        last = tr.samples[-1]
        gap = sq.gap_requirement(prev.samples[-1], last) if prev else None
        schedule_rows.append({
            "order": i + 1,
            "cs": tr.callsign,
            "type": tr.actype,
            "wake": tr.wake_cat,
            "t": round(last.t_s, 1),
            "alt": sq.rules.assigned_altitude_ft(i),
            "holding": sq.rules.ladder_exhausted(i),
            "gap_s": round(gap.seconds) if gap else None,
            "gap_nm": gap.required_nm if gap else None,
            "gap_why": gap.rationale if gap else None,
            "gap_clauses": list(gap.clauses) if gap else [],
            "actual_gap_s": (
                round(last.t_s - prev.samples[-1].t_s) if prev else None
            ),
        })
        prev = tr

    payload = {
        "meta": {
            "airport": "RKTU 청주",
            "runway": "24R",
            "approach": "RNP RWY 24R",
            "sector": ds.airspace.target_sector["id"],
            "unit": ds.airspace.target_sector["unit"],
            "frame_s": FRAME_S,
            "t0": round(t0, 1),
            "t1": round(t1, 1),
            "emergency": emergency_cs,
            "sigma_10min_nm": round(unc.sigma_at(600.0)[0], 2),
            "scorer": "학습 (부스팅)" if scorer else "규칙 (충돌확률)",
            "thresholds": (
                {"caution": round(thresholds.caution, 4),
                 "danger": round(thresholds.danger, 4),
                 "escalation_rate": thresholds.escalation_rate,
                 "caution_recall": thresholds.caution_recall}
                if thresholds else None
            ),
            "separation": {
                "horizontal_nm": ds.airspace.sep_horizontal_nm,
                "vertical_ft": ds.airspace.sep_vertical_ft,
            },
        },
        "geometry": airspace_geometry(ds, sq),
        "frames": frames,
        "exceptions": list(exceptions.values()),
        "events": events,
        "schedule": schedule_rows,
        "ordering": ordering,
        "deconfliction": deconfliction,
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                   encoding="utf-8")
    size = out.stat().st_size / 1024
    print(f"\n프레임 {len(frames)}개, 예외 {len(exceptions)}건, 이벤트 {len(events)}건")
    try:
        shown = out.relative_to(ROOT)
    except ValueError:
        shown = out
    print(f"저장 — {shown} ({size:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
