from dataclasses import replace
from datetime import UTC, datetime, timedelta
from math import sqrt

import pytest

from sentry_atm.domain import (
    AircraftState,
    DataSource,
    EmergencyStatus,
    EmergencyType,
    FlightPhase,
)
from sentry_atm.simulation import SimulationClock, SyntheticAircraftRuntime

START_UTC = datetime(2026, 9, 1, 3, 0, tzinfo=UTC)


def _state(
    *,
    timestamp_offset_seconds: int = 0,
    x_nm: float = 10.0,
    y_nm: float = -5.0,
    altitude_ft: float = 8_000.0,
    ground_speed_kt: float = 360.0,
    heading_deg: float = 90.0,
    vertical_speed_fpm: float = 0.0,
    source: DataSource = DataSource.SYNTHETIC,
) -> AircraftState:
    return AircraftState(
        aircraft_id="MIL-F01",
        timestamp_utc=START_UTC + timedelta(seconds=timestamp_offset_seconds),
        x_nm=x_nm,
        y_nm=y_nm,
        altitude_ft=altitude_ft,
        ground_speed_kt=ground_speed_kt,
        heading_deg=heading_deg,
        vertical_speed_fpm=vertical_speed_fpm,
        source=source,
        flight_phase=FlightPhase.LEVEL,
    )


def _runtime(
    initial_state: AircraftState | None = None,
) -> tuple[SimulationClock, SyntheticAircraftRuntime]:
    clock = SimulationClock(start_time_utc=START_UTC)
    runtime = SyntheticAircraftRuntime(
        clock=clock,
        initial_state=initial_state or _state(),
    )
    return clock, runtime


def test_runtime_exposes_aircraft_and_initial_state() -> None:
    initial_state = _state()
    _, runtime = _runtime(initial_state)

    assert runtime.aircraft_id == "MIL-F01"
    assert runtime.initial_state is initial_state
    assert runtime.current_state is initial_state


def test_current_state_is_none_before_initial_state_time() -> None:
    _, runtime = _runtime(_state(timestamp_offset_seconds=5))

    assert runtime.current_state is None


@pytest.mark.parametrize(
    ("heading_deg", "expected_x", "expected_y"),
    [
        (0.0, 0.0, 1.0),
        (90.0, 1.0, 0.0),
        (180.0, 0.0, -1.0),
        (270.0, -1.0, 0.0),
    ],
)
def test_cardinal_headings_follow_local_axis_policy(
    heading_deg: float,
    expected_x: float,
    expected_y: float,
) -> None:
    clock, runtime = _runtime(_state(x_nm=0.0, y_nm=0.0, heading_deg=heading_deg))
    clock.play()

    clock.tick(steps=10)
    current = runtime.current_state

    assert current is not None
    assert current.x_nm == pytest.approx(expected_x, abs=1e-12)
    assert current.y_nm == pytest.approx(expected_y, abs=1e-12)


def test_diagonal_motion_preserves_ground_distance() -> None:
    clock, runtime = _runtime(_state(x_nm=0.0, y_nm=0.0, heading_deg=45.0))
    clock.play()

    clock.tick(steps=10)
    current = runtime.current_state

    assert current is not None
    assert current.x_nm == pytest.approx(1.0 / sqrt(2.0))
    assert current.y_nm == pytest.approx(1.0 / sqrt(2.0))
    assert current.x_nm**2 + current.y_nm**2 == pytest.approx(1.0)


@pytest.mark.parametrize(
    ("vertical_speed_fpm", "expected_altitude_ft"),
    [(600.0, 8_300.0), (-600.0, 7_700.0)],
)
def test_vertical_speed_changes_altitude(
    vertical_speed_fpm: float,
    expected_altitude_ft: float,
) -> None:
    clock, runtime = _runtime(_state(ground_speed_kt=0.0, vertical_speed_fpm=vertical_speed_fpm))
    clock.play()

    clock.tick(steps=30)
    current = runtime.current_state

    assert current is not None
    assert current.altitude_ft == pytest.approx(expected_altitude_ft)


