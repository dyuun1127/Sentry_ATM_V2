import pytest

from sentry_atm.api import GoldenDemoSessionStage, InProcessGoldenDemoSessionApi
from sentry_atm.domain import AltitudeManeuver
from sentry_atm.infrastructure.http import GoldenDemoSessionWsgiApp
from sentry_atm.runtime import (
    GoldenDemoSessionCommand,
    GoldenDemoSessionCommandService,
    build_golden_demo_session_runtime,
)

_FULL_SEQUENCE = (
    GoldenDemoSessionCommand.START,
    GoldenDemoSessionCommand.ADVANCE_TO_CONFLICT,
    GoldenDemoSessionCommand.GENERATE_RECOMMENDATION,
    GoldenDemoSessionCommand.ACCEPT_RECOMMENDATION,
    GoldenDemoSessionCommand.APPLY_APPROVED_MANEUVER,
)


def test_session_factory_wires_one_unstarted_independent_command_boundary() -> None:
    first = build_golden_demo_session_runtime()
    second = build_golden_demo_session_runtime()

    assert first.command_service.read_api is first.read_api
    assert isinstance(first.http_app, GoldenDemoSessionWsgiApp)
    assert first.read_api.application_orchestrator is first.application_orchestrator
    assert first.read_api.modified_revalidation_orchestrator is (
        first.modified_revalidation_orchestrator
    )
    assert first.read_api.modified_application_orchestrator is (
        first.modified_application_orchestrator
    )
    assert first.application_orchestrator.decision_orchestrator is first.decision_orchestrator
    assert first.decision_orchestrator.resolution_orchestrator is (first.resolution_orchestrator)
    assert first.resolution_orchestrator.step_orchestrator is first.step_orchestrator
    assert first.step_orchestrator.runtime is first.runtime
    assert first.read_api.get_current().stage is GoldenDemoSessionStage.READY
    assert first.runtime.simulation.clock.state.value == "READY"
    assert first.step_orchestrator.last_result is None
    assert first.runtime is not second.runtime
    assert first.command_service is not second.command_service
    assert first.read_api.get_current() == second.read_api.get_current()


def test_command_service_runs_only_calibrated_checkpoints_in_order() -> None:
    session = build_golden_demo_session_runtime()
    commands = session.command_service

    monitoring = commands.execute(GoldenDemoSessionCommand.START)
    assert monitoring.stage is GoldenDemoSessionStage.MONITORING
    assert monitoring.elapsed_seconds == 0.0
    assert monitoring.step_id == "GOLDEN-STEP-000000000000"
    assert monitoring.clock_state == "RUNNING"

    conflict = commands.execute("ADVANCE_TO_CONFLICT")
    assert conflict.stage is GoldenDemoSessionStage.CONFLICT_DETECTED
    assert conflict.elapsed_seconds == 70.0
    assert conflict.step_id == "GOLDEN-STEP-000000000070"
    assert conflict.active_exception_count == 2

    recommendation = commands.execute(GoldenDemoSessionCommand.GENERATE_RECOMMENDATION)
    assert recommendation.stage is GoldenDemoSessionStage.RECOMMENDATION_AVAILABLE
    assert recommendation.elapsed_seconds == 75.0
    assert recommendation.step_id == "GOLDEN-STEP-000000000075"
    assert recommendation.resolution_step_id == "GOLDEN-RESOLUTION-000000000075"
    assert recommendation.recommendation is not None

    accepted = commands.execute(GoldenDemoSessionCommand.ACCEPT_RECOMMENDATION)
    assert accepted.stage is GoldenDemoSessionStage.DECISION_ACCEPTED
    assert accepted.elapsed_seconds == 90.0
    assert accepted.step_id == "GOLDEN-STEP-000000000090"
    assert accepted.decision_step_id == "GOLDEN-DECISION-000000000090"
    assert accepted.controller_decision is not None
    assert accepted.application_step_id is None

    resolved = commands.execute(GoldenDemoSessionCommand.APPLY_APPROVED_MANEUVER)
    assert resolved.stage is GoldenDemoSessionStage.CONFLICT_RESOLVED
    assert resolved.elapsed_seconds == 90.0
    assert resolved.application_step_id == "GOLDEN-APPLICATION-000000000090"
    assert resolved.revalidation is not None
    assert resolved.revalidation.resolved


