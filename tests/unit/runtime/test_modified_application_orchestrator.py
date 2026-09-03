from datetime import timedelta

import pytest

from sentry_atm.domain import AltitudeManeuver, ConflictStatus, ExceptionStatus, RiskLevel
from sentry_atm.runtime import (
    GoldenDemoControllerDecisionOrchestrator,
    GoldenDemoModifiedManeuverRevalidationOrchestrator,
    GoldenDemoResolutionOrchestrator,
    GoldenDemoStepOrchestrator,
    GoldenDemoValidatedModifiedManeuverApplicationOrchestrator,
    build_golden_demo_runtime,
)
from sentry_atm.scenario import GOLDEN_DEMO_START_UTC
from sentry_atm.simulation import SyntheticAircraftRuntime


def _at_modified_revalidation(target_altitude_ft: float = 8_800):
    runtime = build_golden_demo_runtime()
    steps = GoldenDemoStepOrchestrator(runtime)
    resolution = GoldenDemoResolutionOrchestrator(steps)
    decision = GoldenDemoControllerDecisionOrchestrator(resolution)
    revalidation = GoldenDemoModifiedManeuverRevalidationOrchestrator(decision)
    application = GoldenDemoValidatedModifiedManeuverApplicationOrchestrator(revalidation)
    runtime.simulation.clock.play()
    steps.step(75)
    resolution.resolve()
    steps.step(15)
    decision.modify(
        rationale="Controller selected additional vertical margin",
        modified_maneuver=AltitudeManeuver(target_altitude_ft),
    )
    revalidation.revalidate()
    return runtime, steps, resolution, decision, revalidation, application


def _mil_f01_runtime(runtime) -> SyntheticAircraftRuntime:
    selected = next(
        item for item in runtime.simulation.engine.runtimes if item.aircraft_id == "MIL-F01"
    )
    assert isinstance(selected, SyntheticAircraftRuntime)
    return selected


def test_safe_modified_maneuver_is_authorized_applied_and_recalculated() -> None:
    runtime, _, _, decision, revalidation, application = _at_modified_revalidation()
    audit_before = runtime.controller_decision_service.last_audit_log

    result = application.authorize_apply_and_revalidate()

    assert application.modified_revalidation_orchestrator is revalidation
    assert result.application_step_id == "GOLDEN-MODIFIED-APPLICATION-000000000090"
    assert result.source_revalidation_step_id == (
        "GOLDEN-MODIFIED-REVALIDATION-000000000090"
    )
    assert result.source_decision_step_id == "GOLDEN-DECISION-000000000090"
    assert result.authorization_id == "GOLDEN-MODIFIED-AUTHORIZATION-000000000090"
    assert result.authorized_at_utc == GOLDEN_DEMO_START_UTC + timedelta(seconds=90)
    assert result.controller_position_id == "RKTU-DEMO-CONTROLLER"
    assert result.modified_revalidation is revalidation.last_result
    assert result.decision_entry is decision.last_result.decision_entry
    assert result.before_state.aircraft_id == "MIL-F01"
    assert result.before_state.altitude_ft == pytest.approx(7_492.5)
    assert result.applied_state.altitude_ft == 8_800
    assert result.applied_state.vertical_speed_fpm == 0.0
    assert _mil_f01_runtime(runtime).applied_states == (result.applied_state,)
    assert result.prediction_run.prediction_run_id == (
        "POST-MODIFIED-APPLY-PRED-000000000090"
    )
    assert result.conflict_run.assessment_run_id == (
        "POST-MODIFIED-APPLY-CONFLICT-000000000090"
    )
    assert len(result.conflict_run.assessments) == 28
    assert result.primary_conflict_after_application.status is ConflictStatus.SAFE
    assert result.primary_conflict_after_application.minimum_separation.horizontal_nm == (
        pytest.approx(2.3)
    )
    assert result.primary_conflict_after_application.minimum_separation.vertical_ft == (
        pytest.approx(1_591.6666666667)
    )
    primary_risk = next(
        item for item in result.risk_assessments if item.pair.aircraft_ids == ("CIV-A02", "MIL-F01")
    )
    assert primary_risk.risk_level is RiskLevel.LOW
    assert primary_risk.risk_score == 0.0
    source_item = next(
        item
        for item in result.exception_queue_snapshot.items
        if item.subject_aircraft_ids == ("CIV-A02", "MIL-F01")
    )
    assert source_item.status is ExceptionStatus.RESOLVED
    assert runtime.controller_decision_service.last_audit_log is audit_before
    assert runtime.simulation.engine.snapshot() == result.traffic_snapshot


def test_unsafe_modified_maneuver_cannot_be_authorized_or_applied() -> None:
    runtime, _, _, _, _, application = _at_modified_revalidation(7_200)
    traffic_before = runtime.simulation.engine.snapshot()

    with pytest.raises(ValueError, match="only a SAFE"):
        application.authorize_apply_and_revalidate()

    assert application.last_result is None
    assert _mil_f01_runtime(runtime).applied_states == ()
    assert runtime.simulation.engine.snapshot() == traffic_before


def test_modified_application_requires_revalidation_and_runs_once() -> None:
    with pytest.raises(TypeError, match="GoldenDemoModifiedManeuverRevalidationOrchestrator"):
        GoldenDemoValidatedModifiedManeuverApplicationOrchestrator(  # type: ignore[arg-type]
            "revalidation"
        )

    runtime = build_golden_demo_runtime()
    steps = GoldenDemoStepOrchestrator(runtime)
    resolution = GoldenDemoResolutionOrchestrator(steps)
    decision = GoldenDemoControllerDecisionOrchestrator(resolution)
    revalidation = GoldenDemoModifiedManeuverRevalidationOrchestrator(decision)
    application = GoldenDemoValidatedModifiedManeuverApplicationOrchestrator(revalidation)
    with pytest.raises(ValueError, match="Revalidation is required"):
        application.authorize_apply_and_revalidate()

    current_runtime, _, _, _, _, current_application = _at_modified_revalidation()
    first = current_application.authorize_apply_and_revalidate()
    with pytest.raises(ValueError, match="already exists"):
        current_application.authorize_apply_and_revalidate()
    assert current_application.last_result is first
    assert _mil_f01_runtime(current_runtime).applied_states == (first.applied_state,)


def test_reset_clears_modified_application_and_replays_equal_result() -> None:
    runtime, steps, resolution, decision, revalidation, application = (
        _at_modified_revalidation()
    )
    first = application.authorize_apply_and_revalidate()

    runtime.simulation.clock.reset()

    assert application.last_result is None
    assert revalidation.last_result is None
    assert _mil_f01_runtime(runtime).applied_states == ()

    runtime.simulation.clock.play()
    steps.step(75)
    resolution.resolve()
    steps.step(15)
    decision.modify(
        rationale="Controller selected additional vertical margin",
        modified_maneuver=AltitudeManeuver(8_800),
    )
    revalidation.revalidate()
    replayed = application.authorize_apply_and_revalidate()
    assert replayed == first
