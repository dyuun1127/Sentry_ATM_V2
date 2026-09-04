"""Approved Golden Demo maneuver application and post-action revalidation."""

from dataclasses import dataclass
from datetime import datetime

from sentry_atm.domain import (
    AircraftState,
    ConflictAssessmentRun,
    ConflictEvent,
    ConflictRiskAssessment,
    ControllerDecisionAuditEntry,
    ExceptionQueueSnapshot,
    OperationalPriorityAssessment,
    PredictionRun,
)
from sentry_atm.resolution.validator import apply_candidate_maneuver_to_state
from sentry_atm.runtime.decision_orchestrator import (
    GoldenDemoControllerDecisionOrchestrator,
)
from sentry_atm.simulation import SyntheticAircraftRuntime, TrafficSnapshot


@dataclass(frozen=True, slots=True)
class GoldenDemoApprovedManeuverApplicationResult:
    """Immutable actual-state and recalculation evidence after approved application."""

    application_step_id: str
    source_decision_step_id: str
    timestamp_utc: datetime
    decision_entry: ControllerDecisionAuditEntry
    before_state: AircraftState
    applied_state: AircraftState
    traffic_snapshot: TrafficSnapshot
    prediction_run: PredictionRun
    conflict_run: ConflictAssessmentRun
    risk_assessments: tuple[ConflictRiskAssessment, ...]
    priority_assessments: tuple[OperationalPriorityAssessment, ...]
    exception_queue_snapshot: ExceptionQueueSnapshot
    primary_conflict_after_application: ConflictEvent


