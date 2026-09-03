"""접근 순서 재구성 단계 (시나리오 8.9 ~ 8.11).

비상 선언 뒤 전체 도착 열을 다시 세우고, 비상 처리 구간이 언제 끝났는지 판정한다.
앞 단계들과 같은 규약을 지킨다 — 계산만 하고 Runtime 을 바꾸지 않으며, 결과는
근거 코드와 함께 감사 가능한 형태로 남는다.

**순번으로 밀어넣지 않는다.** 비상기는 물리적으로 도달 가능한 가장 이른 자리에
들어가고, 이미 최종접근에 안정된 항공기는 움직이지 않는다(고시 2-1-4 가,
`ASM-023`, `ASM-026`).
"""

from __future__ import annotations

from dataclasses import dataclass
from math import hypot

from sentry_atm.domain import (
    AircraftState,
    ConflictStatus,
    EmergencyStatus,
    FlightPhase,
    OperationalPriorityLevel,
)
from sentry_atm.domain.approach_sequence import (
    _APPROACHING_PHASES,
    _PHASE_RANK,
    STABILISED_PHASES,
    ApproachOrderReasonCode,
    ApproachResequencingResult,
    ApproachSlot,
    EmergencySegmentStatus,
)
from sentry_atm.runtime.orchestrator import GoldenDemoStepResult

_SECONDS_PER_HOUR = 3_600.0


def _eta_seconds(state: AircraftState) -> float:
    """공항 기준점까지의 대략 도달시간.

    x/y 는 RKTU ARP 중심 국지좌표이므로 원점까지의 거리가 곧 잔여 거리다. 활공로
    정렬이나 선회를 반영하지 않는 근사이며, 순서를 세우는 데만 쓰고 슬롯 시각으로
    쓰지 않는다 — 그쪽은 활주로 자원 모델이 따로 계산한다.
    """
    distance_nm = hypot(state.x_nm, state.y_nm)
    speed_kt = max(state.ground_speed_kt, 1.0)
    return distance_nm / speed_kt * _SECONDS_PER_HOUR


def _sort_key(state: AircraftState) -> tuple[int, float, str]:
    return (
        _PHASE_RANK.get(state.flight_phase, len(_PHASE_RANK)),
        _eta_seconds(state),
        state.aircraft_id,
    )


@dataclass(frozen=True, slots=True)
class ApproachResequencingRun:
    """한 단계에서 나온 재구성 결과와 종료 판정."""

    step_id: str
    result: ApproachResequencingResult
    segment_status: EmergencySegmentStatus | None


