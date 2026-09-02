"""Deterministic multi-aircraft traffic simulation coordination."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from sentry_atm.domain.aircraft import AircraftState
from sentry_atm.domain.time_policy import to_utc
from sentry_atm.simulation.clock import SimulationClock
from sentry_atm.simulation.playback import PlaybackAircraftRuntime
from sentry_atm.simulation.synthetic import SyntheticAircraftRuntime

AircraftRuntime = PlaybackAircraftRuntime | SyntheticAircraftRuntime


@dataclass(frozen=True, slots=True)
class TrafficSnapshot:
    """Immutable active aircraft states observed at one simulation time."""

    timestamp_utc: datetime
    states: tuple[AircraftState, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "timestamp_utc",
            to_utc(self.timestamp_utc, field_name="timestamp_utc"),
        )
        object.__setattr__(self, "states", tuple(self.states))
        if not all(isinstance(state, AircraftState) for state in self.states):
            raise TypeError("snapshot states must all be AircraftState instances")

        aircraft_ids = tuple(state.aircraft_id for state in self.states)
        if len(set(aircraft_ids)) != len(aircraft_ids):
            raise ValueError("snapshot states must have unique aircraft IDs")

    @property
    def aircraft_ids(self) -> tuple[str, ...]:
        """Return active aircraft identifiers in deterministic order."""

        return tuple(state.aircraft_id for state in self.states)


class TrafficSimulationEngine:
    """Coordinate multiple aircraft runtimes on one simulation clock."""

    __slots__ = ("_clock", "_runtimes")

    def __init__(
        self,
        *,
        clock: SimulationClock,
        runtimes: Iterable[AircraftRuntime],
    ) -> None:
        if not isinstance(clock, SimulationClock):
            raise TypeError("clock must be a SimulationClock")

        registered_runtimes = tuple(runtimes)
        if not registered_runtimes:
            raise ValueError("traffic runtimes must not be empty")

        supported_runtime_types = (PlaybackAircraftRuntime, SyntheticAircraftRuntime)
        if not all(isinstance(runtime, supported_runtime_types) for runtime in registered_runtimes):
            raise TypeError("traffic runtimes must be supported aircraft runtimes")
        if any(runtime.clock is not clock for runtime in registered_runtimes):
            raise ValueError("traffic runtimes must share the engine clock")

        aircraft_ids = tuple(runtime.aircraft_id for runtime in registered_runtimes)
        if len(set(aircraft_ids)) != len(aircraft_ids):
            raise ValueError("traffic runtimes must have unique aircraft IDs")

        self._clock = clock
        self._runtimes = registered_runtimes

    @property
    def clock(self) -> SimulationClock:
        """Return the shared simulation clock."""

        return self._clock

    @property
    def runtimes(self) -> tuple[AircraftRuntime, ...]:
        """Return registered runtimes in deterministic order."""

        return self._runtimes

    @property
    def aircraft_ids(self) -> tuple[str, ...]:
        """Return all registered aircraft identifiers."""

        return tuple(runtime.aircraft_id for runtime in self._runtimes)

    def snapshot(self) -> TrafficSnapshot:
        """Collect active runtime states at current simulation time."""

        timestamp_utc = self._clock.current_time_utc
        active_states = tuple(
            state for runtime in self._runtimes if (state := runtime.current_state) is not None
        )
        return TrafficSnapshot(timestamp_utc=timestamp_utc, states=active_states)

    def tick(self, steps: int = 1) -> TrafficSnapshot:
        """Advance the shared clock when running and return a new snapshot."""

        self._clock.tick(steps=steps)
        return self.snapshot()
