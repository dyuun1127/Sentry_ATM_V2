"""Deterministic simulation time independent from the system wall clock."""

from datetime import datetime, timedelta
from enum import StrEnum
from numbers import Real

from sentry_atm.domain.time_policy import to_utc
from sentry_atm.domain.units import as_non_negative_float


class ClockState(StrEnum):
    """Playback state of a simulation clock."""

    READY = "READY"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"


class SimulationClock:
    """Advance UTC simulation time by explicit, deterministic ticks."""

    __slots__ = (
        "_start_time_utc",
        "_reset_count",
        "_state",
        "_tick_count",
        "_tick_seconds",
    )

    def __init__(self, *, start_time_utc: datetime, tick_seconds: Real = 1.0) -> None:
        self._start_time_utc = to_utc(start_time_utc, field_name="start_time_utc")
        validated_tick_seconds = as_non_negative_float(
            tick_seconds,
            field_name="tick_seconds",
        )
        if validated_tick_seconds == 0.0:
            raise ValueError("tick_seconds must be greater than zero")
        self._tick_seconds = validated_tick_seconds
        self._tick_count = 0
        self._reset_count = 0
        self._state = ClockState.READY

    @property
    def start_time_utc(self) -> datetime:
        """Return the immutable UTC origin of this simulation run."""

        return self._start_time_utc

    @property
    def current_time_utc(self) -> datetime:
        """Return current UTC simulation time derived from completed ticks."""

        return self._start_time_utc + timedelta(seconds=self.elapsed_seconds)

    @property
    def tick_seconds(self) -> float:
        """Return the duration represented by one tick."""

        return self._tick_seconds

    @property
    def tick_count(self) -> int:
        """Return the number of ticks completed while running."""

        return self._tick_count

    @property
    def reset_count(self) -> int:
        """Return how many explicit resets have started a new deterministic run."""

        return self._reset_count

    @property
    def elapsed_seconds(self) -> float:
        """Return simulation seconds elapsed since the start time."""

        return self._tick_count * self._tick_seconds

    @property
    def state(self) -> ClockState:
        """Return the current playback state."""

        return self._state

    @property
    def is_running(self) -> bool:
        """Return whether ticks currently advance simulation time."""

        return self._state is ClockState.RUNNING

    def play(self) -> None:
        """Start or resume simulation-time advancement."""

        self._state = ClockState.RUNNING

    def pause(self) -> None:
        """Pause a running clock without changing its current time."""

        if self._state is ClockState.RUNNING:
            self._state = ClockState.PAUSED

    def reset(self) -> None:
        """Restore the start time and READY state."""

        self._tick_count = 0
        self._reset_count += 1
        self._state = ClockState.READY

    def tick(self, steps: int = 1) -> datetime:
        """Advance by whole tick steps when running and return current UTC time."""

        if isinstance(steps, bool) or not isinstance(steps, int):
            raise TypeError("steps must be an integer")
        if steps <= 0:
            raise ValueError("steps must be greater than zero")
        if self.is_running:
            self._tick_count += steps
        return self.current_time_utc
