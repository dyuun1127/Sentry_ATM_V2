import json
from dataclasses import replace

import pytest

import sentry_atm.api.session as session_api
from sentry_atm.api import (
    GoldenDemoSessionApiContract,
    GoldenDemoSessionStage,
    InProcessGoldenDemoSessionApi,
)
from sentry_atm.runtime import (
    GoldenDemoApprovedManeuverOrchestrator,
    GoldenDemoControllerDecisionOrchestrator,
    GoldenDemoResolutionOrchestrator,
    GoldenDemoStepOrchestrator,
    build_golden_demo_runtime,
)


def _session():
    runtime = build_golden_demo_runtime()
    steps = GoldenDemoStepOrchestrator(runtime)
    resolution = GoldenDemoResolutionOrchestrator(steps)
    decision = GoldenDemoControllerDecisionOrchestrator(resolution)
    application = GoldenDemoApprovedManeuverOrchestrator(decision)
    api = InProcessGoldenDemoSessionApi(application)
    return runtime, steps, resolution, decision, application, api


def test_ready_session_is_complete_json_ready_and_read_only() -> None:
    runtime, steps, resolution, decision, application, api = _session()

    current = api.get_current()
    payload = current.to_dict()

    assert isinstance(api, GoldenDemoSessionApiContract)
    assert current.session_id == "RKTU_GOLDEN_DEMO_V1-RUN-000000"
    assert current.scenario_id == "RKTU_GOLDEN_DEMO_V1"
    assert current.run_number == 0
    assert current.stage is GoldenDemoSessionStage.READY
    assert current.clock_state == "READY"
    assert current.elapsed_seconds == 0.0
    assert len(current.traffic) == 8
    assert current.traffic[0].aircraft_id == "CIV-A01"
    assert current.traffic[0].aircraft_type == "SYN-AIRLINER"
    assert current.traffic[0].category == "AIRLINER"
    assert current.traffic[0].source == "SYNTHETIC"
    assert current.active_exception_count == 0
    assert current.step_id is None
    assert current.resolution_step_id is None
    assert current.decision_step_id is None
    assert current.application_step_id is None
    assert current.exception_queue is None
    assert current.recommendation is None
    assert current.controller_decision is None
    assert current.revalidation is None
    assert payload["traffic_count"] == 8
    assert payload["stage"] == "READY"
    assert json.loads(json.dumps(payload))["traffic"][0]["aircraft_id"] == "CIV-A01"
    assert runtime.simulation.clock.state.value == "READY"
    assert steps.last_result is None
    assert resolution.last_result is None
    assert decision.last_result is None
    assert application.last_result is None


