from datetime import datetime

import pytest

from sentry_atm.domain.aircraft import AircraftMetadata, AircraftState
from sentry_atm.domain.enums import (
    AircraftCategory,
    DataSource,
    EmergencyStatus,
    EmergencyType,
    FlightPhase,
)
from sentry_atm.domain.time_policy import KST, UTC


def _valid_state(**overrides: object) -> AircraftState:
    values: dict[str, object] = {
        "aircraft_id": "MIL-F01",
        "timestamp_utc": datetime(2026, 9, 1, 12, 0, tzinfo=KST),
        "x_nm": -8.0,
        "y_nm": 2.0,
        "altitude_ft": 7_400.0,
        "ground_speed_kt": 320.0,
        "heading_deg": 210.0,
        "vertical_speed_fpm": -1_200.0,
        "source": DataSource.SYNTHETIC,
        "flight_phase": FlightPhase.DESCENT,
    }
    values.update(overrides)
    return AircraftState(**values)  # type: ignore[arg-type]


def test_aircraft_state_normalizes_time_and_numeric_values() -> None:
    state = _valid_state(x_nm=-8, ground_speed_kt=320)

    assert state.timestamp_utc == datetime(2026, 9, 1, 3, 0, tzinfo=UTC)
    assert state.timestamp_kst == datetime(2026, 9, 1, 12, 0, tzinfo=KST)
    assert state.x_nm == -8.0
    assert state.ground_speed_kt == 320.0


def test_aircraft_metadata_normalizes_icao24() -> None:
    metadata = AircraftMetadata(
        aircraft_id="CIV-A01",
        aircraft_type="A320",
        category=AircraftCategory.AIRLINER,
        callsign="CIV-A01",
        icao24="ABC123",
        performance_class="AIRLINER",
    )

    assert metadata.icao24 == "abc123"


@pytest.mark.parametrize("icao24", ["abc12", "nothex"])
def test_aircraft_metadata_rejects_invalid_icao24(icao24: str) -> None:
    with pytest.raises(ValueError, match="6 hexadecimal"):
        AircraftMetadata(aircraft_id="CIV-A01", icao24=icao24)


def test_aircraft_metadata_rejects_blank_optional_text() -> None:
    with pytest.raises(ValueError, match="callsign must not be blank"):
        AircraftMetadata(aircraft_id="CIV-A01", callsign="  ")


@pytest.mark.parametrize(
    ("field_name", "value", "message"),
    [
        ("aircraft_id", "  ", "must not be blank"),
        ("ground_speed_kt", -1.0, "must be non-negative"),
        ("heading_deg", 360.0, r"must be in \[0, 360\)"),
    ],
)
def test_aircraft_state_rejects_invalid_values(
    field_name: str,
    value: object,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        _valid_state(**{field_name: value})


def test_declared_emergency_requires_a_type() -> None:
    with pytest.raises(ValueError, match="emergency_type is required"):
        _valid_state(emergency_status=EmergencyStatus.DECLARED)


def test_non_emergency_rejects_an_emergency_type() -> None:
    with pytest.raises(ValueError, match="must be None"):
        _valid_state(emergency_type=EmergencyType.PRIORITY_RETURN)


def test_declared_emergency_accepts_a_type() -> None:
    state = _valid_state(
        emergency_status=EmergencyStatus.DECLARED,
        emergency_type=EmergencyType.PRIORITY_RETURN,
    )

    assert state.emergency_type is EmergencyType.PRIORITY_RETURN
