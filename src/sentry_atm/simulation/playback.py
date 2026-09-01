"""Read-only playback runtime for recorded aircraft states."""

from bisect import bisect_right
from collections.abc import Iterable
from datetime import datetime

from sentry_atm.domain.aircraft import AircraftState
from sentry_atm.domain.enums import DataSource
from sentry_atm.simulation.clock import SimulationClock


class PlaybackAircraftRuntime:
    """Select the latest recorded aircraft state at the simulation clock time."""

    __slots__ = ("_clock", "_states", "_timestamps")

    def __init__(
        self,
        *,
        clock: SimulationClock,
        states: Iterable[AircraftState],
    ) -> None:
        if not isinstance(clock, SimulationClock):
            raise TypeError("clock must be a SimulationClock")

        recorded_states = tuple(states)
        if not recorded_states:
            raise ValueError("playback states must not be empty")
        if not all(isinstance(state, AircraftState) for state in recorded_states):
            raise TypeError("playback states must all be AircraftState instances")

        self._validate_single_aircraft(recorded_states)
        self._validate_playback_source(recorded_states)
        self._validate_strict_time_order(recorded_states)

        self._clock = clock
        self._states = recorded_states
        self._timestamps = tuple(state.timestamp_utc for state in recorded_states)

    @staticmethod
    def _validate_single_aircraft(states: tuple[AircraftState, ...]) -> None:
        aircraft_id = states[0].aircraft_id
        if any(state.aircraft_id != aircraft_id for state in states[1:]):
            raise ValueError("playback states must belong to one aircraft")

    @staticmethod
    def _validate_playback_source(states: tuple[AircraftState, ...]) -> None:
        if any(state.source is not DataSource.OPENSKY for state in states):
            raise ValueError("playback states must use the OPENSKY source")

    @staticmethod
    def _validate_strict_time_order(states: tuple[AircraftState, ...]) -> None:
        for previous, current in zip(states, states[1:], strict=False):
            if current.timestamp_utc <= previous.timestamp_utc:
                raise ValueError("playback state timestamps must be strictly increasing")

    @property
    def aircraft_id(self) -> str:
        """Return the aircraft represented by this runtime."""

        return self._states[0].aircraft_id

    @property
    def states(self) -> tuple[AircraftState, ...]:
        """Return the immutable recorded state sequence."""

        return self._states

    @property
    def start_time_utc(self) -> datetime:
        """Return the first recorded state timestamp."""

        return self._timestamps[0]

    @property
    def end_time_utc(self) -> datetime:
        """Return the last recorded state timestamp."""

        return self._timestamps[-1]

    @property
    def current_state(self) -> AircraftState | None:
        """Return the latest state at or before current simulation time."""

        index = bisect_right(self._timestamps, self._clock.current_time_utc) - 1
        if index < 0:
            return None
        return self._states[index]
