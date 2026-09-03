from datetime import timedelta

import pytest

from sentry_atm.domain import (
    AltitudeManeuver,
    ControllerDecisionType,
)
from sentry_atm.runtime import (
    GoldenDemoControllerDecisionOrchestrator,
    GoldenDemoResolutionOrchestrator,
    GoldenDemoStepOrchestrator,
    build_golden_demo_runtime,
)
from sentry_atm.scenario import GOLDEN_DEMO_START_UTC


def _at_decision_time():
    runtime = build_golden_demo_runtime()
    steps = GoldenDemoStepOrchestrator(runtime)
    resolution = GoldenDemoResolutionOrchestrator(steps)
    decision = GoldenDemoControllerDecisionOrchestrator(resolution)
    runtime.simulation.clock.play()
    steps.step(75)
    resolution_result = resolution.resolve()
    decision_step = steps.step(15)
    return runtime, steps, resolution, decision, resolution_result, decision_step


def test_t_plus_90_accept_records_audit_without_applying_maneuver() -> None:
    runtime, _, resolution, decision, resolution_result, decision_step = _at_decision_time()
    traffic_before = runtime.simulation.engine.snapshot()

    result = decision.accept()

    assert decision.resolution_orchestrator is resolution
    assert result.decision_step_id == "GOLDEN-DECISION-000000000090"
    assert result.source_step_id == "GOLDEN-STEP-000000000090"
    assert result.source_resolution_step_id == "GOLDEN-RESOLUTION-000000000075"
    assert result.timestamp_utc == GOLDEN_DEMO_START_UTC + timedelta(seconds=90)
    assert result.selected_recommendation.candidate_id == "CAND-A"
    assert result.selected_recommendation.candidate.target_aircraft_id == "MIL-F01"
    assert result.selected_recommendation.candidate.maneuver == AltitudeManeuver(9_000)
    assert result.decision_entry.decision_type is ControllerDecisionType.ACCEPT
    assert result.decision_entry.controller_position_id == "RKTU-DEMO-CONTROLLER"
    assert result.decision_entry.rationale is None
    assert result.decision_entry.modified_maneuver is None
    assert result.decision_entry.authorizes_application
    assert not result.decision_entry.requires_revalidation
    assert result.decision_entry.approved_candidate is (result.selected_recommendation.candidate)
    assert result.audit_log.revision == 1
    assert result.audit_log.entries == (result.decision_entry,)
    assert runtime.controller_decision_service.last_audit_log is result.audit_log
    assert runtime.controller_decision_api.get_current() is not None
    assert runtime.recommendation_catalog.get_current_recommendation() is (
        resolution_result.recommendation_set
    )
    assert decision.last_result is result
    assert runtime.simulation.engine.snapshot() == traffic_before == decision_step.traffic_snapshot


@pytest.mark.parametrize(
    ("decision_type", "rationale", "modified_maneuver"),
    [
        (
            ControllerDecisionType.MODIFY,
            "Maintain additional vertical margin",
            AltitudeManeuver(8_800),
        ),
        (ControllerDecisionType.REJECT, "Coordinate a different sector strategy", None),
    ],
)
def test_modify_and_reject_are_audited_without_applying_runtime_state(
    decision_type: ControllerDecisionType,
    rationale: str,
    modified_maneuver: AltitudeManeuver | None,
) -> None:
    runtime, _, _, decision, _, decision_step = _at_decision_time()
    traffic_before = runtime.simulation.engine.snapshot()

    if decision_type is ControllerDecisionType.MODIFY:
        result = decision.modify(
            rationale=rationale,
            modified_maneuver=modified_maneuver,  # type: ignore[arg-type]
        )
    else:
        result = decision.reject(rationale=rationale)

    assert result.decision_entry.decision_type is decision_type
    assert result.decision_entry.rationale == rationale
    assert result.decision_entry.modified_maneuver == modified_maneuver
    assert not result.decision_entry.authorizes_application
    assert result.decision_entry.requires_revalidation is (
        decision_type is ControllerDecisionType.MODIFY
    )
    assert result.decision_entry.approved_candidate is None
    assert runtime.simulation.engine.snapshot() == traffic_before == decision_step.traffic_snapshot


def test_identical_decision_runs_produce_equal_audit_evidence() -> None:
    first_runtime, _, _, first, _, _ = _at_decision_time()
    second_runtime, _, _, second, _, _ = _at_decision_time()

    first_result = first.accept()
    second_result = second.accept()

    assert first_result == second_result
    assert first_runtime.controller_decision_service.current_entries == (
        first_result.decision_entry,
    )
    assert second_runtime.controller_decision_service.current_entries == (
        second_result.decision_entry,
    )


def test_decision_requires_resolution_time_freshness_catalog_and_uniqueness() -> None:
    with pytest.raises(TypeError, match="GoldenDemoResolutionOrchestrator"):
        GoldenDemoControllerDecisionOrchestrator("resolution")  # type: ignore[arg-type]

    runtime = build_golden_demo_runtime()
    steps = GoldenDemoStepOrchestrator(runtime)
    resolution = GoldenDemoResolutionOrchestrator(steps)
    decision = GoldenDemoControllerDecisionOrchestrator(resolution)
    runtime.simulation.clock.play()
    steps.step(90)
    with pytest.raises(ValueError, match="Resolution is required"):
        decision.accept()

    early_runtime = build_golden_demo_runtime()
    early_steps = GoldenDemoStepOrchestrator(early_runtime)
    early_resolution = GoldenDemoResolutionOrchestrator(early_steps)
    early_decision = GoldenDemoControllerDecisionOrchestrator(early_resolution)
    early_runtime.simulation.clock.play()
    early_steps.step(75)
    early_resolution.resolve()
    with pytest.raises(ValueError, match=r"T\+90"):
        early_decision.accept()

    current_runtime, _, _, current_decision, _, _ = _at_decision_time()
    first = current_decision.accept()
    with pytest.raises(ValueError, match="already exists"):
        current_decision.accept()
    assert current_decision.last_result is first
    assert current_runtime.controller_decision_service.revision == 1

    stale_runtime, _, _, stale_decision, _, _ = _at_decision_time()
    stale_runtime.simulation.engine.tick()
    with pytest.raises(ValueError, match="current Clock"):
        stale_decision.accept()
    assert stale_runtime.controller_decision_service.revision == 0

    missing_runtime, _, _, missing_decision, _, _ = _at_decision_time()
    missing_runtime.recommendation_catalog.reset()
    with pytest.raises(ValueError, match="current in the Catalog"):
        missing_decision.accept()
    assert missing_runtime.controller_decision_service.revision == 0


def test_clock_reset_clears_decision_audit_then_replays_equal_result() -> None:
    runtime, steps, resolution, decision, _, _ = _at_decision_time()
    first = decision.accept()

    runtime.simulation.clock.reset()

    assert decision.last_result is None
    assert resolution.last_result is None
    assert steps.last_result is None
    assert runtime.controller_decision_service.last_audit_log is None
    assert runtime.controller_decision_service.revision == 0
    assert runtime.recommendation_catalog.recommendation_sets == ()

    runtime.simulation.clock.play()
    steps.step(75)
    resolution.resolve()
    steps.step(15)
    replayed = decision.accept()
    assert replayed == first
