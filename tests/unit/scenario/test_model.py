from datetime import UTC, datetime, timedelta

import pytest

from sentry_atm.domain import AircraftMetadata, AircraftState, DataSource
from sentry_atm.scenario import (
    EntryConformanceDeviationPayload,
    ScenarioAircraft,
    ScenarioDefinition,
    ScenarioEvent,
    ScenarioEventType,
)

START_UTC = datetime(2026, 9, 2, 3, 0, tzinfo=UTC)


def _state(
    aircraft_id: str = "CIV-A01",
    *,
    timestamp_utc: datetime = START_UTC,
    source: DataSource = DataSource.SYNTHETIC,
) -> AircraftState:
    return AircraftState(
        aircraft_id=aircraft_id,
        timestamp_utc=timestamp_utc,
        x_nm=0.0,
        y_nm=0.0,
        altitude_ft=8_000.0,
        ground_speed_kt=200.0,
        heading_deg=90.0,
        vertical_speed_fpm=0.0,
        source=source,
    )


def _scenario_aircraft(aircraft_id: str = "CIV-A01") -> ScenarioAircraft:
    return ScenarioAircraft(
        metadata=AircraftMetadata(
            aircraft_id=aircraft_id,
            performance_class="AIRLINER-POC-V1",
        ),
        initial_state=_state(aircraft_id),
    )


def _event(
    *,
    event_id: str = "EVT-001",
    target_aircraft_id: str = "CIV-A01",
    scheduled_time_utc: datetime = START_UTC,
) -> ScenarioEvent:
    return ScenarioEvent(
        event_id=event_id,
        event_type=ScenarioEventType.ENTRY_CONFORMANCE_DEVIATION,
        scheduled_time_utc=scheduled_time_utc,
        target_aircraft_id=target_aircraft_id,
        payload=EntryConformanceDeviationPayload(
            expected_entry_point="ENTRY-A",
            expected_altitude_ft=9_000.0,
            expected_heading_deg=210.0,
            actual_altitude_ft=7_400.0,
            lateral_deviation_nm=2.1,
            time_deviation_seconds=25.0,
        ),
    )


def test_scenario_definition_materializes_ordered_aircraft_views() -> None:
    first = _scenario_aircraft("CIV-A01")
    second = _scenario_aircraft("MIL-F01")
    source = [first, second]

    definition = ScenarioDefinition(
        scenario_id=" SCENARIO-001 ",
        start_time_utc=START_UTC,
        aircraft=source,
    )
    source.clear()

    assert definition.scenario_id == "SCENARIO-001"
    assert definition.aircraft == (first, second)
    assert definition.aircraft_ids == ("CIV-A01", "MIL-F01")
    assert definition.metadata == (first.metadata, second.metadata)
    assert definition.initial_states == (first.initial_state, second.initial_state)
    assert first.aircraft_id == "CIV-A01"


def test_scenario_aircraft_requires_matching_synthetic_state_and_profile() -> None:
    with pytest.raises(ValueError, match="IDs must match"):
        ScenarioAircraft(
            metadata=AircraftMetadata(
                aircraft_id="CIV-A01",
                performance_class="AIRLINER-POC-V1",
            ),
            initial_state=_state("CIV-A02"),
        )
    with pytest.raises(ValueError, match="SYNTHETIC"):
        ScenarioAircraft(
            metadata=AircraftMetadata(
                aircraft_id="CIV-A01",
                performance_class="AIRLINER-POC-V1",
            ),
            initial_state=_state(source=DataSource.OPENSKY),
        )
    with pytest.raises(ValueError, match="performance profile"):
        ScenarioAircraft(
            metadata=AircraftMetadata(aircraft_id="CIV-A01"),
            initial_state=_state(),
        )


def test_scenario_aircraft_rejects_wrong_component_types() -> None:
    with pytest.raises(TypeError, match="AircraftMetadata"):
        ScenarioAircraft(metadata="metadata", initial_state=_state())  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="AircraftState"):
        ScenarioAircraft(
            metadata=AircraftMetadata(
                aircraft_id="CIV-A01",
                performance_class="AIRLINER-POC-V1",
            ),
            initial_state="state",  # type: ignore[arg-type]
        )


