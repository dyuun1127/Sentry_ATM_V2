import json
from dataclasses import replace

import pytest

import sentry_atm.api.session as session_api
from sentry_atm.api import (
    GoldenDemoSessionApiContract,
    GoldenDemoSessionStage,
    InProcessGoldenDemoSessionApi,
)
from sentry_atm.regulation.policy import active_separation_profile
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
    assert current.traffic[0].aircraft_type == "B738"
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
    # 고시 3NM 기준에서는 임계 근접 항목이 하나 줄어 2건이다 (test_orchestrator 참조).
    assert conflict.active_exception_count == 2
    assert conflict.primary_conflict is not None
    assert conflict.primary_conflict.aircraft_ids == ("CIV-A02", "MIL-F01")
    assert conflict.primary_conflict.status == "PREDICTED"
    assert conflict.primary_conflict.risk_level == "HIGH"
    assert conflict.primary_conflict.risk_score == 75.0
    assert conflict.primary_conflict.tcpa_seconds == 85.0
    assert conflict.primary_conflict.horizontal_separation_nm == pytest.approx(2.3)
    assert conflict.primary_conflict.vertical_separation_ft == pytest.approx(500.0)
    rule = active_separation_profile()
    assert conflict.primary_conflict.horizontal_threshold_nm == (
        rule.horizontal_threshold_nm
    )
    assert conflict.primary_conflict.vertical_threshold_ft == rule.vertical_threshold_ft
    assert conflict.primary_conflict.rule_profile_id == active_separation_profile().profile_id
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


def test_traffic_keeps_moving_after_the_controller_decision_is_applied() -> None:
    """판단을 적용한 뒤에도 항적이 시계를 따라가는가.

    스냅샷 고르기가 고정 우선순위였다 — 적용 결과가 있으면 무조건 그것. 적용
    결과는 한 번 생기면 사라지지 않으므로 **영원히** 이겼고, 관제사가 승인을
    적용한 순간 스코프의 항적이 그 시각에 얼어붙었다. 시계와 경과시각은 계속
    갔으므로 화면은 「시간은 흐르는데 아무도 움직이지 않는」 상태가 됐다.

    시각으로 고르면 그 일이 생기지 않는다. 적용한 순간에는 적용 결과가 가장
    최근이라 그것이 뽑히고(적용된 기동이 보인다), 시계가 더 가면 새 단계 결과가
    더 최근이 되어 자연히 넘어간다.
    """
    runtime, steps, resolution, decision, application, _, api = _session()
    runtime.simulation.clock.play()

    steps.step(0)
    steps.step(75)
    resolution.resolve()
    steps.step(15)
    decision.accept()
    application.apply_and_revalidate()

    applied = api.get_current()
    assert applied.stage is GoldenDemoSessionStage.CONFLICT_RESOLVED

    samples = [applied]
    for _ in range(3):
        steps.step(30)
        samples.append(api.get_current())

    # 항적이 관측된 시각이 경과시각을 따라 늘어야 한다. 이것이 얼어붙었던 값이다.
    observed = [item.traffic[0].timestamp_utc for item in samples]
    assert len(set(observed)) == len(observed), "적용 뒤 항적이 한 시각에 얼어붙었다"
    assert observed == sorted(observed)
    assert [item.elapsed_seconds for item in samples] == sorted(
        item.elapsed_seconds for item in samples
    )

    # 그리고 실제로 자리를 옮긴다. CIV-A01 은 x 가 고정인 항로라 다른 기체로 본다.
    def position_of(sample, aircraft_id):
        entry = next(item for item in sample.traffic if item.aircraft_id == aircraft_id)
        return (round(entry.x_nm, 6), round(entry.y_nm, 6))

    places = {position_of(sample, "CIV-A02") for sample in samples}
    assert len(places) == len(samples), "적용 뒤 항적이 한 자리에 얼어붙었다"


def test_the_applied_manoeuvre_is_what_is_shown_at_the_moment_of_application() -> None:
    """적용한 순간에는 적용된 상태가 보이는가.

    시각이 같은 스냅샷이 둘 있을 때(적용 결과와 단계 결과) **적용된 기동이
    반영된 쪽**을 보여야 한다. 그러지 않으면 승인한 것이 화면에 나타나지 않는다.
    """
    runtime, steps, resolution, decision, application, _, api = _session()
    runtime.simulation.clock.play()

    steps.step(0)
    steps.step(75)
    resolution.resolve()
    steps.step(15)
    decision.accept()
    result = application.apply_and_revalidate()

    current = api.get_current()

    applied_ids = {state.aircraft_id for state in result.traffic_snapshot.states}
    assert {item.aircraft_id for item in current.traffic} == applied_ids
    for state in result.traffic_snapshot.states:
        shown = next(item for item in current.traffic if item.aircraft_id == state.aircraft_id)
        assert shown.altitude_ft == state.altitude_ft
        assert shown.x_nm == state.x_nm
