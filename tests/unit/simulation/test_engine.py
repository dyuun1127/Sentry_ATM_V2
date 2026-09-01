from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta

import pytest

from sentry_atm.domain import AircraftState, DataSource
from sentry_atm.domain.time_policy import KST
from sentry_atm.simulation import (
    PlaybackAircraftRuntime,
    SimulationClock,
    SyntheticAircraftRuntime,
    TrafficSimulationEngine,
    TrafficSnapshot,
)

START_UTC = datetime(2026, 9, 1, 3, 0, tzinfo=UTC)


def _state(
    aircraft_id: str,
    seconds: int,
    *,
    source: DataSource,
    x_nm: float = 0.0,
    ground_speed_kt: float = 0.0,
    heading_deg: float = 90.0,
) -> AircraftState:
    return AircraftState(
        aircraft_id=aircraft_id,
        timestamp_utc=START_UTC + timedelta(seconds=seconds),
        x_nm=x_nm,
        y_nm=0.0,
        altitude_ft=8_000.0,
        ground_speed_kt=ground_speed_kt,
        heading_deg=heading_deg,
        vertical_speed_fpm=0.0,
        source=source,
    )


def _mixed_engine() -> tuple[
    SimulationClock,
    PlaybackAircraftRuntime,
    SyntheticAircraftRuntime,
    TrafficSimulationEngine,
]:
    clock = SimulationClock(start_time_utc=START_UTC)
    playback = PlaybackAircraftRuntime(
        clock=clock,
        states=(
            _state("CIV-A01", 0, source=DataSource.OPENSKY, x_nm=1.0),
            _state("CIV-A01", 5, source=DataSource.OPENSKY, x_nm=2.0),
        ),
    )
    synthetic = SyntheticAircraftRuntime(
        clock=clock,
        initial_state=_state(
            "MIL-F01",
            0,
            source=DataSource.SYNTHETIC,
            x_nm=10.0,
            ground_speed_kt=360.0,
        ),
    )
    engine = TrafficSimulationEngine(
        clock=clock,
        runtimes=(playback, synthetic),
    )
    return clock, playback, synthetic, engine


def test_engine_exposes_shared_clock_runtimes_and_aircraft_ids() -> None:
    clock, playback, synthetic, engine = _mixed_engine()

    assert playback.clock is clock
    assert synthetic.clock is clock
    assert engine.clock is clock
    assert engine.runtimes == (playback, synthetic)
    assert engine.aircraft_ids == ("CIV-A01", "MIL-F01")


def test_snapshot_collects_mixed_runtime_states_in_registration_order() -> None:
    _, _, _, engine = _mixed_engine()

    snapshot = engine.snapshot()

    assert snapshot.timestamp_utc == START_UTC
    assert snapshot.aircraft_ids == ("CIV-A01", "MIL-F01")
    assert tuple(state.source for state in snapshot.states) == (
        DataSource.OPENSKY,
        DataSource.SYNTHETIC,
    )


def test_tick_advances_shared_clock_and_returns_updated_snapshot() -> None:
    clock, _, _, engine = _mixed_engine()
    clock.play()

    snapshot = engine.tick(steps=10)

    assert snapshot.timestamp_utc == START_UTC + timedelta(seconds=10)
    playback_state, synthetic_state = snapshot.states
    assert playback_state.timestamp_utc == START_UTC + timedelta(seconds=5)
    assert playback_state.x_nm == 2.0
    assert synthetic_state.timestamp_utc == snapshot.timestamp_utc
    assert synthetic_state.x_nm == pytest.approx(11.0)


def test_tick_does_not_advance_when_clock_is_paused() -> None:
    clock, _, _, engine = _mixed_engine()
    clock.play()
    engine.tick(steps=3)
    clock.pause()

    paused_snapshot = engine.tick(steps=10)

    assert paused_snapshot.timestamp_utc == START_UTC + timedelta(seconds=3)


def test_clock_reset_restores_initial_traffic_snapshot() -> None:
    clock, _, _, engine = _mixed_engine()
    initial_snapshot = engine.snapshot()
    clock.play()
    engine.tick(steps=10)

    clock.reset()

    assert engine.snapshot() == initial_snapshot


