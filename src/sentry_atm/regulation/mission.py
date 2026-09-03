"""임무 소티 — 출격에서 복귀까지를 하나의 생애주기로 본다.

도착만 다루면 전투기는 "어디선가 나타난 항적"이다. 실제로는 같은 활주로에서
이륙해 SID 를 타고 나가 작전지역에서 임무를 수행하고 돌아온다. 그 전 구간이
민항 도착 흐름과 같은 공역·같은 활주로를 쓰므로, 출격의 비용은 도착에서 치러진다.

**작전지역은 지어내지 않는다.** AIP ENR 5.2 에 고시된 훈련공역(MOA)을 쓴다.
청주 인근에는 MOA 2H·2L·3A·4·11 이 있고, 고도 블록이 각각 다르다 — 2L 은
3,000ft AGL~9,000ft 로 낮아 접근 흐름과 고도가 겹치고, 2H 는 10,000ft 이상이라
겹치지 않는다. 어느 공역을 지정하느냐가 도착에 미치는 영향을 바꾼다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .geo import parse_latlon, separation_distance_nm
from .sector import PolygonVolume, resolve_altitude_ft
from .state import AircraftState


class SortiePhase(Enum):
    """소티 단계. 단계마다 관제 관심사가 다르다."""

    GROUND = "지상"
    """활주로 자원 문제 — 레이더 분리 대상이 아니다."""

    CLIMBOUT = "상승"
    """SID 추종. 도착 흐름과 고도가 겹치는 구간."""

    TRANSIT_OUT = "진출"
    """관할 이양 후 작전지역으로."""

    ON_STATION = "작전중"
    """작전지역 내. 청주 GCA 관할 밖이다."""

    RECOVERY = "복귀"
    """작전지역 이탈 후 청주로. 여기서부터 다시 도착 흐름과 경합한다."""

    APPROACH = "접근"
    """도착 시퀀스 편입."""

    LANDED = "착륙"


class MissionKind(Enum):
    """임무 종류. 우선권과 예측 가능성이 다르다."""

    PATROL = "초계"
    """매일 있는 주기적 임무. 계획에 들어 있어 미리 슬롯을 잡을 수 있다."""

    SCRAMBLE = "비상출격"
    """예기치 못한 출격. 계획에 없으므로 도착 흐름을 비집고 들어가야 한다."""


@dataclass(frozen=True)
class OperatingArea:
    """지정된 작전지역 — AIP 고시 훈련공역 하나."""

    id: str
    volume: PolygonVolume
    centroid: tuple[float, float]

    @property
    def lower_ft(self) -> float:
        return self.volume.lower_ft

    @property
    def upper_ft(self) -> float:
        return self.volume.upper_ft

    def contains(self, ac: AircraftState) -> bool:
        return self.volume.contains(ac.lat, ac.lon, ac.alt_ft)

    def contains_position(self, lat: float, lon: float) -> bool:
        return self.volume.contains_position(lat, lon)

    def distance_from_nm(self, lat: float, lon: float) -> float:
        """중심까지의 거리. 진입 여부는 `contains_position` 으로 본다."""
        return separation_distance_nm(lat, lon, *self.centroid)

    def overlaps_altitude(self, lower_ft: float, upper_ft: float) -> bool:
        """주어진 고도 밴드와 겹치는가 — 도착 흐름과의 간섭 판단에 쓴다."""
        return not (self.upper_ft < lower_ft or self.lower_ft > upper_ft)


@dataclass
class Sortie:
    """한 대의 소티 진행 상태."""

    callsign: str
    actype: str
    wake_cat: str
    kind: MissionKind
    area: OperatingArea

    phase: SortiePhase = SortiePhase.GROUND
    takeoff_s: float | None = None
    on_station_s: float | None = None
    off_station_s: float | None = None
    recovery_declared_s: float | None = None
    landed_s: float | None = None
    emergency: bool = False

    def time_on_station_s(self) -> float | None:
        if self.on_station_s is None or self.off_station_s is None:
            return None
        return self.off_station_s - self.on_station_s

    def describe(self) -> str:
        return (
            f"{self.callsign} ({self.actype}) — {self.kind.value} / "
            f"{self.area.id} / {self.phase.value}"
        )


@dataclass
class MissionBook:
    """작전지역 조회와 소티 단계 판정.

    공역 형상은 airspace.json 의 special_use.moa 에서만 읽는다.
    """

    ds: object

    areas: dict[str, OperatingArea] = field(init=False, default_factory=dict)

    def __post_init__(self) -> None:
        elev = self.ds.procedures.raw["aerodrome"]["elev_ft"]
        for m in self.ds.airspace.raw.get("special_use", {}).get("moa", []):
            pts = tuple(
                (parse_latlon(x.split()[0]), parse_latlon(x.split()[1]))
                for x in m["polygon"]
            )
            vol = PolygonVolume(
                id=m["id"],
                lower_ft=resolve_altitude_ft(m["lower"], elev),
                upper_ft=resolve_altitude_ft(m["upper"], elev),
                polygon=pts,
            )
            lat = sum(p[0] for p in pts) / len(pts)
            lon = sum(p[1] for p in pts) / len(pts)
            self.areas[m["id"]] = OperatingArea(m["id"], vol, (lat, lon))

    # ------------------------------------------------------------------

    def designate(self, area_id: str) -> OperatingArea:
        """작전지역 지정. 고시된 공역 중에서만 고른다."""
        if area_id not in self.areas:
            raise KeyError(
                f"고시된 훈련공역이 아니다: {area_id} — 가능: {sorted(self.areas)}"
            )
        return self.areas[area_id]

    def nearest_area(self, lat: float, lon: float) -> OperatingArea:
        return min(self.areas.values(), key=lambda a: a.distance_from_nm(lat, lon))

    def areas_conflicting_with_approach(self) -> list[OperatingArea]:
        """도착 배정고도 사다리와 고도가 겹치는 작전지역.

        겹치면 작전지역 진입·이탈 항적이 도착 흐름과 같은 고도를 쓰게 되어,
        수직분리로 풀 수 없고 수평·시간으로 풀어야 한다.
        """
        ladder = self.ds.airspace.raw["assigned_altitudes"]["ladder_ft"]
        lo, hi = min(ladder), max(ladder)
        return [a for a in self.areas.values() if a.overlaps_altitude(lo, hi)]

    # ------------------------------------------------------------------

    def phase_at(self, sortie: Sortie, ac: AircraftState, sector) -> SortiePhase:
        """현재 상태로 소티 단계를 판정한다.

        판정 순서가 중요하다 — 작전지역 안에 있으면 그것이 먼저이고, 복귀 선언이
        있으면 지역 밖 항적은 전부 복귀다. 거리로만 나누면 진출과 복귀가 구분되지
        않는다.
        """
        if sortie.landed_s is not None:
            return SortiePhase.LANDED
        if sortie.takeoff_s is None:
            return SortiePhase.GROUND
        if sortie.area.contains(ac):
            return SortiePhase.ON_STATION
        if sortie.recovery_declared_s is not None or sortie.off_station_s is not None:
            return (
                SortiePhase.APPROACH
                if sector.is_under_control(ac)
                else SortiePhase.RECOVERY
            )
        if sector.is_under_control(ac):
            return SortiePhase.CLIMBOUT
        return SortiePhase.TRANSIT_OUT

    def advance(self, sortie: Sortie, ac: AircraftState, sector, t_s: float) -> SortiePhase:
        """단계를 갱신하고 전이 시각을 기록한다."""
        phase = self.phase_at(sortie, ac, sector)
        if phase is SortiePhase.ON_STATION and sortie.on_station_s is None:
            sortie.on_station_s = t_s
        if (
            sortie.on_station_s is not None
            and sortie.off_station_s is None
            and phase in (SortiePhase.RECOVERY, SortiePhase.APPROACH)
        ):
            sortie.off_station_s = t_s
        if phase is SortiePhase.LANDED and sortie.landed_s is None:
            sortie.landed_s = t_s
        sortie.phase = phase
        return phase

    def declare_recovery(self, sortie: Sortie, t_s: float, *, emergency: bool = False) -> None:
        """비상복귀 선언. 이 시점부터 복귀 경로와 우선권 판단이 시작된다."""
        sortie.recovery_declared_s = t_s
        if emergency:
            sortie.emergency = True


def build(ds) -> MissionBook:
    return MissionBook(ds=ds)
