"""규정 계층을 한 단계에 붙인다 — 관할·활주로·체공·복귀경로.

각각 따로 오케스트레이터를 두지 않는 이유는, 넷 다 같은 질문의 다른 면이기
때문이다: **이 시점의 교통에 대해 고시는 무엇을 말하는가.** 넷을 나누면 같은 상태
변환과 같은 시각 처리를 네 번 반복하게 된다.

계산만 하고 Runtime 을 바꾸지 않는다. 앞 단계들과 같은 규약이다.
"""

from __future__ import annotations

from dataclasses import dataclass

from sentry_atm.domain import EmergencyStatus, FlightPhase
from sentry_atm.domain.approach_sequence import STABILISED_PHASES
from sentry_atm.regulation import data as regulation_data
from sentry_atm.regulation import handoff as handoff_module
from sentry_atm.regulation import hold as hold_module
from sentry_atm.regulation import route as route_module
from sentry_atm.regulation import runway as runway_module
from sentry_atm.regulation.bridge import to_geodetic_states
from sentry_atm.regulation.geo import separation_distance_nm
from sentry_atm.runtime.orchestrator import GoldenDemoStepResult

# 도착 열로 보는 비행단계. 상승 중인 항적은 활주로 도착 자원을 쓰지 않는다.
_ARRIVING = frozenset({FlightPhase.FINAL, FlightPhase.APPROACH, FlightPhase.DESCENT})


@dataclass(frozen=True, slots=True)
class ControlUnitAssignment:
    """한 항적을 지금 누가 관제하는가 (고시 2-1-15)."""

    aircraft_id: str
    unit: str
    altitude_ft: float
    lateral: bool
    """수직 사슬이 아니라 측방 이양으로 결정된 경우."""


@dataclass(frozen=True, slots=True)
class RunwaySlotAdvisory:
    """활주로 사용 한 자리와 그 근거 조항."""

    aircraft_id: str
    operation: str
    position: int
    distance_to_threshold_nm: float
    required_gap_seconds: float
    binding: str
    clauses: tuple[str, ...]
    line_up_and_wait_prohibited: bool


@dataclass(frozen=True, slots=True)
class HoldingAdvisory:
    """공고 체공장주 배정 (고시 4-6-1 ~ 4-6-7)."""

    aircraft_id: str
    fix: str
    level_ft: float
    circuits: int
    delay_seconds: float
    phraseology: str


@dataclass(frozen=True, slots=True)
class RecoveryRouteAdvisory:
    """비상 복귀 최단 경로."""

    aircraft_id: str
    fixes: tuple[str, ...]
    total_nm: float
    detour_nm: float
    clearance: str


@dataclass(frozen=True, slots=True)
class RegulatoryAdvisory:
    """한 단계에 적용되는 관제 절차 전부."""

    step_id: str
    control_units: tuple[ControlUnitAssignment, ...]
    runway_slots: tuple[RunwaySlotAdvisory, ...]
    holdings: tuple[HoldingAdvisory, ...]
    holding_refused: tuple[str, ...]
    recovery_route: RecoveryRouteAdvisory | None

    def unit_of(self, aircraft_id: str) -> str:
        for assignment in self.control_units:
            if assignment.aircraft_id == aircraft_id:
                return assignment.unit
        raise KeyError(aircraft_id)

    @property
    def units_in_use(self) -> tuple[str, ...]:
        return tuple(sorted({a.unit for a in self.control_units}))


