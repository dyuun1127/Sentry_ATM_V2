"""관제 스코프가 그릴 형상 — 전부 AIP 실좌표.

지금까지 이 계산은 오프라인 도구(`tools/export_scenario.py`)에만 있었고, 산출물
JSON 에 구워져 콘솔로 갔다. 실시간 콘솔은 그 JSON 을 거치지 않으므로 같은 형상을
API 로 받아야 한다. 도구 안에 남겨 두고 한 벌을 더 만들면 두 화면이 서로 다른
공역을 그리게 되고, 둘 다 그럴듯해서 어긋난 사실이 드러나지 않는다.

여기서 새로 정하는 값은 없다. 활주로 시단도 픽스도 공역 경계도 전사 데이터에
있는 것을 좌표로 펴기만 한다. 원이나 장주처럼 점 목록이 필요한 것은 측지선
직접문제(`vincenty_direct`)로 그린다 — 평면 근사로 그리면 30 NM 링에서 눈에
보이는 만큼 찌그러진다.
"""

from __future__ import annotations

import json
from functools import lru_cache

from sentry_atm.regulation import data as regulation_data
from sentry_atm.regulation import sequencing as sequencing_module
from sentry_atm.regulation.data import DATA_DIR
from sentry_atm.regulation.geo import (
    M_PER_NM,
    parse_latlon,
    separation_distance_nm,
    vincenty_direct,
    vincenty_inverse,
)
from sentry_atm.regulation.sector import resolve_altitude_ft

# 스코프에 그릴 거리 링. 관제권과 터미널 경계가 먼저 오고 나머지는 눈금이다.
_RINGS = (
    (5.0, "관제권 5NM"),
    (10.0, "터미널 10NM"),
    (20.0, "20NM"),
    (30.0, "30NM"),
)

# 픽스를 표시할 범위. 이보다 먼 픽스는 스코프 밖이라 이름만 어지럽힌다.
_FIX_RANGE_NM = 32.0

# 원과 링을 몇 각형으로 그릴 것인가. 30 NM 링에서 72 각형이면 한 변이 2.6 NM 이고
# 화면에서 직선으로 보이지 않는다.
_RING_SEGMENTS = 72
_CIRCLE_SEGMENTS = 48


def _circle(lat: float, lon: float, radius_nm: float, segments: int) -> list[list[float]]:
    return [
        list(vincenty_direct(lat, lon, 360.0 * index / segments, radius_nm * M_PER_NM))
        for index in range(segments + 1)
    ]


def _sector_polygon(block: dict, blocks: list[dict]) -> list[dict]:
    """이 블록의 평면 경계.

    ENR 2.1 은 T17 폴리곤을 두 번 고시한다 — 중원 TMA 항(6,500ft 아래, 청주 GCA)과
    오산 TMA 항(FL145~6,500ft, 오산 APP). 두 번째는 좌표를 다시 적지 않고 같은
    도형을 가리키므로, 여기서 그것을 이어 준다.
    """
    if block.get("polygon"):
        return block["polygon"]
    shared = block.get("same_polygon_as")
    if not shared:
        return []
    origin = next((item for item in blocks if item["id"] == shared), None)
    return origin.get("polygon", []) if origin else []


def _zone_detail(item: dict, elevation_ft: float, **extra) -> dict:
    """공역 하나를 눌렀을 때 보여 줄 것.

    전부 전사 데이터에 있는 값이다. 화면에서 다시 계산하거나 채워 넣지 않는다 —
    관제사가 이 상자를 보고 판단하므로, 여기 뜬 것은 고시가 말한 것이어야 한다.

    포함 판정에 필요한 고도는 AMSL ft 로 환산해 함께 보낸다. AGL/GND/SFC/FL 이
    섞여 있어 화면에서 환산하게 두면 두 벌이 되고 언젠가 어긋난다.
    """
    detail = {
        "id": item["id"],
        "name": item.get("name", ""),
        "lower_ft": resolve_altitude_ft(item["lower"], elevation_ft),
        "upper_ft": resolve_altitude_ft(item["upper"], elevation_ft),
        "lower_label": _altitude_label(item["lower"]),
        "upper_label": _altitude_label(item["upper"]),
        "note": item.get("note") or item.get("_note") or "",
        **extra,
    }
    for key in ("activity", "authority", "class", "unit"):
        if item.get(key):
            detail[key] = item[key]
    return detail