def test_scenario_aircraft_materializes_and_validates_scheduled_states() -> None:
    scheduled = _state(timestamp_utc=START_UTC + timedelta(seconds=5))
    source = [scheduled]
    aircraft = ScenarioAircraft(
        metadata=AircraftMetadata(
            aircraft_id="CIV-A01",
            performance_class="AIRLINER-POC-V1",
        ),
        initial_state=_state(),
        scheduled_states=source,
    )
    source.clear()
    assert aircraft.scheduled_states == (scheduled,)

    base = {
        "metadata": AircraftMetadata(
            aircraft_id="CIV-A01",
            performance_class="AIRLINER-POC-V1",
        ),
        "initial_state": _state(),
    }
    with pytest.raises(TypeError, match="iterable"):
        ScenarioAircraft(**base, scheduled_states="state")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="iterable"):
        ScenarioAircraft(**base, scheduled_states=None)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="AircraftState"):
        ScenarioAircraft(**base, scheduled_states=("state",))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="aircraft ID"):
        ScenarioAircraft(
            **base,
            scheduled_states=(
                _state(
                    "MIL-F01",
                    timestamp_utc=START_UTC + timedelta(seconds=5),
                ),
            ),
        )
    with pytest.raises(ValueError, match="SYNTHETIC"):
        ScenarioAircraft(
            **base,
            scheduled_states=(
                _state(
                    timestamp_utc=START_UTC + timedelta(seconds=5),
                    source=DataSource.OPENSKY,
                ),
            ),
        )
    with pytest.raises(ValueError, match="strictly ordered"):
        ScenarioAircraft(**base, scheduled_states=(_state(),))


def test_scenario_definition_rejects_empty_invalid_duplicate_or_wrong_time() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        ScenarioDefinition(scenario_id="EMPTY", start_time_utc=START_UTC, aircraft=())
    with pytest.raises(TypeError, match="ScenarioAircraft"):
        ScenarioDefinition(
            scenario_id="INVALID",
            start_time_utc=START_UTC,
            aircraft=("CIV-A01",),  # type: ignore[arg-type]
        )

    aircraft = _scenario_aircraft()
    with pytest.raises(ValueError, match="must be unique"):
        ScenarioDefinition(
            scenario_id="DUPLICATE",
            start_time_utc=START_UTC,
            aircraft=(aircraft, aircraft),
        )

    later_aircraft = ScenarioAircraft(
        metadata=AircraftMetadata(
            aircraft_id="CIV-A01",
            performance_class="AIRLINER-POC-V1",
        ),
        initial_state=_state(timestamp_utc=START_UTC + timedelta(seconds=1)),
    )
    # 시작 이후에 등장하는 것은 허용된다. 소티는 75분에 걸쳐 15대가 들어오므로
    # 항공기마다 등장 시각이 다르다.
    ScenarioDefinition(
        scenario_id="LATER-ENTRY",
        start_time_utc=START_UTC,
        aircraft=(later_aircraft,),
    )

    # 시작 **이전**은 거부한다. 시계가 도달할 수 없는 시각이라 그 항공기는
    # 영원히 나타나지 않고, 시나리오에 적혀 있으므로 빠진 사실도 드러나지 않는다.
    early_aircraft = ScenarioAircraft(
        metadata=AircraftMetadata(
            aircraft_id="CIV-A01",
            performance_class="AIRLINER-POC-V1",
        ),
        initial_state=_state(timestamp_utc=START_UTC - timedelta(seconds=1)),
    )
    with pytest.raises(ValueError, match="precede the scenario start time"):
        ScenarioDefinition(
            scenario_id="EARLY-ENTRY",
            start_time_utc=START_UTC,
            aircraft=(early_aircraft,),
        )


def test_scenario_definition_materializes_and_validates_events() -> None:
    first = _event()
    second = _event(
        event_id="EVT-002",
        scheduled_time_utc=START_UTC + timedelta(seconds=1),
    )
    source = [first, second]

    definition = ScenarioDefinition(
        scenario_id="WITH-EVENTS",
        start_time_utc=START_UTC,
        aircraft=(_scenario_aircraft(),),
        events=source,
    )
    source.clear()
    assert definition.events == (first, second)

    with pytest.raises(TypeError, match="ScenarioEvent"):
        ScenarioDefinition(
            scenario_id="INVALID-EVENT",
            start_time_utc=START_UTC,
            aircraft=(_scenario_aircraft(),),
            events=("event",),  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError, match="IDs must be unique"):
        ScenarioDefinition(
            scenario_id="DUPLICATE-EVENT",
            start_time_utc=START_UTC,
            aircraft=(_scenario_aircraft(),),
            events=(first, first),
        )
    with pytest.raises(ValueError, match="reference scenario aircraft"):
        ScenarioDefinition(
            scenario_id="WRONG-TARGET",
            start_time_utc=START_UTC,
            aircraft=(_scenario_aircraft(),),
            events=(_event(target_aircraft_id="MIL-F01"),),
        )
    with pytest.raises(ValueError, match="precede"):
        ScenarioDefinition(
            scenario_id="EARLY-EVENT",
            start_time_utc=START_UTC,
            aircraft=(_scenario_aircraft(),),
            events=(_event(scheduled_time_utc=START_UTC - timedelta(seconds=1)),),
        )
    with pytest.raises(ValueError, match="ordered"):
        ScenarioDefinition(
            scenario_id="UNORDERED-EVENT",
            start_time_utc=START_UTC,
            aircraft=(_scenario_aircraft(),),
            events=(second, first),
        )