def _advance_to_recommendation(session) -> None:
    session.command_service.execute(GoldenDemoSessionCommand.START)
    session.command_service.execute(GoldenDemoSessionCommand.ADVANCE_TO_CONFLICT)
    session.command_service.execute(GoldenDemoSessionCommand.GENERATE_RECOMMENDATION)


def test_modify_command_records_revalidation_required_without_runtime_application() -> None:
    session = build_golden_demo_session_runtime()
    _advance_to_recommendation(session)

    modified = session.command_service.execute(
        GoldenDemoSessionCommand.MODIFY_RECOMMENDATION,
        rationale="Maintain additional vertical margin",
        modified_maneuver=AltitudeManeuver(8_800),
    )

    assert modified.stage is GoldenDemoSessionStage.DECISION_MODIFIED
    assert modified.elapsed_seconds == 90.0
    assert modified.application_step_id is None
    assert modified.controller_decision is not None
    entry = modified.controller_decision.entries[-1]
    assert entry.decision_type == "MODIFY"
    assert entry.rationale == "Maintain additional vertical margin"
    assert entry.modified_maneuver is not None
    assert entry.modified_maneuver.target_altitude_ft == 8_800
    assert entry.requires_revalidation
    assert not entry.authorizes_application
    snapshot = session.runtime.simulation.engine.snapshot()
    assert snapshot == session.step_orchestrator.last_result.traffic_snapshot
    target_state = next(item for item in snapshot.states if item.aircraft_id == "MIL-F01")
    assert target_state.altitude_ft != 8_800


def test_modified_maneuver_revalidation_returns_isolated_safety_evidence() -> None:
    session = build_golden_demo_session_runtime()
    _advance_to_recommendation(session)
    session.command_service.execute(
        GoldenDemoSessionCommand.MODIFY_RECOMMENDATION,
        rationale="Maintain additional vertical margin",
        modified_maneuver=AltitudeManeuver(8_800),
    )
    traffic_before = session.runtime.simulation.engine.snapshot()

    revalidated = session.command_service.execute(
        GoldenDemoSessionCommand.REVALIDATE_MODIFIED_MANEUVER
    )

    assert revalidated.stage is GoldenDemoSessionStage.MODIFICATION_REVALIDATED
    assert revalidated.elapsed_seconds == 90.0
    assert revalidated.application_step_id is None
    assert revalidated.modified_revalidation is not None
    evidence = revalidated.modified_revalidation
    assert evidence.verdict == "SAFE"
    assert evidence.primary_conflict_status == "SAFE"
    assert evidence.primary_horizontal_separation_nm == pytest.approx(2.3)
    assert evidence.primary_vertical_separation_ft == pytest.approx(1_591.6666666667)
    assert evidence.secondary_conflict_aircraft_ids == ()
    assert evidence.performance_feasible
    assert evidence.rule_violation_ids == ()
    assert evidence.safe_to_apply
    assert session.runtime.simulation.engine.snapshot() == traffic_before


def test_safe_modified_maneuver_requires_explicit_application_command() -> None:
    session = build_golden_demo_session_runtime()
    _advance_to_recommendation(session)
    session.command_service.execute(
        GoldenDemoSessionCommand.MODIFY_RECOMMENDATION,
        rationale="Maintain additional vertical margin",
        modified_maneuver=AltitudeManeuver(8_800),
    )
    session.command_service.execute(
        GoldenDemoSessionCommand.REVALIDATE_MODIFIED_MANEUVER
    )
    before = session.runtime.simulation.engine.snapshot()

    applied = session.command_service.execute(
        GoldenDemoSessionCommand.APPLY_VALIDATED_MODIFIED_MANEUVER
    )

    assert applied.stage is GoldenDemoSessionStage.CONFLICT_RESOLVED
    assert applied.application_step_id == "GOLDEN-MODIFIED-APPLICATION-000000000090"
    assert applied.revalidation is not None
    assert applied.revalidation.application_source == "REVALIDATED_MODIFICATION"
    assert applied.revalidation.source_modified_revalidation_step_id == (
        "GOLDEN-MODIFIED-REVALIDATION-000000000090"
    )
    assert applied.revalidation.authorization_id == (
        "GOLDEN-MODIFIED-AUTHORIZATION-000000000090"
    )
    assert applied.revalidation.authorized_at_utc is not None
    assert applied.revalidation.applied_maneuver_type == "ALTITUDE"
    assert applied.revalidation.before_altitude_ft == pytest.approx(7_492.5)
    assert applied.revalidation.applied_altitude_ft == 8_800
    assert applied.revalidation.resolved
    assert next(
        item for item in applied.traffic if item.aircraft_id == "MIL-F01"
    ).altitude_ft == 8_800
    assert session.runtime.simulation.engine.snapshot() != before