def _altitude_label(spec: dict) -> str:
    """AIP 표기를 그대로 읽히게. 환산값이 아니라 고시된 형태로 보여 준다."""
    if "fl" in spec:
        return f"FL{spec['fl']}"
    reference = spec.get("ref", "AMSL")
    if reference in ("GND", "SFC"):
        return reference
    return f"{spec['ft']:,}ft {reference}"


def _sector_label(block: dict) -> str:
    return (
        f"{block['id']} {block['unit']} "
        f"{_altitude_label(block['lower'])}~{_altitude_label(block['upper'])} "
        f"Class {block['class'].replace(', ', '/')}"
    )


def _msa(dataset) -> dict:
    """최저고도 차트 (AD 2-16) — 경계·고도 숫자·장애물.

    **표시 전용이다.** 판정에 쓰지 않는다 (`ASM-037`). 화면에 그리는 이유는,
    비상기를 낮게 복귀시킬 때 왜 그 경로가 아닌지가 숫자로 보여야 하기 때문이다.

    라디얼은 직선이라 두 점을 잇기만 하면 되고, 원호는 CHO 를 중심으로 두 점
    사이를 잘게 나눠 그린다 — 직선으로 이으면 24 NM 호에서 눈에 보이게 꺾인다.
    """
    chart = dataset.msa
    navaid = dataset.procedures.raw["navaids"][chart.raw["reference_navaid"]]
    centre = (parse_latlon(navaid["lat"]), parse_latlon(navaid["lon"]))

    def point(name: str) -> tuple[float, float]:
        node = chart.vertices[name]
        return parse_latlon(node["lat"]), parse_latlon(node["lon"])

    def arc_between(start, end, radius_nm):
        """CHO 중심 원호. 짧은 쪽으로 돈다 — 섹터 경계는 늘 짧은 쪽이다."""
        _, from_brg, _ = vincenty_inverse(*centre, *start)
        _, to_brg, _ = vincenty_inverse(*centre, *end)
        sweep = (to_brg - from_brg + 540.0) % 360.0 - 180.0
        steps = max(2, int(abs(sweep) / 2.0) + 1)
        return [
            list(vincenty_direct(*centre, from_brg + sweep * i / steps, radius_nm * M_PER_NM))
            for i in range(steps + 1)
        ]

    lines = []
    for segment in chart.boundaries:
        via = segment["via"]
        if segment["kind"] == "radial":
            lines.append({"kind": "radial", "label": segment.get("label", ""),
                          "points": [list(point(name)) for name in via]})
            continue
        points: list[list[float]] = []
        for first, second in zip(via, via[1:], strict=False):
            leg = arc_between(point(first), point(second), segment["radius_nm"])
            points.extend(leg if not points else leg[1:])
        lines.append({"kind": "arc", "label": f"{segment['radius_nm']:.0f} NM",
                      "points": points})

    return {
        "lines": lines,
        "vertices": [
            list(point(name)) for name in chart.vertices
        ],
        "altitudes": [
            {
                "altitude_ft": item["altitude_ft"],
                "low_temperature_ft": item["low_temperature_ft"],
                "at": [item["lat"], item["lon"]],
            }
            for item in chart.minimum_altitudes
        ],
        "obstacles": [
            {
                "id": item["id"],
                "elevation_ft": item["elevation_ft"],
                "at": [parse_latlon(item["lat"]), parse_latlon(item["lon"])],
                "remark": item.get("remark", ""),
            }
            for item in chart.obstacles
        ],
    }


def _terrain() -> dict:
    """지형 배경. 없으면 빈 채로 둔다 — 스코프는 지형 없이도 성립한다."""
    path = DATA_DIR / "terrain.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8")).get("layers", {})


