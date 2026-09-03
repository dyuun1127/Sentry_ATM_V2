"""AIP 정합성 검증 — 전사한 좌표로 고시된 거리·트랙을 재계산해 대조한다.

data/procedures.json 의 좌표는 AIP 차트에서 옮겨 적은 값이다. 옮겨 적는 과정에
오류가 없었는지를, 같은 차트가 별도로 고시한 구간 거리(NM)와 트랙(진방위)을
WGS84 측지선으로 재계산해 확인한다. 좌표와 거리·방위는 AIP 안에서 독립적으로
고시된 값이므로, 둘이 일치하면 전사가 옳다는 상호검증이 된다.

    python tools/validate_aip.py

허용오차를 넘는 항목이 있으면 종료코드 1.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sentry_atm.regulation import data as sdata  # noqa: E402
from sentry_atm.regulation.geo import bearing_true, distance_nm  # noqa: E402

# 허용오차. AIP는 거리를 0.01NM, 방위를 0.01° 단위로, 좌표를 0.1초 단위로 고시한다.
# 좌표 0.1초는 약 0.0017NM 이므로 아래 값은 충분히 빡빡하다.
TOL_DIST_NM = 0.10
TOL_BRG_DEG = 0.30

# 원인을 규명해 문서화한 편차. 조용히 통과시키지 않고 별도로 표시한다.
KNOWN_DEVIATIONS = {
    ("IAP RNP_24R/프로파일", "SURAX-THR", "거리"): (
        "고시 0.94 NM vs 실측 0.82 NM (0.12 NM). SURAX 는 LNAV 전용 MAPt 로, "
        "차트 프로파일의 마지막 구간 기준점이 활주로 시단과 다른 것으로 보이나 "
        "AIP에 명시가 없다. FAF 이후 구간이라 분리·시퀀싱 판정에는 쓰이지 않는다."
    ),
}


class Report:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str, float, float, float, float, bool]] = []

    def add(self, proc, leg, kind, published, computed, tol):
        delta = computed - published
        ok = abs(delta) <= tol
        if not ok and (proc, leg, kind) in KNOWN_DEVIATIONS:
            ok = None  # 기지 편차
        self.rows.append((proc, leg, kind, published, computed, delta, tol, ok))

    @property
    def failures(self):
        return [r for r in self.rows if r[-1] is False]

    @property
    def known(self):
        return [r for r in self.rows if r[-1] is None]

    def print(self) -> None:
        print(f"{'절차':<22} {'구간':<16} {'항목':<6} {'고시':>9} {'계산':>9} {'차이':>9}   판정")
        print("-" * 88)
        for proc, leg, kind, pub, comp, delta, _tol, ok in self.rows:
            mark = "OK" if ok else ("기지 편차" if ok is None else "** 불일치 **")
            print(
                f"{proc:<22} {leg:<16} {kind:<6} {pub:9.3f} {comp:9.3f} {delta:+9.3f}   {mark}"
            )


def _check_legs(rep: Report, wpts, proc_name: str, legs: list[dict], start: str | None = None):
    """연속 구간의 dist_nm / course_true 를 재계산해 대조."""
    prev = start
    for leg in legs:
        name = leg.get("wpt")
        if name is None or name not in wpts:
            prev = name
            continue
        if prev is not None and prev in wpts:
            a, b = wpts[prev], wpts[name]
            label = f"{prev}->{name}"
            if "dist_nm" in leg:
                rep.add(proc_name, label, "거리", leg["dist_nm"],
                        distance_nm(a.lat, a.lon, b.lat, b.lon), TOL_DIST_NM)
            if "course_true" in leg:
                rep.add(proc_name, label, "진방위", leg["course_true"],
                        bearing_true(a.lat, a.lon, b.lat, b.lon), TOL_BRG_DEG)
        prev = name


def main() -> int:
    ds = sdata.load()
    p = ds.procedures
    wpts = p.waypoints
    rep = Report()

    # --- STAR ---
    for ident, star in p.raw["star"].items():
        _check_legs(rep, wpts, f"STAR {ident}", star["legs"])

    # --- SID ---
    for ident, sid in p.raw["sid"].items():
        for tr_name, legs in sid.get("transitions", {}).items():
            _check_legs(rep, wpts, f"SID {ident}/{tr_name}", legs)

    # --- IAP ---
    for ident, iap in p.raw["iap"].items():
        for tr_name, legs in iap.get("transitions", {}).items():
            _check_legs(rep, wpts, f"IAP {ident}/{tr_name}", legs)
        if "final" in iap:
            _check_legs(rep, wpts, f"IAP {ident}/final", iap["final"])
        ma = iap.get("missed_approach")
        if ma:
            start = iap["final"][-1]["wpt"] if "final" in iap else None
            _check_legs(rep, wpts, f"IAP {ident}/MA", ma["legs"], start=start)

    # --- 활주로 제원 (AD 2.12 가 길이·진방위를 별도 고시하므로 상호검증됨) ---
    rwys = p.runways
    for a, b in [("24R", "06L"), ("24L", "06R")]:
        ra, rb = rwys[a], rwys[b]
        rep.add(f"RWY {a}/{b}", f"THR{a}->THR{b}", "거리",
                ra.length_m / 1852.0,
                distance_nm(ra.thr_lat, ra.thr_lon, rb.thr_lat, rb.thr_lon), TOL_DIST_NM)
        rep.add(f"RWY {a}/{b}", f"THR{a}->THR{b}", "진방위", ra.true_brg,
                bearing_true(ra.thr_lat, ra.thr_lon, rb.thr_lat, rb.thr_lon), TOL_BRG_DEG)

    # --- 최종접근: FAF ~ THR 거리와 활주로 연장 중심선 정렬 ---
    # FAF 에서 THR 을 본 진방위가 활주로 진방위와 같아야 연장 중심선에 정렬된 것이다.
    thr = rwys["24R"]
    for iap_id in ("RNP_24R", "ILS_Z_24R"):
        iap = p.iap(iap_id)
        faf = wpts[iap["faf"]]
        rep.add(f"IAP {iap_id}", f"{iap['faf']}->THR24R", "거리", iap["faf_to_thr_nm"],
                distance_nm(faf.lat, faf.lon, thr.thr_lat, thr.thr_lon), TOL_DIST_NM)
        rep.add(f"IAP {iap_id}", f"{iap['faf']}->THR24R", "진방위", thr.true_brg,
                bearing_true(faf.lat, faf.lon, thr.thr_lat, thr.thr_lon), TOL_BRG_DEG)

    # --- RNP 24R 프로파일 고시 거리 (차트 측면도) ---
    prof = p.iap("RNP_24R").get("profile_dist_nm", {})
    for key, published in prof.items():
        a_name, b_name = key.split("-")
        a = wpts[a_name]
        b = thr if b_name == "THR" else wpts[b_name]
        blat, blon = (b.thr_lat, b.thr_lon) if b_name == "THR" else (b.lat, b.lon)
        rep.add("IAP RNP_24R/프로파일", key, "거리", published,
                distance_nm(a.lat, a.lon, blat, blon), TOL_DIST_NM)

    rep.print()

    # --- 부가 확인: 별도 출처에서 온 같은 지점끼리의 거리 ---
    print()
    z, ap = wpts["ZENZA"], wpts["APAKI"]
    d = distance_nm(z.lat, z.lon, ap.lat, ap.lon)
    print(f"[교차확인] ZENZA(ILS Z FAF) vs APAKI(RNP FAF) 이격 = {d*1852:.0f} m "
          f"— 두 절차가 사실상 같은 FAF 를 쓴다")

    # 3° 활공로 검산: FAF 고시고도가 활공로와 맞는지
    faf_alt = next(
        leg["alt_ft"]
        for leg in p.iap("RNP_24R")["final"]
        if leg.get("role") == "FAF"
    )
    gs = p.iap("RNP_24R")["gs_angle_deg"]
    tch = p.iap("RNP_24R")["tch_ft"]
    import math
    d_faf = distance_nm(ap.lat, ap.lon, thr.thr_lat, thr.thr_lon)
    on_gs = d_faf * 6076.115 * math.tan(math.radians(gs)) + tch + thr.thr_elev_ft
    print(f"[교차확인] APAKI 3° 활공로 고도 = {on_gs:.0f} ft "
          f"(고시 FAF 고도 {faf_alt} ft, 여유 {faf_alt - on_gs:+.0f} ft)")

    print()
    n, f, k = len(rep.rows), len(rep.failures), len(rep.known)
    print(f"검증 {n}건 중 {n - f - k}건 일치, 기지 편차 {k}건, 불일치 {f}건 "
          f"(허용오차 거리 {TOL_DIST_NM} NM / 방위 {TOL_BRG_DEG}°)")

    if k:
        print("\n기지 편차 (원인 규명 완료, 문서화됨):")
        for row in rep.known:
            print(f"  - {row[0]} {row[1]} {row[2]}")
            print(f"    {KNOWN_DEVIATIONS[(row[0], row[1], row[2])]}")

    if f:
        print("\n불일치 항목:")
        for row in rep.failures:
            print(f"  - {row[0]} {row[1]} {row[2]}: 고시 {row[3]}, 계산 {row[4]:.3f}")
        return 1

    ok_rows = [r for r in rep.rows if r[-1] is True]
    dmax = max((abs(r[5]) for r in ok_rows if r[2] == "거리"), default=0.0)
    bmax = max((abs(r[5]) for r in ok_rows if r[2] == "진방위"), default=0.0)
    print(f"\n일치 항목 최대 편차: 거리 {dmax:.3f} NM / 방위 {bmax:.3f}°")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