def test_snapshot_excludes_runtimes_that_have_not_started() -> None:
    clock = SimulationClock(start_time_utc=START_UTC)
    future_runtime = SyntheticAircraftRuntime(
        clock=clock,
        initial_state=_state("MIL-F01", 5, source=DataSource.SYNTHETIC),
    )
    engine = TrafficSimulationEngine(clock=clock, runtimes=(future_runtime,))

    snapshot = engine.snapshot()

    assert snapshot.states == ()
    assert snapshot.aircraft_ids == ()


def test_inactive_runtime_appears_when_clock_reaches_start_time() -> None:
    clock = SimulationClock(start_time_utc=START_UTC)
    future_runtime = SyntheticAircraftRuntime(
        clock=clock,
        initial_state=_state("MIL-F01", 5, source=DataSource.SYNTHETIC),
    )
    engine = TrafficSimulationEngine(clock=clock, runtimes=(future_runtime,))
    clock.play()

    snapshot = engine.tick(steps=5)

    assert snapshot.aircraft_ids == ("MIL-F01",)


def test_engine_materializes_runtime_generator_once() -> None:
    clock, playback, synthetic, _ = _mixed_engine()

    engine = TrafficSimulationEngine(
        clock=clock,
        runtimes=(runtime for runtime in (playback, synthetic)),
    )

    assert len(engine.runtimes) == 2


def test_engine_rejects_incorrect_clock_type() -> None:
    _, playback, _, _ = _mixed_engine()

    with pytest.raises(TypeError, match="SimulationClock"):
        TrafficSimulationEngine(clock=START_UTC, runtimes=(playback,))  # type: ignore[arg-type]


def test_engine_rejects_empty_runtimes() -> None:
    clock = SimulationClock(start_time_utc=START_UTC)

    with pytest.raises(ValueError, match="must not be empty"):
        TrafficSimulationEngine(clock=clock, runtimes=())


def test_engine_rejects_unsupported_runtime() -> None:
    clock = SimulationClock(start_time_utc=START_UTC)

    with pytest.raises(TypeError, match="supported aircraft runtimes"):
        TrafficSimulationEngine(clock=clock, runtimes=("CIV-A01",))  # type: ignore[arg-type]


def test_engine_rejects_runtime_using_another_clock() -> None:
    engine_clock = SimulationClock(start_time_utc=START_UTC)
    runtime_clock = SimulationClock(start_time_utc=START_UTC)
    runtime = SyntheticAircraftRuntime(
        clock=runtime_clock,
        initial_state=_state("MIL-F01", 0, source=DataSource.SYNTHETIC),
    )

    with pytest.raises(ValueError, match="share the engine clock"):
        TrafficSimulationEngine(clock=engine_clock, runtimes=(runtime,))


def test_engine_rejects_duplicate_aircraft_ids() -> None:
    clock = SimulationClock(start_time_utc=START_UTC)
    first = SyntheticAircraftRuntime(
        clock=clock,
        initial_state=_state("MIL-F01", 0, source=DataSource.SYNTHETIC),
    )
    second = SyntheticAircraftRuntime(
        clock=clock,
        initial_state=_state("MIL-F01", 1, source=DataSource.SYNTHETIC),
    )

    with pytest.raises(ValueError, match="unique aircraft IDs"):
        TrafficSimulationEngine(clock=clock, runtimes=(first, second))


def test_snapshot_normalizes_time_and_materializes_states() -> None:
    state = _state("CIV-A01", 0, source=DataSource.OPENSKY)
    timestamp_kst = datetime(2026, 9, 1, 12, 0, tzinfo=KST)

    snapshot = TrafficSnapshot(
        timestamp_utc=timestamp_kst,
        states=(item for item in (state,)),
    )

    assert snapshot.timestamp_utc == START_UTC
    assert snapshot.timestamp_utc.tzinfo is UTC
    assert snapshot.states == (state,)


def test_snapshot_rejects_invalid_state_element() -> None:
    with pytest.raises(TypeError, match="AircraftState"):
        TrafficSnapshot(timestamp_utc=START_UTC, states=("CIV-A01",))  # type: ignore[arg-type]


def test_snapshot_rejects_duplicate_aircraft_ids() -> None:
    state = _state("CIV-A01", 0, source=DataSource.OPENSKY)

    with pytest.raises(ValueError, match="unique aircraft IDs"):
        TrafficSnapshot(timestamp_utc=START_UTC, states=(state, state))


def test_snapshot_is_immutable() -> None:
    snapshot = TrafficSnapshot(timestamp_utc=START_UTC, states=())

    with pytest.raises(FrozenInstanceError):
        snapshot.states = ()  # type: ignore[misc]
