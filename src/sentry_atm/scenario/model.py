"""Immutable scenario definition models independent from runtime state."""

from dataclasses import dataclass
from datetime import datetime

from sentry_atm.domain import AircraftMetadata, AircraftState, DataSource
from sentry_atm.domain.time_policy import to_utc
from sentry_atm.domain.validation import require_identifier
from sentry_atm.scenario.event import ScenarioEvent


@dataclass(frozen=True, slots=True)
class ScenarioAircraft:
    """Bind metadata to one initial state and optional future state anchors."""

    metadata: AircraftMetadata
    initial_state: AircraftState
    scheduled_states: tuple[AircraftState, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.metadata, AircraftMetadata):
            raise TypeError("metadata must be AircraftMetadata")
        if not isinstance(self.initial_state, AircraftState):
            raise TypeError("initial_state must be AircraftState")
        if self.metadata.aircraft_id != self.initial_state.aircraft_id:
            raise ValueError("metadata and initial_state aircraft IDs must match")
        if self.initial_state.source is not DataSource.SYNTHETIC:
            raise ValueError("scenario initial_state must use the SYNTHETIC source")
        if self.metadata.performance_class is None:
            raise ValueError("scenario metadata must reference a performance profile")

        if isinstance(self.scheduled_states, (str, bytes)):
            raise TypeError("scheduled_states must be an iterable of AircraftState instances")
        try:
            materialized_states = tuple(self.scheduled_states)
        except TypeError:
            raise TypeError(
                "scheduled_states must be an iterable of AircraftState instances"
            ) from None
        object.__setattr__(self, "scheduled_states", materialized_states)
        if not all(isinstance(state, AircraftState) for state in self.scheduled_states):
            raise TypeError("scheduled_states must contain only AircraftState instances")
        if any(state.aircraft_id != self.aircraft_id for state in self.scheduled_states):
            raise ValueError("scheduled_states must use the scenario aircraft ID")
        if any(state.source is not DataSource.SYNTHETIC for state in self.scheduled_states):
            raise ValueError("scheduled_states must use the SYNTHETIC source")
        motion_anchors = (self.initial_state, *self.scheduled_states)
        if any(
            current.timestamp_utc <= previous.timestamp_utc
            for previous, current in zip(motion_anchors, motion_anchors[1:], strict=False)
        ):
            raise ValueError("scheduled_states must be strictly ordered after initial_state")

    @property
    def aircraft_id(self) -> str:
        return self.metadata.aircraft_id


@dataclass(frozen=True, slots=True)
class ScenarioDefinition:
    """A deterministic ordered aircraft and event set sharing one UTC origin."""

    scenario_id: str
    start_time_utc: datetime
    aircraft: tuple[ScenarioAircraft, ...]
    events: tuple[ScenarioEvent, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "scenario_id",
            require_identifier(self.scenario_id, field_name="scenario_id"),
        )
        object.__setattr__(
            self,
            "start_time_utc",
            to_utc(self.start_time_utc, field_name="start_time_utc"),
        )
        object.__setattr__(self, "aircraft", tuple(self.aircraft))
        if not self.aircraft:
            raise ValueError("scenario aircraft must not be empty")
        if not all(isinstance(item, ScenarioAircraft) for item in self.aircraft):
            raise TypeError("scenario aircraft must contain only ScenarioAircraft instances")
        aircraft_ids = self.aircraft_ids
        if len(set(aircraft_ids)) != len(aircraft_ids):
            raise ValueError("scenario aircraft IDs must be unique")
        if any(item.initial_state.timestamp_utc != self.start_time_utc for item in self.aircraft):
            raise ValueError("all initial states must use the scenario start time")

        object.__setattr__(self, "events", tuple(self.events))
        if not all(isinstance(event, ScenarioEvent) for event in self.events):
            raise TypeError("scenario events must contain only ScenarioEvent instances")
        event_ids = tuple(event.event_id for event in self.events)
        if len(set(event_ids)) != len(event_ids):
            raise ValueError("scenario event IDs must be unique")
        if any(event.target_aircraft_id not in aircraft_ids for event in self.events):
            raise ValueError("scenario event targets must reference scenario aircraft")
        if any(event.scheduled_time_utc < self.start_time_utc for event in self.events):
            raise ValueError("scenario events must not precede the scenario start time")
        if any(
            current.scheduled_time_utc < previous.scheduled_time_utc
            for previous, current in zip(self.events, self.events[1:], strict=False)
        ):
            raise ValueError("scenario events must be ordered by scheduled time")

    @property
    def aircraft_ids(self) -> tuple[str, ...]:
        return tuple(item.aircraft_id for item in self.aircraft)

    @property
    def metadata(self) -> tuple[AircraftMetadata, ...]:
        return tuple(item.metadata for item in self.aircraft)

    @property
    def initial_states(self) -> tuple[AircraftState, ...]:
        return tuple(item.initial_state for item in self.aircraft)