def airspace_geometry(dataset=None, sequencer=None) -> dict:
    """공역·활주로·픽스·지형 — 시나리오와 무관한 배경 형상."""
    dataset = dataset or regulation_data.load()
    sequencer = sequencer or sequencing_module.build(dataset)

    airspace = dataset.airspace.raw
    terminal = airspace["cheongju_terminal"]
    centre_lat = parse_latlon(terminal["center"]["lat"])
    centre_lon = parse_latlon(terminal["center"]["lon"])

    elevation_ft = dataset.procedures.raw["aerodrome"]["elev_ft"]

    runway_24r = dataset.procedures.runways["24R"]
    runway_06l = dataset.procedures.runways["06L"]

    centreline = [
        list(
            vincenty_direct(
                *sequencer.thr,
                (sequencer.final_course_deg + 180.0) % 360.0,
                distance_nm * M_PER_NM,
            )
        )
        for distance_nm in (0.0, 30.0)
    ]

    # 특수사용공역 (AIP ENR 5.1 / 5.2). 청주는 제한구역과 훈련공역이 접근로
    # 바로 옆 8~18 NM 에 붙어 있어, 이 공역이 까다로운 이유가 화면으로 설명된다.
    special_use = airspace.get("special_use", {})
    restricted = [
        _zone_detail(
            item,
            elevation_ft,
            kind="제한구역",
            radius_nm=item["radius_nm"],
            points=_circle(
                parse_latlon(item["center"]["lat"]),
                parse_latlon(item["center"]["lon"]),
                item["radius_nm"],
                _CIRCLE_SEGMENTS,
            ),
            centre=[
                parse_latlon(item["center"]["lat"]),
                parse_latlon(item["center"]["lon"]),
            ],
        )
        for item in special_use.get("restricted", [])
    ]
    moa = [
        _zone_detail(
            item,
            elevation_ft,
            kind="훈련공역",
            points=[
                [parse_latlon(node.split()[0]), parse_latlon(node.split()[1])]
                for node in item["polygon"]
            ],
        )
        for item in special_use.get("moa", [])
    ]
    neighbour_ctr = [
        _zone_detail(
            item,
            elevation_ft,
            kind="인접 관제권",
            radius_nm=item["radius_nm"],
            points=_circle(
                parse_latlon(item["center"]["lat"]),
                parse_latlon(item["center"]["lon"]),
                item["radius_nm"],
                _CIRCLE_SEGMENTS,
            ),
            centre=[
                parse_latlon(item["center"]["lat"]),
                parse_latlon(item["center"]["lon"]),
            ],
        )
        for item in special_use.get("neighbour_ctr", [])
    ]

    # 중원 TMA 전체. 담당 섹터 하나만 그리면 그 경계 밖이 빈 곳처럼 보이는데,
    # 실제로는 인접 기관이 이어받는 공역이다. 어디로 이양되는지가 화면에 있어야
    # 「관할이 넘어간다」는 말이 그림으로 설명된다.
    tma = [
        {
            "id": block["id"],
            "unit": block["unit"],
            "class": block["class"],
            "lower_ft": resolve_altitude_ft(block["lower"], elevation_ft),
            "upper_ft": resolve_altitude_ft(block["upper"], elevation_ft),
            "target": bool(block.get("is_target_sector")),
            "kind": "담당 섹터" if block.get("is_target_sector") else "인접 섹터",
            "label": _sector_label(block),
            "lower_label": _altitude_label(block["lower"]),
            "upper_label": _altitude_label(block["upper"]),
            "ifr_vfr_separation": block["ifr_vfr_separation"],
            "frequencies": block.get("freq_mhz_aip") or block.get("freq_mhz") or [],
            "note": block.get("_note", ""),
            "points": [
                [parse_latlon(node["lat"]), parse_latlon(node["lon"])]
                for node in _sector_polygon(block, airspace["tma"]["blocks"])
            ],
        }
        for block in airspace["tma"]["blocks"]
        if _sector_polygon(block, airspace["tma"]["blocks"])
    ]

    return {
        "restricted": restricted,
        "moa": moa,
        "neighbour_ctr": neighbour_ctr,
        "terrain": _terrain(),
        "msa": _msa(dataset),
        "tma": tma,
        "rings": [
            {
                "radius_nm": radius_nm,
                "points": _circle(centre_lat, centre_lon, radius_nm, _RING_SEGMENTS),
                "label": label,
            }
            for radius_nm, label in _RINGS
        ],
        "centre": [centre_lat, centre_lon],
        "runway": {
            "name": "06L/24R",
            "thr24r": [runway_24r.thr_lat, runway_24r.thr_lon],
            "thr06l": [runway_06l.thr_lat, runway_06l.thr_lon],
            "true_brg": runway_24r.true_brg,
        },
        "centreline": centreline,
        "fixes": [
            {
                "name": name,
                "lat": waypoint.lat,
                "lon": waypoint.lon,
                "dist_thr_nm": round(
                    separation_distance_nm(waypoint.lat, waypoint.lon, *sequencer.thr), 2
                ),
            }
            for name, waypoint in dataset.procedures.waypoints.items()
            if separation_distance_nm(waypoint.lat, waypoint.lon, *sequencer.thr)
            < _FIX_RANGE_NM
        ],
        "approach": {
            "faf": dataset.procedures.iap("RNP_24R")["faf"],
            "faf_dist_nm": sequencer.faf_dist_nm,
            "if_dist_nm": sequencer.join_dist_nm,
            "gs_angle_deg": sequencer.gs_angle_deg,
            "thr_elev_ft": sequencer.thr_elev_ft,
        },
    }


