"""경로 계획 — 복귀 경로를 관제 지시로 표현 가능한 형태로 만든다.

임의 곡선을 그리면 안 된다. 관제사가 낼 수 있는 것은 "DIRECT (픽스)" 또는
"레이더 유도 침로 XXX" 이므로, 경로는 **고시된 픽스를 잇는 직선 구간의 연속**이어야
한다. 부드러운 최적 곡선은 계산상 짧아도 지시로 옮길 수 없다.

**고도를 함께 본다.** 제한구역은 고도 상한이 있다 — R19 는 3,400ft, R152 는 2,100ft
까지다. 평면으로만 회피하면 그 위로 곧장 지날 수 있는 경로를 불필요하게 우회시킨다.
반대로 고도를 무시하면 낮게 복귀하는 항적을 제한구역으로 밀어 넣는다.
"""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field

from .geo import bearing_true, parse_latlon, separation_distance_nm, vincenty_direct
from .sector import CircleVolume, PolygonVolume, Volume, resolve_altitude_ft
from .state import AircraftState

M_PER_NM = 1852.0


@dataclass(frozen=True)
class RouteLeg:
    """직선 구간 하나 — 관제 지시 한 줄에 대응한다."""

    to_fix: str
    lat: float
    lon: float
    dist_nm: float
    course_true: float


@dataclass(frozen=True)
class Route:
    """계획된 경로."""

    legs: tuple[RouteLeg, ...]
    origin: tuple[float, float]
    detour_nm: float
    """직선거리 대비 추가 거리. 0 이면 직행이다."""

    @property
    def total_nm(self) -> float:
        return sum(leg.dist_nm for leg in self.legs)

    @property
    def fixes(self) -> list[str]:
        return [leg.to_fix for leg in self.legs]

    def ete_s(self, gs_kt: float) -> float:
        return self.total_nm / max(gs_kt, 1.0) * 3600.0

    def clearance(self, callsign: str) -> str:
        """관제 허가 문구. 픽스를 잇는 직행 지시로만 표현한다."""
        if not self.legs:
            return f"{callsign}, 경로 없음"
        via = " ".join(f"DIRECT {leg.to_fix}" for leg in self.legs)
        return f"{callsign}, CLEARED TO {self.legs[-1].to_fix} VIA {via}"

    def describe(self) -> str:
        path = " → ".join(self.fixes)
        extra = f" (+{self.detour_nm:.1f}NM 우회)" if self.detour_nm > 0.05 else " (직행)"
        return f"{path} — {self.total_nm:.1f}NM{extra}"


