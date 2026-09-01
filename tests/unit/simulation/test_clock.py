from datetime import UTC, datetime

import pytest

from sentry_atm.domain.time_policy import KST
from sentry_atm.simulation import ClockState, SimulationClock

START_UTC = datetime(2026, 9, 1, 3, 0, tzinfo=UTC)


def test_clock_starts_ready_at_explicit_utc_time() -> None:
    clock = SimulationClock(start_time_utc=START_UTC)

    assert clock.start_time_utc == START_UTC
    assert clock.current_time_utc == START_UTC
    assert clock.tick_seconds == 1.0
    assert clock.tick_count == 0
    assert clock.elapsed_seconds == 0.0
    assert clock.state is ClockState.READY
    assert not clock.is_running


def test_clock_normalizes_aware_start_time_to_utc() -> None:
    start_kst = datetime(2026, 9, 1, 12, 0, tzinfo=KST)

    clock = SimulationClock(start_time_utc=start_kst)

    assert clock.start_time_utc == START_UTC
    assert clock.start_time_utc.tzinfo is UTC


def test_clock_rejects_naive_start_time() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        SimulationClock(start_time_utc=datetime(2026, 9, 1, 3, 0))


def test_clock_rejects_non_datetime_start_time() -> None:
    with pytest.raises(TypeError, match="datetime"):
        SimulationClock(start_time_utc="2026-09-01T03:00:00Z")  # type: ignore[arg-type]


@pytest.mark.parametrize("invalid", [0.0, -1.0, float("nan"), float("inf"), True])
def test_clock_rejects_invalid_tick_duration(invalid: object) -> None:
    expected_error = TypeError if isinstance(invalid, bool) else ValueError

    with pytest.raises(expected_error):
        SimulationClock(
            start_time_utc=START_UTC,
            tick_seconds=invalid,  # type: ignore[arg-type]
        )


def test_running_clock_advances_one_default_tick() -> None:
    clock = SimulationClock(start_time_utc=START_UTC)
    clock.play()

    current_time = clock.tick()

    assert current_time == datetime(2026, 9, 1, 3, 0, 1, tzinfo=UTC)
    assert clock.tick_count == 1
    assert clock.elapsed_seconds == 1.0


def test_clock_advances_multiple_steps_without_wall_clock_waiting() -> None:
    clock = SimulationClock(start_time_utc=START_UTC, tick_seconds=0.5)
    clock.play()

    current_time = clock.tick(steps=6)

    assert current_time == datetime(2026, 9, 1, 3, 0, 3, tzinfo=UTC)
    assert clock.tick_count == 6
    assert clock.elapsed_seconds == 3.0


def test_ready_clock_does_not_advance() -> None:
    clock = SimulationClock(start_time_utc=START_UTC)

    assert clock.tick() == START_UTC
    assert clock.tick_count == 0


def test_paused_clock_does_not_advance_and_can_resume() -> None:
    clock = SimulationClock(start_time_utc=START_UTC)
    clock.play()
    clock.tick(steps=2)
    clock.pause()

    paused_time = clock.tick(steps=5)

    assert paused_time == datetime(2026, 9, 1, 3, 0, 2, tzinfo=UTC)
    assert clock.state is ClockState.PAUSED
    assert not clock.is_running

    clock.play()
    assert clock.tick() == datetime(2026, 9, 1, 3, 0, 3, tzinfo=UTC)


def test_pause_before_play_preserves_ready_state() -> None:
    clock = SimulationClock(start_time_utc=START_UTC)

    clock.pause()

    assert clock.state is ClockState.READY


def test_reset_restores_start_time_and_ready_state() -> None:
    clock = SimulationClock(start_time_utc=START_UTC)
    clock.play()
    clock.tick(steps=10)

    clock.reset()

    assert clock.current_time_utc == START_UTC
    assert clock.tick_count == 0
    assert clock.elapsed_seconds == 0.0
    assert clock.state is ClockState.READY


@pytest.mark.parametrize("invalid", [0, -1, 1.5, True])
def test_tick_rejects_invalid_step_count(invalid: object) -> None:
    clock = SimulationClock(start_time_utc=START_UTC)

    expected_error = TypeError if isinstance(invalid, (bool, float)) else ValueError
    with pytest.raises(expected_error):
        clock.tick(invalid)  # type: ignore[arg-type]


def test_same_commands_produce_identical_time() -> None:
    first = SimulationClock(start_time_utc=START_UTC)
    second = SimulationClock(start_time_utc=START_UTC)

    for clock in (first, second):
        clock.play()
        clock.tick(steps=5)
        clock.pause()
        clock.tick(steps=20)
        clock.play()
        clock.tick(steps=3)

    assert first.current_time_utc == second.current_time_utc
    assert first.tick_count == second.tick_count == 8