def test_unsafe_modified_maneuver_has_no_application_command_effect() -> None:
    session = build_golden_demo_session_runtime()
    _advance_to_recommendation(session)
    session.command_service.execute(
        GoldenDemoSessionCommand.MODIFY_RECOMMENDATION,
        rationale="Exercise unsafe application gate",
        modified_maneuver=AltitudeManeuver(7_200),
    )
    revalidated = session.command_service.execute(
        GoldenDemoSessionCommand.REVALIDATE_MODIFIED_MANEUVER
    )
    assert revalidated.modified_revalidation is not None
    assert not revalidated.modified_revalidation.safe_to_apply
    before = session.runtime.simulation.engine.snapshot()

    with pytest.raises(ValueError, match="only a SAFE"):
        session.command_service.execute(
            GoldenDemoSessionCommand.APPLY_VALIDATED_MODIFIED_MANEUVER
        )

    assert session.read_api.get_current() == revalidated
    assert session.runtime.simulation.engine.snapshot() == before


def test_reject_command_records_reason_without_runtime_application() -> None:
    session = build_golden_demo_session_runtime()
    _advance_to_recommendation(session)

    rejected = session.command_service.execute(
        GoldenDemoSessionCommand.REJECT_RECOMMENDATION,
        rationale="Coordinate a different sector strategy",
    )

    assert rejected.stage is GoldenDemoSessionStage.DECISION_REJECTED
    assert rejected.elapsed_seconds == 90.0
    assert rejected.application_step_id is None
    assert rejected.controller_decision is not None
    entry = rejected.controller_decision.entries[-1]
    assert entry.decision_type == "REJECT"
    assert entry.rationale == "Coordinate a different sector strategy"
    assert entry.modified_maneuver is None
    assert not entry.requires_revalidation
    assert not entry.authorizes_application
    snapshot = session.runtime.simulation.engine.snapshot()
    assert snapshot == session.step_orchestrator.last_result.traffic_snapshot


@pytest.mark.parametrize(
    ("command", "rationale", "maneuver", "message"),
    [
        (GoldenDemoSessionCommand.MODIFY_RECOMMENDATION, "", AltitudeManeuver(8_800), "rationale"),
        (
            GoldenDemoSessionCommand.MODIFY_RECOMMENDATION,
            "No actual change",
            AltitudeManeuver(9_000),
            "must change",
        ),
        (GoldenDemoSessionCommand.REJECT_RECOMMENDATION, "", None, "rationale"),
    ],
)
def test_invalid_operator_decision_does_not_advance_or_mutate_session(
    command: GoldenDemoSessionCommand,
    rationale: str,
    maneuver: AltitudeManeuver | None,
    message: str,
) -> None:
    session = build_golden_demo_session_runtime()
    _advance_to_recommendation(session)
    before = session.read_api.get_current()

    with pytest.raises(ValueError, match=message):
        session.command_service.execute(
            command,
            rationale=rationale,
            modified_maneuver=maneuver,
        )

    assert session.read_api.get_current() == before
    assert session.runtime.simulation.clock.elapsed_seconds == 75.0
    assert session.runtime.controller_decision_service.revision == 0


def test_out_of_order_and_duplicate_commands_are_rejected_without_state_change() -> None:
    session = build_golden_demo_session_runtime()
    commands = session.command_service

    def rejected(command, expected_stage: str) -> None:
        before = session.read_api.get_current()
        with pytest.raises(ValueError, match=expected_stage):
            commands.execute(command)
        assert session.read_api.get_current() == before

    rejected(GoldenDemoSessionCommand.ADVANCE_TO_CONFLICT, "MONITORING")
    commands.execute(GoldenDemoSessionCommand.START)
    rejected(GoldenDemoSessionCommand.START, "READY")
    commands.execute(GoldenDemoSessionCommand.ADVANCE_TO_CONFLICT)
    rejected(GoldenDemoSessionCommand.ACCEPT_RECOMMENDATION, "RECOMMENDATION_AVAILABLE")
    commands.execute(GoldenDemoSessionCommand.GENERATE_RECOMMENDATION)
    rejected(GoldenDemoSessionCommand.APPLY_APPROVED_MANEUVER, "DECISION_ACCEPTED")
    commands.execute(GoldenDemoSessionCommand.ACCEPT_RECOMMENDATION)
    rejected(GoldenDemoSessionCommand.GENERATE_RECOMMENDATION, "CONFLICT_DETECTED")
    commands.execute(GoldenDemoSessionCommand.APPLY_APPROVED_MANEUVER)
    rejected(GoldenDemoSessionCommand.APPLY_APPROVED_MANEUVER, "DECISION_ACCEPTED")