def test_session_projects_each_completed_backend_stage() -> None:
    runtime, steps, resolution, decision, application, api = _session()
    runtime.simulation.clock.play()

    steps.step(0)
    monitoring = api.get_current()
    assert monitoring.stage is GoldenDemoSessionStage.MONITORING
    assert monitoring.step_id == "GOLDEN-STEP-000000000000"
    assert monitoring.exception_queue is not None
    assert monitoring.active_exception_count == 0

    conflict_step = steps.step(75)
    conflict = api.get_current()
    assert conflict.stage is GoldenDemoSessionStage.CONFLICT_DETECTED
    assert conflict.step_id == "GOLDEN-STEP-000000000075"
    assert conflict.active_exception_count == 3
    assert conflict.exception_queue is not None
    assert conflict.exception_queue.top_exception_id == ("EXCEPTION-CONFLICT-7-CIV-A02-7-MIL-F01")
    assert conflict.recommendation is None

    resolution_result = resolution.resolve()
    recommended = api.get_current()
    assert recommended.stage is GoldenDemoSessionStage.RECOMMENDATION_AVAILABLE
    assert recommended.resolution_step_id == resolution_result.resolution_step_id
    assert recommended.recommendation is not None
    assert recommended.recommendation.availability == "AVAILABLE"
    assert tuple(item.candidate_id for item in recommended.recommendation.recommendations) == (
        "CAND-A",
    )

    steps.step(15)
    decision_result = decision.accept()
    accepted = api.get_current()
    assert accepted.stage is GoldenDemoSessionStage.DECISION_ACCEPTED
    assert accepted.decision_step_id == decision_result.decision_step_id
    assert accepted.controller_decision is not None
    assert accepted.controller_decision.entries[0].decision_type == "ACCEPT"
    assert accepted.application_step_id is None

    application_result = application.apply_and_revalidate()
    resolved = api.get_current()
    assert resolved.stage is GoldenDemoSessionStage.CONFLICT_RESOLVED
    assert resolved.application_step_id == application_result.application_step_id
    assert resolved.revalidation is not None
    assert resolved.revalidation.applied_aircraft_id == "MIL-F01"
    assert resolved.revalidation.before_altitude_ft == pytest.approx(7_492.5)
    assert resolved.revalidation.applied_altitude_ft == 9_000.0
    assert resolved.revalidation.conflict_status == "SAFE"
    assert resolved.revalidation.risk_level == "LOW"
    assert resolved.revalidation.source_exception_status == "RESOLVED"
    assert resolved.revalidation.resolved
    assert resolved.exception_queue is not None
    source_item = next(
        item
        for item in resolved.exception_queue.items
        if item.subject_aircraft_ids == ("CIV-A02", "MIL-F01")
    )
    assert source_item.status == "RESOLVED"
    assert (
        next(item for item in resolved.traffic if item.aircraft_id == "MIL-F01").altitude_ft
        == 9_000.0
    )
    payload = resolved.to_dict()
    assert payload["revalidation"]["resolved"] is True  # type: ignore[index]
    assert json.loads(json.dumps(payload))["controller_decision"]["revision"] == 1
    assert conflict_step.traffic_snapshot != application_result.traffic_snapshot


def test_deviation_stage_is_distinct_from_conflict_and_monitoring() -> None:
    runtime, steps, _, _, _, _ = _session()
    runtime.simulation.clock.play()
    conflict_step = steps.step(75)
    deviation_only = replace(conflict_step, risk_assessments=())

    stage = session_api._stage(
        step_result=deviation_only,
        resolution_result=None,
        decision_result=None,
        application_result=None,
    )

    assert stage is GoldenDemoSessionStage.DEVIATION_DETECTED


def test_reset_returns_a_new_empty_session_run_with_initial_traffic() -> None:
    runtime, steps, resolution, decision, application, api = _session()
    runtime.simulation.clock.play()
    steps.step(75)
    resolution.resolve()
    steps.step(15)
    decision.accept()
    application.apply_and_revalidate()

    runtime.simulation.clock.reset()
    current = api.get_current()

    assert current.session_id == "RKTU_GOLDEN_DEMO_V1-RUN-000001"
    assert current.run_number == 1
    assert current.stage is GoldenDemoSessionStage.READY
    assert current.clock_state == "READY"
    assert current.elapsed_seconds == 0.0
    assert current.step_id is None
    assert current.exception_queue is None
    assert current.recommendation is None
    assert current.controller_decision is None
    assert current.revalidation is None
    assert next(item for item in current.traffic if item.aircraft_id == "MIL-F01").altitude_ft == (
        13_000.0
    )


def test_identical_session_sequences_produce_equal_read_models() -> None:
    first_runtime, first_steps, first_resolution, first_decision, first_application, first = (
        _session()
    )
    second_runtime, second_steps, second_resolution, second_decision, second_application, second = (
        _session()
    )
    for runtime, steps, resolution, decision, application in (
        (
            first_runtime,
            first_steps,
            first_resolution,
            first_decision,
            first_application,
        ),
        (
            second_runtime,
            second_steps,
            second_resolution,
            second_decision,
            second_application,
        ),
    ):
        runtime.simulation.clock.play()
        steps.step(75)
        resolution.resolve()
        steps.step(15)
        decision.accept()
        application.apply_and_revalidate()

    assert first.get_current() == second.get_current()
    assert first.get_current().to_dict() == second.get_current().to_dict()


def test_session_api_rejects_unsupported_source() -> None:
    with pytest.raises(TypeError, match="GoldenDemoApprovedManeuverOrchestrator"):
        InProcessGoldenDemoSessionApi("application")  # type: ignore[arg-type]