class GoldenDemoApprovedManeuverOrchestrator:
    """Apply the audited CAND-A once and recalculate all traffic evidence."""

    __slots__ = (
        "_decision_orchestrator",
        "_last_result",
        "_last_tick_count",
        "_observed_reset_count",
    )

    def __init__(
        self,
        decision_orchestrator: GoldenDemoControllerDecisionOrchestrator,
    ) -> None:
        if not isinstance(
            decision_orchestrator,
            GoldenDemoControllerDecisionOrchestrator,
        ):
            raise TypeError(
                "decision_orchestrator must be a GoldenDemoControllerDecisionOrchestrator"
            )
        self._decision_orchestrator = decision_orchestrator
        clock = self._runtime.simulation.clock
        self._observed_reset_count = clock.reset_count
        self._last_tick_count: int | None = None
        self._last_result: GoldenDemoApprovedManeuverApplicationResult | None = None

    @property
    def decision_orchestrator(self) -> GoldenDemoControllerDecisionOrchestrator:
        return self._decision_orchestrator

    @property
    def last_result(self) -> GoldenDemoApprovedManeuverApplicationResult | None:
        _ = self._decision_orchestrator.last_result
        self._synchronize_reset()
        return self._last_result

    @property
    def _runtime(self):
        return self._decision_orchestrator.resolution_orchestrator.step_orchestrator.runtime

    def apply_and_revalidate(self) -> GoldenDemoApprovedManeuverApplicationResult:
        """Apply the accepted altitude Candidate and calculate post-action evidence."""

        decision_result = self._decision_orchestrator.last_result
        self._synchronize_reset()
        if decision_result is None:
            raise ValueError("an accepted Golden Demo Controller Decision is required")

        runtime = self._runtime
        resolution_result = self._decision_orchestrator.resolution_orchestrator.last_result
        if resolution_result is None:  # pragma: no cover - Decision implies a Resolution
            raise ValueError("a Resolution is required before Maneuver Application")
        steps = self._decision_orchestrator.resolution_orchestrator.step_orchestrator
        step_result = steps.last_result
        if step_result is None:  # pragma: no cover - Decision implies a source Step
            raise ValueError("a Golden Demo Step is required before Maneuver Application")
        clock = runtime.simulation.clock
        # 적용은 승인과 같은 시각의 증거 위에서 이루어져야 한다. 시각 자체를
        # 못박지는 않는다 — 언제 승인할지는 상황이 정한다.
        if step_result.timestamp_utc != clock.current_time_utc:
            raise ValueError("the latest Golden Demo Step must match the current Clock")
        # 승인이 지난 시각의 것이면 적용하지 않는다. SAFE 판정은 그 시점의
        # 교통에 대해 계산된 것이고, 시간이 흐른 뒤에 그대로 적용하면 검증하지
        # 않은 상황에 검증된 기동을 넣는 것이 된다. T+90 고정이 우연히 지켜 주던
        # 성질이며, 고정을 걷어낸 자리에는 이 조건이 들어가야 한다.
        if decision_result.timestamp_utc != step_result.timestamp_utc:
            raise ValueError(
                "the Controller Decision must be contemporaneous with the current Step"
            )
        if self._last_tick_count == clock.tick_count:
            raise ValueError("a Golden Demo Maneuver Application already exists for this Tick")

        decision_entry = decision_result.decision_entry
        if runtime.controller_decision_service.last_audit_log is not decision_result.audit_log:
            raise ValueError("the accepted Decision must be current in the Audit Service")
        candidate = decision_entry.approved_candidate
        if candidate is None:  # pragma: no cover - ACCEPT Decision invariant
            raise ValueError("Controller Decision must authorize Candidate application")
        # 어느 후보가 승인되었는지는 상황이 정한다. 특정 후보 식별자나 고도를
        # 요구하면 그 값이 나오지 않는 상황에서는 승인해도 적용할 수 없다.
        target_aircraft_id = candidate.target_aircraft_id
        if target_aircraft_id is None:
            raise ValueError("an approved Candidate must target one Aircraft")

        aircraft_runtime = _synthetic_runtime_for_aircraft(
            runtime.simulation.engine.runtimes,
            target_aircraft_id,
        )
        before_state = aircraft_runtime.current_state
        if before_state is None:
            raise ValueError("target Aircraft must be active at application time")
        # 검증에 쓴 것과 같은 함수로 적용한다. 여기서 상태를 따로 고치면 검증한
        # 것과 적용한 것이 갈리고, SAFE 판정이 실제 기동을 보증하지 못한다.
        applied_state = apply_candidate_maneuver_to_state(before_state, candidate)
        aircraft_runtime.apply_state_anchor(applied_state)
        traffic_snapshot = runtime.simulation.engine.snapshot()

        tick_token = f"{clock.tick_count:012d}"
        prediction_run = runtime.prediction_scheduler.service.run(
            traffic_snapshot,
            prediction_run_id=f"POST-APPLY-PRED-{tick_token}",
            generated_at_utc=traffic_snapshot.timestamp_utc,
        )
        conflict_run = runtime.conflict_scheduler.service.run(
            traffic_snapshot,
            assessment_run_id=f"POST-APPLY-CONFLICT-{tick_token}",
        )
        risk_assessments = tuple(
            runtime.risk_evaluator.evaluate(event) for event in conflict_run.assessments
        )
        priority_assessments = tuple(
            runtime.priority_evaluator.evaluate(state, runtime.definition.events)
            for state in traffic_snapshot.states
        )
        queue_snapshot = runtime.exception_queue_service.refresh(
            traffic_snapshot.timestamp_utc,
            risk_assessments=risk_assessments,
            priority_assessments=priority_assessments,
        )
        # 적용 뒤에 다시 보는 것은 이 판단이 대상으로 삼았던 그 짝이다. 짝을
        # 못박으면 다른 짝을 푼 결과를 확인할 수 없다.
        source_pair = resolution_result.source_exception.assessment.pair.aircraft_ids
        primary_conflict = next(
            (
                event
                for event in conflict_run.assessments
                if event.pair.aircraft_ids == source_pair
            ),
            None,
        )
        if primary_conflict is None:
            raise ValueError(
                "the resolved Conflict Pair must be re-evaluated after application"
            )
        result = GoldenDemoApprovedManeuverApplicationResult(
            application_step_id=f"GOLDEN-APPLICATION-{tick_token}",
            source_decision_step_id=decision_result.decision_step_id,
            timestamp_utc=traffic_snapshot.timestamp_utc,
            decision_entry=decision_entry,
            before_state=before_state,
            applied_state=applied_state,
            traffic_snapshot=traffic_snapshot,
            prediction_run=prediction_run,
            conflict_run=conflict_run,
            risk_assessments=risk_assessments,
            priority_assessments=priority_assessments,
            exception_queue_snapshot=queue_snapshot,
            primary_conflict_after_application=primary_conflict,
        )
        self._last_tick_count = clock.tick_count
        self._last_result = result
        return result

    def _synchronize_reset(self) -> None:
        clock = self._runtime.simulation.clock
        if clock.reset_count == self._observed_reset_count:
            return
        for runtime in self._runtime.simulation.engine.runtimes:
            if isinstance(runtime, SyntheticAircraftRuntime):  # pragma: no branch
                _ = runtime.applied_states
        self._last_tick_count = None
        self._last_result = None
        self._observed_reset_count = clock.reset_count


def _synthetic_runtime_for_aircraft(
    runtimes: tuple,
    aircraft_id: str,
) -> SyntheticAircraftRuntime:
    matches = tuple(runtime for runtime in runtimes if runtime.aircraft_id == aircraft_id)
    if len(matches) != 1 or not isinstance(matches[0], SyntheticAircraftRuntime):
        raise ValueError("approved target must have one Synthetic Aircraft Runtime")
    return matches[0]
