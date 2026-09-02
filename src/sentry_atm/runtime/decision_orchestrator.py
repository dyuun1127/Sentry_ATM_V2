"""Deterministic Golden Demo controller ACCEPT audit orchestration."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from sentry_atm.domain import (
    ControllerDecisionAuditEntry,
    ControllerDecisionAuditLog,
    ControllerDecisionType,
    ResolutionRecommendation,
)
from sentry_atm.runtime.resolution_orchestrator import GoldenDemoResolutionOrchestrator

_DECISION_AT_SECONDS = 90
_EXPECTED_CANDIDATE_ID = "CAND-A"
_CONTROLLER_POSITION_ID = "RKTU-DEMO-CONTROLLER"


@dataclass(frozen=True, slots=True)
class GoldenDemoControllerDecisionResult:
    """Immutable evidence for the Golden Demo controller ACCEPT action."""

    decision_step_id: str
    source_step_id: str
    source_resolution_step_id: str
    timestamp_utc: datetime
    selected_recommendation: ResolutionRecommendation
    decision_entry: ControllerDecisionAuditEntry
    audit_log: ControllerDecisionAuditLog


class GoldenDemoControllerDecisionOrchestrator:
    """Record the calibrated T+90 CAND-A ACCEPT without applying its Maneuver."""

    __slots__ = (
        "_last_result",
        "_last_tick_count",
        "_observed_reset_count",
        "_resolution_orchestrator",
    )

    def __init__(self, resolution_orchestrator: GoldenDemoResolutionOrchestrator) -> None:
        if not isinstance(resolution_orchestrator, GoldenDemoResolutionOrchestrator):
            raise TypeError("resolution_orchestrator must be a GoldenDemoResolutionOrchestrator")
        self._resolution_orchestrator = resolution_orchestrator
        clock = resolution_orchestrator.step_orchestrator.runtime.simulation.clock
        self._observed_reset_count = clock.reset_count
        self._last_tick_count: int | None = None
        self._last_result: GoldenDemoControllerDecisionResult | None = None

    @property
    def resolution_orchestrator(self) -> GoldenDemoResolutionOrchestrator:
        return self._resolution_orchestrator

    @property
    def last_result(self) -> GoldenDemoControllerDecisionResult | None:
        _ = self._resolution_orchestrator.last_result
        self._synchronize_reset()
        return self._last_result

    def accept(self) -> GoldenDemoControllerDecisionResult:
        """Record the selected SAFE Recommendation as accepted at T+90."""

        resolution_result = self._resolution_orchestrator.last_result
        self._synchronize_reset()
        if resolution_result is None:
            raise ValueError("a Golden Demo Resolution is required before Controller Decision")

        steps = self._resolution_orchestrator.step_orchestrator
        step_result = steps.last_result
        if step_result is None:  # pragma: no cover - Resolution implies a source Step
            raise ValueError("a Golden Demo Step is required before Controller Decision")
        runtime = steps.runtime
        clock = runtime.simulation.clock
        expected_time = clock.start_time_utc + timedelta(seconds=_DECISION_AT_SECONDS)
        if step_result.timestamp_utc != clock.current_time_utc:
            raise ValueError("the latest Golden Demo Step must match the current Clock")
        if step_result.timestamp_utc != expected_time:
            raise ValueError("Golden Demo Controller Decision must run at T+90 seconds")
        if self._last_tick_count == clock.tick_count:
            raise ValueError(
                "a Golden Demo Controller Decision already exists for the current Tick"
            )

        recommendation_set = resolution_result.recommendation_set
        if runtime.recommendation_catalog.get_current_recommendation() is not recommendation_set:
            raise ValueError("the Golden Demo Recommendation must be current in the Catalog")
        recommendation = recommendation_set.primary_recommendation
        if (  # pragma: no cover - calibrated Resolution invariant
            recommendation is None or recommendation.candidate_id != _EXPECTED_CANDIDATE_ID
        ):
            raise ValueError("the Golden Demo primary Recommendation must be CAND-A")

        audit_log = runtime.controller_decision_service.decide(
            recommendation_set,
            recommendation.recommendation_id,
            ControllerDecisionType.ACCEPT,
            decided_at_utc=step_result.timestamp_utc,
            controller_position_id=_CONTROLLER_POSITION_ID,
        )
        decision_entry = audit_log.latest_entry
        if decision_entry is None:  # pragma: no cover - successful decide always appends
            raise RuntimeError("Controller Decision Service returned an empty Audit Log")
        result = GoldenDemoControllerDecisionResult(
            decision_step_id=f"GOLDEN-DECISION-{clock.tick_count:012d}",
            source_step_id=step_result.step_id,
            source_resolution_step_id=resolution_result.resolution_step_id,
            timestamp_utc=step_result.timestamp_utc,
            selected_recommendation=recommendation,
            decision_entry=decision_entry,
            audit_log=audit_log,
        )
        self._last_tick_count = clock.tick_count
        self._last_result = result
        return result

    def _synchronize_reset(self) -> None:
        clock = self._resolution_orchestrator.step_orchestrator.runtime.simulation.clock
        if clock.reset_count == self._observed_reset_count:
            return
        self._last_tick_count = None
        self._last_result = None
        self._observed_reset_count = clock.reset_count