@dataclass
class RoutePlanner:
    """고시 픽스 그래프 위의 최단 경로.

    노드는 AIP 전사 웨이포인트, 간선은 위험구역을 침범하지 않는 직선이다.
    """

    ds: object

    nodes: dict[str, tuple[float, float]] = field(init=False, default_factory=dict)
    hazards: tuple[Volume, ...] = field(init=False, default=())
    sample_nm: float = field(init=False, default=0.35)

    def __post_init__(self) -> None:
        self.nodes = {
            name: (w.lat, w.lon) for name, w in self.ds.procedures.waypoints.items()
        }
        self.hazards = self._build_hazards()
        # 샘플 간격은 가장 작은 위험구역보다 촘촘해야 한다. R139 반경 0.7NM 이
        # 최소이므로 그 절반으로 둔다 — 더 성기면 구역을 건너뛰고 통과한다.
        radii = [
            h.radius_nm for h in self.hazards if isinstance(h, CircleVolume)
        ]
        if radii:
            self.sample_nm = min(radii) / 2.0

    def _build_hazards(self) -> tuple[Volume, ...]:
        """제한구역과 인접 관제권 — 복귀 경로가 통과해서는 안 되는 공역.

        훈련공역(MOA)은 여기 넣지 않는다. 자기 임무공역일 수도 있고, 활성 여부가
        NOTAM 에 달려 있어 항상 회피 대상이 아니다. 호출자가 필요하면 더한다.
        """
        elev = self.ds.procedures.raw["aerodrome"]["elev_ft"]
        su = self.ds.airspace.raw.get("special_use", {})
        out: list[Volume] = []
        for r in su.get("restricted", []):
            out.append(
                CircleVolume(
                    id=r["id"],
                    lower_ft=resolve_altitude_ft(r["lower"], elev),
                    upper_ft=resolve_altitude_ft(r["upper"], elev),
                    center_lat=parse_latlon(r["center"]["lat"]),
                    center_lon=parse_latlon(r["center"]["lon"]),
                    radius_nm=r["radius_nm"],
                )
            )
        for c in su.get("neighbour_ctr", []):
            out.append(
                CircleVolume(
                    id=c["id"],
                    lower_ft=resolve_altitude_ft(c["lower"], elev),
                    upper_ft=resolve_altitude_ft(c["upper"], elev),
                    center_lat=parse_latlon(c["center"]["lat"]),
                    center_lon=parse_latlon(c["center"]["lon"]),
                    radius_nm=c["radius_nm"],
                )
            )
        return tuple(out)

    def moa_volume(self, moa_id: str) -> Volume:
        """훈련공역을 회피 대상으로 쓰고 싶을 때."""
        elev = self.ds.procedures.raw["aerodrome"]["elev_ft"]
        m = next(
            x for x in self.ds.airspace.raw["special_use"]["moa"] if x["id"] == moa_id
        )
        pts = tuple(
            (parse_latlon(v.split()[0]), parse_latlon(v.split()[1])) for v in m["polygon"]
        )
        return PolygonVolume(
            id=m["id"],
            lower_ft=resolve_altitude_ft(m["lower"], elev),
            upper_ft=resolve_altitude_ft(m["upper"], elev),
            polygon=pts,
        )

    # ------------------------------------------------------------------
    # 침범 판정
    # ------------------------------------------------------------------

    def blocking(
        self,
        a: tuple[float, float],
        b: tuple[float, float],
        alt_ft: float,
        extra: tuple[Volume, ...] = (),
    ) -> str | None:
        """구간 a→b 가 침범하는 공역의 id. 없으면 None.

        대권 구간을 촘촘히 샘플링해 3차원 포함 여부를 본다. 해석해가 아니라
        샘플링인 이유는 폴리곤·환형이 섞여 있어서다 — 대신 샘플 간격을 가장 작은
        구역보다 촘촘하게 잡아 건너뛰기를 막는다.
        """
        volumes = tuple(self.hazards) + tuple(extra)
        if not volumes:
            return None
        d = separation_distance_nm(*a, *b)
        n = max(2, int(math.ceil(d / self.sample_nm)) + 1)
        crs = bearing_true(*a, *b)
        for i in range(n + 1):
            f = d * i / n
            lat, lon = vincenty_direct(*a, crs, f * M_PER_NM) if f > 0 else a
            for v in volumes:
                if v.contains(lat, lon, alt_ft):
                    return v.id
        return None

    # ------------------------------------------------------------------
    # 계획
    # ------------------------------------------------------------------

    def plan(
        self,
        origin: tuple[float, float],
        destination: str,
        alt_ft: float,
        *,
        avoid: tuple[Volume, ...] = (),
        max_leg_nm: float = 60.0,
    ) -> Route | None:
        """출발 지점에서 목적 픽스까지, 고시 픽스만 거치는 최단 경로.

        직행이 뚫려 있으면 그것이 답이다. 막혀 있을 때만 픽스를 경유한다 —
        관제사가 이해할 수 없는 우회를 만들지 않기 위해서다.
        """
        if destination not in self.nodes:
            raise KeyError(f"고시된 픽스가 아니다: {destination}")
        goal = self.nodes[destination]

        direct_nm = separation_distance_nm(*origin, *goal)
        if self.blocking(origin, goal, alt_ft, avoid) is None:
            leg = RouteLeg(
                destination, goal[0], goal[1], direct_nm, bearing_true(*origin, *goal)
            )
            return Route(legs=(leg,), origin=origin, detour_nm=0.0)

        # --- 픽스 그래프 탐색 (A*) ---
        START = "\x00START"
        coords = dict(self.nodes)
        coords[START] = origin

        def h(name: str) -> float:
            return separation_distance_nm(*coords[name], *goal)

        def neighbours(name: str):
            here = coords[name]
            for other, pt in coords.items():
                if other == name or other == START:
                    continue
                d = separation_distance_nm(*here, *pt)
                if d > max_leg_nm or d < 1e-6:
                    continue
                if self.blocking(here, pt, alt_ft, avoid) is not None:
                    continue
                yield other, d

        best = {START: 0.0}
        prev: dict[str, str] = {}
        pq: list[tuple[float, float, str]] = [(h(START), 0.0, START)]
        seen: set[str] = set()
        while pq:
            _, g, name = heapq.heappop(pq)
            if name in seen:
                continue
            seen.add(name)
            if name == destination:
                break
            for nxt, d in neighbours(name):
                ng = g + d
                if ng < best.get(nxt, math.inf) - 1e-9:
                    best[nxt] = ng
                    prev[nxt] = name
                    heapq.heappush(pq, (ng + h(nxt), ng, nxt))

        if destination not in prev:
            return None

        chain = [destination]
        while chain[-1] != START:
            chain.append(prev[chain[-1]])
        chain.reverse()

        legs: list[RouteLeg] = []
        for a_name, b_name in zip(chain, chain[1:]):
            a, b = coords[a_name], coords[b_name]
            legs.append(
                RouteLeg(
                    b_name, b[0], b[1],
                    separation_distance_nm(*a, *b), bearing_true(*a, *b),
                )
            )
        total = sum(leg.dist_nm for leg in legs)
        return Route(legs=tuple(legs), origin=origin, detour_nm=total - direct_nm)

    # ------------------------------------------------------------------
    # 복귀
    # ------------------------------------------------------------------

    def approach_entries(self, approach: str = "RNP_24R") -> list[str]:
        """접근 전이의 최초접근픽스(IAF) 목록 — 복귀 경로의 목적지 후보."""
        iap = self.ds.procedures.iap(approach)
        out = []
        for legs in iap.get("transitions", {}).values():
            for leg in legs:
                if leg.get("role") == "IAF":
                    out.append(leg["wpt"])
                    break
        return out

    def recovery(
        self,
        ac: AircraftState,
        *,
        approach: str = "RNP_24R",
        avoid: tuple[Volume, ...] = (),
    ) -> Route | None:
        """청주 최단 복귀경로.

        고시된 IAF 중 **총 비행거리가 가장 짧은** 곳으로 넣는다. 직선거리가 가까운
        IAF 를 고르면 안 된다 — 그쪽이 제한구역에 막혀 크게 우회하는 경우가 있고,
        그러면 더 먼 IAF 로 곧장 가는 편이 실제로 빠르다.
        """
        best: Route | None = None
        for iaf in self.approach_entries(approach):
            r = self.plan((ac.lat, ac.lon), iaf, ac.alt_ft, avoid=avoid)
            if r is None:
                continue
            if best is None or r.total_nm < best.total_nm:
                best = r
        return best


def build(ds) -> RoutePlanner:
    return RoutePlanner(ds=ds)
