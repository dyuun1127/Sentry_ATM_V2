"""공역 포함 판정 — 관제기관별 담당 구역과 관제이양 경계.

AIP 를 그대로 읽으면 청주 관제는 하나의 폴리곤이 아니다.

    청주 GCA 담당 = T17 회랑 (Class D/E, 1,000ft AGL ~ 6,500ft AMSL)
                  ∪ 청주 터미널 Class C (관제권 5NM + 남서·북동 확장 + 5~10NM 링)
                  − 성무 Class D (중첩 제외)

T17 회랑만 쓰면 RWY 24R 최종접근(TURTU~TU746)이 전부 회랑 밖으로 나온다.
회랑의 남동측 경계가 공항을 스치듯 지나가고, 접근로는 그 남동쪽에 있기 때문이다.
그 구간은 청주 터미널 Class C 의 5~10NM 링과 관제권이 담당한다.

관제이양은 두 방향이다 (고시 2-1-15).
    수직 — T17 상한 6,500ft 위는 OSAN APP (ENR 2.1 의 OSAN TMA 항 T17)
    측방 — T17 남동쪽 T19 는 JUNGWON APP (IKAPO·MENOL·TURTU 가 여기)
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass

from .geo import parse_latlon, separation_distance_nm
from .state import AircraftState


def resolve_altitude_ft(spec: dict, aerodrome_elev_ft: float) -> float:
    """공역 고도 표기를 AMSL ft 로 환산한다.

    AIP 는 SFC / GND / AGL / AMSL / FL 을 섞어 쓴다. 하나로 환산하지 않으면
    섹터 판정에서 조용히 틀린다.

    지형 DB 가 없으므로 AGL·GND·SFC 는 공항 표고로 근사한다. 도착 시퀀싱은
    1,000ft AGL 을 한참 넘는 고도에서 이뤄지므로 실질 영향이 없다.
    """
    if "fl" in spec:
        return spec["fl"] * 100.0
    ref = spec.get("ref", "AMSL")
    if ref in ("GND", "SFC"):
        return aerodrome_elev_ft
    if ref == "AGL":
        return aerodrome_elev_ft + spec["ft"]
    if ref == "AMSL":
        return spec["ft"]
    raise ValueError(f"알 수 없는 고도 기준: {ref!r}")


def point_in_polygon(lat: float, lon: float, polygon: list[tuple[float, float]]) -> bool:
    """폴리곤 내부 판정 (ray casting).

    폴리곤 변을 위경도 평면의 직선으로 본다. TMA 규모(한 변 30NM 안팎)에서
    측지선과의 차이는 수십 m 이하라 섹터 판정에 영향이 없다.
    """
    n = len(polygon)
    if n < 3:
        return False

    inside = False
    j = n - 1
    for i in range(n):
        lat_i, lon_i = polygon[i]
        lat_j, lon_j = polygon[j]
        if (lon_i > lon) != (lon_j > lon):
            lat_cross = lat_i + (lon - lon_i) * (lat_j - lat_i) / (lon_j - lon_i)
            if lat < lat_cross:
                inside = not inside
        j = i
    return inside


# ----------------------------------------------------------------------
# 공역 볼륨
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class Volume(ABC):
    """고도 밴드를 가진 공역 조각."""

    id: str
    lower_ft: float
    upper_ft: float

    def contains(self, lat: float, lon: float, alt_ft: float) -> bool:
        return self.contains_altitude(alt_ft) and self.contains_position(lat, lon)

    def contains_altitude(self, alt_ft: float) -> bool:
        return self.lower_ft <= alt_ft <= self.upper_ft

    @abstractmethod
    def contains_position(self, lat: float, lon: float) -> bool: ...


@dataclass(frozen=True)
class PolygonVolume(Volume):
    polygon: tuple[tuple[float, float], ...] = ()

    def contains_position(self, lat: float, lon: float) -> bool:
        return point_in_polygon(lat, lon, list(self.polygon))


@dataclass(frozen=True)
class CircleVolume(Volume):
    """원통. inner_nm 을 주면 환형(annulus)."""

    center_lat: float = 0.0
    center_lon: float = 0.0
    radius_nm: float = 0.0
    inner_nm: float = 0.0

    def contains_position(self, lat: float, lon: float) -> bool:
        d = separation_distance_nm(self.center_lat, self.center_lon, lat, lon)
        return self.inner_nm <= d <= self.radius_nm


@dataclass(frozen=True)
class ControlledArea:
    """한 관제기관이 담당하는 공역 — 볼륨의 합집합에서 제외구역을 뺀 것."""

    unit: str
    airspace_class: str
    volumes: tuple[Volume, ...]
    excludes: tuple[Volume, ...] = ()
    ifr_vfr_separation: bool = False

    def contains(self, lat: float, lon: float, alt_ft: float) -> bool:
        if any(v.contains(lat, lon, alt_ft) for v in self.excludes):
            return False
        return any(v.contains(lat, lon, alt_ft) for v in self.volumes)

    def containing_volume(self, lat: float, lon: float, alt_ft: float) -> str | None:
        """어느 볼륨에 들어 있는지 — 표출·설명용."""
        if any(v.contains(lat, lon, alt_ft) for v in self.excludes):
            return None
        for v in self.volumes:
            if v.contains(lat, lon, alt_ft):
                return v.id
        return None


# ----------------------------------------------------------------------
# 섹터 모델
# ----------------------------------------------------------------------


def _poly(nodes: list[dict]) -> tuple[tuple[float, float], ...]:
    return tuple((parse_latlon(n["lat"]), parse_latlon(n["lon"])) for n in nodes)


class SectorModel:
    """청주 GCA 담당 공역과 인접 기관, 관제이양 경계."""

    def __init__(
        self,
        gca: ControlledArea,
        corridor: PolygonVolume,
        neighbours: dict[str, ControlledArea],
        handoff_alt_ft: float,
        upper_unit: str,
        lateral_unit: str,
    ):
        self.gca = gca
        self.corridor = corridor
        self.neighbours = neighbours
        self.handoff_alt_ft = handoff_alt_ft
        self.upper_unit = upper_unit
        self.lateral_unit = lateral_unit

    @classmethod
    def from_dataset(cls, ds) -> SectorModel:
        elev = ds.procedures.raw["aerodrome"]["elev_ft"]
        air = ds.airspace.raw

        def alt(spec):
            return resolve_altitude_ft(spec, elev)

        # T17 회랑
        t17 = ds.airspace.target_sector
        corridor = PolygonVolume(
            id="T17",
            lower_ft=alt(t17["lower"]),
            upper_ft=alt(t17["upper"]),
            polygon=_poly(t17["polygon"]),
        )

        # 청주 터미널 Class C
        term = air["cheongju_terminal"]
        c_lat = parse_latlon(term["center"]["lat"])
        c_lon = parse_latlon(term["center"]["lon"])
        volumes: list[Volume] = [corridor]
        for v in term["volumes"]:
            lo, up = alt(v["lower"]), alt(v["upper"])
            if v["shape"] == "polygon":
                volumes.append(PolygonVolume(v["id"], lo, up, _poly(v["polygon"])))
            elif v["shape"] == "circle":
                volumes.append(CircleVolume(v["id"], lo, up, c_lat, c_lon, v["radius_nm"]))
            elif v["shape"] == "annulus":
                volumes.append(
                    CircleVolume(v["id"], lo, up, c_lat, c_lon, v["outer_nm"], v["inner_nm"])
                )
            else:
                raise ValueError(f"알 수 없는 공역 형상: {v['shape']!r}")

        excludes: list[Volume] = []
        for e in term.get("excludes", []):
            excludes.append(
                CircleVolume(
                    e["id"], alt(e["lower"]), alt(e["upper"]),
                    parse_latlon(e["center"]["lat"]), parse_latlon(e["center"]["lon"]),
                    e["radius_nm"],
                )
            )

        gca = ControlledArea(
            unit=term["unit"],
            airspace_class=term["class"],
            volumes=tuple(volumes),
            excludes=tuple(excludes),
            ifr_vfr_separation=term["provides_ifr_vfr_separation"],
        )

        # 인접 기관
        neighbours: dict[str, ControlledArea] = {}
        for b in air["tma"]["blocks"]:
            if b.get("is_target_sector"):
                continue
            poly = b.get("polygon")
            if b.get("same_polygon_as") == "T17":
                poly = t17["polygon"]
            if not poly:
                continue
            vol = PolygonVolume(b["id"], alt(b["lower"]), alt(b["upper"]), _poly(poly))
            area = neighbours.get(b["id"])
            neighbours[b["id"]] = ControlledArea(
                unit=b["unit"],
                airspace_class=b["class"],
                volumes=(vol,) if area is None else area.volumes + (vol,),
                ifr_vfr_separation=b["ifr_vfr_separation"],
            )

        h = air["handoff"]
        return cls(
            gca=gca,
            corridor=corridor,
            neighbours=neighbours,
            handoff_alt_ft=h["t17_upper_ft_amsl"],
            upper_unit=h["upper_unit"],
            lateral_unit=h["lateral_unit"],
        )

    # --- 판정 ---

    def owner(self, ac: AircraftState) -> str:
        """이 항적을 지금 누가 관제하는가.

        고시 2-1-15 — 통신 인수가 곧 관제책임 인수다. 여기서 돌려주는 값은
        '공역 구조상 누가 잡고 있어야 하는가'이며, 실제 이양 시각은
        시뮬레이터가 이벤트로 기록한다.
        """
        if self.gca.contains(ac.lat, ac.lon, ac.alt_ft):
            return self.gca.unit
        for area in self.neighbours.values():
            if area.contains(ac.lat, ac.lon, ac.alt_ft):
                return area.unit
        return "OUTSIDE"

    def is_under_control(self, ac: AircraftState) -> bool:
        """청주 GCA 가 책임지는 항적인가."""
        return self.gca.contains(ac.lat, ac.lon, ac.alt_ft)

    def volume_of(self, ac: AircraftState) -> str | None:
        """청주 GCA 담당 공역 중 어느 볼륨에 있는가 — 표출·설명용."""
        return self.gca.containing_volume(ac.lat, ac.lon, ac.alt_ft)

    def crosses_handoff(self, before: AircraftState, after: AircraftState) -> str | None:
        """두 시점 사이에 수직 관제이양 경계(T17 상한)를 넘었는가.

        Returns:
            "INBOUND"  상위 섹터 → 청주 GCA (강하하며 인수)
            "OUTBOUND" 청주 GCA → 상위 섹터 (상승하며 이양)
            None       경계를 넘지 않음
        """
        h = self.handoff_alt_ft
        if before.alt_ft > h >= after.alt_ft:
            return "INBOUND"
        if before.alt_ft <= h < after.alt_ft:
            return "OUTBOUND"
        return None

    def transfer_event(
        self, before: AircraftState, after: AircraftState
    ) -> tuple[str, str] | None:
        """관제권이 실제로 바뀌었는가.

        Returns:
            (인계 기관, 인수 기관) 또는 None.
        """
        a, b = self.owner(before), self.owner(after)
        return None if a == b else (a, b)

    @property
    def provides_ifr_vfr_separation(self) -> bool:
        """청주 터미널은 Class C 로 변경되어 IFR-VFR 분리를 제공한다 (AD 2.17, AMDT 1/26).

        단 T17 회랑 자체는 Class D/E 로 남아 있어 회랑 안에서는 교통정보만 제공된다.
        """
        return self.gca.ifr_vfr_separation

    @property
    def corridor_provides_ifr_vfr_separation(self) -> bool:
        return False
