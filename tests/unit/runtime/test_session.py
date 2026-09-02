import pytest

from sentry_atm.api import GoldenDemoSessionStage, InProcessGoldenDemoSessionApi
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
        GoldenDemoSessionCommandService("application", session.read_api)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="InProcessGoldenDemoSessionApi"):
        GoldenDemoSessionCommandService(
            session.application_orchestrator,
            "api",  # type: ignore[arg-type]
        )

    other = build_golden_demo_session_runtime()
    mismatched_api = InProcessGoldenDemoSessionApi(other.application_orchestrator)
    with pytest.raises(ValueError, match="same Application Orchestrator"):
        GoldenDemoSessionCommandService(session.application_orchestrator, mismatched_api)

    with pytest.raises(TypeError, match="GoldenDemoSessionCommand"):
        session.command_service.execute(1)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="not a valid GoldenDemoSessionCommand"):
        session.command_service.execute("UNKNOWN")  # type: ignore[arg-type]
