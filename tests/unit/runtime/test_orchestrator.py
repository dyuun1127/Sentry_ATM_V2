from datetime import timedelta

import pytest

from sentry_atm.domain import (
    ConflictStatus,
    OperationalPriorityLevel,
    RiskLevel,
)
from sentry_atm.runtime import (
    GoldenDemoStepOrchestrator,
    build_golden_demo_runtime,
)
from sentry_atm.scenario import GOLDEN_DEMO_START_UTC, ScenarioEventType


def _running_orchestrator():
    runtime = build_golden_demo_runtime()
    orchestrator = GoldenDemoStepOrchestrator(runtime)
    runtime.simulation.clock.play()
    return runtime, orchestrator


def test_t_zero_step_runs_complete_pre_resolution_pipeline_in_order() -> None:
    runtime, orchestrator = _running_orchestrator()

    result = orchestrator.step(advance_steps=0)

    assert orchestrator.runtime is runtime
    assert result.step_id == "GOLDEN-STEP-000000000000"
    assert result.timestamp_utc == GOLDEN_DEMO_START_UTC
    assert result.traffic_snapshot == runtime.simulation.engine.snapshot()
    assert result.due_events == ()
    assert result.prediction_run is not None
    assert result.prediction_run.prediction_run_id == "PRED-000000000000"
    assert result.conflict_run is not None
    assert result.conflict_run.assessment_run_id == "CONFLICT-000000000000"
    assert len(result.conflict_run.assessments) == 28
    assert result.conflict_run.predicted_events == ()
    assert len(result.risk_assessments) == 28
    assert all(item.risk_level is RiskLevel.LOW for item in result.risk_assessments)
    assert len(result.priority_assessments) == 8
    assert all(
        item.priority_level is OperationalPriorityLevel.ROUTINE
        for item in result.priority_assessments
    )
    assert result.exception_queue_snapshot.items == ()
    assert runtime.exception_queue_service.last_snapshot is result.exception_queue_snapshot
    assert orchestrator.last_result is result


def test_non_due_step_still_refreshes_priority_and_queue_without_duplicate_runs() -> None:
    _, orchestrator = _running_orchestrator()
    orchestrator.step(advance_steps=0)

    result = orchestrator.step(advance_steps=1)

    assert result.step_id == "GOLDEN-STEP-000000000001"
    assert result.prediction_run is None
    assert result.conflict_run is None
    assert result.risk_assessments == ()
    assert len(result.priority_assessments) == 8
    assert result.exception_queue_snapshot.queue_snapshot_id.endswith("-000002")


def test_t_plus_60_step_emits_event_conflict_risk_priority_and_queue() -> None:
    runtime, orchestrator = _running_orchestrator()
    orchestrator.step(advance_steps=0)

    result = orchestrator.step(advance_steps=60)

    assert result.timestamp_utc == GOLDEN_DEMO_START_UTC + timedelta(seconds=60)
    assert tuple(item.event_type for item in result.due_events) == (
        ScenarioEventType.ENTRY_CONFORMANCE_DEVIATION,
    )
    assert result.prediction_run is not None
    assert result.conflict_run is not None
    assert tuple(event.pair.aircraft_ids for event in result.conflict_run.predicted_events) == (
        ("CIV-A02", "MIL-F01"),
    )
    conflict = result.conflict_run.predicted_events[0]
    assert conflict.status is ConflictStatus.PREDICTED
    risk_by_conflict = {item.conflict_id: item for item in result.risk_assessments}
    assert risk_by_conflict[conflict.conflict_id].risk_level is RiskLevel.HIGH
    priority_by_aircraft = {item.aircraft_id: item for item in result.priority_assessments}
    assert priority_by_aircraft["MIL-F01"].priority_level is OperationalPriorityLevel.ATTENTION
    assert priority_by_aircraft["MIL-F01"].source_event_ids == ("EVT-MIL-F01-ENTRY-DEVIATION",)
    assert tuple(
        item.subject_aircraft_ids for item in result.exception_queue_snapshot.active_items
    # CIV-A02/MIL-F02 는 4.37NM 이격이다. 가정값 5NM 아래에서는 "임계 근접"(비율
    # 1.25 이내)이라 큐에 올라왔지만, 고시 3NM 기준으로는 비율 1.46 이라 근접이
    # 아니다. 상신 대상이 줄어드는 것이 이 교체의 결과이며, 큐를 채우려고 기하를
    # 옮기지 않는다.
    ) == (
        ("CIV-A02", "MIL-F01"),
        ("MIL-F01",),
    )
    assert tuple(item.score for item in result.exception_queue_snapshot.active_items) == (
        75.0,
        40.0,
    )
    assert runtime.recommendation_catalog.get_current_recommendation() is None
    assert runtime.controller_decision_service.last_audit_log is None


def test_identical_step_sequences_produce_equal_results() -> None:
    first_runtime, first = _running_orchestrator()
    second_runtime, second = _running_orchestrator()

    first_results = (first.step(0), first.step(5), first.step(55))
    second_results = (second.step(0), second.step(5), second.step(55))

    assert first_results == second_results
    assert first_runtime.simulation.engine.snapshot() == second_runtime.simulation.engine.snapshot()


def test_step_requires_running_clock_valid_steps_and_one_result_per_tick() -> None:
    runtime = build_golden_demo_runtime()
    orchestrator = GoldenDemoStepOrchestrator(runtime)

    with pytest.raises(ValueError, match="RUNNING"):
        orchestrator.step(0)
    for invalid in (True, 1.5, "1"):
        with pytest.raises(TypeError, match="integer"):
            orchestrator.step(invalid)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="non-negative"):
        orchestrator.step(-1)
    with pytest.raises(TypeError, match="GoldenDemoRuntime"):
        GoldenDemoStepOrchestrator("runtime")  # type: ignore[arg-type]

    runtime.simulation.clock.play()
    first = orchestrator.step(0)
    with pytest.raises(ValueError, match="already exists"):
        orchestrator.step(0)
    assert orchestrator.last_result is first
    assert runtime.exception_queue_service.last_snapshot is first.exception_queue_snapshot


def test_clock_reset_clears_process_state_and_replays_same_result() -> None:
    runtime, orchestrator = _running_orchestrator()
    first = orchestrator.step(60)
    assert runtime.exception_queue_service.last_snapshot is not None

    runtime.simulation.clock.reset()

    assert orchestrator.last_result is None
    assert runtime.exception_queue_service.last_snapshot is None
    assert runtime.recommendation_catalog.recommendation_sets == ()
    assert runtime.controller_decision_service.last_audit_log is None

    runtime.simulation.clock.play()
    replayed = orchestrator.step(60)
    assert replayed == first
