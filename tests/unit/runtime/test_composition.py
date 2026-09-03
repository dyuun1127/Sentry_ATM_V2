from datetime import UTC, datetime, timedelta

import pytest

from sentry_atm.api import (
    ControllerDecisionApiContract,
    ExceptionQueueApiContract,
    GoldenDemoPlaybackApiContract,
    RecommendationApiContract,
    RecommendationSetLookup,
    RecommendationSetSource,
)
from sentry_atm.domain import (
    AltitudeManeuver,
    CandidateCostEstimate,
    CandidateSafetyValidationResult,
    ConflictEvent,
    ConflictPair,
    ConflictStatus,
    RecommendationAvailability,
    RecommendationReasonCode,
    ResolutionCandidate,
    ResolutionObjective,
    ResolutionRecommendation,
    ResolutionRecommendationSet,
    ResolutionValidationReasonCode,
    ResolutionValidationVerdict,
    SeparationMinimum,
)
from sentry_atm.infrastructure.http import (
    ControllerDecisionWsgiApp,
    ExceptionQueueWsgiApp,
    RecommendationWsgiApp,
)
from sentry_atm.runtime import (
    InMemoryRecommendationCatalog,
    build_golden_demo_runtime,
)
from sentry_atm.scenario import GOLDEN_DEMO_SCENARIO_ID, GOLDEN_DEMO_START_UTC
from sentry_atm.simulation import ClockState

EVALUATED_AT = datetime(2026, 9, 1, 3, 1, 15, tzinfo=UTC)
RECOMMENDED_AT = EVALUATED_AT + timedelta(seconds=5)


def _recommendation_set(
    suffix: str = "A",
    *,
    generated_at=RECOMMENDED_AT,
) -> ResolutionRecommendationSet:
    candidate = ResolutionCandidate(
        candidate_id=f"CAND-{suffix}",
        target_aircraft_id="MIL-F01",
        maneuver=AltitudeManeuver(9_000),
        objective=ResolutionObjective.VERTICAL_SEPARATION,
        effective_from_utc=EVALUATED_AT,
        cost=CandidateCostEstimate(operational_cost_score=10),
    )
    conflict = ConflictEvent(
        conflict_id=f"CONFLICT-{suffix}",
        pair=ConflictPair("CIV-A02", "MIL-F01"),
        status=ConflictStatus.SAFE,
        evaluated_at_utc=EVALUATED_AT,
        closest_approach_time_utc=EVALUATED_AT + timedelta(seconds=120),
        minimum_separation=SeparationMinimum(1.356, 1_016.25),
        rule_profile_id="POC_TERMINAL_V1",
    )
    validation = CandidateSafetyValidationResult(
        validation_result_id=f"VALIDATION-{suffix}",
        candidate_id=candidate.candidate_id,
        evaluated_at_utc=EVALUATED_AT,
        verdict=ResolutionValidationVerdict.SAFE,
        primary_conflict=conflict,
        secondary_conflicts=(),
        performance_feasible=True,
        rule_violations=(),
        reason_codes=(ResolutionValidationReasonCode.PRIMARY_CONFLICT_RESOLVED,),
        validation_profile_id="POC_SAFETY_V1",
    )
    recommendation = ResolutionRecommendation(
        recommendation_id=f"RECOMMENDATION-{suffix}",
        rank=1,
        candidate=candidate,
        validation_result=validation,
        generated_at_utc=generated_at,
        reason_codes=tuple(RecommendationReasonCode),
        explanation="Validated safe recommendation",
    )
    return ResolutionRecommendationSet(
        recommendation_set_id=f"RECOMMENDATION-SET-{suffix}",
        source_exception_id=f"EXCEPTION-{suffix}",
        source_candidate_batch_id=f"BATCH-{suffix}",
        source_validation_run_id=f"RUN-{suffix}",
        generated_at_utc=generated_at,
        ranking_policy_id="POC_RECOMMENDATION_V1",
        availability=RecommendationAvailability.AVAILABLE,
        recommendations=(recommendation,),
    )


def test_composition_wires_one_shared_clock_and_all_core_services() -> None:
    runtime = build_golden_demo_runtime()
    clock = runtime.simulation.clock

    assert runtime.definition.scenario_id == GOLDEN_DEMO_SCENARIO_ID
    assert runtime.definition.start_time_utc == GOLDEN_DEMO_START_UTC
    assert len(runtime.definition.aircraft) == 8
    assert tuple(profile.profile_id for profile in runtime.performance_profiles) == (
        "AIRLINER-POC-V1",
        "FAST-JET-POC-V1",
        "TRANSPORT-POC-V1",
    )
    assert clock.state is ClockState.READY
    assert runtime.simulation.engine.clock is clock
    assert runtime.simulation.timeline.clock is clock
    assert runtime.prediction_scheduler.clock is clock
    assert runtime.conflict_scheduler.clock is clock
    assert runtime.prediction_scheduler.service.predictor.CONFIGURATION_ID == "BASELINE-CV-V1"
    assert runtime.conflict_scheduler.service.detector.rule_profile.profile_id == "POC_TERMINAL_V1"
    assert runtime.risk_evaluator.risk_policy.profile_id == "POC_RISK_V1"
    assert runtime.priority_evaluator.policy.profile_id == "POC_OPERATIONAL_PRIORITY_V1"
    assert runtime.exception_queue_service.policy.profile_id == "POC_EXCEPTION_QUEUE_V1"
    assert runtime.candidate_generator.profile.profile_id == "POC_RESOLUTION_V1"
    assert runtime.safety_validator.profile.profile_id == "POC_SAFETY_V1"
    assert runtime.recommendation_service.profile.profile_id == "POC_RECOMMENDATION_V1"


