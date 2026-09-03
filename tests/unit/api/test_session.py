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
    GoldenDemoModifiedManeuverRevalidationOrchestrator,
    GoldenDemoResolutionOrchestrator,
    GoldenDemoStepOrchestrator,
    GoldenDemoValidatedModifiedManeuverApplicationOrchestrator,
    build_golden_demo_runtime,
)


def _session():
    runtime = build_golden_demo_runtime()
    steps = GoldenDemoStepOrchestrator(runtime)
    resolution = GoldenDemoResolutionOrchestrator(steps)
    decision = GoldenDemoControllerDecisionOrchestrator(resolution)
    modified_revalidation = GoldenDemoModifiedManeuverRevalidationOrchestrator(decision)
    modified_application = GoldenDemoValidatedModifiedManeuverApplicationOrchestrator(
        modified_revalidation
    )
    application = GoldenDemoApprovedManeuverOrchestrator(decision)
    api = InProcessGoldenDemoSessionApi(
        application,
        modified_revalidation,
        modified_application,
    )
    return runtime, steps, resolution, decision, application, modified_application, api


def test_ready_session_is_complete_json_ready_and_read_only() -> None:
    runtime, steps, resolution, decision, application, _, api = _session()

    current = api.get_current()
    payload = current.to_dict()

    assert isinstance(api, GoldenDemoSessionApiContract)
    assert api.application_orchestrator is application
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
    assert current.primary_conflict is None
    assert current.deviation is None
    assert current.candidate_comparisons == ()
    assert current.exception_queue is None
    assert current.recommendation is None
    assert current.controller_decision is None
    assert current.modified_revalidation is None
    assert current.revalidation is None
    assert payload["traffic_count"] == 8
    assert payload["stage"] == "READY"
    assert payload["modified_revalidation"] is None
    assert json.loads(json.dumps(payload))["traffic"][0]["aircraft_id"] == "CIV-A01"
    assert runtime.simulation.clock.state.value == "READY"
    assert steps.last_result is None
    assert resolution.last_result is None
    assert decision.last_result is None
    assert application.last_result is None


