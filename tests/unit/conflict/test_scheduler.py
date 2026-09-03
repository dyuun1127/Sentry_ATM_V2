from datetime import UTC, datetime, timedelta

import pytest

from sentry_atm.conflict import (
    ConflictAssessmentService,
    PairwiseConflictDetector,
    RollingConflictScheduler,
)
from sentry_atm.scenario import build_golden_demo_scenario
from sentry_atm.simulation import (
    SimulationClock,
    SyntheticAircraftRuntime,
    TrafficSimulationEngine,
    TrafficSnapshot,
)

START_UTC = datetime(2026, 9, 1, 3, 0, tzinfo=UTC)


def _components(
    *,
    tick_seconds: float = 1.0,
    interval_seconds: float = 5.0,
) -> tuple[SimulationClock, TrafficSimulationEngine, RollingConflictScheduler]:
    definition = build_golden_demo_scenario()
    clock = SimulationClock(
        start_time_utc=definition.start_time_utc,
        tick_seconds=tick_seconds,
    )
    runtimes = tuple(
        SyntheticAircraftRuntime(clock=clock, initial_state=state)
        for state in definition.initial_states
    )
    engine = TrafficSimulationEngine(clock=clock, runtimes=runtimes)
    scheduler = RollingConflictScheduler(
        clock=clock,
        service=ConflictAssessmentService(PairwiseConflictDetector()),
        interval_seconds=interval_seconds,
    )
    return clock, engine, scheduler


def test_scheduler_runs_at_start_and_every_five_simulation_seconds() -> None:
    clock, engine, scheduler = _components()
    clock.play()

    initial = scheduler.run_if_due(engine.snapshot())
    assert initial is not None
    assert initial.assessment_run_id == "CONFLICT-000000000000"
    assert initial.input_timestamp_utc == START_UTC
    assert len(initial.assessments) == 28
    assert initial.predicted_events == ()

    for _ in range(4):
        assert scheduler.run_if_due(engine.tick()) is None
    next_run = scheduler.run_if_due(engine.tick())
    assert next_run is not None
    assert next_run.assessment_run_id == "CONFLICT-000000000005"
    assert next_run.input_timestamp_utc == START_UTC + timedelta(seconds=5)


def test_scheduler_suppresses_duplicate_calls_and_exposes_state() -> None:
    clock, engine, scheduler = _components(interval_seconds=7.5)
    clock.play()
    snapshot = engine.snapshot()

    first = scheduler.run_if_due(snapshot)

    assert first is not None
    assert scheduler.run_if_due(snapshot) is None
    assert scheduler.last_run is first
    assert scheduler.clock is clock
    assert isinstance(scheduler.service, ConflictAssessmentService)
    assert scheduler.interval_seconds == 7.5


def test_scheduler_does_not_run_while_ready_or_paused() -> None:
    clock, engine, scheduler = _components()

    assert scheduler.run_if_due(engine.snapshot()) is None
    clock.play()
    engine.tick(steps=4)
    clock.pause()
    assert scheduler.run_if_due(engine.snapshot()) is None

    clock.play()
    due_run = scheduler.run_if_due(engine.tick())
    assert due_run is not None
    assert due_run.input_timestamp_utc == START_UTC + timedelta(seconds=5)


def test_scheduler_reset_replays_identical_initial_run() -> None:
    clock, engine, scheduler = _components()
    clock.play()
    first = scheduler.run_if_due(engine.snapshot())
    engine.tick(steps=10)
    assert scheduler.run_if_due(engine.snapshot()) is not None

    clock.reset()
    assert scheduler.last_run is None
    clock.play()
    replayed = scheduler.run_if_due(engine.snapshot())

    assert replayed == first


def test_scheduler_catches_up_once_after_large_tick_jump() -> None:
    clock, engine, scheduler = _components()
    clock.play()
    assert scheduler.run_if_due(engine.snapshot()) is not None

    jumped = scheduler.run_if_due(engine.tick(steps=12))

    assert jumped is not None
    assert jumped.input_timestamp_utc == START_UTC + timedelta(seconds=12)
    assert scheduler.run_if_due(engine.snapshot()) is None


def test_fractional_clock_ticks_follow_simulation_time_slots() -> None:
    clock, engine, scheduler = _components(tick_seconds=0.5)
    clock.play()
    assert scheduler.run_if_due(engine.snapshot()) is not None

    engine.tick(steps=9)
    assert scheduler.run_if_due(engine.snapshot()) is None
    run = scheduler.run_if_due(engine.tick())

    assert run is not None
    assert run.input_timestamp_utc == START_UTC + timedelta(seconds=5)
    assert run.assessment_run_id == "CONFLICT-000000000010"


def test_scheduler_rejects_wrong_snapshot_time() -> None:
    clock, _, scheduler = _components()
    clock.play()
    wrong_snapshot = TrafficSnapshot(
        timestamp_utc=START_UTC + timedelta(seconds=1),
        states=(),
    )

    with pytest.raises(ValueError, match="must match"):
        scheduler.run_if_due(wrong_snapshot)


@pytest.mark.parametrize("invalid", [0.0, -1.0, float("nan"), float("inf"), True])
def test_scheduler_rejects_invalid_interval(invalid: object) -> None:
    clock, _, _ = _components()
    service = ConflictAssessmentService(PairwiseConflictDetector())
    expected_error = TypeError if isinstance(invalid, bool) else ValueError

    with pytest.raises(expected_error):
        RollingConflictScheduler(
            clock=clock,
            service=service,
            interval_seconds=invalid,  # type: ignore[arg-type]
        )


def test_scheduler_rejects_wrong_dependencies_and_snapshot() -> None:
    clock, _, _ = _components()
    service = ConflictAssessmentService(PairwiseConflictDetector())

    with pytest.raises(TypeError, match="SimulationClock"):
        RollingConflictScheduler(clock=START_UTC, service=service)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="ConflictAssessmentService"):
        RollingConflictScheduler(
            clock=clock,
            service="service",  # type: ignore[arg-type]
        )

    scheduler = RollingConflictScheduler(clock=clock, service=service)
    with pytest.raises(TypeError, match="TrafficSnapshot"):
        scheduler.run_if_due("snapshot")  # type: ignore[arg-type]
