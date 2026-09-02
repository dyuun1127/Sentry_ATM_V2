"""Deterministic Golden Demo exception-to-recommendation orchestration."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from sentry_atm.domain import (
    AircraftPerformanceProfile,
    ConflictExceptionItem,
    ExceptionStatus,
    ResolutionCandidateBatch,
    ResolutionRecommendationSet,
    ResolutionSafetyValidationRun,
    RiskLevel,
)
from sentry_atm.runtime.orchestrator import GoldenDemoStepOrchestrator
from sentry_atm.scenario import ScenarioAircraft

_RESOLUTION_AT_SECONDS = 75
_RESOLUTION_PAIR = ("CIV-A02", "MIL-F01")
_PREFERRED_TARGET_AIRCRAFT_ID = "MIL-F01"
_PREFERRED_ALTITUDE_FT = 9_000.0


@dataclass(frozen=True, slots=True)
class GoldenDemoResolutionResult:
    """Immutable evidence produced from one Golden Demo Conflict Exception."""

    resolution_step_id: str
    source_step_id: str
    timestamp_utc: datetime
    source_exception: ConflictExceptionItem
    candidate_batch: ResolutionCandidateBatch
    validation_run: ResolutionSafetyValidationRun
    recommendation_set: ResolutionRecommendationSet


class GoldenDemoResolutionOrchestrator:
    """Generate, validate, rank and publish the calibrated T+75 Resolution."""

    __slots__ = (
        "_last_result",
        "_last_tick_count",
        "_observed_reset_count",
        "_step_orchestrator",
    )

    def __init__(self, step_orchestrator: GoldenDemoStepOrchestrator) -> None:
        if not isinstance(step_orchestrator, GoldenDemoStepOrchestrator):
            raise TypeError("step_orchestrator must be a GoldenDemoStepOrchestrator")
        self._step_orchestrator = step_orchestrator
        self._observed_reset_count = step_orchestrator.runtime.simulation.clock.reset_count
        self._last_tick_count: int | None = None
        self._last_result: GoldenDemoResolutionResult | None = None

    @property
    def step_orchestrator(self) -> GoldenDemoStepOrchestrator:
        return self._step_orchestrator

    @property
    def last_result(self) -> GoldenDemoResolutionResult | None:
        _ = self._step_orchestrator.last_result
        self._synchronize_reset()
        return self._last_result

    def resolve(self) -> GoldenDemoResolutionResult:
        """Publish the SAFE ranked outcome for the current calibrated T+75 Step."""

        step_result = self._step_orchestrator.last_result
        self._synchronize_reset()
        if step_result is None:
            raise ValueError("a Golden Demo Step is required before Resolution")

        runtime = self._step_orchestrator.runtime
        clock = runtime.simulation.clock
        expected_time = clock.start_time_utc + timedelta(seconds=_RESOLUTION_AT_SECONDS)
        if step_result.timestamp_utc != clock.current_time_utc:
            raise ValueError("the latest Golden Demo Step must match the current Clock")
        if step_result.timestamp_utc != expected_time:
            raise ValueError("Golden Demo Resolution must run at T+75 seconds")
        if self._last_tick_count == clock.tick_count:
            raise ValueError("a Golden Demo Resolution already exists for the current Tick")

        source_exception = _select_source_exception(
            step_result.exception_queue_snapshot.active_items
        )
        pair_states = tuple(
            state
            for state in step_result.traffic_snapshot.states
            if state.aircraft_id in source_exception.subject_aircraft_ids
        )
        performance_profiles = _performance_profiles_for_pair(
            runtime.performance_profiles,
            runtime.definition.aircraft,
            source_exception.subject_aircraft_ids,
        )
        candidate_batch = runtime.candidate_generator.generate(
            source_exception,
            pair_states,
            performance_profiles,
            preferred_target_aircraft_id=_PREFERRED_TARGET_AIRCRAFT_ID,
            preferred_altitude_ft=_PREFERRED_ALTITUDE_FT,
        )
        validation_run = runtime.safety_validator.validate(
            candidate_batch,
            step_result.traffic_snapshot.states,
            performance_profiles,
        )
        recommendation_set = runtime.recommendation_service.recommend(
            candidate_batch,
            validation_run,
            generated_at_utc=step_result.timestamp_utc,
        )
        runtime.recommendation_catalog.publish(recommendation_set)

        result = GoldenDemoResolutionResult(
            resolution_step_id=f"GOLDEN-RESOLUTION-{clock.tick_count:012d}",
            source_step_id=step_result.step_id,
            timestamp_utc=step_result.timestamp_utc,
            source_exception=source_exception,
            candidate_batch=candidate_batch,
            validation_run=validation_run,
            recommendation_set=recommendation_set,
        )
        self._last_tick_count = clock.tick_count
        self._last_result = result
        return result

    def _synchronize_reset(self) -> None:
        reset_count = self._step_orchestrator.runtime.simulation.clock.reset_count
        if reset_count == self._observed_reset_count:
            return
        self._last_tick_count = None
        self._last_result = None
        self._observed_reset_count = reset_count


def _select_source_exception(items: tuple) -> ConflictExceptionItem:
    matches = tuple(
        item
        for item in items
        if isinstance(item, ConflictExceptionItem)
        and item.subject_aircraft_ids == _RESOLUTION_PAIR
        and item.status is not ExceptionStatus.RESOLVED
    )
    if len(matches) != 1:
        raise ValueError("one active CIV-A02 / MIL-F01 Conflict Exception is required")
    selected = matches[0]
    if selected.assessment.risk_level not in (RiskLevel.HIGH, RiskLevel.CRITICAL):
        raise ValueError("Golden Demo Resolution requires HIGH or CRITICAL Risk")
    return selected


def _performance_profiles_for_pair(
    profiles: tuple[AircraftPerformanceProfile, ...],
    scenario_aircraft: tuple[ScenarioAircraft, ...],
    aircraft_ids: tuple[str, str],
) -> dict[str, AircraftPerformanceProfile]:
    profile_by_id = {profile.profile_id: profile for profile in profiles}
    metadata_by_id = {item.aircraft_id: item.metadata for item in scenario_aircraft}
    try:
        return {
            aircraft_id: profile_by_id[metadata_by_id[aircraft_id].performance_class]
            for aircraft_id in aircraft_ids
        }
    except KeyError:
        raise ValueError(
            "Golden Demo Aircraft must reference an available Performance Profile"
        ) from None
