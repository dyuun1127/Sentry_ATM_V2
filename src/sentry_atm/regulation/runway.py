"""활주로 자원 모델 — 출발과 도착이 같은 활주로를 두고 경합할 때.

공중 분리(5-5-4)와는 근거 조항이 다르다. 활주로는 한 번에 한 대만 쓰는 자원이고,
후행기가 얼마나 기다려야 하는가는 **선행기가 무엇을 했느냐**에 달렸다 — 착륙해서
활주로를 개방했는가(3-9-6 나), 이륙해서 종단을 통과했는가(3-9-6 가 / 3-10-3 가 2).

`sequencing.ArrivalSequencer` 는 착륙 슬롯만 다뤘다. 출발이 끼면 활주로가 도착
전용이 아니게 되므로, 배치 기준을 '착륙 간격'에서 '활주로 점유 구간'으로 바꾼다.

**후류는 두 군데서 온다.** 공중 종렬(5-5-4 사·아)은 거리 요건이고, 이륙 후류
(3-9-6 바)는 시간 요건이다. 같은 후류 현상이지만 조항도 단위도 다르므로 따로
계산해서 큰 쪽을 쓴다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum

FT_PER_NM = 6076.11548556


class Operation(Enum):
    """활주로 사용 종류. 선행·후행 조합마다 근거 조항이 다르다."""

    DEPARTURE = "출발"
    ARRIVAL = "도착"


@dataclass(frozen=True)
class RunwayOp:
    """활주로를 쓰는 한 대.

    `time_s` 는 출발이면 이륙활주 시작 시각, 도착이면 시단 통과 시각이다.
    두 시각의 기준점이 다르므로 조항별 계산에서 항상 어느 쪽인지 밝힌다.
    """

    callsign: str
    actype: str
    wake_cat: str
    op: Operation
    time_s: float = 0.0
    earliest_s: float = 0.0
    """이 시각보다 앞당길 수 없다 — 도착기의 물리적 도달시각, 출발기의 준비완료."""

    emergency: bool = False

    @property
    def is_departure(self) -> bool:
        return self.op is Operation.DEPARTURE


@dataclass(frozen=True)
class RunwayRequirement:
    """선행 → 후행 최소 간격과 근거."""

    seconds: float
    clauses: tuple[str, ...]
    rationale: str
    binding: str
    """무엇이 간격을 지배했는가 — 활주로개방 / 종단통과 / 이륙후류 / 공중종렬."""

    luaw_prohibited: bool = False
    """이륙위치 대기허가 금지 여부 (3-9-6 라)."""

    def __str__(self) -> str:
        return f"{self.seconds:.0f}s [{self.binding}] {', '.join(self.clauses)}"


@dataclass
class RunwayRules:
    """활주로 분리 해석기.

    수치는 전부 data/airspace.json 의 separation.runway 와 aircraft.json 에서 읽는다.
    이 클래스는 '언제 무엇을 쓰는가'만 안다.
    """

    ds: object
    runway: str = "24R"

    _cfg: dict = field(init=False, repr=False)
    _length_ft: float = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._cfg = self.ds.airspace.raw["separation"]["runway"]
        rwy = self.ds.procedures.runways[self.runway]
        self._length_ft = rwy.length_m / 0.3048

    # ------------------------------------------------------------------
    # 기초량
    # ------------------------------------------------------------------

    def srs_distance_ft(self, leader: RunwayOp, follower: RunwayOp) -> tuple[float, str]:
        """동일활주로 거리 최저치 (3-9-6 가 / 3-10-3 가).

        청주는 군 공항이라 헬기를 뺀 전 기종이 CAT III 이고, 따라서 실질적으로
        6,000ft 하나만 쓰인다. 그래도 조합을 따져 두는 이유는, 회전익이 들어오거나
        기준이 개정될 때 표만 고치면 되게 하기 위해서다.
        """
        tbl = self._cfg["same_runway_distance_ft"]
        fleet = self.ds.fleet
        a, b = fleet.srs_cat(leader.actype), fleet.srs_cat(follower.actype)
        if "CAT_III" in (a, b):
            return tbl["either_is_cat3"], "둘 중 하나가 CAT III"
        if b == "CAT_II":
            return tbl["cat2_behind_cat1_or_cat2"], "후행이 CAT II"
        return tbl["cat1_behind_cat1_or_cat2"], "양측 CAT I"

    def time_to_roll_distance_s(self, ac: RunwayOp, distance_ft: float) -> float:
        """이륙활주 시작 후 활주로 위 `distance_ft` 를 지나기까지의 시간.

        등가속을 가정한다 — 거리 ∝ t² 이므로 t(d) = T·√(d/L). 등속으로 보면
        같은 거리를 더 빨리 지나는 것으로 계산되어 간격이 짧아지므로, 등가속
        가정이 안전 측이다. T 는 종단 통과까지의 추정 활주시간, L 은 AIP 활주로 길이.
        """
        roll_s = self.ds.fleet.departure_roll_s(ac.actype, ac.wake_cat)
        if distance_ft >= self._length_ft:
            return roll_s
        return roll_s * math.sqrt(max(distance_ft, 0.0) / self._length_ft)

    def departure_wake_time_s(self, leader: RunwayOp, follower: RunwayOp) -> tuple[float, str]:
        """이륙 후류 시간간격 (3-9-6 바 1)·2)).

        선행기가 **이륙활주를 시작한 시점**부터 센다. 등급표에 없는 조합은 0 이다.
        """
        tbl = self._cfg["departure_wake_time_s"]
        row = tbl.get(leader.wake_cat)
        if not isinstance(row, dict):
            return 0.0, ""
        v = row.get(follower.wake_cat)
        if v is None:
            return 0.0, ""
        return float(v), f"{leader.wake_cat} 뒤 {follower.wake_cat} — {v:g}초"

    # ------------------------------------------------------------------
    # 조합별 요건
    # ------------------------------------------------------------------

    def requirement(self, leader: RunwayOp, follower: RunwayOp) -> RunwayRequirement:
        """선행 → 후행 최소 간격. 두 시각의 기준점 차이를 반영한다."""
        fleet = self.ds.fleet

        # --- 착륙 → 이륙 (3-9-6 나) : 선행기가 활주로를 개방해야 한다 ---
        if not leader.is_departure and follower.is_departure:
            rot = fleet.runway_occupancy_s(leader.actype, leader.wake_cat)
            return RunwayRequirement(
                seconds=rot,
                clauses=("3-9-6 나",),
                rationale=f"선행 착륙기 활주로 개방 — 점유 {rot:g}초",
                binding="활주로개방",
            )

        # --- 이륙 → 이륙 (3-9-6 가 + 바) ---
        if leader.is_departure and follower.is_departure:
            dist_ft, why = self.srs_distance_ft(leader, follower)
            t_dist = self.time_to_roll_distance_s(leader, dist_ft)
            t_wake, wake_why = self.departure_wake_time_s(leader, follower)

            if t_wake >= t_dist:
                return RunwayRequirement(
                    seconds=t_wake,
                    clauses=("3-9-6 바",),
                    rationale=f"이륙 후류 시간간격 — {wake_why}",
                    binding="이륙후류",
                    luaw_prohibited=self._luaw_prohibited(leader, follower),
                )
            return RunwayRequirement(
                seconds=t_dist,
                clauses=("3-9-6 가",),
                rationale=f"동일활주로 거리 {dist_ft:g}ft ({why}) 도달까지 {t_dist:.0f}초",
                binding="종단통과",
                luaw_prohibited=self._luaw_prohibited(leader, follower),
            )

        # --- 이륙 → 착륙 (3-10-3 가 2) 다)) ---
        if leader.is_departure and not follower.is_departure:
            dist_ft, why = self.srs_distance_ft(leader, follower)
            t_dist = self.time_to_roll_distance_s(leader, dist_ft)
            return RunwayRequirement(
                seconds=t_dist,
                clauses=("3-10-3 가 2)",),
                rationale=(
                    f"선행 이륙기가 시단에서 {dist_ft:g}ft ({why}) 확보 — {t_dist:.0f}초"
                ),
                binding="종단통과",
            )

        # --- 착륙 → 착륙 (3-10-3 가 1)) ---
        # 공중 종렬 요건(5-5-4 사·아)은 ArrivalSequencer 가 계산한다. 여기서는
        # 활주로 자원으로서의 하한만 준다 — 둘 중 큰 쪽이 실제 간격이 된다.
        rot = fleet.runway_occupancy_s(leader.actype, leader.wake_cat)
        return RunwayRequirement(
            seconds=rot,
            clauses=("3-10-3 가 1)",),
            rationale=f"선행 착륙기 활주로 개방 — 점유 {rot:g}초",
            binding="활주로개방",
        )

    def _luaw_prohibited(self, leader: RunwayOp, follower: RunwayOp) -> bool:
        """3-9-6 라 — 초대형·대형 뒤 소형에게 이륙위치 대기허가 금지.

        후류 시간간격을 활주로 위에서 소진하지 못하게 하는 조항이다. 대기 중에는
        간격이 줄지 않으므로, 이 조합은 후행기를 대기지점 밖에 세워 두어야 한다.
        """
        return leader.wake_cat in ("초대형", "대형") and follower.wake_cat == "소형"


# ----------------------------------------------------------------------
# 배치
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class RunwaySlot:
    """확정된 활주로 사용 구간."""

    op: RunwayOp
    time_s: float
    requirement: RunwayRequirement | None
    """앞 슬롯과의 요건. 첫 슬롯은 None."""

    @property
    def delay_s(self) -> float:
        return self.time_s - self.op.earliest_s


@dataclass(frozen=True)
class RunwaySchedule:
    slots: tuple[RunwaySlot, ...]

    @property
    def order(self) -> list[str]:
        return [s.op.callsign for s in self.slots]

    @property
    def makespan_s(self) -> float:
        if not self.slots:
            return 0.0
        return self.slots[-1].time_s - self.slots[0].time_s

    @property
    def total_delay_s(self) -> float:
        return sum(s.delay_s for s in self.slots)

    def by_callsign(self, callsign: str) -> RunwaySlot:
        for s in self.slots:
            if s.op.callsign == callsign:
                return s
        raise KeyError(callsign)

    def departures(self) -> list[RunwaySlot]:
        return [s for s in self.slots if s.op.is_departure]

    def arrivals(self) -> list[RunwaySlot]:
        return [s for s in self.slots if not s.op.is_departure]

    def max_gap_s(self) -> float:
        """가장 큰 슬롯 간격 — 활주로가 비는 구간을 본다."""
        if len(self.slots) < 2:
            return 0.0
        return max(
            b.time_s - a.time_s for a, b in zip(self.slots, self.slots[1:], strict=False)
        )


@dataclass
class RunwaySequencer:
    """출발·도착 혼합 활주로 배치.

    주어진 순서대로 놓되, 각 슬롯은 `earliest_s` 와 앞 슬롯의 요건 중 늦은 쪽에
    놓인다. 순서 자체를 고르는 일은 호출자(또는 최적화기)의 몫이다 — 선착순
    원칙(고시 2-1-4)을 어디까지 흔들 수 있는지는 규정 판단이지 배치 문제가 아니다.
    """

    rules: RunwayRules

    def lay_out(self, ops: list[RunwayOp], now_s: float = 0.0) -> RunwaySchedule:
        slots: list[RunwaySlot] = []
        t = now_s
        prev: RunwayOp | None = None
        for op in ops:
            if prev is None:
                t = max(now_s, op.earliest_s)
                slots.append(RunwaySlot(op=op, time_s=t, requirement=None))
            else:
                req = self.rules.requirement(prev, op)
                t = max(t + req.seconds, op.earliest_s)
                slots.append(RunwaySlot(op=op, time_s=t, requirement=req))
            prev = op
        return RunwaySchedule(slots=tuple(slots))

    def first_come_first_served(
        self, ops: list[RunwayOp], now_s: float = 0.0
    ) -> RunwaySchedule:
        """고시 2-1-4 선착순 — `earliest_s` 순서 그대로 놓는다."""
        return self.lay_out(sorted(ops, key=lambda o: o.earliest_s), now_s)

    def insert_emergency(
        self, ops: list[RunwayOp], subject: str, now_s: float = 0.0
    ) -> RunwaySchedule:
        """고시 2-1-4 가 — 조난 항공기를 물리적 최단 도달시각 기준으로 삽입한다.

        순번으로 밀어넣지 않는다. 아직 도달하지 못하는 자리에 넣으면 활주로가 비고
        뒤 항적 전체가 밀린다 — 도착 시퀀싱에서 이미 확인한 실패다.
        """
        rest = [o for o in ops if o.callsign != subject]
        target = next(o for o in ops if o.callsign == subject)
        order = sorted(rest, key=lambda o: o.earliest_s)
        for i in range(len(order) + 1):
            trial = order[:i] + [target] + order[i:]
            sched = self.lay_out(trial, now_s)
            if sched.by_callsign(subject).time_s <= target.earliest_s + 1e-6:
                return sched
        return self.lay_out(order + [target], now_s)


def build(ds, runway: str = "24R") -> RunwaySequencer:
    return RunwaySequencer(rules=RunwayRules(ds=ds, runway=runway))
