"""Clock-driven deterministic scenario event sequencing."""

from collections.abc import Iterable

from sentry_atm.scenario.event import ScenarioEvent
from sentry_atm.simulation import SimulationClock


class ScenarioEventTimeline:
    """Emit due immutable events once per Clock run in declared order."""

    __slots__ = ("_clock", "_events", "_next_index", "_observed_reset_count")

    def __init__(
        self,
        *,
        clock: SimulationClock,
        events: Iterable[ScenarioEvent],
    ) -> None:
        if not isinstance(clock, SimulationClock):
            raise TypeError("clock must be a SimulationClock")

        materialized_events = tuple(events)
        if not all(isinstance(event, ScenarioEvent) for event in materialized_events):
            raise TypeError("events must contain only ScenarioEvent instances")

        event_ids = tuple(event.event_id for event in materialized_events)
        if len(set(event_ids)) != len(event_ids):
            raise ValueError("scenario event IDs must be unique")
        if any(event.scheduled_time_utc < clock.start_time_utc for event in materialized_events):
            raise ValueError("scenario events must not precede the Clock start time")
        if any(
            current.scheduled_time_utc < previous.scheduled_time_utc
            for previous, current in zip(
                materialized_events,
                materialized_events[1:],
                strict=False,
            )
        ):
            raise ValueError("scenario events must be ordered by scheduled time")

        self._clock = clock
        self._events = materialized_events
        self._next_index = 0
        self._observed_reset_count = clock.reset_count

    @property
    def clock(self) -> SimulationClock:
        """Return the Simulation Clock controlling event delivery."""

        return self._clock

    @property
    def events(self) -> tuple[ScenarioEvent, ...]:
        """Return all events in deterministic delivery order."""

        return self._events

    @property
    def pending_events(self) -> tuple[ScenarioEvent, ...]:
        """Return events not emitted during the current Clock run."""

        self._synchronize_reset()
        return self._events[self._next_index :]

    def poll_due_events(self) -> tuple[ScenarioEvent, ...]:
        """Return newly due events while running, without changing runtime state."""

        self._synchronize_reset()
        if not self._clock.is_running:
            return ()

        start_index = self._next_index
        while (
            self._next_index < len(self._events)
            and self._events[self._next_index].scheduled_time_utc <= self._clock.current_time_utc
        ):
            self._next_index += 1
        return self._events[start_index : self._next_index]

    def _synchronize_reset(self) -> None:
        if self._observed_reset_count != self._clock.reset_count:
            self._next_index = 0
            self._observed_reset_count = self._clock.reset_count
