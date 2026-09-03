from datetime import timedelta

import pytest

from sentry_atm.domain import (
    AltitudeManeuver,
    ConflictStatus,
    ResolutionValidationVerdict,
)
from sentry_atm.runtime import (
    GoldenDemoControllerDecisionOrchestrator,
    GoldenDemoModifiedManeuverRevalidationOrchestrator,
    GoldenDemoResolutionOrchestrator,
    GoldenDemoStepOrchestrator,
    build_golden_demo_runtime,
)
from sentry_atm.scenario import GOLDEN_DEMO_START_UTC


def _at_modified_decision(target_altitude_ft: float = 8_800):
    runtime = build_golden_demo_runtime()
    steps = GoldenDemoStepOrchestrator(runtime)
    resolution = GoldenDemoResolutionOrchestrator(steps)
    decision = GoldenDemoControllerDecisionOrchestrator(resolution)
    revalidation = GoldenDemoModifiedManeuverRevalidationOrchestrator(decision)
    runtime.simulation.clock.play()
    steps.step(75)
    resolution.resolve()
    steps.step(15)
    decision.modify(
        rationale="Controller selected additional vertical margin",
        modified_maneuver=AltitudeManeuver(target_altitude_ft),
    )
    return runtime, steps, resolution, decision, revalidation


def test_modified_altitude_is_revalidated_safe_without_runtime_mutation() -> None:
    runtime, steps, _, decision, revalidation = _at_modified_decision()
    traffic_before = runtime.simulation.engine.snapshot()
    audit_before = runtime.controller_decision_service.last_audit_log

    result = revalidation.revalidate()

    assert revalidation.decision_orchestrator is decision
    assert result.revalidation_step_id == "GOLDEN-MODIFIED-REVALIDATION-000000000090"
    assert result.source_decision_step_id == "GOLDEN-DECISION-000000000090"
    assert result.timestamp_utc == GOLDEN_DEMO_START_UTC + timedelta(seconds=90)
    assert result.modified_candidate.target_aircraft_id == "MIL-F01"
    assert result.modified_candidate.maneuver == AltitudeManeuver(8_800)
    assert len(result.candidate_batch.candidates) == 2
    assert result.candidate_batch.baseline_candidate.target_aircraft_id is None
    assert result.validation_result.candidate_id == result.modified_candidate.candidate_id
    assert result.validation_result.verdict is ResolutionValidationVerdict.SAFE
    assert result.validation_result.primary_conflict.status is ConflictStatus.SAFE
    assert result.validation_result.primary_conflict.minimum_separation.horizontal_nm == (
        pytest.approx(2.3)
    )
    assert result.validation_result.primary_conflict.minimum_separation.vertical_ft == (
        pytest.approx(1_591.6666666667)
    )
    assert result.validation_result.secondary_conflicts == ()
    assert result.validation_result.performance_feasible
    assert result.validation_result.rule_violations == ()
    assert runtime.simulation.engine.snapshot() == traffic_before
    assert steps.last_result.traffic_snapshot == traffic_before
    assert runtime.controller_decision_service.last_audit_log is audit_before
    assert revalidation.last_result is result


def test_unsafe_modified_altitude_preserves_rule_and_conflict_evidence() -> None:
    runtime, _, _, _, revalidation = _at_modified_decision(7_200)
    traffic_before = runtime.simulation.engine.snapshot()

    result = revalidation.revalidate()
    validation = result.validation_result

    assert validation.verdict is ResolutionValidationVerdict.UNSAFE
    assert validation.primary_conflict.status is ConflictStatus.PREDICTED
    assert validation.primary_conflict.minimum_separation.vertical_ft == pytest.approx(
        8.3333333333
    )
    assert tuple(item.rule_id for item in validation.rule_violations) == (
        "POC-MINIMUM-CANDIDATE-ALTITUDE-V1",
    )
    assert runtime.simulation.engine.snapshot() == traffic_before


def test_revalidation_requires_current_modify_decision_and_runs_once() -> None:
    with pytest.raises(TypeError, match="GoldenDemoControllerDecisionOrchestrator"):
        GoldenDemoModifiedManeuverRevalidationOrchestrator("decision")  # type: ignore[arg-type]

    runtime = build_golden_demo_runtime()
    steps = GoldenDemoStepOrchestrator(runtime)
    resolution = GoldenDemoResolutionOrchestrator(steps)
    decision = GoldenDemoControllerDecisionOrchestrator(resolution)
    revalidation = GoldenDemoModifiedManeuverRevalidationOrchestrator(decision)
    with pytest.raises(ValueError, match="modified.*Decision"):
        revalidation.revalidate()

    runtime, _, _, _, accepted_revalidation = _at_modified_decision()
    first = accepted_revalidation.revalidate()
    with pytest.raises(ValueError, match="already exists"):
        accepted_revalidation.revalidate()
    assert accepted_revalidation.last_result is first
    assert runtime.controller_decision_service.revision == 1


def test_clock_reset_clears_modified_revalidation_and_replays_equal_result() -> None:
    runtime, steps, resolution, decision, revalidation = _at_modified_decision()
    first = revalidation.revalidate()

    runtime.simulation.clock.reset()

    assert revalidation.last_result is None
    assert decision.last_result is None
    assert resolution.last_result is None
    assert steps.last_result is None

    runtime.simulation.clock.play()
    steps.step(75)
    resolution.resolve()
    steps.step(15)
    decision.modify(
        rationale="Controller selected additional vertical margin",
        modified_maneuver=AltitudeManeuver(8_800),
    )
    replayed = revalidation.revalidate()
    assert replayed == first