def hold_geometry(pattern) -> list[list[float]]:
    """공고 체공 장주를 스코프에 그릴 좌표로.

    경주로형 장주 — 인바운드 구간, 180° 선회, 아웃바운드 구간, 180° 선회. 선회는
    반원을 8분할해 근사한다. 실제 선회는 속도와 경사각으로 반경이 정해지지만,
    스코프에서 장주의 위치와 방향을 읽는 데는 이 근사로 충분하다.
    """
    inbound = pattern.inbound_course_true
    fix = (pattern.lat, pattern.lon)
    leg_m = pattern.leg_nm * M_PER_NM
    # 인바운드는 픽스로 들어오는 방향이므로 아웃바운드 시작점은 그 반대편이다.
    outbound = (inbound + 180.0) % 360.0
    side = 1.0 if pattern.right_turns else -1.0
    turn_radius_nm = pattern.leg_nm / 4.0
    offset = (inbound + 90.0 * side) % 360.0

    corner_a = fix
    corner_b = vincenty_direct(*fix, outbound, leg_m)
    corner_c = vincenty_direct(*corner_b, offset, 2 * turn_radius_nm * M_PER_NM)
    corner_d = vincenty_direct(*corner_c, inbound, leg_m)

    points = [corner_a, corner_b]
    for start, centre_bearing in (
        (corner_b, offset),
        (corner_d, (offset + 180.0) % 360.0),
    ):
        centre = vincenty_direct(*start, centre_bearing, turn_radius_nm * M_PER_NM)
        base = (centre_bearing + 180.0) % 360.0
        for step in range(1, 9):
            angle = (base + side * 180.0 * step / 8.0) % 360.0
            points.append(vincenty_direct(*centre, angle, turn_radius_nm * M_PER_NM))
    points.append(corner_a)
    return [[round(lat, 6), round(lon, 6)] for lat, lon in points]


def area_geometry(area) -> dict:
    """작전지역 하나."""
    return {
        "id": area.id,
        "points": [[round(lat, 6), round(lon, 6)] for lat, lon in area.volume.polygon],
        "lower_ft": round(area.lower_ft),
        "upper_ft": round(area.upper_ft),
        "centre": [round(area.centroid[0], 6), round(area.centroid[1], 6)],
    }


def route_geometry(route) -> dict | None:
    """복귀 경로 하나. 경로가 없으면 그릴 것도 없다."""
    if route is None:
        return None
    return {
        "fixes": list(route.fixes),
        "points": [[round(route.origin[0], 6), round(route.origin[1], 6)]]
        + [[round(leg.lat, 6), round(leg.lon, 6)] for leg in route.legs],
        "total_nm": round(route.total_nm, 2),
        "detour_nm": round(route.detour_nm, 2),
    }


def published_holds(dataset=None) -> list[dict]:
    """공고된 체공 장주 전부. 어느 항공기가 쓰는지와 무관한 배경 형상이다."""
    dataset = dataset or regulation_data.load()
    from sentry_atm.regulation import hold as hold_module

    book = hold_module.build(dataset)
    return [
        {
            "fix": pattern.fix,
            "points": hold_geometry(pattern),
            "inbound_course_true": pattern.inbound_course_true,
            "leg_nm": pattern.leg_nm,
            "right_turns": pattern.right_turns,
            "lower_ft": getattr(pattern, "lower_ft", None),
            "upper_ft": getattr(pattern, "upper_ft", None),
        }
        for pattern in book.patterns
    ]


@lru_cache(maxsize=1)
def scope_geometry() -> dict:
    """스코프 배경 전부. 시나리오와 무관하므로 한 번 만들어 두고 쓴다.

    한 번만 만드는 이유는 크기 때문이다. 지형과 링을 합치면 수백 KB 가 되고,
    요청마다 다시 만들면 재생 중에 그 비용이 매 초 반복된다.
    """
    dataset = regulation_data.load()
    geometry = airspace_geometry(dataset)
    geometry["holds"] = published_holds(dataset)
    return geometry


__all__ = [
    "airspace_geometry",
    "area_geometry",
    "hold_geometry",
    "published_holds",
    "route_geometry",
    "scope_geometry",
]