def test_calculated_state_preserves_motion_and_status_fields() -> None:
    initial_state = AircraftState(
        aircraft_id="MIL-T01",
        timestamp_utc=START_UTC,
        x_nm=0.0,
        y_nm=0.0,
        altitude_ft=6_000.0,
        ground_speed_kt=180.0,
        heading_deg=210.0,
        vertical_speed_fpm=-300.0,
        source=DataSource.SYNTHETIC,
        flight_phase=FlightPhase.DESCENT,
        emergency_status=EmergencyStatus.DECLARED,
        emergency_type=EmergencyType.PRIORITY_RETURN,
    )
    clock = SimulationClock(start_time_utc=START_UTC)
    runtime = SyntheticAircraftRuntime(clock=clock, initial_state=initial_state)
    clock.play()

    clock.tick(steps=1)
    current = runtime.current_state

    assert current is not None
    assert current.timestamp_utc == START_UTC + timedelta(seconds=1)
    assert current.aircraft_id == initial_state.aircraft_id
    assert current.ground_speed_kt == initial_state.ground_speed_kt
    assert current.heading_deg == initial_state.heading_deg
    assert current.vertical_speed_fpm == initial_state.vertical_speed_fpm
    assert current.source is DataSource.SYNTHETIC
    assert current.flight_phase is FlightPhase.DESCENT
    assert current.emergency_status is EmergencyStatus.DECLARED
    assert current.emergency_type is EmergencyType.PRIORITY_RETURN


def test_runtime_follows_clock_pause_resume_and_reset() -> None:
    clock, runtime = _runtime()
    clock.play()
    clock.tick(steps=5)
    clock.pause()

    paused_state = runtime.current_state
    clock.tick(steps=20)

    assert runtime.current_state == paused_state

    clock.play()
    clock.tick(steps=5)
    advanced_state = runtime.current_state

    assert advanced_state is not None
    assert advanced_state.x_nm == pytest.approx(11.0)

    clock.reset()
    assert runtime.current_state is runtime.initial_state


def test_scheduled_state_becomes_new_motion_anchor_and_replays_after_reset() -> None:
    scheduled = _state(
        timestamp_offset_seconds=5,
        x_nm=20.0,
        y_nm=1.0,
        altitude_ft=7_400.0,
        heading_deg=180.0,
        vertical_speed_fpm=-600.0,
    )
    clock = SimulationClock(start_time_utc=START_UTC)
    runtime = SyntheticAircraftRuntime(
        clock=clock,
        initial_state=_state(),
        scheduled_states=(scheduled,),
    )
    clock.play()

    clock.tick(steps=4)
    assert runtime.current_state is not scheduled
    clock.tick()
    assert runtime.current_state is scheduled
    clock.tick(steps=5)
    current = runtime.current_state
    assert current is not None
    assert current.x_nm == pytest.approx(20.0)
    assert current.y_nm == pytest.approx(0.5)
    assert current.altitude_ft == pytest.approx(7_350.0)

    clock.reset()
    assert runtime.current_state is runtime.initial_state
    clock.play()
    clock.tick(steps=5)
    assert runtime.current_state is scheduled


def test_runtime_materializes_and_validates_scheduled_states() -> None:
    clock = SimulationClock(start_time_utc=START_UTC)
    scheduled = _state(timestamp_offset_seconds=5)
    source = [scheduled]
    runtime = SyntheticAircraftRuntime(
        clock=clock,
        initial_state=_state(),
        scheduled_states=source,
    )
    source.clear()
    assert runtime.scheduled_states == (scheduled,)

    with pytest.raises(TypeError, match="iterable"):
        SyntheticAircraftRuntime(
            clock=clock,
            initial_state=_state(),
            scheduled_states="state",  # type: ignore[arg-type]
        )
    with pytest.raises(TypeError, match="iterable"):
        SyntheticAircraftRuntime(
            clock=clock,
            initial_state=_state(),
            scheduled_states=None,  # type: ignore[arg-type]
        )
    with pytest.raises(TypeError, match="AircraftState"):
        SyntheticAircraftRuntime(
            clock=clock,
            initial_state=_state(),
            scheduled_states=("state",),  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError, match="aircraft ID"):
        SyntheticAircraftRuntime(
            clock=clock,
            initial_state=_state(),
            scheduled_states=(
                AircraftState(
                    aircraft_id="CIV-A01",
                    timestamp_utc=START_UTC + timedelta(seconds=5),
                    x_nm=0.0,
                    y_nm=0.0,
                    altitude_ft=8_000.0,
                    ground_speed_kt=200.0,
                    heading_deg=0.0,
                    vertical_speed_fpm=0.0,
                    source=DataSource.SYNTHETIC,
                ),
            ),
        )
    with pytest.raises(ValueError, match="strictly ordered"):
        SyntheticAircraftRuntime(
            clock=clock,
            initial_state=_state(),
            scheduled_states=(_state(),),
        )
    with pytest.raises(ValueError, match="SYNTHETIC"):
        SyntheticAircraftRuntime(
            clock=clock,
            initial_state=_state(),
            scheduled_states=(_state(timestamp_offset_seconds=5, source=DataSource.OPENSKY),),
        )


