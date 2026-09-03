"""Authorized application of one safely revalidated controller modification."""

from dataclasses import dataclass
from datetime import datetime, timedelta

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
from sentry_atm.resolution import apply_candidate_maneuver_to_state
from sentry_atm.runtime.application_orchestrator import _synthetic_runtime_for_aircraft
from sentry_atm.runtime.modified_revalidation_orchestrator import (
    GoldenDemoModifiedManeuverRevalidationOrchestrator,
    GoldenDemoModifiedManeuverRevalidationResult,
)
from sentry_atm.simulation import SyntheticAircraftRuntime, TrafficSnapshot

_APPLICATION_AT_SECONDS = 90


@dataclass(frozen=True, slots=True)
class GoldenDemoValidatedModifiedManeuverApplicationResult:
    """Actual-state and post-action evidence for an authorized safe modification."""

    application_step_id: str
    source_revalidation_step_id: str
    source_decision_step_id: str
    authorization_id: str
    authorized_at_utc: datetime
    controller_position_id: str
    timestamp_utc: datetime
    decision_entry: ControllerDecisionAuditEntry
    modified_revalidation: GoldenDemoModifiedManeuverRevalidationResult
    before_state: AircraftState
    applied_state: AircraftState
    traffic_snapshot: TrafficSnapshot
    prediction_run: PredictionRun
    conflict_run: ConflictAssessmentRun
    risk_assessments: tuple[ConflictRiskAssessment, ...]
    priority_assessments: tuple[OperationalPriorityAssessment, ...]
    exception_queue_snapshot: ExceptionQueueSnapshot
    primary_conflict_after_application: ConflictEvent


class GoldenDemoValidatedModifiedManeuverApplicationOrchestrator:
    """Authorize and apply one SAFE modified Maneuver, then recalculate evidence."""

    __slots__ = (
        "_last_result",
        "_last_tick_count",
        "_modified_revalidation_orchestrator",
        "_observed_reset_count",
    )

    def __init__(
        self,
        modified_revalidation_orchestrator: (
            GoldenDemoModifiedManeuverRevalidationOrchestrator
        ),
    ) -> None:
        if not isinstance(
            modified_revalidation_orchestrator,
            GoldenDemoModifiedManeuverRevalidationOrchestrator,
        ):
            raise TypeError(
                "modified_revalidation_orchestrator must be a "
                "GoldenDemoModifiedManeuverRevalidationOrchestrator"
            )
        self._modified_revalidation_orchestrator = modified_revalidation_orchestrator
        clock = self._runtime.simulation.clock
        self._observed_reset_count = clock.reset_count
        self._last_tick_count: int | None = None
        self._last_result: GoldenDemoValidatedModifiedManeuverApplicationResult | None = None

    @property
    def modified_revalidation_orchestrator(
        self,
    ) -> GoldenDemoModifiedManeuverRevalidationOrchestrator:
        return self._modified_revalidation_orchestrator

    @property
    def last_result(self) -> GoldenDemoValidatedModifiedManeuverApplicationResult | None:
        _ = self._modified_revalidation_orchestrator.last_result
        self._synchronize_reset()
        return self._last_result

    @property
    def _runtime(self):
        return (
            self._modified_revalidation_orchestrator.decision_orchestrator
            .resolution_orchestrator.step_orchestrator.runtime
        )

    def authorize_apply_and_revalidate(
        self,
    ) -> GoldenDemoValidatedModifiedManeuverApplicationResult:
        """Treat this explicit call as operator authorization and apply only SAFE evidence."""

        revalidation = self._modified_revalidation_orchestrator.last_result
        self._synchronize_reset()
        if revalidation is None:
            raise ValueError("a modified Maneuver Revalidation is required before application")
        if not revalidation.validation_result.is_safe:
            raise ValueError("only a SAFE modified Maneuver may be authorized for application")

        runtime = self._runtime
        decision = self._modified_revalidation_orchestrator.decision_orchestrator
        step_result = decision.resolution_orchestrator.step_orchestrator.last_result
        if step_result is None:  # pragma: no cover - Revalidation implies a source Step
            raise ValueError("a Golden Demo Step is required before modified application")
        clock = runtime.simulation.clock
        expected_time = clock.start_time_utc + timedelta(seconds=_APPLICATION_AT_SECONDS)
        if step_result.timestamp_utc != clock.current_time_utc:
            raise ValueError("the latest Golden Demo Step must match the current Clock")
        if step_result.timestamp_utc != expected_time:
            raise ValueError("Golden Demo modified Maneuver Application must run at T+90 seconds")
        if revalidation.timestamp_utc != step_result.timestamp_utc:
            raise ValueError("modified Revalidation must match the current Golden Demo Step")
        if self._last_tick_count == clock.tick_count:
            raise ValueError("a modified Maneuver Application already exists for this Tick")
        decision_result = decision.last_result
        if decision_result is None:  # pragma: no cover - Revalidation implies Decision
            raise ValueError("a current modified Decision is required before application")
        if runtime.controller_decision_service.last_audit_log is not decision_result.audit_log:
            raise ValueError("the modified Decision must be current in the Audit Service")

        candidate = revalidation.modified_candidate
        target_aircraft_id = candidate.target_aircraft_id
        if target_aircraft_id is None:  # pragma: no cover - modified action invariant
            raise ValueError("modified Maneuver must target one Aircraft")
        aircraft_runtime = _synthetic_runtime_for_aircraft(
            runtime.simulation.engine.runtimes,
            target_aircraft_id,
        )
        before_state = aircraft_runtime.current_state
        if before_state is None:  # pragma: no cover - Golden Aircraft active at T+90
            raise ValueError("target Aircraft must be active at application time")
        applied_state = apply_candidate_maneuver_to_state(before_state, candidate)
        aircraft_runtime.apply_state_anchor(applied_state)
        traffic_snapshot = runtime.simulation.engine.snapshot()

        tick_token = f"{clock.tick_count:012d}"
        prediction_run = runtime.prediction_scheduler.service.run(
            traffic_snapshot,
            prediction_run_id=f"POST-MODIFIED-APPLY-PRED-{tick_token}",
            generated_at_utc=traffic_snapshot.timestamp_utc,
        )
        conflict_run = runtime.conflict_scheduler.service.run(
            traffic_snapshot,
            assessment_run_id=f"POST-MODIFIED-APPLY-CONFLICT-{tick_token}",
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
        primary_pair = revalidation.candidate_batch.conflict_pair.aircraft_ids
        primary_conflict = next(
            event
            for event in conflict_run.assessments
            if event.pair.aircraft_ids == primary_pair
        )
        decision_entry = revalidation.decision_entry
        result = GoldenDemoValidatedModifiedManeuverApplicationResult(
            application_step_id=f"GOLDEN-MODIFIED-APPLICATION-{tick_token}",
            source_revalidation_step_id=revalidation.revalidation_step_id,
            source_decision_step_id=revalidation.source_decision_step_id,
            authorization_id=f"GOLDEN-MODIFIED-AUTHORIZATION-{tick_token}",
            authorized_at_utc=traffic_snapshot.timestamp_utc,
            controller_position_id=decision_entry.controller_position_id,
            timestamp_utc=traffic_snapshot.timestamp_utc,
            decision_entry=decision_entry,
            modified_revalidation=revalidation,
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
