from collections.abc import Callable
from datetime import UTC, datetime

import pytest

from sentry_atm.domain import (
    AircraftCategory,
    AircraftMetadata,
    AircraftState,
    DataSource,
    EmergencyStatus,
    EmergencyType,
    FlightPhase,
)
from sentry_atm.geo import RKTU_ARP_LATITUDE_DEG, RKTU_ARP_LONGITUDE_DEG
from sentry_atm.infrastructure.persistence.mappers import (
    aircraft_from_row,
    aircraft_state_from_row,
    aircraft_state_to_row,
    aircraft_to_row,
)
from sentry_atm.infrastructure.persistence.models import AircraftRow, AircraftStateRow

TIMESTAMP_UTC = datetime(2026, 9, 1, 3, 0, tzinfo=UTC)


def _state() -> AircraftState:
    return AircraftState(
        aircraft_id="MIL-F01",
        timestamp_utc=TIMESTAMP_UTC,
        x_nm=0.0,
        y_nm=0.0,
        altitude_ft=7_400.0,
        ground_speed_kt=320.0,
        heading_deg=210.0,
        vertical_speed_fpm=-1_200.0,
        source=DataSource.SYNTHETIC,
        flight_phase=FlightPhase.DESCENT,
        emergency_status=EmergencyStatus.DECLARED,
        emergency_type=EmergencyType.PRIORITY_RETURN,
    )


def test_aircraft_mapper_round_trip_preserves_domain_fields() -> None:
    aircraft = AircraftMetadata(
        aircraft_id="CIV-A01",
        aircraft_type="a320",
        category=AircraftCategory.AIRLINER,
        callsign="CIV-A01",
        icao24="ABC123",
        performance_class="AIRLINER-POC-V1",
    )

    row = aircraft_to_row(aircraft)
    restored = aircraft_from_row(row)

    assert row.aircraft_type == "A320"
    assert restored.aircraft_id == aircraft.aircraft_id
    assert restored.category is AircraftCategory.AIRLINER
    assert restored.icao24 == "abc123"
    assert restored.performance_class == "AIRLINER-POC-V1"


def test_aircraft_state_mapper_adds_rktu_origin_coordinates() -> None:
    row = aircraft_state_to_row(_state())

    assert row.longitude_deg == pytest.approx(RKTU_ARP_LONGITUDE_DEG)
    assert row.latitude_deg == pytest.approx(RKTU_ARP_LATITUDE_DEG)


def test_aircraft_state_mapper_round_trip_uses_canonical_local_values() -> None:
    state = _state()

    restored = aircraft_state_from_row(aircraft_state_to_row(state))

    assert restored == state


@pytest.mark.parametrize(
    ("mapper", "value", "message"),
    [
        (aircraft_to_row, "aircraft", "AircraftMetadata"),
        (aircraft_from_row, "row", "AircraftRow"),
        (aircraft_state_to_row, "state", "AircraftState"),
        (aircraft_state_from_row, "row", "AircraftStateRow"),
    ],
)
def test_mappers_reject_wrong_types(
    mapper: Callable[[object], object],
    value: str,
    message: str,
) -> None:
    with pytest.raises(TypeError, match=message):
        mapper(value)


def test_state_row_mapping_does_not_depend_on_geodetic_columns_when_reading() -> None:
    row = AircraftStateRow(
        aircraft_id="CIV-A01",
        timestamp_utc=TIMESTAMP_UTC,
        x_nm=1.0,
        y_nm=2.0,
        latitude_deg=36.7,
        longitude_deg=127.5,
        altitude_ft=8_000.0,
        ground_speed_kt=250.0,
        heading_deg=90.0,
        vertical_speed_fpm=0.0,
        source="OPENSKY",
        flight_phase="LEVEL",
        emergency_status="NONE",
        emergency_type=None,
    )

    state = aircraft_state_from_row(row)

    assert state.x_nm == 1.0
    assert state.source is DataSource.OPENSKY


def test_aircraft_row_can_be_mapped_without_optional_fields() -> None:
    row = AircraftRow(
        aircraft_id="CIV-A01",
        aircraft_type="UNKNOWN",
        category="UNKNOWN",
    )

    assert aircraft_from_row(row).aircraft_type == "UNKNOWN"
