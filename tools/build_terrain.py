"""지형 배경 추출 — Natural Earth 해안선을 오프라인 데이터로 굽는다.

    python tools/build_terrain.py

cartopy 가 캐시해 둔 Natural Earth(퍼블릭 도메인) 자료에서 청주 주변만 잘라
`data/terrain.json` 으로 저장한다. 한 번 만들어 두면 이후에는 외부 접속이
필요 없다 — 폐쇄망 반입 가능성을 지키기 위한 선택이다.

축척 주의: 청주에서 서해안까지 약 65km 이므로, 스코프를 60NM 이상으로
넓혔을 때만 해안선이 화면에 들어온다. 관제 축척(20~45NM)에서 실제로 유용한
배경은 지형이 아니라 특수사용공역이다(data/airspace.json 의 special_use).
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 참조 데이터는 패키지 안에 있고(저장소 배치와 무관), 산출물은 artifacts/ 로 모은다.
REFERENCE = ROOT / "src" / "sentry_atm" / "regulation" / "reference"
ARTIFACTS = ROOT / "artifacts"
ARTIFACTS.mkdir(exist_ok=True)

# 청주 중심으로 넉넉히 — 스코프 최대 90NM 까지 커버
LAT0, LON0 = 36.71639, 127.4992
DLAT, DLON = 1.6, 2.0
TOL_DEG = 0.004          # 단순화 허용오차 (약 400m). 표출용이므로 충분하다.


def clip(geom, box):
    try:
        g = geom.intersection(box)
        return None if g.is_empty else g
    except Exception:
        return None


def lines_of(geom):
    """도형을 폴리라인 목록으로 편다."""
    out = []
    gt = geom.geom_type
    if gt == "LineString":
        out.append(list(geom.coords))
    elif gt in ("MultiLineString", "GeometryCollection", "MultiPolygon"):
        for g in geom.geoms:
            out += lines_of(g)
    elif gt == "Polygon":
        out.append(list(geom.exterior.coords))
        for r in geom.interiors:
            out.append(list(r.coords))
    return out


def main() -> int:
    try:
        import cartopy.io.shapereader as shpreader
        from shapely.geometry import box as shp_box
    except ImportError:
        print("cartopy / shapely 가 필요하다: python -m pip install cartopy")
        return 1

    bbox = shp_box(LON0 - DLON, LAT0 - DLAT, LON0 + DLON, LAT0 + DLAT)
    layers = {}

    for key, name in (("coastline", "coastline"), ("land", "land")):
        try:
            path = shpreader.natural_earth(resolution="50m", category="physical",
                                           name=name)
        except Exception as exc:
            print(f"  {name}: 사용 불가 ({exc})")
            continue

        polys = []
        for rec in shpreader.Reader(path).geometries():
            g = clip(rec, bbox)
            if g is None:
                continue
            g = g.simplify(TOL_DEG, preserve_topology=True)
            for ln in lines_of(g):
                if len(ln) >= 2:
                    # (lon, lat) → (lat, lon), 소수 4자리(약 11m)면 표출에 충분
                    polys.append([[round(y, 4), round(x, 4)] for x, y in ln])
        layers[key] = polys
        pts = sum(len(p) for p in polys)
        print(f"  {name:<10} 선 {len(polys):3d}개, 점 {pts}개")

    if not layers.get("coastline"):
        print("  주의 — 이 범위에 해안선이 없다. 청주는 내륙이라 정상이다.")

    out = {
        "_source": "Natural Earth 50m (퍼블릭 도메인), cartopy 로컬 캐시에서 추출",
        "_note": "표출 전용. 청주는 내륙이라 60NM 이상으로 넓혀야 해안선이 보인다.",
        "bbox": {"lat0": LAT0 - DLAT, "lat1": LAT0 + DLAT,
                 "lon0": LON0 - DLON, "lon1": LON0 + DLON},
        "layers": layers,
    }
    path = REFERENCE / "terrain.json"
    path.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")),
                    encoding="utf-8")
    print(f"저장 - {path.name} ({path.stat().st_size/1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