def test_command_rejects_clock_drift_before_advancing_checkpoint() -> None:
    session = build_golden_demo_session_runtime()
    session.command_service.execute(GoldenDemoSessionCommand.START)
    session.runtime.simulation.engine.tick()
    before = session.read_api.get_current()

    with pytest.raises(ValueError, match="elapsed_seconds=0.0"):
        session.command_service.execute(GoldenDemoSessionCommand.ADVANCE_TO_CONFLICT)

    assert session.read_api.get_current() == before
    assert session.runtime.simulation.clock.elapsed_seconds == 1.0


def test_reset_clears_completed_run_and_allows_a_deterministic_replay() -> None:
    session = build_golden_demo_session_runtime()
    first_outputs = tuple(session.command_service.execute(item) for item in _FULL_SEQUENCE)
    first_final = first_outputs[-1]

    reset = session.command_service.execute(GoldenDemoSessionCommand.RESET)

    assert reset.stage is GoldenDemoSessionStage.READY
    assert reset.run_number == 1
    assert reset.session_id == "RKTU_GOLDEN_DEMO_V1-RUN-000001"
    assert reset.elapsed_seconds == 0.0
    assert reset.step_id is None
    assert reset.recommendation is None
    assert reset.controller_decision is None
    assert reset.revalidation is None

    replay_outputs = tuple(session.command_service.execute(item) for item in _FULL_SEQUENCE)
    replay_final = replay_outputs[-1]
    assert tuple(item.stage for item in replay_outputs) == tuple(
        item.stage for item in first_outputs
    )
    assert replay_final.stage is first_final.stage
    assert replay_final.traffic == first_final.traffic
    assert replay_final.exception_queue == first_final.exception_queue
    assert replay_final.recommendation == first_final.recommendation
    assert replay_final.controller_decision == first_final.controller_decision
    assert replay_final.revalidation == first_final.revalidation


def test_identical_command_sequences_produce_equal_session_views() -> None:
    first = build_golden_demo_session_runtime()
    second = build_golden_demo_session_runtime()

    first_outputs = tuple(first.command_service.execute(item) for item in _FULL_SEQUENCE)
    second_outputs = tuple(second.command_service.execute(item) for item in _FULL_SEQUENCE)

    assert first_outputs == second_outputs


def test_command_service_validates_dependencies_and_command_type() -> None:
    session = build_golden_demo_session_runtime()
    with pytest.raises(TypeError, match="GoldenDemoApprovedManeuverOrchestrator"):
        GoldenDemoSessionCommandService(
            "application",  # type: ignore[arg-type]
            session.modified_revalidation_orchestrator,
            session.modified_application_orchestrator,
            session.read_api,
        )
    with pytest.raises(TypeError, match="InProcessGoldenDemoSessionApi"):
        GoldenDemoSessionCommandService(
            session.application_orchestrator,
            session.modified_revalidation_orchestrator,
            session.modified_application_orchestrator,
            "api",  # type: ignore[arg-type]
        )
    with pytest.raises(TypeError, match="ValidatedModifiedManeuverApplication"):
        GoldenDemoSessionCommandService(
            session.application_orchestrator,
            session.modified_revalidation_orchestrator,
            "modified application",  # type: ignore[arg-type]
            session.read_api,
        )

    other = build_golden_demo_session_runtime()
    mismatched_api = InProcessGoldenDemoSessionApi(
        other.application_orchestrator,
        other.modified_revalidation_orchestrator,
        other.modified_application_orchestrator,
    )
    with pytest.raises(ValueError, match="same Application Orchestrator"):
        GoldenDemoSessionCommandService(
            session.application_orchestrator,
            session.modified_revalidation_orchestrator,
            session.modified_application_orchestrator,
            mismatched_api,
        )

    with pytest.raises(TypeError, match="GoldenDemoSessionCommand"):
        session.command_service.execute(1)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="not a valid GoldenDemoSessionCommand"):
        session.command_service.execute("UNKNOWN")  # type: ignore[arg-type]