def test_fractional_tick_duration_is_reflected_in_motion() -> None:
    clock = SimulationClock(start_time_utc=START_UTC, tick_seconds=0.5)
    runtime = SyntheticAircraftRuntime(clock=clock, initial_state=_state())
    clock.play()

    clock.tick(steps=5)
    current = runtime.current_state

    assert current is not None
    assert current.timestamp_utc == START_UTC + timedelta(seconds=2.5)
    assert current.x_nm == pytest.approx(10.25)


def test_same_clock_commands_produce_identical_synthetic_state() -> None:
    first_clock, first_runtime = _runtime()
    second_clock, second_runtime = _runtime()

    for clock in (first_clock, second_clock):
        clock.play()
        clock.tick(steps=7)
        clock.pause()
        clock.tick(steps=100)
        clock.play()
        clock.tick(steps=3)

    assert first_runtime.current_state == second_runtime.current_state


def test_runtime_rejects_incorrect_clock_type() -> None:
    with pytest.raises(TypeError, match="SimulationClock"):
        SyntheticAircraftRuntime(clock=START_UTC, initial_state=_state())  # type: ignore[arg-type]


def test_runtime_rejects_incorrect_initial_state_type() -> None:
    clock = SimulationClock(start_time_utc=START_UTC)

    with pytest.raises(TypeError, match="AircraftState"):
        SyntheticAircraftRuntime(clock=clock, initial_state="MIL-F01")  # type: ignore[arg-type]


def test_runtime_rejects_opensky_initial_state() -> None:
    clock = SimulationClock(start_time_utc=START_UTC)

    with pytest.raises(ValueError, match="SYNTHETIC"):
        SyntheticAircraftRuntime(
            clock=clock,
            initial_state=_state(source=DataSource.OPENSKY),
        )


def test_applied_state_anchor_changes_motion_and_clears_on_clock_reset() -> None:
    clock, runtime = _runtime()
    clock.play()
    clock.tick(steps=10)
    before = runtime.current_state
    assert before is not None
    applied = replace(
        before,
        altitude_ft=9_000.0,
        heading_deg=0.0,
        vertical_speed_fpm=0.0,
    )

    runtime.apply_state_anchor(applied)

    assert runtime.applied_states == (applied,)
    assert runtime.current_state is applied
    clock.tick(steps=10)
    current = runtime.current_state
    assert current is not None
    assert current.x_nm == pytest.approx(applied.x_nm)
    assert current.y_nm == pytest.approx(applied.y_nm + 1.0)
    assert current.altitude_ft == 9_000.0

    clock.reset()
    assert runtime.applied_states == ()
    assert runtime.current_state is runtime.initial_state


def test_apply_state_anchor_validates_runtime_identity_source_time_and_duplicates() -> None:
    clock, runtime = _runtime()
    with pytest.raises(ValueError, match="RUNNING"):
        runtime.apply_state_anchor(_state())

    clock.play()
    clock.tick(steps=10)
    current = runtime.current_state
    assert current is not None
    with pytest.raises(TypeError, match="AircraftState"):
        runtime.apply_state_anchor("state")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="Runtime aircraft ID"):
        runtime.apply_state_anchor(replace(current, aircraft_id="CIV-A01"))
    with pytest.raises(ValueError, match="SYNTHETIC"):
        runtime.apply_state_anchor(replace(current, source=DataSource.OPENSKY))
    with pytest.raises(ValueError, match="Runtime Clock"):
        runtime.apply_state_anchor(replace(current, timestamp_utc=START_UTC + timedelta(seconds=9)))

    runtime.apply_state_anchor(current)
    with pytest.raises(ValueError, match="already exists"):
        runtime.apply_state_anchor(current)


def test_applied_anchor_cannot_replace_a_scheduled_anchor_at_same_time() -> None:
    clock = SimulationClock(start_time_utc=START_UTC)
    scheduled = _state(timestamp_offset_seconds=10)
    runtime = SyntheticAircraftRuntime(
        clock=clock,
        initial_state=_state(),
        scheduled_states=(scheduled,),
    )
    clock.play()
    clock.tick(steps=10)

    with pytest.raises(ValueError, match="already exists"):
        runtime.apply_state_anchor(scheduled)
