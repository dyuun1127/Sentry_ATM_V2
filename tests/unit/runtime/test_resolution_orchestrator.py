from dataclasses import replace
from datetime import timedelta

import pytest

import sentry_atm.runtime.resolution_orchestrator as resolution_orchestrator
from sentry_atm.domain import (
    ConflictExceptionItem,
    RecommendationAvailability,
    ResolutionValidationReasonCode,
    ResolutionValidationVerdict,
    RiskLevel,
)
from sentry_atm.runtime import (
    GoldenDemoResolutionOrchestrator,
    GoldenDemoStepOrchestrator,
    build_golden_demo_runtime,
)
from sentry_atm.scenario import GOLDEN_DEMO_START_UTC


def _at_resolution_time():
    runtime = build_golden_demo_runtime()
    steps = GoldenDemoStepOrchestrator(runtime)
    resolution = GoldenDemoResolutionOrchestrator(steps)
    runtime.simulation.clock.play()
    step_result = steps.step(75)
    return runtime, steps, resolution, step_result


def test_t_plus_75_resolution_publishes_only_calculated_safe_candidate() -> None:
    runtime, steps, resolution, step_result = _at_resolution_time()
    traffic_before = runtime.simulation.engine.snapshot()

    result = resolution.resolve()

    assert resolution.step_orchestrator is steps
    assert result.resolution_step_id == "GOLDEN-RESOLUTION-000000000075"
    assert result.source_step_id == "GOLDEN-STEP-000000000075"
    assert result.timestamp_utc == GOLDEN_DEMO_START_UTC + timedelta(seconds=75)
    assert result.source_exception.exception_id == ("EXCEPTION-CONFLICT-7-CIV-A02-7-MIL-F01")
    assert result.source_exception.assessment.risk_level is RiskLevel.HIGH
    assert tuple(item.candidate_id for item in result.candidate_batch.candidates) == (
        "CAND-A",
        "CAND-B",
        "CAND-C",
        "CAND-D",
        "CAND-E",
    )
    verdict_by_id = {item.candidate_id: item.verdict for item in result.validation_run.results}
    assert verdict_by_id == {
        "CAND-A": ResolutionValidationVerdict.SAFE,
        "CAND-B": ResolutionValidationVerdict.UNSAFE,
        "CAND-C": ResolutionValidationVerdict.INEFFECTIVE,
        "CAND-D": ResolutionValidationVerdict.UNSAFE,
        "CAND-E": ResolutionValidationVerdict.UNSAFE,
    }
    validation_b = next(
        item for item in result.validation_run.results if item.candidate_id == "CAND-B"
    )
    assert ResolutionValidationReasonCode.SECONDARY_CONFLICT_DETECTED in (validation_b.reason_codes)
    assert tuple(event.pair.aircraft_ids for event in validation_b.secondary_conflicts) == (
        ("MIL-F01", "MIL-F02"),
    )
    assert result.recommendation_set.availability is RecommendationAvailability.AVAILABLE
    assert tuple(item.candidate_id for item in result.recommendation_set.recommendations) == (
        "CAND-A",
    )
    assert runtime.recommendation_catalog.get_current_recommendation() is (
        result.recommendation_set
    )
    assert resolution.last_result is result
    assert runtime.recommendation_api.get_current() is not None
    assert runtime.controller_decision_service.last_audit_log is None
    assert runtime.simulation.engine.snapshot() == traffic_before == step_result.traffic_snapshot


def test_identical_resolution_runs_produce_equal_auditable_outputs() -> None:
    first_runtime, _, first, _ = _at_resolution_time()
    second_runtime, _, second, _ = _at_resolution_time()

    first_result = first.resolve()
    second_result = second.resolve()

    assert first_result == second_result
    assert first_runtime.recommendation_catalog.recommendation_sets == (
        first_result.recommendation_set,
    )
    assert second_runtime.recommendation_catalog.recommendation_sets == (
        second_result.recommendation_set,
    )


def test_resolution_requires_constructor_step_time_freshness_and_uniqueness() -> None:
    with pytest.raises(TypeError, match="GoldenDemoStepOrchestrator"):
        GoldenDemoResolutionOrchestrator("steps")  # type: ignore[arg-type]

    runtime = build_golden_demo_runtime()
    steps = GoldenDemoStepOrchestrator(runtime)
    resolution = GoldenDemoResolutionOrchestrator(steps)
    with pytest.raises(ValueError, match="Step is required"):
        resolution.resolve()

    runtime.simulation.clock.play()
    steps.step(60)
    with pytest.raises(ValueError, match=r"T\+75"):
        resolution.resolve()

    fresh_runtime, _, fresh_resolution, _ = _at_resolution_time()
    first = fresh_resolution.resolve()
    with pytest.raises(ValueError, match="already exists"):
        fresh_resolution.resolve()
    assert fresh_resolution.last_result is first
    assert fresh_runtime.recommendation_catalog.recommendation_sets == (first.recommendation_set,)

    stale_runtime, _, stale_resolution, _ = _at_resolution_time()
    stale_runtime.simulation.engine.tick()
    with pytest.raises(ValueError, match="current Clock"):
        stale_resolution.resolve()
    assert stale_runtime.recommendation_catalog.recommendation_sets == ()


def test_resolution_rejects_missing_performance_reference_atomically() -> None:
    runtime = replace(build_golden_demo_runtime(), performance_profiles=())
    steps = GoldenDemoStepOrchestrator(runtime)
    resolution = GoldenDemoResolutionOrchestrator(steps)
    runtime.simulation.clock.play()
    steps.step(75)

    with pytest.raises(ValueError, match="available Performance Profile"):
        resolution.resolve()

    assert resolution.last_result is None
    assert runtime.recommendation_catalog.recommendation_sets == ()


def test_source_selection_requires_one_active_high_risk_golden_pair() -> None:
    _, _, _, step_result = _at_resolution_time()
    source = next(
        item
        for item in step_result.exception_queue_snapshot.active_items
        if isinstance(item, ConflictExceptionItem)
        and item.subject_aircraft_ids == ("CIV-A02", "MIL-F01")
    )

    with pytest.raises(ValueError, match="one active"):
        resolution_orchestrator._select_source_exception(())

    low_source = replace(
        source,
        assessment=replace(
            source.assessment,
            risk_level=RiskLevel.LOW,
            risk_score=0.0,
        ),
    )
    with pytest.raises(ValueError, match="HIGH or CRITICAL"):
        resolution_orchestrator._select_source_exception((low_source,))


def test_clock_reset_clears_resolution_and_catalog_then_replays_equal_result() -> None:
    runtime, steps, resolution, _ = _at_resolution_time()
    first = resolution.resolve()

    runtime.simulation.clock.reset()

    assert resolution.last_result is None
    assert steps.last_result is None
    assert runtime.recommendation_catalog.recommendation_sets == ()

    runtime.simulation.clock.play()
    steps.step(75)
    replayed = resolution.resolve()
    assert replayed == first