class RegulatoryAdvisoryOrchestrator:
    """고시 계층을 단계 결과에 붙인다."""

    __slots__ = ("_book", "_chain", "_dataset", "_planner", "_runway", "_threshold")

    def __init__(self, dataset=None) -> None:
        self._dataset = dataset or regulation_data.load()
        self._chain = handoff_module.build(self._dataset)
        self._book = hold_module.build(self._dataset)
        self._planner = route_module.build(self._dataset)
        self._runway = runway_module.build(self._dataset)
        runway_spec = self._dataset.procedures.runways["24R"]
        self._threshold = (runway_spec.thr_lat, runway_spec.thr_lon)

    # ------------------------------------------------------------------

    def advise(self, step_result: GoldenDemoStepResult) -> RegulatoryAdvisory:
        if not isinstance(step_result, GoldenDemoStepResult):
            raise TypeError("step_result must be a GoldenDemoStepResult")

        local_states = tuple(step_result.traffic_snapshot.states)
        geodetic = to_geodetic_states(local_states)
        paired = tuple(zip(local_states, geodetic, strict=True))

        emergency = self._emergency_id(step_result, local_states)
        control_units = self._assign_units(paired)
        runway_slots = self._runway_sequence(paired, emergency)
        holdings, refused = self._holdings(paired, emergency)
        route = self._recovery_route(paired, emergency)

        return RegulatoryAdvisory(
            step_id=step_result.step_id,
            control_units=control_units,
            runway_slots=runway_slots,
            holdings=holdings,
            holding_refused=refused,
            recovery_route=route,
        )

    # ------------------------------------------------------------------

    def _assign_units(self, paired) -> tuple[ControlUnitAssignment, ...]:
        lateral_unit = self._chain.lateral_unit
        return tuple(
            ControlUnitAssignment(
                aircraft_id=local.aircraft_id,
                unit=(unit := self._chain.controller(geo)),
                altitude_ft=local.altitude_ft,
                lateral=unit == lateral_unit,
            )
            for local, geo in paired
        )

    def _distance_to_threshold_nm(self, geo) -> float:
        return separation_distance_nm(geo.lat, geo.lon, *self._threshold)

    def _runway_sequence(
        self, paired, emergency: str | None = None
    ) -> tuple[RunwaySlotAdvisory, ...]:
        """도착 순서대로 활주로 요건을 매긴다.

        골든 데모에는 출발이 없으므로 지금은 도착만 나온다. 조합별 요건은
        출발이 섞여도 그대로 성립한다 — 규칙이 조합을 보고 고르기 때문이다.

        **비상 복귀기는 비행단계와 무관하게 넣는다.** 선언한 순간 그 항공기는
        활주로로 온다. 아직 순항 단계라는 이유로 열에서 빼면, 다른 항공기를 그
        항공기의 점유시간만큼 붙들면서 정작 자리는 잡아 주지 않는 상태가 되고,
        순서 재구성이 내놓는 열과도 어긋난다.
        """
        arriving = [
            (local, geo)
            for local, geo in paired
            if local.flight_phase in _ARRIVING or local.aircraft_id == emergency
        ]
        if not arriving:
            return ()
        arriving.sort(key=lambda item: self._distance_to_threshold_nm(item[1]))

        ops = [
            runway_module.RunwayOp(
                callsign=local.aircraft_id,
                actype=getattr(local, "aircraft_type", "") or "",
                wake_cat=geo.wake_cat,
                op=runway_module.Operation.ARRIVAL,
            )
            for local, geo in arriving
        ]

        advisories: list[RunwaySlotAdvisory] = []
        for index, ((local, geo), op) in enumerate(zip(arriving, ops, strict=True)):
            requirement = (
                self._runway.rules.requirement(ops[index - 1], op) if index else None
            )
            advisories.append(
                RunwaySlotAdvisory(
                    aircraft_id=local.aircraft_id,
                    operation=op.op.value,
                    position=index + 1,
                    distance_to_threshold_nm=round(self._distance_to_threshold_nm(geo), 2),
                    required_gap_seconds=round(requirement.seconds, 1) if requirement else 0.0,
                    binding=requirement.binding if requirement else "",
                    clauses=requirement.clauses if requirement else (),
                    line_up_and_wait_prohibited=bool(
                        requirement and requirement.luaw_prohibited
                    ),
                )
            )
        return tuple(advisories)

    @staticmethod
    def _emergency_id(step_result, local_states) -> str | None:
        from sentry_atm.domain import OperationalPriorityLevel

        for assessment in step_result.priority_assessments:
            if assessment.priority_level is OperationalPriorityLevel.EMERGENCY:
                return assessment.aircraft_id
        for state in local_states:
            if state.emergency_status is EmergencyStatus.DECLARED:
                return state.aircraft_id
        return None

    def _holdings(self, paired, emergency: str | None):
        """비상기가 자리를 차지하는 동안 도착기를 어디에 세울 것인가.

        필요한 시간은 비상기의 활주로 점유시간이다. 그보다 오래 붙들면 우선권과
        무관한 지연을 만들고, 짧게 잡으면 자리가 겹친다.

        **최종접근에 안정된 항공기는 세우지 않는다.** 순서 재구성에서 그 항공기를
        밀지 않기로 해 놓고 체공을 지시하면 같은 규칙을 한쪽에서만 지키는 것이
        되고, 늦은 기동의 위험은 순서를 바꾸든 붙들든 똑같이 생긴다
        (`ASM-023`, `ASM-026`).
        """
        if emergency is None:
            return (), ()

        emergency_state = next(
            (geo for local, geo in paired if local.aircraft_id == emergency), None
        )
        if emergency_state is None:
            return (), ()
        need_seconds = self._dataset.fleet.runway_occupancy_s(
            emergency_state.actype, emergency_state.wake_cat
        )

        requests = [
            (local.aircraft_id, geo.gs_kt, need_seconds)
            for local, geo in paired
            if local.aircraft_id != emergency
            and local.flight_phase in _ARRIVING
            and local.flight_phase not in STABILISED_PHASES
        ]
        if not requests:
            return (), ()

        placed, refused = self._book.stack(requests)
        return (
            tuple(
                HoldingAdvisory(
                    aircraft_id=item.callsign,
                    fix=item.pattern.fix,
                    level_ft=item.level_ft,
                    circuits=item.circuits,
                    delay_seconds=round(item.delay_s, 1),
                    phraseology=item.phraseology(),
                )
                for item in placed
            ),
            tuple(refused),
        )

    def _recovery_route(self, paired, emergency: str | None) -> RecoveryRouteAdvisory | None:
        if emergency is None:
            return None
        state = next((geo for local, geo in paired if local.aircraft_id == emergency), None)
        if state is None:
            return None
        route = self._planner.recovery(state)
        if route is None:
            return None
        return RecoveryRouteAdvisory(
            aircraft_id=emergency,
            fixes=tuple(route.fixes),
            total_nm=round(route.total_nm, 2),
            detour_nm=round(route.detour_nm, 2),
            clearance=route.clearance(emergency),
        )


__all__ = [
    "ControlUnitAssignment",
    "HoldingAdvisory",
    "RecoveryRouteAdvisory",
    "RegulatoryAdvisory",
    "RegulatoryAdvisoryOrchestrator",
    "RunwaySlotAdvisory",
]