def test_session_projects_each_completed_backend_stage() -> None:
    runtime, steps, resolution, decision, application, _, api = _session()
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
    assert conflict.primary_conflict is not None
    assert conflict.primary_conflict.aircraft_ids == ("CIV-A02", "MIL-F01")
    assert conflict.primary_conflict.status == "PREDICTED"
    assert conflict.primary_conflict.risk_level == "HIGH"
    assert conflict.primary_conflict.risk_score == 75.0
    assert conflict.primary_conflict.tcpa_seconds == 85.0
    assert conflict.primary_conflict.horizontal_separation_nm == pytest.approx(2.3)
    assert conflict.primary_conflict.vertical_separation_ft == pytest.approx(500.0)
    assert conflict.primary_conflict.horizontal_threshold_nm == 5.0
    assert conflict.primary_conflict.vertical_threshold_ft == 1_000.0
    assert conflict.primary_conflict.rule_profile_id == "POC_TERMINAL_V1"
    assert conflict.primary_conflict.risk_policy_profile_id == "POC_RISK_V1"
    assert conflict.deviation is not None
    assert conflict.deviation.aircraft_id == "MIL-F01"
    assert conflict.deviation.expected_entry_point == "ENTRY-A"
    assert conflict.deviation.expected_altitude_ft == 9_000.0
    assert conflict.deviation.actual_altitude_ft == 7_400.0
    assert conflict.deviation.vertical_deviation_ft == -1_600.0
    assert conflict.deviation.expected_heading_deg == 210.0
    assert conflict.deviation.actual_heading_deg == 180.0
    assert conflict.deviation.heading_deviation_deg == -30.0
    assert conflict.deviation.lateral_deviation_nm == 2.1
    assert conflict.deviation.time_deviation_seconds == 25.0
    assert conflict.candidate_comparisons == ()
    assert conflict.exception_queue is not None
    assert conflict.exception_queue.top_exception_id == ("EXCEPTION-CONFLICT-7-CIV-A02-7-MIL-F01")
    assert conflict.recommendation is None

    resolution_result = resolution.resolve()
    recommended = api.get_current()
    assert recommended.stage is GoldenDemoSessionStage.RECOMMENDATION_AVAILABLE
    assert recommended.resolution_step_id == resolution_result.resolution_step_id
    assert recommended.recommendation is not None
    assert recommended.recommendation.availability == "AVAILABLE"
    assert recommended.primary_conflict is not None
    assert recommended.primary_conflict.conflict_id.endswith("CIV-A02-MIL-F01")
    assert recommended.deviation == conflict.deviation
    assert tuple(item.candidate_id for item in recommended.candidate_comparisons) == (
        "CAND-A",
        "CAND-B",
        "CAND-C",
        "CAND-D",
        "CAND-E",
    )
    comparison_by_id = {
        item.candidate_id: item for item in recommended.candidate_comparisons
    }
    assert comparison_by_id["CAND-A"].recommended
    assert comparison_by_id["CAND-A"].verdict == "SAFE"
    assert comparison_by_id["CAND-A"].target_altitude_ft == 9_000.0
    assert comparison_by_id["CAND-B"].secondary_conflict_aircraft_ids == (
        ("MIL-F01", "MIL-F02"),
    )
    assert comparison_by_id["CAND-C"].verdict == "INEFFECTIVE"
    assert comparison_by_id["CAND-D"].rule_violation_ids == (
        "POC-MINIMUM-CANDIDATE-ALTITUDE-V1",
    )
    assert comparison_by_id["CAND-E"].maneuver_type == "NO_ACTION"
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
    assert resolved.revalidation.application_source == "ACCEPTED_RECOMMENDATION"
    assert resolved.revalidation.source_modified_revalidation_step_id is None
    assert resolved.revalidation.authorization_id is None
    assert resolved.revalidation.authorized_at_utc is None
    assert resolved.revalidation.applied_maneuver_type == "ALTITUDE"
    assert resolved.revalidation.before_altitude_ft == pytest.approx(7_492.5)
    assert resolved.revalidation.applied_altitude_ft == 9_000.0
    assert resolved.revalidation.conflict_status == "SAFE"
    assert resolved.revalidation.risk_level == "LOW"
    assert resolved.revalidation.source_exception_status == "RESOLVED"
    assert resolved.revalidation.resolved
    assert resolved.primary_conflict == recommended.primary_conflict
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
    assert payload["primary_conflict"]["aircraft_ids"] == [  # type: ignore[index]
        "CIV-A02",
        "MIL-F01",
    ]
    assert payload["deviation"]["vertical_deviation_ft"] == -1_600.0  # type: ignore[index]
    assert len(payload["candidate_comparisons"]) == 5  # type: ignore[arg-type]
    assert json.loads(json.dumps(payload))["controller_decision"]["revision"] == 1
    assert conflict_step.traffic_snapshot != application_result.traffic_snapshot


def test_deviation_stage_is_distinct_from_conflict_and_monitoring() -> None:
    runtime, steps, _, _, _, _, _ = _session()
    runtime.simulation.clock.play()
    conflict_step = steps.step(75)
    deviation_only = replace(conflict_step, risk_assessments=())

    stage = session_api._stage(
        step_result=deviation_only,
        resolution_result=None,
        decision_result=None,
        modified_revalidation_result=None,
        application_result=None,
    )

    assert stage is GoldenDemoSessionStage.DEVIATION_DETECTED


def test_reset_returns_a_new_empty_session_run_with_initial_traffic() -> None:
    runtime, steps, resolution, decision, application, _, api = _session()
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
    assert current.primary_conflict is None
    assert current.deviation is None
    assert current.candidate_comparisons == ()
    assert current.revalidation is None
    assert next(item for item in current.traffic if item.aircraft_id == "MIL-F01").altitude_ft == (
        13_000.0
    )


def test_identical_session_sequences_produce_equal_read_models() -> None:
    first_runtime, first_steps, first_resolution, first_decision, first_application, _, first = (
        _session()
    )
    (
        second_runtime,
        second_steps,
        second_resolution,
        second_decision,
        second_application,
        _,
        second,
    ) = _session()
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
        InProcessGoldenDemoSessionApi(
            "application",  # type: ignore[arg-type]
            "modified",  # type: ignore[arg-type]
            "modified application",  # type: ignore[arg-type]
        )
