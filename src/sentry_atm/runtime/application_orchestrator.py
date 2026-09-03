"""Approved Golden Demo maneuver application and post-action revalidation."""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from sentry_atm.domain import (
    AircraftState,
    AltitudeManeuver,
    ConflictAssessmentRun,
    ConflictEvent,
    ConflictRiskAssessment,
    ControllerDecisionAuditEntry,
    ExceptionQueueSnapshot,
    OperationalPriorityAssessment,
    PredictionRun,
)
from sentry_atm.runtime.decision_orchestrator import (
    GoldenDemoControllerDecisionOrchestrator,
)
from sentry_atm.simulation import SyntheticAircraftRuntime, TrafficSnapshot

_APPLICATION_AT_SECONDS = 90
_EXPECTED_CANDIDATE_ID = "CAND-A"
_EXPECTED_TARGET_AIRCRAFT_ID = "MIL-F01"
_EXPECTED_TARGET_ALTITUDE_FT = 9_000.0
_RESOLVED_PAIR = ("CIV-A02", "MIL-F01")


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
        steps = self._decision_orchestrator.resolution_orchestrator.step_orchestrator
        step_result = steps.last_result
        if step_result is None:  # pragma: no cover - Decision implies a source Step
            raise ValueError("a Golden Demo Step is required before Maneuver Application")
        clock = runtime.simulation.clock
        expected_time = clock.start_time_utc + timedelta(seconds=_APPLICATION_AT_SECONDS)
        if step_result.timestamp_utc != clock.current_time_utc:
            raise ValueError("the latest Golden Demo Step must match the current Clock")
        if step_result.timestamp_utc != expected_time:
            raise ValueError("Golden Demo Maneuver Application must run at T+90 seconds")
        if self._last_tick_count == clock.tick_count:
            raise ValueError("a Golden Demo Maneuver Application already exists for this Tick")

        decision_entry = decision_result.decision_entry
        if runtime.controller_decision_service.last_audit_log is not decision_result.audit_log:
            raise ValueError("the accepted Decision must be current in the Audit Service")
        candidate = decision_entry.approved_candidate
        if candidate is None:  # pragma: no cover - ACCEPT Decision invariant
            raise ValueError("Controller Decision must authorize Candidate application")
        maneuver = candidate.maneuver
        if (  # pragma: no cover - calibrated Decision invariant
            candidate.candidate_id != _EXPECTED_CANDIDATE_ID
            or candidate.target_aircraft_id != _EXPECTED_TARGET_AIRCRAFT_ID
            or not isinstance(maneuver, AltitudeManeuver)
            or maneuver.target_altitude_ft != _EXPECTED_TARGET_ALTITUDE_FT
        ):
            raise ValueError("Golden Demo Application requires CAND-A altitude 9000 ft")

        aircraft_runtime = _synthetic_runtime_for_aircraft(
            runtime.simulation.engine.runtimes,
            candidate.target_aircraft_id,
        )
        before_state = aircraft_runtime.current_state
        if before_state is None:  # pragma: no cover - Golden aircraft is active at T+90
            raise ValueError("target Aircraft must be active at application time")
        applied_state = replace(
            before_state,
            altitude_ft=maneuver.target_altitude_ft,
            vertical_speed_fpm=0.0,
        )
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
        primary_conflict = next(
            event for event in conflict_run.assessments if event.pair.aircraft_ids == _RESOLVED_PAIR
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
