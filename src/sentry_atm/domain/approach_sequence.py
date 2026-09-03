"""접근 순서 재구성 — 비상 항공기를 넣고 나머지를 다시 세운 결과.

고시 2-1-4 는 선착순을 원칙으로 두고 가항에서 조난 항공기에 최우선 통행권을 준다.
그 둘을 함께 지키려면 **순번으로 밀어넣지 않아야 한다.** 비상기를 아직 도달할 수
없는 자리에 세우면 그 자리가 비고 뒤 항적 전체가 밀린다.

또 하나, 이미 최종접근에 안정된 항공기는 움직이지 않는다. 늦은 기동은 그 자체가
위험이고(`ASM-023`, `ASM-026`), 비상기를 앞세우려고 안정된 항적을 흔드는 것은
안전을 한 곳에서 빼서 다른 곳에 넣는 것에 지나지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from sentry_atm.domain.enums import FlightPhase
from sentry_atm.domain.time_policy import to_utc
from sentry_atm.domain.units import as_non_negative_float
from sentry_atm.domain.validation import require_identifier


class ApproachOrderReasonCode(StrEnum):
    """한 자리가 왜 그 자리인지."""

    EMERGENCY_PRIORITY = "EMERGENCY_PRIORITY"
    """고시 2-1-4 가 — 조난 항공기 최우선 통행권."""

    STABILISED_ON_APPROACH = "STABILISED_ON_APPROACH"
    """최종접근에 안정됨 — 늦은 기동 위험 때문에 움직이지 않는다."""

    EARLIEST_REACHABLE = "EARLIEST_REACHABLE"
    """물리적으로 도달 가능한 가장 이른 자리."""

    FIRST_COME_FIRST_SERVED = "FIRST_COME_FIRST_SERVED"
    """고시 2-1-4 선착순 원칙."""

    DISPLACED_BY_EMERGENCY = "DISPLACED_BY_EMERGENCY"
    """비상기 삽입으로 한 자리 밀렸다."""


# 최종접근에 안정된 것으로 보는 단계. 이 단계의 항공기는 순서를 바꾸지 않는다.
STABILISED_PHASES = frozenset({FlightPhase.FINAL, FlightPhase.APPROACH})

# 접근 순서에 들어가는 단계. 상승 중이거나 단계를 모르는 항적은 도착 열이 아니다.
_APPROACHING_PHASES = frozenset({FlightPhase.FINAL, FlightPhase.APPROACH, FlightPhase.DESCENT})

# 정렬 시 단계가 갖는 우선순위. 거리·속도만 보면 6,000ft 에서 빠르게 강하 중인
# 항공기가 3,000ft 에 안정된 항공기보다 앞선다고 계산되는데, 접근 순서에서는
# 그렇지 않다.
_PHASE_RANK = {
    FlightPhase.FINAL: 0,
    FlightPhase.APPROACH: 1,
    FlightPhase.DESCENT: 2,
}


@dataclass(frozen=True, slots=True)
class ApproachSlot:
    """재구성된 순서에서 한 항공기가 차지한 자리."""

    aircraft_id: str
    position: int
    eta_seconds: float
    flight_phase: FlightPhase
    stabilised: bool
    reason_codes: tuple[ApproachOrderReasonCode, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "aircraft_id", require_identifier(self.aircraft_id, field_name="aircraft_id")
        )
        if isinstance(self.position, bool) or not isinstance(self.position, int):
            raise TypeError("position must be an integer")
        if self.position < 1:
            raise ValueError("position must start at 1")
        object.__setattr__(
            self, "eta_seconds", as_non_negative_float(self.eta_seconds, field_name="eta_seconds")
        )
        if not isinstance(self.flight_phase, FlightPhase):
            raise TypeError("flight_phase must be a FlightPhase")
        if not self.reason_codes:
            raise ValueError("reason_codes must not be empty")
        for code in self.reason_codes:
            if not isinstance(code, ApproachOrderReasonCode):
                raise TypeError("reason_codes must be ApproachOrderReasonCode values")


@dataclass(frozen=True, slots=True)
class ApproachResequencingResult:
    """비상 삽입 전후의 접근 순서와 그 근거."""

    evaluated_at_utc: datetime
    baseline_order: tuple[str, ...]
    recommended_order: tuple[str, ...]
    slots: tuple[ApproachSlot, ...]
    emergency_aircraft_id: str | None
    displaced_aircraft_ids: tuple[str, ...]
    stabilised_aircraft_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "evaluated_at_utc", to_utc(self.evaluated_at_utc))
        if sorted(self.baseline_order) != sorted(self.recommended_order):
            raise ValueError("recommended_order must be a permutation of baseline_order")
        if len(set(self.recommended_order)) != len(self.recommended_order):
            raise ValueError("recommended_order must not repeat an aircraft")
        if tuple(slot.aircraft_id for slot in self.slots) != self.recommended_order:
            raise ValueError("slots must follow recommended_order")

    @property
    def changed(self) -> bool:
        return self.baseline_order != self.recommended_order

    def position_of(self, aircraft_id: str) -> int:
        for slot in self.slots:
            if slot.aircraft_id == aircraft_id:
                return slot.position
        raise KeyError(aircraft_id)

    def moved_up(self, aircraft_id: str) -> bool:
        """이 항공기가 앞으로 당겨졌는가."""
        if aircraft_id not in self.baseline_order:
            return False
        return self.recommended_order.index(aircraft_id) < self.baseline_order.index(aircraft_id)


@dataclass(frozen=True, slots=True)
class EmergencySegmentStatus:
    """비상 처리 구간의 종료 판정.

    시나리오 8.11 은 "안전한 최종접근 상태 도달 + 이양 준비 완료"를 종료 조건으로
    둔다. 순서를 바꾼 것만으로 끝났다고 보면, 정작 비상기가 아직 위험한 상태인데
    화면은 정상으로 돌아간다.
    """

    aircraft_id: str
    complete: bool
    established_on_approach: bool
    conflict_free: bool
    reason: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "aircraft_id", require_identifier(self.aircraft_id, field_name="aircraft_id")
        )
        if self.complete != (self.established_on_approach and self.conflict_free):
            raise ValueError("complete must be both conditions together")


__all__ = [
    "STABILISED_PHASES",
    "ApproachOrderReasonCode",
    "ApproachResequencingResult",
    "ApproachSlot",
    "EmergencySegmentStatus",
]
