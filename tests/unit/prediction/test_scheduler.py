from datetime import UTC, datetime, timedelta

import pytest

from sentry_atm.domain import AircraftState, DataSource
from sentry_atm.prediction import (
    ConstantVelocityPredictor,
    PredictionRunService,
    RollingPredictionScheduler,
)
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
) -> tuple[SimulationClock, TrafficSimulationEngine, RollingPredictionScheduler]:
    clock = SimulationClock(start_time_utc=START_UTC, tick_seconds=tick_seconds)
    state = AircraftState(
        aircraft_id="CIV-A01",
        timestamp_utc=START_UTC,
        x_nm=0.0,
        y_nm=0.0,
        altitude_ft=8_000.0,
        ground_speed_kt=360.0,
        heading_deg=90.0,
        vertical_speed_fpm=0.0,
        source=DataSource.SYNTHETIC,
    )
    runtime = SyntheticAircraftRuntime(clock=clock, initial_state=state)
    engine = TrafficSimulationEngine(clock=clock, runtimes=(runtime,))
    service = PredictionRunService(ConstantVelocityPredictor())
    scheduler = RollingPredictionScheduler(
        clock=clock,
        service=service,
        interval_seconds=interval_seconds,
    )
    return clock, engine, scheduler


def test_scheduler_runs_at_start_and_every_five_simulation_seconds() -> None:
    clock, engine, scheduler = _components()
    clock.play()

    initial_run = scheduler.run_if_due(engine.snapshot())
    assert initial_run is not None
    assert initial_run.prediction_run_id == "PRED-000000000000"
    assert initial_run.input_timestamp_utc == START_UTC

    for _ in range(4):
        snapshot = engine.tick()
        assert scheduler.run_if_due(snapshot) is None

    five_second_run = scheduler.run_if_due(engine.tick())
    assert five_second_run is not None
    assert five_second_run.prediction_run_id == "PRED-000000000005"
    assert five_second_run.input_timestamp_utc == START_UTC + timedelta(seconds=5)

    for _ in range(4):
        assert scheduler.run_if_due(engine.tick()) is None
    assert scheduler.run_if_due(engine.tick()) is not None


def test_scheduler_suppresses_duplicate_calls_in_same_slot() -> None:
    clock, engine, scheduler = _components()
    clock.play()
    snapshot = engine.snapshot()

    first = scheduler.run_if_due(snapshot)

    assert first is not None
    assert scheduler.run_if_due(snapshot) is None
    assert scheduler.last_run is first


def test_scheduler_exposes_clock_service_and_interval() -> None:
    clock, _, scheduler = _components(interval_seconds=7.5)

    assert scheduler.clock is clock
    assert isinstance(scheduler.service, PredictionRunService)
    assert scheduler.interval_seconds == 7.5


def test_scheduler_does_not_run_while_ready_or_paused() -> None:
    clock, engine, scheduler = _components()

    assert scheduler.run_if_due(engine.snapshot()) is None
    clock.play()
    engine.tick(steps=4)
    clock.pause()

    paused_snapshot = engine.tick(steps=20)
    assert scheduler.run_if_due(paused_snapshot) is None

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
    assert scheduler.last_run is replayed


def test_scheduler_detects_reset_even_after_clock_returns_to_same_tick() -> None:
    clock, engine, scheduler = _components()
    clock.play()
    engine.tick(steps=5)
    first = scheduler.run_if_due(engine.snapshot())

    clock.reset()
    clock.play()
    engine.tick(steps=5)
    replayed = scheduler.run_if_due(engine.snapshot())

    assert first is not None
    assert replayed == first


def test_scheduler_catches_up_once_after_large_tick_jump() -> None:
    clock, engine, scheduler = _components()
    clock.play()
    assert scheduler.run_if_due(engine.snapshot()) is not None

    jumped_run = scheduler.run_if_due(engine.tick(steps=12))

    assert jumped_run is not None
    assert jumped_run.input_timestamp_utc == START_UTC + timedelta(seconds=12)
    assert scheduler.run_if_due(engine.snapshot()) is None
    engine.tick(steps=2)
    assert scheduler.run_if_due(engine.snapshot()) is None
    assert scheduler.run_if_due(engine.tick()) is not None


def test_fractional_clock_ticks_follow_simulation_time_slots() -> None:
    clock, engine, scheduler = _components(tick_seconds=0.5)
    clock.play()
    assert scheduler.run_if_due(engine.snapshot()) is not None

    engine.tick(steps=9)
    assert scheduler.run_if_due(engine.snapshot()) is None
    run = scheduler.run_if_due(engine.tick())

    assert run is not None
    assert run.input_timestamp_utc == START_UTC + timedelta(seconds=5)
    assert run.prediction_run_id == "PRED-000000000010"


def test_scheduler_rejects_snapshot_from_another_time() -> None:
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
    service = PredictionRunService(ConstantVelocityPredictor())
    expected_error = TypeError if isinstance(invalid, bool) else ValueError

    with pytest.raises(expected_error):
        RollingPredictionScheduler(
            clock=clock,
            service=service,
            interval_seconds=invalid,  # type: ignore[arg-type]
        )


def test_scheduler_rejects_wrong_dependencies_and_snapshot() -> None:
    clock, _, _ = _components()
    service = PredictionRunService(ConstantVelocityPredictor())

    with pytest.raises(TypeError, match="SimulationClock"):
        RollingPredictionScheduler(clock=START_UTC, service=service)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="PredictionRunService"):
        RollingPredictionScheduler(clock=clock, service="service")  # type: ignore[arg-type]

    scheduler = RollingPredictionScheduler(clock=clock, service=service)
    with pytest.raises(TypeError, match="TrafficSnapshot"):
        scheduler.run_if_due("snapshot")  # type: ignore[arg-type]
