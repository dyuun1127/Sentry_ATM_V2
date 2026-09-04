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

    # 시각을 못박지 않는다. 거부 사유는 "시계가 T+75 가 아니다" 가 아니라
    # "상신할 예외가 없다" 이다. 골든 데모에서 HIGH 충돌은 T+60 에 생기므로
    # 그 전에는 올릴 것이 없다.
    runtime.simulation.clock.play()
    steps.step(55)
    with pytest.raises(ValueError, match="HIGH or CRITICAL"):
        resolution.resolve()

    # 예외가 생긴 뒤에는 보정된 시각을 기다리지 않는다. T+75 고정은 15초를
    # 그냥 기다리고 있었다.
    early_runtime = build_golden_demo_runtime()
    early_steps = GoldenDemoStepOrchestrator(early_runtime)
    early_runtime.simulation.clock.play()
    early_steps.step(60)
    assert GoldenDemoResolutionOrchestrator(early_steps).resolve() is not None

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


def test_source_selection_takes_the_most_severe_active_exception() -> None:
    """대상 예외는 기체 짝이 아니라 심각도로 고른다.

    특정 짝을 못박으면 그 짝이 없는 시나리오에서는 상신 자체가 성립하지 않는다.
    """
    _, _, _, step_result = _at_resolution_time()
    source = next(
        item
        for item in step_result.exception_queue_snapshot.active_items
        if isinstance(item, ConflictExceptionItem)
    )

    with pytest.raises(ValueError, match="HIGH or CRITICAL"):
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

    # 심각한 쪽이 뽑힌다.
    critical = replace(
        source,
        exception_id="EXCEPTION-CONFLICT-ZZZ",
        assessment=replace(source.assessment, risk_level=RiskLevel.CRITICAL),
    )
    chosen = resolution_orchestrator._select_source_exception((source, critical))
    assert chosen is critical

    # 같은 심각도면 식별자로 정한다 — 순서가 흔들리면 같은 입력에서 다른 회피안이
    # 나오고, 시연에서 무엇을 보여 주는지 설명할 수 없다.
    twin = replace(source, exception_id="EXCEPTION-CONFLICT-0000")
    assert resolution_orchestrator._select_source_exception((source, twin)) is twin
    assert resolution_orchestrator._select_source_exception((twin, source)) is twin


def test_preferred_target_never_moves_priority_or_stabilised_traffic() -> None:
    """기동시킬 항공기를 규칙으로 정한다 — 콜사인으로 정하지 않는다."""
    from dataclasses import replace as dc_replace

    from sentry_atm.domain import EmergencyStatus, EmergencyType, FlightPhase

    runtime, _, _, step_result = _at_resolution_time()
    states = {s.aircraft_id: s for s in step_result.traffic_snapshot.states}
    civil = states["CIV-A02"]
    fast = states["MIL-F01"]
    profiles = resolution_orchestrator._performance_profiles_for_pair(
        runtime.performance_profiles,
        runtime.definition.aircraft,
        ("CIV-A02", "MIL-F01"),
    )

    # 기본: 수직 여유가 큰 쪽. 전투기가 여객기보다 상승률이 크다.
    assert (
        resolution_orchestrator._preferred_target_aircraft_id((civil, fast), profiles)
        == "MIL-F01"
    )

    # 비상 선언한 항공기는 움직이지 않는다 (고시 2-1-4 가).
    emergency_fast = dc_replace(
        fast,
        emergency_status=EmergencyStatus.DECLARED,
        emergency_type=EmergencyType.PRIORITY_RETURN,
    )
    assert (
        resolution_orchestrator._preferred_target_aircraft_id(
            (civil, emergency_fast), profiles
        )
        == "CIV-A02"
    )

    # 최종접근에 안정된 항공기도 움직이지 않는다.
    final_fast = dc_replace(fast, flight_phase=FlightPhase.FINAL)
    assert (
        resolution_orchestrator._preferred_target_aircraft_id((civil, final_fast), profiles)
        == "CIV-A02"
    )

    # 둘 다 건드릴 수 없으면 조용히 한쪽을 고르지 않는다.
    final_civil = dc_replace(civil, flight_phase=FlightPhase.FINAL)
    with pytest.raises(ValueError, match="neither Conflict Pair"):
        resolution_orchestrator._preferred_target_aircraft_id(
            (final_civil, emergency_fast), profiles
        )


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