class ApproachSequenceOrchestrator:
    """도착 열을 다시 세우고 비상 구간의 종료를 판정한다."""

    __slots__ = ()

    def resequence(self, step_result: GoldenDemoStepResult) -> ApproachResequencingRun | None:
        """이 단계의 접근 순서. 도착 열이 비어 있으면 None."""
        if not isinstance(step_result, GoldenDemoStepResult):
            raise TypeError("step_result must be a GoldenDemoStepResult")

        states = tuple(step_result.traffic_snapshot.states)
        emergency_id = self._emergency_aircraft_id(step_result)

        # 도착 열 — 접근 중인 항공기와, 도착으로 복귀하는 비상기.
        arriving = [
            state
            for state in states
            if state.flight_phase in _APPROACHING_PHASES or state.aircraft_id == emergency_id
        ]
        if not arriving:
            return None

        baseline = tuple(s.aircraft_id for s in sorted(arriving, key=_sort_key))
        by_id = {s.aircraft_id: s for s in arriving}

        stabilised = tuple(
            s.aircraft_id for s in arriving if s.flight_phase in STABILISED_PHASES
        )
        recommended = self._insert_emergency(baseline, by_id, emergency_id, stabilised)

        displaced = tuple(
            aircraft_id
            for aircraft_id in baseline
            if aircraft_id != emergency_id
            and recommended.index(aircraft_id) > baseline.index(aircraft_id)
        )

        slots = tuple(
            ApproachSlot(
                aircraft_id=aircraft_id,
                position=index + 1,
                eta_seconds=_eta_seconds(by_id[aircraft_id]),
                flight_phase=by_id[aircraft_id].flight_phase,
                stabilised=aircraft_id in stabilised,
                reason_codes=self._reasons(
                    aircraft_id, emergency_id, stabilised, displaced
                ),
            )
            for index, aircraft_id in enumerate(recommended)
        )

        result = ApproachResequencingResult(
            evaluated_at_utc=step_result.timestamp_utc,
            baseline_order=baseline,
            recommended_order=recommended,
            slots=slots,
            emergency_aircraft_id=emergency_id,
            displaced_aircraft_ids=displaced,
            stabilised_aircraft_ids=stabilised,
        )
        status = (
            self._segment_status(emergency_id, by_id.get(emergency_id), step_result)
            if emergency_id is not None
            else None
        )
        return ApproachResequencingRun(
            step_id=step_result.step_id, result=result, segment_status=status
        )

    # ------------------------------------------------------------------

    @staticmethod
    def _emergency_aircraft_id(step_result: GoldenDemoStepResult) -> str | None:
        """비상 우선권을 가진 항공기. 없으면 None.

        상태의 비상 플래그와 우선순위 평가 중 어느 쪽이든 잡히면 비상으로 본다 —
        선언 시점과 평가 시점이 한 틱 어긋나도 놓치지 않기 위해서다.
        """
        for assessment in step_result.priority_assessments:
            if assessment.priority_level is OperationalPriorityLevel.EMERGENCY:
                return assessment.aircraft_id
        for state in step_result.traffic_snapshot.states:
            if state.emergency_status is EmergencyStatus.DECLARED:
                return state.aircraft_id
        return None

    @staticmethod
    def _insert_emergency(
        baseline: tuple[str, ...],
        by_id: dict[str, AircraftState],
        emergency_id: str | None,
        stabilised: tuple[str, ...],
    ) -> tuple[str, ...]:
        """비상기를 도달 가능한 가장 이른 자리에 넣는다.

        안정된 항공기 뒤가 그 자리다. 그 앞으로 넣으면 최종접근에 들어선 항적을
        늦은 기동으로 흔들게 되고, 뒤로 더 밀면 우선권이 이름뿐이 된다.
        """
        if emergency_id is None or emergency_id not in baseline:
            return baseline
        rest = [a for a in baseline if a != emergency_id]
        cut = 0
        for aircraft_id in rest:
            if aircraft_id in stabilised:
                cut += 1
            else:
                break
        return tuple(rest[:cut] + [emergency_id] + rest[cut:])

    @staticmethod
    def _reasons(
        aircraft_id: str,
        emergency_id: str | None,
        stabilised: tuple[str, ...],
        displaced: tuple[str, ...],
    ) -> tuple[ApproachOrderReasonCode, ...]:
        codes: list[ApproachOrderReasonCode] = []
        if aircraft_id == emergency_id:
            codes.append(ApproachOrderReasonCode.EMERGENCY_PRIORITY)
            codes.append(ApproachOrderReasonCode.EARLIEST_REACHABLE)
        if aircraft_id in stabilised:
            codes.append(ApproachOrderReasonCode.STABILISED_ON_APPROACH)
        if aircraft_id in displaced:
            codes.append(ApproachOrderReasonCode.DISPLACED_BY_EMERGENCY)
        if not codes:
            codes.append(ApproachOrderReasonCode.FIRST_COME_FIRST_SERVED)
        return tuple(codes)

    @staticmethod
    def _segment_status(
        emergency_id: str,
        state: AircraftState | None,
        step_result: GoldenDemoStepResult,
    ) -> EmergencySegmentStatus:
        """비상 처리 구간이 끝났는가 (시나리오 8.11).

        순서를 바꾼 것만으로는 끝난 것이 아니다. 비상기가 최종접근에 들어섰고,
        그 기체가 걸린 미해소 충돌이 없어야 끝났다고 본다.
        """
        established = state is not None and state.flight_phase in STABILISED_PHASES
        conflicting = [
            event
            for event in (
                step_result.conflict_run.assessments if step_result.conflict_run else ()
            )
            if event.status is ConflictStatus.PREDICTED
            and emergency_id in event.pair.aircraft_ids
        ]
        conflict_free = not conflicting
        if not established:
            phase = state.flight_phase.value if state is not None else FlightPhase.UNKNOWN.value
            reason = f"{emergency_id} 최종접근 미도달 (현재 {phase})"
        elif not conflict_free:
            reason = f"{emergency_id} 미해소 충돌 {len(conflicting)}건"
        else:
            reason = f"{emergency_id} 최종접근 안정, 미해소 충돌 없음"
        return EmergencySegmentStatus(
            aircraft_id=emergency_id,
            complete=established and conflict_free,
            established_on_approach=established,
            conflict_free=conflict_free,
            reason=reason,
        )


__all__ = ["ApproachResequencingRun", "ApproachSequenceOrchestrator"]
