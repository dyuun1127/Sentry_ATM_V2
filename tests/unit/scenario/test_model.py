from datetime import UTC, datetime, timedelta

import pytest

from sentry_atm.domain import AircraftMetadata, AircraftState, DataSource
from sentry_atm.scenario import ScenarioAircraft, ScenarioDefinition

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
    with pytest.raises(ValueError, match="scenario start time"):
        ScenarioDefinition(
            scenario_id="WRONG-TIME",
            start_time_utc=START_UTC,
            aircraft=(later_aircraft,),
        )
