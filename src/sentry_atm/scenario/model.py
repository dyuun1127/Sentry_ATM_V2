"""Immutable scenario definition models independent from runtime state."""

from dataclasses import dataclass
from datetime import datetime

from sentry_atm.domain import AircraftMetadata, AircraftState, DataSource
from sentry_atm.domain.time_policy import to_utc
from sentry_atm.domain.validation import require_identifier
from sentry_atm.scenario.event import ScenarioEvent
from sentry_atm.scenario.presence import normalize_presence


@dataclass(frozen=True, slots=True)
class ScenarioAircraft:
    """Bind metadata to one initial state and optional future state anchors."""

    metadata: AircraftMetadata
    initial_state: AircraftState
    scheduled_states: tuple[AircraftState, ...] = ()
    presence: tuple[tuple[datetime, datetime], ...] = ()
    """이 항공기가 관할 구역 안에 있는 구간들. 비어 있으면 계속 있는 것으로 본다.

    골든 데모는 8대가 5분 동안 전부 떠 있었으므로 이런 것이 필요 없었다. 소티는
    다르다. 착륙한 항공기를 그대로 두면 활주로를 지나 계속 직진하고, 그 유령이
    끝까지 분리 판정의 대상이 된다.

    구간이 **여럿일 수 있는** 이유는 출격 소티 때문이다. 전투기는 이륙 후 터미널
    구역을 떠나 작전지역에서 임무를 수행하고 돌아온다. 그 사이 항공기는 우리
    관할이 아니다 — 없는 항적을 지어내 두 구간을 이으면 규정 계층이 만들지 않은
    데이터가 산출물 한가운데 들어간다. 안 보이는 것이 사실에 가깝다.
    """

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

        windows = normalize_presence(self.presence)
        object.__setattr__(self, "presence", windows)
        if windows and windows[0][0] > self.initial_state.timestamp_utc:
            raise ValueError("presence must start no later than the initial state")

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
        # 초기 상태가 시작 시각과 **같아야 한다**는 규칙이었다. 8대가 5분 동안
        # 전부 떠 있던 골든 데모에서는 참이었지만, 시나리오의 성질이 아니라 그
        # 시나리오의 성질이었다. 소티는 75분에 걸쳐 15대가 들어오므로 항공기마다
        # 등장 시각이 다르다. 시작 이전으로 가는 것만 막는다 — 그것은 시계가
        # 도달할 수 없는 시각이라 그 항공기는 영원히 나타나지 않는다.
        if any(item.initial_state.timestamp_utc < self.start_time_utc for item in self.aircraft):
            raise ValueError("initial states must not precede the scenario start time")

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
