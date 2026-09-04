"""소티 시나리오 내보내기 — 출격에서 정상 운항 복귀까지 13단계.

    python tools/build_sortie_demo.py [--out hmi/scenario_sortie.json]

기존 `export_scenario.py` 는 도착 한 단면을 낸다. 이쪽은 활주로를 공유하는
출발·도착·군 소티를 함께 놓고, 시간표에 맞춰 항적을 배치한 뒤 비상복귀까지
흐르게 한다. 공역 형상과 예외 판정은 기존 도구의 함수를 그대로 쓴다 —
같은 판정을 두 벌로 만들지 않기 위해서다.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# 참조 데이터는 패키지 안에 있고(저장소 배치와 무관), 산출물은 artifacts/ 로 모은다.
REFERENCE = ROOT / "src" / "sentry_atm" / "regulation" / "reference"
ARTIFACTS = ROOT / "artifacts"
ARTIFACTS.mkdir(exist_ok=True)
sys.path.insert(0, str(ROOT / "tools"))

import export_scenario as ex  # noqa: E402

from sentry_atm.regulation import conflict as cf  # noqa: E402
from sentry_atm.regulation import data as sdata  # noqa: E402
from sentry_atm.regulation import handoff as ho  # noqa: E402
from sentry_atm.regulation import (  # noqa: E402
    mbe,  # noqa: E402
    synth,  # noqa: E402
)
from sentry_atm.regulation import resolution as res  # noqa: E402
from sentry_atm.regulation import schedule as sched_mod  # noqa: E402
from sentry_atm.regulation import sequencing as seq  # noqa: E402
from sentry_atm.regulation import sortie as sortie_mod  # noqa: E402
from sentry_atm.regulation.geo import separation_distance_nm, vincenty_direct  # noqa: E402
from sentry_atm.scenario import sortie_builder as sortie_scenario  # noqa: E402

FRAME_S = ex.FRAME_S
M_PER_NM = 1852.0

# 한 항적에 여러 쌍 판정이 걸리면 더 높은 등급이 남아야 한다.
LEVEL_ORDER = {"정상": 0, "주의": 1, "위험": 2, "비상": 3}


# ----------------------------------------------------------------------
# 항적 배치
# ----------------------------------------------------------------------


def runway_events(sc):
    """실제로 활주로를 쓰는 사건 전부 — (기체, 확정 시각).

    라이브러리와 같은 것을 쓴다. 여기에 한 벌을 더 두면 시연용 산출물과 시뮬레이터
    시나리오가 서로 다른 활주로 순서를 갖게 되고, 둘 다 그럴듯해서 어긋난 사실이
    드러나지 않는다.
    """
    return sortie_scenario._runway_events(sc)


def make_trajectories(ds, gen, sq, events, rng):
    """활주로 사건마다 항적 하나. 같은 콜사인이 두 번 나올 수 있다."""
    return [
        (f"{op.callsign}:{'D' if is_departure else 'A'}", track)
        for op, is_departure, track in sortie_scenario._make_tracks(
            ds, gen, events, rng
        )
    ]


# ----------------------------------------------------------------------
# 부가 형상
# ----------------------------------------------------------------------


def hold_geometry(pattern, book):
    """체공 장주를 스코프에 그릴 좌표로.

    경주로형 장주 — 인바운드 구간, 180° 선회, 아웃바운드 구간, 180° 선회.
    선회는 반원으로 근사한다(반경 = 장주 길이 / π 가 아니라 표준선회 반경).
    """
    inb = pattern.inbound_course_true
    fix = (pattern.lat, pattern.lon)
    leg_m = pattern.leg_nm * M_PER_NM
    # 인바운드는 픽스로 들어오는 방향이므로, 아웃바운드 시작점은 그 반대편
    back = (inb + 180.0) % 360.0
    side = 1.0 if pattern.right_turns else -1.0
    turn_r_nm = pattern.leg_nm / 4.0
    off = (inb + 90.0 * side) % 360.0

    a = fix
    b = vincenty_direct(*fix, back, leg_m)
    c = vincenty_direct(*b, off, 2 * turn_r_nm * M_PER_NM)
    d = vincenty_direct(*c, inb, leg_m)
    pts = [a, b]
    # 반원 두 개를 각각 8분할해 이어 붙인다
    for start, centre_brg in ((b, off), (d, (off + 180.0) % 360.0)):
        centre = vincenty_direct(*start, centre_brg, turn_r_nm * M_PER_NM)
        base = (centre_brg + 180.0) % 360.0
        for k in range(1, 9):
            ang = (base + side * 180.0 * k / 8.0) % 360.0
            pts.append(vincenty_direct(*centre, ang, turn_r_nm * M_PER_NM))
    pts.append(a)
    return [[round(p[0], 6), round(p[1], 6)] for p in pts]


def area_geometry(area):
    return {
        "id": area.id,
        "points": [[round(p[0], 6), round(p[1], 6)] for p in area.volume.polygon],
        "lower_ft": round(area.lower_ft),
        "upper_ft": round(area.upper_ft),
        "centre": [round(area.centroid[0], 6), round(area.centroid[1], 6)],
    }


def route_geometry(route):
    if route is None:
        return None
    return {
        "fixes": route.fixes,
        "points": [[round(route.origin[0], 6), round(route.origin[1], 6)]]
        + [[round(x.lat, 6), round(x.lon, 6)] for x in route.legs],
        "total_nm": round(route.total_nm, 2),
        "detour_nm": round(route.detour_nm, 2),
    }


ACT_GROUPS = (
    (1, "평시", (1, 2), "민항과 군이 같은 활주로를 나눠 쓴다",
     "시간표에 맞춰 도착·출발이 교대로 활주로를 쓰고, 작전지역이 지정된다."),
    (2, "출격", (3, 4, 5, 6), "출격 비용은 도착 흐름에서 치러진다",
     "전투기가 민항 슬롯 사이로 이륙해 SID 를 타고 나가며 관제권이 순차 이양된다."),
    (3, "비상복귀", (7, 8, 9, 10), "판단이 필요한 것만 근거와 함께 상신한다",
     "TCAS 미장착 전투기가 비상 선언, 최단 복귀경로가 도착 흐름과 경합한다."),
    (4, "우선착륙", (11, 12, 13), "순번이 아니라 물리적 최단 도달시각",
     "공고 체공장주로 민항을 붙들고 비상기를 먼저 내린 뒤 순서를 재구성한다."),
)


def _acts_from_steps(steps, shift, t1):
    """13단계를 4막으로 묶는다.

    기존 콘솔이 `acts` 를 읽으므로 스키마를 유지하면서, 단계별 상세는
    `steps` 에 따로 실어 화면이 둘 다 쓸 수 있게 한다.
    """
    by_n = {s.n: s for s in steps}
    out = []
    for n, name, members, headline, text in ACT_GROUPS:
        got = [by_n[m] for m in members if m in by_n]
        if not got:
            continue
        t0 = min(s.t_s for s in got) + shift
        out.append({
            "n": n, "name": name,
            "t0": round(t0, 1), "t1": 0.0,
            "headline": headline,
            "text": text,
            "steps": [s.n for s in got],
        })
    for i, a in enumerate(out):
        a["t1"] = round(out[i + 1]["t0"] if i + 1 < len(out) else t1, 1)
    return out


def _schedule_rows(sc, shift):
    """활주로 일정 전체 — 계획(with_sortie)에 비상 후 재배치(final) 결과를 얹는다.

    `final` 만 내보내면 비상 이후 잔여분만 남아 앞 구간이 통째로 사라진다.
    재배치로 시각이 바뀐 항적은 `resequenced` 로 표시해 화면에서 구분한다.
    """
    final_by = {s.op.callsign: s for s in sc.final.slots}
    rows = []
    slots = list(sc.with_sortie.slots)
    emg = final_by.get(sc.fighter_callsign)
    if emg is not None and not emg.op.is_departure:
        slots.append(emg)
    for slot in slots:
        f = final_by.get(slot.op.callsign)
        moved = f is not None and f.op.op is slot.op.op and abs(f.time_s - slot.time_s) > 1.0
        t = f.time_s if (f is not None and f.op.op is slot.op.op) else slot.time_s
        req = slot.requirement
        rows.append({
            "cs": slot.op.callsign, "type": slot.op.actype, "wake": slot.op.wake_cat,
            "op": slot.op.op.value,
            "t": round(t + shift, 1),
            "planned_t": round(slot.op.earliest_s + shift, 1),
            "delay_s": round(t - slot.op.earliest_s, 1),
            "resequenced": bool(moved),
            "emergency": bool(slot.op.emergency),
            "binding": req.binding if req else "",
            "clauses": list(req.clauses) if req else [],
            "req_s": round(req.seconds, 1) if req else 0,
            "luaw": bool(req and req.luaw_prohibited),
        })
    rows.sort(key=lambda r: r["t"])
    return rows


# ----------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--window", nargs=2, default=("09:00", "10:00"))
    ap.add_argument("--seed", type=int, default=4)
    ap.add_argument("--area", default="MOA 3A")
    ap.add_argument("--patrol", type=int, default=3)
    ap.add_argument("--schedule", default=str(REFERENCE / "schedule.json"))
    ap.add_argument("--mbe", default=str(ROOT / "models" / "mbe.pkl"))
    ap.add_argument("--predictor", default=str(ROOT / "models" / "predictor.pt"))
    ap.add_argument("--out", default=str(ARTIFACTS / "scenario_sortie.json"))
    args = ap.parse_args()

    ds = sdata.load()
    det = cf.build(ds)
    sq = seq.build(ds)
    gen = synth.build(ds)
    resolver = res.build(ds)
    chain = ho.build(ds, det.sector)
    rng = random.Random(args.seed)

    # --- 시간표와 13단계 ---
    timetable = sched_mod.build(
        ds, path=args.schedule, window=tuple(args.window), seed=args.seed
    )
    sc = sortie_mod.build(
        ds, timetable, area_id=args.area, patrol_sorties=args.patrol
    )
    steps = sc.build()
    print(timetable.provenance())
    for s in steps:
        print("  " + s.describe())

    # --- 항적 ---
    print("\n항적 생성 중…")
    events_rw = runway_events(sc)
    tracks = make_trajectories(ds, gen, sq, events_rw, rng)
    print(f"  활주로 사건 {len(events_rw)}건 → 항적 {len(tracks)}개")

    # 시간축을 0 부터 — 콘솔 슬라이더가 읽기 쉽다
    shift = -min(tr.samples[0].t_s for _, tr in tracks)
    tracks = [
        (key, synth.Trajectory(
            tr.callsign, tr.actype, tr.wake_cat,
            [replace(s, t_s=s.t_s + shift) for s in tr.samples], tr.dt_s,
        ))
        for key, tr in tracks
    ]
    t0 = min(tr.samples[0].t_s for _, tr in tracks)
    t1 = max(tr.samples[-1].t_s for _, tr in tracks)

    # --- 예외 판정 재료 ---
    unc = mbe.build_uncertainty_from_checkpoint(args.predictor)
    resolver.uncertainty = unc
    scorer, thresholds = ex.load_scorer(args.mbe)
    fb = mbe.FeatureBuilder(det, unc)

    frames, events = [], []
    exceptions: dict[str, dict] = {}
    prev_unit: dict[str, str] = {}
    t = t0
    while t <= t1:
        # (키, 상태) — 같은 콜사인의 출격·복귀를 구분하기 위해 키를 함께 든다
        live_keyed = [(k, s) for k, tr in tracks if (s := tr.at(t)) is not None]
        live = [s for _, s in live_keyed]

        for key, a in live_keyed:
            unit = chain.controller(a)
            if prev_unit.get(key) not in (None, unit):
                events.append({
                    "t": round(t, 1), "kind": "HANDOFF", "callsign": a.callsign,
                    "text": f"{a.callsign} {prev_unit[key]} → {unit}",
                    "alt_ft": round(a.alt_ft),
                })
            prev_unit[key] = unit

        mine = [a for a in live if det.sector.is_under_control(a)]
        levels: dict[str, str] = {}
        pair_rows = []
        for i, a in enumerate(mine):
            for b in mine[i + 1:]:
                std = det.rules.separation_standard(a, b)
                f = fb.build(a, b)
                score = scorer.score([f])[0] if scorer else f[0]
                level = (
                    thresholds.level(score, a.emergency or b.emergency)
                    if thresholds else ("위험" if score > 0.5 else "정상")
                )
                if level == "정상":
                    continue
                pair_rows.append({
                    "key": f"{min(a.callsign, b.callsign)}|{max(a.callsign, b.callsign)}",
                    "pair": [a.callsign, b.callsign],
                    "level": level, "score": round(score, 4),
                    "evidence": {
                        "sep_nm": round(
                            separation_distance_nm(a.lat, a.lon, b.lat, b.lon), 2),
                        "sep_ft": round(abs(a.alt_ft - b.alt_ft)),
                        "cpa_nm": round(f[1], 2), "cpa_ft": round(f[2]),
                        "t_cpa_s": round(f[3]),
                        "ttv_s": round(f[7]) if f[7] < 9000 else None,
                        "collision_prob": round(f[0], 3),
                        "sigma_nm": round(unc.sigma_at(min(f[3], 600.0))[0], 2),
                        "h_min_nm": std.horizontal_nm, "v_min_ft": std.vertical_ft,
                    },
                    "clauses": list(std.clauses),
                })
                for cs in (a.callsign, b.callsign):
                    if LEVEL_ORDER.get(level, 0) > LEVEL_ORDER.get(
                        levels.get(cs, "정상"), 0
                    ):
                        levels[cs] = level

                row = pair_rows[-1]
                key = row["key"]
                if level in ("위험", "비상") and key not in exceptions:
                    window = cf.pair_conflict(
                        a, b, std.horizontal_nm, std.vertical_ft, det.lookahead_s)
                    options = []
                    if window is not None:
                        conflict = cf.Conflict(
                            kind=cf.ConflictKind.RADAR,
                            first=a.callsign, second=b.callsign,
                            clauses=std.clauses, rationale=std.rationale,
                            window=window,
                        )
                        for r in resolver.resolve(
                            conflict, mine, final_course_deg=sq.final_course_deg
                        ):
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
                        "lead_s": None if violating else row["evidence"]["ttv_s"],
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
            "pairs": pair_rows,
            "aircraft": [{
                "cs": a.callsign, "lat": round(a.lat, 6), "lon": round(a.lon, 6),
                "alt": round(a.alt_ft), "gs": round(a.gs_kt), "trk": round(a.track_deg, 1),
                "vs": round(a.vs_fpm), "type": a.actype, "wake": a.wake_cat,
                "dep": key.endswith(":D"),
                "unit": chain.controller(a), "owner": chain.controller(a),
                "mine": det.sector.is_under_control(a),
                "level": "비상" if a.emergency else levels.get(a.callsign, "정상"),
            } for key, a in live_keyed],
        })
        t += FRAME_S

    # --- 부가 형상 ---
    geometry = ex.airspace_geometry(ds, sq)
    geometry["operating_area"] = area_geometry(sc.sortie.area)
    geometry["holds"] = [
        {
            "fix": p.fix,
            "points": hold_geometry(p, sc.holding),
            "alt_ft": round(p.alt_ft),
            "max_alt_ft": round(p.max_alt_ft) if p.max_alt_ft else None,
            "levels": [round(x) for x in sc.holding.levels(p)],
        }
        for p in sc.holding.patterns
    ]
    geometry["recovery_route"] = route_geometry(sc.recovery_route)

    payload = {
        "meta": {
            "airport": "RKTU 청주", "runway": "24R", "approach": "RNP RWY 24R",
            "sector": "T17", "unit": "CHEONGJU GCA", "frame_s": FRAME_S,
            "t0": round(t0, 1), "t1": round(t1, 1),
            "window": list(args.window),
            "timetable": {
                "synthetic": timetable.synthetic,
                "provenance": timetable.provenance(),
                "movements_per_hour": round(timetable.movements_per_hour(), 1),
            },
            "mission": {
                "callsign": sc.fighter_callsign, "actype": sc.fighter_type,
                "area": sc.sortie.area.id, "kind": sc.sortie.kind.value,
                "tcas": ds.fleet.has_tcas(sc.fighter_type),
                "takeoff_s": sc.sortie.takeoff_s,
                "on_station_s": sc.sortie.on_station_s,
                "recovery_s": sc.sortie.recovery_declared_s,
                "landed_s": sc.sortie.landed_s,
            },
            "shift_s": shift,
            # 기존 콘솔이 헤더·각주에서 읽는 값들 — 스키마를 맞춰 둔다
            "separation": {
                "horizontal_nm": ds.airspace.sep_horizontal_nm,
                "vertical_ft": ds.airspace.raw["separation"]["vertical"]["below_fl410_ft"],
            },
            "scorer": "학습 (부스팅)" if scorer else "규칙",
            "sigma_10min_nm": round(unc.sigma_at(600.0)[0], 2),
            "thresholds": None if thresholds is None else {
                "caution": round(thresholds.caution, 4),
                "danger": round(thresholds.danger, 4),
                "escalation_rate": thresholds.escalation_rate,
                "caution_recall": thresholds.caution_recall,
            },
        },
        "acts": _acts_from_steps(steps, shift, t1),
        "steps": [{
            "n": s.n, "t": round(s.t_s + shift, 1), "clock": s.hhmm(),
            "name": s.name, "detail": s.detail, "clauses": list(s.clauses),
        } for s in steps],
        "handoff_chain": [{
            "unit": s.unit, "lower_ft": round(s.lower_ft),
            "upper_ft": None if s.upper_ft == float("inf") else round(s.upper_ft),
            "source": s.source,
        } for s in chain.steps] + [
            {"unit": chain.lateral_unit, "lower_ft": None, "upper_ft": None,
             "source": "측방 (T19)"}
        ],
        "runway_schedule": _schedule_rows(sc, shift),
        "holds": [{
            "cs": h.callsign, "fix": h.pattern.fix, "level_ft": round(h.level_ft),
            "circuits": h.circuits, "delay_s": round(h.delay_s, 1),
            "efc_s": None if h.efc_s is None else round(h.efc_s + shift, 1),
            "phraseology": h.phraseology(),
        } for h in sc.holds],
        "hold_refused": list(sc.hold_refused),
        "exceptions": sorted(exceptions.values(), key=lambda e: e["raised_t"]),
        "frames": frames,
        "events": events,
        "geometry": geometry,
    }

    out = Path(args.out)
    out.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    kb = out.stat().st_size / 1024
    print(f"\n{out} — {kb:.0f} KB, 프레임 {len(frames)}개, 이양 {len(events)}건")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
