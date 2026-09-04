from datetime import timedelta

import pytest

import sentry_atm.runtime.application_orchestrator as application_orchestrator
from sentry_atm.domain import (
    ConflictStatus,
    ExceptionStatus,
    RiskLevel,
)
from sentry_atm.runtime import (
    GoldenDemoApprovedManeuverOrchestrator,
    GoldenDemoControllerDecisionOrchestrator,
    GoldenDemoResolutionOrchestrator,
    GoldenDemoStepOrchestrator,
    build_golden_demo_runtime,
)
from sentry_atm.scenario import GOLDEN_DEMO_START_UTC
from sentry_atm.simulation import SyntheticAircraftRuntime


def _at_accepted_decision():
    runtime = build_golden_demo_runtime()
    steps = GoldenDemoStepOrchestrator(runtime)
    resolution = GoldenDemoResolutionOrchestrator(steps)
    decision = GoldenDemoControllerDecisionOrchestrator(resolution)
    application = GoldenDemoApprovedManeuverOrchestrator(decision)
    runtime.simulation.clock.play()
    steps.step(75)
    resolution.resolve()
    steps.step(15)
    decision_result = decision.accept()
    return runtime, steps, resolution, decision, application, decision_result


def _mil_f01_runtime(runtime) -> SyntheticAircraftRuntime:
    selected = next(
        item for item in runtime.simulation.engine.runtimes if item.aircraft_id == "MIL-F01"
    )
    assert isinstance(selected, SyntheticAircraftRuntime)
    return selected


def test_accepted_cand_a_applies_and_recalculates_resolved_primary_conflict() -> None:
    runtime, _, _, decision, application, decision_result = _at_accepted_decision()
    decision_log_before = runtime.controller_decision_service.last_audit_log

    result = application.apply_and_revalidate()

    assert application.decision_orchestrator is decision
    assert result.application_step_id == "GOLDEN-APPLICATION-000000000090"
    assert result.source_decision_step_id == "GOLDEN-DECISION-000000000090"
    assert result.timestamp_utc == GOLDEN_DEMO_START_UTC + timedelta(seconds=90)
    assert result.decision_entry is decision_result.decision_entry
    assert result.before_state.aircraft_id == "MIL-F01"
    assert result.before_state.altitude_ft == pytest.approx(7_492.5)
    assert result.before_state.vertical_speed_fpm == 185.0
    assert result.applied_state.altitude_ft == 9_000.0
    assert result.applied_state.vertical_speed_fpm == 0.0
    assert result.applied_state.x_nm == result.before_state.x_nm
    assert result.applied_state.y_nm == result.before_state.y_nm
    assert _mil_f01_runtime(runtime).applied_states == (result.applied_state,)
    assert (
        next(state for state in result.traffic_snapshot.states if state.aircraft_id == "MIL-F01")
        is result.applied_state
    )
    assert result.prediction_run.prediction_run_id == "POST-APPLY-PRED-000000000090"
    assert result.conflict_run.assessment_run_id == "POST-APPLY-CONFLICT-000000000090"
    assert len(result.conflict_run.assessments) == 28
    assert result.conflict_run.predicted_events == ()
    assert result.primary_conflict_after_application.status is ConflictStatus.SAFE
    assert result.primary_conflict_after_application.minimum_separation.horizontal_nm == (
        pytest.approx(2.3)
    )
    assert result.primary_conflict_after_application.minimum_separation.vertical_ft == (
        pytest.approx(1_791.6666666667)
    )
    primary_risk = next(
        item for item in result.risk_assessments if item.pair.aircraft_ids == ("CIV-A02", "MIL-F01")
    )
    assert primary_risk.risk_level is RiskLevel.LOW
    assert primary_risk.risk_score == 0.0
    resolved_item = next(
        item
        for item in result.exception_queue_snapshot.items
        if item.subject_aircraft_ids == ("CIV-A02", "MIL-F01")
    )
    assert resolved_item.status is ExceptionStatus.RESOLVED
    assert runtime.exception_queue_service.last_snapshot is result.exception_queue_snapshot
    assert runtime.controller_decision_service.last_audit_log is decision_log_before
    assert application.last_result is result
    assert runtime.simulation.engine.snapshot() == result.traffic_snapshot