def test_composition_connects_catalog_services_apis_and_http_adapters() -> None:
    runtime = build_golden_demo_runtime()

    assert isinstance(runtime.recommendation_catalog, RecommendationSetSource)
    assert isinstance(runtime.recommendation_catalog, RecommendationSetLookup)
    assert isinstance(runtime.exception_queue_api, ExceptionQueueApiContract)
    assert isinstance(runtime.recommendation_api, RecommendationApiContract)
    assert isinstance(runtime.controller_decision_api, ControllerDecisionApiContract)
    assert isinstance(runtime.playback_api, GoldenDemoPlaybackApiContract)
    assert isinstance(runtime.exception_queue_http_app, ExceptionQueueWsgiApp)
    assert isinstance(runtime.recommendation_http_app, RecommendationWsgiApp)
    assert isinstance(runtime.controller_decision_http_app, ControllerDecisionWsgiApp)
    assert runtime.exception_queue_api.get_current() is None
    assert runtime.recommendation_api.get_current() is None
    assert runtime.controller_decision_api.get_current() is None


def test_build_does_not_start_clock_or_calculate_or_mutate_initial_traffic() -> None:
    runtime = build_golden_demo_runtime()

    assert runtime.simulation.engine.snapshot().states == runtime.definition.initial_states
    assert runtime.prediction_scheduler.last_run is None
    assert runtime.conflict_scheduler.last_run is None
    assert runtime.simulation.timeline.pending_events == runtime.definition.events
    assert runtime.exception_queue_service.last_snapshot is None
    assert runtime.controller_decision_service.last_audit_log is None
    assert runtime.recommendation_catalog.recommendation_sets == ()

    before_playback_read = runtime.simulation.engine.snapshot()
    assert runtime.playback_api.get_playback().frame_count == 301
    assert runtime.simulation.engine.snapshot() == before_playback_read
    assert runtime.simulation.clock.state is ClockState.READY


def test_repeated_builds_are_equal_at_boundary_but_have_independent_state() -> None:
    first = build_golden_demo_runtime()
    second = build_golden_demo_runtime()

    assert first.definition == second.definition
    assert first.simulation.engine.snapshot() == second.simulation.engine.snapshot()
    assert first.simulation.clock is not second.simulation.clock
    assert first.exception_queue_service is not second.exception_queue_service
    assert first.recommendation_catalog is not second.recommendation_catalog
    assert first.controller_decision_service is not second.controller_decision_service

    first.simulation.clock.play()
    first.simulation.engine.tick(steps=5)
    assert first.simulation.clock.elapsed_seconds == 5
    assert second.simulation.clock.elapsed_seconds == 0


def test_catalog_publishes_orders_and_looks_up_immutable_sets() -> None:
    catalog = InMemoryRecommendationCatalog()
    later = _recommendation_set("B", generated_at=RECOMMENDED_AT + timedelta(seconds=1))
    first = _recommendation_set("A")

    catalog.publish(first)
    catalog.publish(later)

    assert catalog.get_current_recommendation() is later
    assert catalog.get_recommendation_set(" RECOMMENDATION-SET-A ") is first
    assert catalog.get_recommendation_set("MISSING") is None
    assert catalog.recommendation_sets == (first, later)


def test_catalog_rejects_invalid_duplicate_and_time_regression_atomically() -> None:
    catalog = InMemoryRecommendationCatalog()
    current = _recommendation_set("A")
    catalog.publish(current)

    with pytest.raises(TypeError, match="ResolutionRecommendationSet"):
        catalog.publish("set")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="already exists"):
        catalog.publish(current)
    with pytest.raises(ValueError, match="cannot precede"):
        catalog.publish(
            _recommendation_set(
                "B",
                generated_at=RECOMMENDED_AT - timedelta(seconds=1),
            )
        )
    with pytest.raises(ValueError, match="recommendation_set_id"):
        catalog.get_recommendation_set(" ")

    assert catalog.recommendation_sets == (current,)
    assert catalog.get_current_recommendation() is current


def test_catalog_reset_restores_empty_initial_state() -> None:
    catalog = InMemoryRecommendationCatalog()
    catalog.publish(_recommendation_set())

    catalog.reset()

    assert catalog.recommendation_sets == ()
    assert catalog.get_current_recommendation() is None
    assert catalog.get_recommendation_set("RECOMMENDATION-SET-A") is None
