"""관제 이양 사슬 — 출격에서 복귀까지 누가 언제 잡고 있는가.

도착만 다룰 때는 이양이 한 번(상위 섹터 → 청주 GCA)이면 충분했다. 출격을 넣으면
사슬이 길어진다 — 관제탑에서 시작해 접근관제, 상위 섹터, 그 위 ACC 까지 올라가고,
복귀할 때 역순으로 내려온다. 남동측으로 벗어나면 고도와 무관하게 중원 APP 이
인수하므로, 수직 사슬과 측방 이양은 **별개 경로**다.

고시 2-1-15 — 합의된 위치·고도에서, 충돌요인을 제거한 뒤 이양하며, **통신 인수가
곧 관제책임 인수**다. 그래서 이양은 순간이 아니라 조건을 만족해야 하는 절차이고,
이 모듈은 그 조건 충족 여부까지 함께 낸다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .sector import SectorModel, resolve_altitude_ft
from .state import AircraftState


class HandoffDirection(Enum):
    CLIMB = "상승 이양"
    """더 높은 단계로 넘긴다 — 출격."""

    DESCEND = "강하 인수"
    """더 낮은 단계로 받는다 — 복귀."""

    LATERAL = "측방 이양"
    """수직 사슬이 아니라 옆 관제소로."""


@dataclass(frozen=True)
class HandoffStep:
    """사슬의 한 단계."""

    unit: str
    lower_ft: float
    upper_ft: float
    source: str

    def covers(self, alt_ft: float) -> bool:
        return self.lower_ft <= alt_ft < self.upper_ft


@dataclass(frozen=True)
class HandoffEvent:
    """실제로 일어난 이양 한 건."""

    t_s: float
    callsign: str
    direction: HandoffDirection
    from_unit: str
    to_unit: str
    alt_ft: float
    conditions_met: bool
    blocking_reason: str = ""

    def describe(self) -> str:
        mark = "" if self.conditions_met else f"  [보류 — {self.blocking_reason}]"
        return (
            f"{int(self.t_s // 60):02d}:{int(self.t_s % 60):02d} {self.callsign} "
            f"{self.from_unit} → {self.to_unit} ({self.alt_ft:,.0f}ft){mark}"
        )


@dataclass
class HandoffChain:
    """고도별 관제기관 사슬과 이양 판정.

    경계 고도를 코드에 두지 않는다 — 공역 블록(T17, T17_UPPER)과 관제권(CTR)의
    전사 상한을 그대로 읽는다.
    """

    ds: object
    sector: SectorModel

    steps: tuple[HandoffStep, ...] = field(init=False, default=())
    lateral_unit: str = field(init=False, default="")
    _cfg: dict = field(init=False, repr=False)

    def __post_init__(self) -> None:
        air = self.ds.airspace.raw
        self._cfg = air["handoff"]["chain"]
        elev = self.ds.procedures.raw["aerodrome"]["elev_ft"]
        blocks = {b["id"]: b for b in air["tma"]["blocks"]}

        built: list[HandoffStep] = []
        for step in self._cfg["steps"]:
            src = step["from"]
            if src == "ctr":
                node = air["ctr"]
                lo = resolve_altitude_ft(node["lower"], elev)
                hi = resolve_altitude_ft(node["upper"], elev)
            elif src.startswith("tma:"):
                node = blocks[src.split(":", 1)[1]]
                lo = resolve_altitude_ft(node["lower"], elev)
                hi = resolve_altitude_ft(node["upper"], elev)
            elif src == "above":
                lo = built[-1].upper_ft
                hi = float("inf")
            else:
                raise ValueError(f"알 수 없는 사슬 출처: {src!r}")
            built.append(HandoffStep(step["unit"], lo, hi, src))
        self.steps = tuple(built)

        lat_block = self._cfg["lateral_unit_block"]
        self.lateral_unit = blocks[lat_block]["unit"]

    # ------------------------------------------------------------------

    def unit_at(self, alt_ft: float) -> str:
        """고도만으로 본 담당 기관. 측방 이탈은 보지 않는다."""
        for s in self.steps:
            if s.covers(alt_ft):
                return s.unit
        return self.steps[-1].unit

    def controller(self, ac: AircraftState) -> str:
        """실제 담당 기관 — 측방 이탈이 수직 사슬보다 우선한다.

        남동측 T19 로 벗어나면 고도와 무관하게 중원 APP 이 잡는다. 고도만 보면
        상승 중인 항적을 계속 OSAN APP 으로 표시하게 되어 이양 시점을 놓친다.
        """
        owner = self.sector.owner(ac)
        if owner == self.lateral_unit:
            return self.lateral_unit
        if self.sector.is_under_control(ac):
            # 청주 관할 안 — 관제권(TWR) 안이면 관제탑, 아니면 접근관제
            twr = self.steps[0]
            if twr.covers(ac.alt_ft) and self._within_ctr(ac):
                return twr.unit
            return self.steps[1].unit
        return self.unit_at(ac.alt_ft)

    def _within_ctr(self, ac: AircraftState) -> bool:
        from .geo import parse_latlon, separation_distance_nm

        ctr = self.ds.airspace.raw["ctr"]
        d = separation_distance_nm(
            ac.lat, ac.lon,
            parse_latlon(ctr["center"]["lat"]),
            parse_latlon(ctr["center"]["lon"]),
        )
        return d <= ctr["radius_nm"]

    # ------------------------------------------------------------------

    def transfer(
        self,
        before: AircraftState,
        after: AircraftState,
        *,
        conflicts_pending: bool = False,
        t_s: float | None = None,
    ) -> HandoffEvent | None:
        """두 시점 사이에 관제권이 바뀌었는가.

        고시 2-1-15 는 **충돌요인 제거 후** 이양하도록 한다. 해소되지 않은 충돌이
        걸려 있으면 이양 자체는 일어나되 '보류' 로 표시한다 — 조용히 넘기면
        인수 기관이 문제를 그대로 물려받는다.
        """
        a, b = self.controller(before), self.controller(after)
        if a == b:
            return None

        if b == self.lateral_unit or a == self.lateral_unit:
            direction = HandoffDirection.LATERAL
        elif after.alt_ft > before.alt_ft:
            direction = HandoffDirection.CLIMB
        else:
            direction = HandoffDirection.DESCEND

        return HandoffEvent(
            t_s=t_s if t_s is not None else after.t_s,
            callsign=after.callsign,
            direction=direction,
            from_unit=a,
            to_unit=b,
            alt_ft=after.alt_ft,
            conditions_met=not conflicts_pending,
            blocking_reason="충돌요인 미해소 (2-1-15)" if conflicts_pending else "",
        )

    def scan(
        self,
        track: list[AircraftState],
        *,
        pending_at: set[float] | None = None,
    ) -> list[HandoffEvent]:
        """한 항적의 전 구간에서 일어나는 이양들.

        `pending_at` 은 그 시각에 미해소 충돌이 있었던 시점의 집합이다.
        """
        pending = pending_at or set()
        out: list[HandoffEvent] = []
        for a, b in zip(track, track[1:]):
            ev = self.transfer(a, b, conflicts_pending=b.t_s in pending)
            if ev is not None:
                out.append(ev)
        return out


def build(ds, sector: SectorModel | None = None) -> HandoffChain:
    return HandoffChain(ds=ds, sector=sector or SectorModel.from_dataset(ds))
