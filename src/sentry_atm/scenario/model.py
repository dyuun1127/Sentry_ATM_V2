"""Immutable scenario definition models independent from runtime state."""

from dataclasses import dataclass
from datetime import datetime

from sentry_atm.domain import AircraftMetadata, AircraftState, DataSource
from sentry_atm.domain.time_policy import to_utc
from sentry_atm.domain.validation import require_identifier


@dataclass(frozen=True, slots=True)
class ScenarioAircraft:
    """Bind stable metadata to one Synthetic scenario initial state."""

    metadata: AircraftMetadata
    initial_state: AircraftState

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

    @property
    def aircraft_id(self) -> str:
        return self.metadata.aircraft_id


@dataclass(frozen=True, slots=True)
class ScenarioDefinition:
    """A deterministic ordered set of aircraft sharing one UTC start time."""

    scenario_id: str
    start_time_utc: datetime
    aircraft: tuple[ScenarioAircraft, ...]

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

    @property
    def aircraft_ids(self) -> tuple[str, ...]:
        return tuple(item.aircraft_id for item in self.aircraft)

    @property
    def metadata(self) -> tuple[AircraftMetadata, ...]:
        return tuple(item.metadata for item in self.aircraft)

    @property
    def initial_states(self) -> tuple[AircraftState, ...]:
        return tuple(item.initial_state for item in self.aircraft)