def test_identical_application_runs_produce_equal_post_action_evidence() -> None:
    first_runtime, _, _, _, first, _ = _at_accepted_decision()
    second_runtime, _, _, _, second, _ = _at_accepted_decision()

    first_result = first.apply_and_revalidate()
    second_result = second.apply_and_revalidate()

    assert first_result == second_result
    assert first_runtime.simulation.engine.snapshot() == second_runtime.simulation.engine.snapshot()


def test_application_requires_decision_time_freshness_audit_and_uniqueness() -> None:
    with pytest.raises(TypeError, match="GoldenDemoControllerDecisionOrchestrator"):
        GoldenDemoApprovedManeuverOrchestrator("decision")  # type: ignore[arg-type]

    runtime = build_golden_demo_runtime()
    steps = GoldenDemoStepOrchestrator(runtime)
    resolution = GoldenDemoResolutionOrchestrator(steps)
    decision = GoldenDemoControllerDecisionOrchestrator(resolution)
    application = GoldenDemoApprovedManeuverOrchestrator(decision)
    runtime.simulation.clock.play()
    steps.step(75)
    resolution.resolve()
    steps.step(15)
    with pytest.raises(ValueError, match="accepted.*Decision"):
        application.apply_and_revalidate()

    current_runtime, _, _, _, current_application, _ = _at_accepted_decision()
    first = current_application.apply_and_revalidate()
    with pytest.raises(ValueError, match="already exists"):
        current_application.apply_and_revalidate()
    assert current_application.last_result is first
    assert _mil_f01_runtime(current_runtime).applied_states == (first.applied_state,)

    # 시각을 못박는 대신 동시대성을 요구한다. 승인은 그 시점의 교통에 대해
    # 검증된 것이므로, 시간이 흐른 뒤 그대로 적용하면 검증하지 않은 상황에
    # 검증된 기동을 넣는 것이 된다.
    late_runtime, late_steps, _, _, late_application, _ = _at_accepted_decision()
    late_steps.step(5)
    with pytest.raises(ValueError, match="contemporaneous"):
        late_application.apply_and_revalidate()
    assert _mil_f01_runtime(late_runtime).applied_states == ()

    stale_runtime, _, _, _, stale_application, _ = _at_accepted_decision()
    stale_runtime.simulation.engine.tick(steps=5)
    with pytest.raises(ValueError, match="current Clock"):
        stale_application.apply_and_revalidate()
    assert _mil_f01_runtime(stale_runtime).applied_states == ()

    audit_runtime, _, _, _, audit_application, _ = _at_accepted_decision()
    audit_runtime.controller_decision_service.reset()
    with pytest.raises(ValueError, match="current in the Audit Service"):
        audit_application.apply_and_revalidate()
    assert _mil_f01_runtime(audit_runtime).applied_states == ()


def test_runtime_lookup_rejects_missing_approved_target() -> None:
    with pytest.raises(ValueError, match="one Synthetic"):
        application_orchestrator._synthetic_runtime_for_aircraft((), "MIL-F01")


def test_clock_reset_clears_applied_anchor_and_replays_equal_result() -> None:
    runtime, steps, resolution, decision, application, _ = _at_accepted_decision()
    first = application.apply_and_revalidate()
    aircraft_runtime = _mil_f01_runtime(runtime)
    assert aircraft_runtime.applied_states == (first.applied_state,)

    runtime.simulation.clock.reset()

    assert application.last_result is None
    assert decision.last_result is None
    assert resolution.last_result is None
    assert steps.last_result is None
    assert aircraft_runtime.applied_states == ()
    assert runtime.simulation.engine.snapshot().timestamp_utc == GOLDEN_DEMO_START_UTC

    runtime.simulation.clock.play()
    steps.step(75)
    resolution.resolve()
    steps.step(15)
    decision.accept()
    replayed = application.apply_and_revalidate()
    assert replayed == first
