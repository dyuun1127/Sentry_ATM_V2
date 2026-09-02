from datetime import UTC, datetime, timedelta

import pytest

from sentry_atm.domain import AircraftState, DataSource
from sentry_atm.simulation import PlaybackAircraftRuntime, SimulationClock

START_UTC = datetime(2026, 9, 1, 3, 0, tzinfo=UTC)


def _state(
    seconds: int,
    *,
    aircraft_id: str = "CIV-A01",
    source: DataSource = DataSource.OPENSKY,
) -> AircraftState:
    return AircraftState(
        aircraft_id=aircraft_id,
        timestamp_utc=START_UTC + timedelta(seconds=seconds),
        x_nm=float(seconds),
        y_nm=0.0,
        altitude_ft=8_000.0,
        ground_speed_kt=240.0,
        heading_deg=90.0,
        vertical_speed_fpm=0.0,
        source=source,
    )


def _runtime(
    *,
    clock_start_seconds: int = 0,
) -> tuple[SimulationClock, PlaybackAircraftRuntime]:
    clock = SimulationClock(start_time_utc=START_UTC + timedelta(seconds=clock_start_seconds))
    runtime = PlaybackAircraftRuntime(
        clock=clock,
        states=(_state(2), _state(5), _state(9)),
    )
    return clock, runtime


def test_runtime_exposes_single_aircraft_recording_bounds() -> None:
    _, runtime = _runtime()

    assert runtime.aircraft_id == "CIV-A01"
    assert runtime.start_time_utc == START_UTC + timedelta(seconds=2)
    assert runtime.end_time_utc == START_UTC + timedelta(seconds=9)
    assert runtime.states == (_state(2), _state(5), _state(9))


def test_current_state_is_none_before_first_record() -> None:
    _, runtime = _runtime()

    assert runtime.current_state is None


def test_current_state_selects_record_at_exact_timestamp() -> None:
    _, runtime = _runtime(clock_start_seconds=5)

    assert runtime.current_state == _state(5)


def test_current_state_holds_latest_record_between_timestamps() -> None:
    _, runtime = _runtime(clock_start_seconds=7)

    assert runtime.current_state == _state(5)


def test_current_state_holds_final_record_after_track_end() -> None:
    _, runtime = _runtime(clock_start_seconds=30)

    assert runtime.current_state == _state(9)


def test_runtime_follows_clock_play_pause_resume_and_reset() -> None:
    clock, runtime = _runtime()
    clock.play()

    clock.tick(steps=2)
    assert runtime.current_state == _state(2)

    clock.tick(steps=4)
    assert runtime.current_state == _state(5)

    clock.pause()
    clock.tick(steps=20)
    assert runtime.current_state == _state(5)

    clock.play()
    clock.tick(steps=3)
    assert runtime.current_state == _state(9)

    clock.reset()
    assert runtime.current_state is None


def test_runtime_materializes_a_state_generator_once() -> None:
    clock = SimulationClock(start_time_utc=START_UTC)
    states = (_state(seconds) for seconds in (2, 5, 9))

    runtime = PlaybackAircraftRuntime(clock=clock, states=states)

    assert len(runtime.states) == 3


def test_two_aircraft_runtimes_select_independently_on_shared_clock() -> None:
    clock = SimulationClock(start_time_utc=START_UTC)
    first = PlaybackAircraftRuntime(
        clock=clock,
        states=(_state(1, aircraft_id="CIV-A01"), _state(4, aircraft_id="CIV-A01")),
    )
    second = PlaybackAircraftRuntime(
        clock=clock,
        states=(_state(2, aircraft_id="CIV-A02"), _state(6, aircraft_id="CIV-A02")),
    )
    clock.play()

    clock.tick(steps=5)

    assert first.current_state == _state(4, aircraft_id="CIV-A01")
    assert second.current_state == _state(2, aircraft_id="CIV-A02")


def test_runtime_rejects_incorrect_clock_type() -> None:
    with pytest.raises(TypeError, match="SimulationClock"):
        PlaybackAircraftRuntime(clock=START_UTC, states=(_state(0),))  # type: ignore[arg-type]


def test_runtime_rejects_empty_states() -> None:
    clock = SimulationClock(start_time_utc=START_UTC)

    with pytest.raises(ValueError, match="must not be empty"):
        PlaybackAircraftRuntime(clock=clock, states=())


def test_runtime_rejects_non_aircraft_state_element() -> None:
    clock = SimulationClock(start_time_utc=START_UTC)

    with pytest.raises(TypeError, match="AircraftState"):
        PlaybackAircraftRuntime(clock=clock, states=(_state(0), "invalid"))  # type: ignore[arg-type]


def test_runtime_rejects_mixed_aircraft_ids() -> None:
    clock = SimulationClock(start_time_utc=START_UTC)

    with pytest.raises(ValueError, match="one aircraft"):
        PlaybackAircraftRuntime(
            clock=clock,
            states=(_state(0, aircraft_id="CIV-A01"), _state(1, aircraft_id="CIV-A02")),
        )


def test_runtime_rejects_synthetic_states() -> None:
    clock = SimulationClock(start_time_utc=START_UTC)

    with pytest.raises(ValueError, match="OPENSKY"):
        PlaybackAircraftRuntime(
            clock=clock,
            states=(_state(0, source=DataSource.SYNTHETIC),),
        )


@pytest.mark.parametrize("seconds", [(2, 1), (1, 1)])
def test_runtime_requires_strictly_increasing_timestamps(
    seconds: tuple[int, int],
) -> None:
    clock = SimulationClock(start_time_utc=START_UTC)

    with pytest.raises(ValueError, match="strictly increasing"):
        PlaybackAircraftRuntime(
            clock=clock,
            states=tuple(_state(second) for second in seconds),
        )
