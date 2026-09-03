"""Isolated revalidation of one controller-modified Golden Demo Maneuver."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from sentry_atm.domain import (
    AircraftPerformanceProfile,
    CandidateCostEstimate,
    CandidateSafetyValidationResult,
    ControllerDecisionAuditEntry,
    ControllerDecisionType,
    NoActionManeuver,
    ResolutionCandidate,
    ResolutionCandidateBatch,
    ResolutionManeuver,
    ResolutionManeuverType,
    ResolutionObjective,
    ResolutionSafetyValidationRun,
)
from sentry_atm.runtime.decision_orchestrator import (
    GoldenDemoControllerDecisionOrchestrator,
)

_REVALIDATION_AT_SECONDS = 90
_GENERATOR_PROFILE_ID = "CONTROLLER_MODIFICATION_V1"


@dataclass(frozen=True, slots=True)
class GoldenDemoModifiedManeuverRevalidationResult:
    """Immutable isolated evidence for one audited controller modification."""

    revalidation_step_id: str
    source_decision_step_id: str
    timestamp_utc: datetime
    decision_entry: ControllerDecisionAuditEntry
    modified_candidate: ResolutionCandidate
    candidate_batch: ResolutionCandidateBatch
    validation_run: ResolutionSafetyValidationRun
    validation_result: CandidateSafetyValidationResult


class GoldenDemoModifiedManeuverRevalidationOrchestrator:
    """Revalidate a MODIFY decision once without mutating Aircraft Runtime."""

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
        self._last_result: GoldenDemoModifiedManeuverRevalidationResult | None = None

    @property
    def decision_orchestrator(self) -> GoldenDemoControllerDecisionOrchestrator:
        return self._decision_orchestrator

    @property
    def last_result(self) -> GoldenDemoModifiedManeuverRevalidationResult | None:
        _ = self._decision_orchestrator.last_result
        self._synchronize_reset()
        return self._last_result

    @property
    def _runtime(self):
        return self._decision_orchestrator.resolution_orchestrator.step_orchestrator.runtime

    def revalidate(self) -> GoldenDemoModifiedManeuverRevalidationResult:
        """Validate the audited modified action against a copied T+90 snapshot."""

        decision_result = self._decision_orchestrator.last_result
        self._synchronize_reset()
        if decision_result is None:
            raise ValueError("a modified Golden Demo Controller Decision is required")
        decision_entry = decision_result.decision_entry
        if decision_entry.decision_type is not ControllerDecisionType.MODIFY:
            raise ValueError("Golden Demo modified revalidation requires a MODIFY Decision")

        resolution = self._decision_orchestrator.resolution_orchestrator
        resolution_result = resolution.last_result
        steps = resolution.step_orchestrator
        step_result = steps.last_result
        if resolution_result is None or step_result is None:  # pragma: no cover
            raise ValueError("Resolution and Step evidence are required for revalidation")
        runtime = steps.runtime
        clock = runtime.simulation.clock
        expected_time = clock.start_time_utc + timedelta(seconds=_REVALIDATION_AT_SECONDS)
        if step_result.timestamp_utc != clock.current_time_utc:
            raise ValueError("the latest Golden Demo Step must match the current Clock")
        if step_result.timestamp_utc != expected_time:
            raise ValueError("Golden Demo modified revalidation must run at T+90 seconds")
        if self._last_tick_count == clock.tick_count:
            raise ValueError("modified Maneuver revalidation already exists for this Tick")
        if runtime.controller_decision_service.last_audit_log is not decision_result.audit_log:
            raise ValueError("the modified Decision must be current in the Audit Service")

        modified_maneuver = decision_entry.modified_maneuver
        if modified_maneuver is None:  # pragma: no cover - MODIFY Domain invariant
            raise ValueError("MODIFY Decision must contain a modified Maneuver")
        timestamp = step_result.timestamp_utc
        tick_token = f"{clock.tick_count:012d}"
        modified_candidate = ResolutionCandidate(
            candidate_id=f"CONTROLLER-MODIFIED-{tick_token}",
            target_aircraft_id=decision_entry.recommendation.candidate.target_aircraft_id,
            maneuver=modified_maneuver,
            objective=_objective_for_maneuver(modified_maneuver),
            effective_from_utc=timestamp,
            cost=CandidateCostEstimate(),
        )
        baseline = ResolutionCandidate(
            candidate_id=f"CONTROLLER-BASELINE-{tick_token}",
            target_aircraft_id=None,
            maneuver=NoActionManeuver(),
            objective=ResolutionObjective.BASELINE_COMPARISON,
            effective_from_utc=timestamp,
            cost=CandidateCostEstimate(),
        )
        source_batch = resolution_result.candidate_batch
        batch = ResolutionCandidateBatch(
            candidate_batch_id=f"CONTROLLER-MODIFIED-BATCH-{tick_token}",
            source_exception_id=source_batch.source_exception_id,
            source_conflict_id=source_batch.source_conflict_id,
            conflict_pair=source_batch.conflict_pair,
            generated_at_utc=timestamp,
            generator_profile_id=_GENERATOR_PROFILE_ID,
            candidates=(modified_candidate, baseline),
        )
        traffic_snapshot = step_result.traffic_snapshot
        validation_run = runtime.safety_validator.validate(
            batch,
            traffic_snapshot.states,
            _performance_profiles_for_pair(runtime, source_batch.conflict_pair.aircraft_ids),
        )
        validation_result = next(
            item
            for item in validation_run.results
            if item.candidate_id == modified_candidate.candidate_id
        )
        result = GoldenDemoModifiedManeuverRevalidationResult(
            revalidation_step_id=f"GOLDEN-MODIFIED-REVALIDATION-{tick_token}",
            source_decision_step_id=decision_result.decision_step_id,
            timestamp_utc=timestamp,
            decision_entry=decision_entry,
            modified_candidate=modified_candidate,
            candidate_batch=batch,
            validation_run=validation_run,
            validation_result=validation_result,
        )
        self._last_tick_count = clock.tick_count
        self._last_result = result
        return result

    def _synchronize_reset(self) -> None:
        clock = self._runtime.simulation.clock
        if clock.reset_count == self._observed_reset_count:
            return
        self._last_tick_count = None
        self._last_result = None
        self._observed_reset_count = clock.reset_count


_OBJECTIVE_BY_MANEUVER_TYPE = {
    ResolutionManeuverType.HEADING: ResolutionObjective.LATERAL_SEPARATION,
    ResolutionManeuverType.ALTITUDE: ResolutionObjective.VERTICAL_SEPARATION,
    ResolutionManeuverType.SPEED: ResolutionObjective.TIME_SEPARATION,
    ResolutionManeuverType.ENTRY_DELAY: ResolutionObjective.TIME_SEPARATION,
    ResolutionManeuverType.SEQUENCE_CHANGE: ResolutionObjective.SEQUENCE_MANAGEMENT,
}


def _objective_for_maneuver(maneuver: ResolutionManeuver) -> ResolutionObjective:
    try:
        return _OBJECTIVE_BY_MANEUVER_TYPE[maneuver.maneuver_type]
    except KeyError:
        raise ValueError("modified revalidation requires an action Maneuver") from None


def _performance_profiles_for_pair(
    runtime,
    aircraft_ids: tuple[str, str],
) -> dict[str, AircraftPerformanceProfile]:
    profile_by_id = {item.profile_id: item for item in runtime.performance_profiles}
    metadata_by_id = {
        item.aircraft_id: item.metadata for item in runtime.definition.aircraft
    }
    try:
        return {
            aircraft_id: profile_by_id[metadata_by_id[aircraft_id].performance_class]
            for aircraft_id in aircraft_ids
        }
    except KeyError:
        raise ValueError(
            "Golden Demo Aircraft must reference an available Performance Profile"
        ) from None
