from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone

import pytest

from sentry_atm.domain import EmergencyType
from sentry_atm.scenario import (
    EmergencyDeclaredPayload,
    EmergencyReasonCategory,
    EntryConformanceDeviationPayload,
    ScenarioEvent,
    ScenarioEventType,
)

START_UTC = datetime(2026, 9, 2, 3, 0, tzinfo=UTC)


def _entry_payload() -> EntryConformanceDeviationPayload:
    return EntryConformanceDeviationPayload(
        expected_entry_point=" ENTRY-A ",
        expected_altitude_ft=9_000,
        expected_heading_deg=210,
        actual_altitude_ft=7_400,
        lateral_deviation_nm=2.1,
        time_deviation_seconds=25,
    )


def test_scenario_event_normalizes_identifiers_enums_time_and_payload_values() -> None:
    event = ScenarioEvent(
        event_id=" EVT-001 ",
        event_type="ENTRY_CONFORMANCE_DEVIATION",
        scheduled_time_utc=datetime(
            2026,
            9,
            2,
            12,
            1,
            tzinfo=timezone(timedelta(hours=9)),
        ),
        target_aircraft_id=" MIL-F01 ",
        payload=_entry_payload(),
    )

    assert event.event_id == "EVT-001"
    assert event.event_type is ScenarioEventType.ENTRY_CONFORMANCE_DEVIATION
    assert event.scheduled_time_utc == START_UTC + timedelta(minutes=1)
    assert event.target_aircraft_id == "MIL-F01"
    assert event.payload.expected_entry_point == "ENTRY-A"
    assert event.payload.expected_altitude_ft == 9_000.0

    with pytest.raises(FrozenInstanceError):
        event.event_id = "CHANGED"  # type: ignore[misc]


def test_emergency_payload_normalizes_stable_enum_values() -> None:
    payload = EmergencyDeclaredPayload(
        emergency_type="PRIORITY_RETURN",  # type: ignore[arg-type]
        reason_category="AIRCRAFT_CONDITION",  # type: ignore[arg-type]
    )

    assert payload.emergency_type is EmergencyType.PRIORITY_RETURN
    assert payload.reason_category is EmergencyReasonCategory.AIRCRAFT_CONDITION


def test_scenario_event_requires_payload_matching_event_type() -> None:
    with pytest.raises(TypeError, match="EmergencyDeclaredPayload"):
        ScenarioEvent(
            event_id="EVT-001",
            event_type=ScenarioEventType.EMERGENCY_DECLARED,
            scheduled_time_utc=START_UTC,
            target_aircraft_id="MIL-T01",
            payload=_entry_payload(),
        )


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"expected_heading_deg": 360.0}, "expected_heading_deg"),
        ({"lateral_deviation_nm": -0.1}, "lateral_deviation_nm"),
        ({"time_deviation_seconds": float("inf")}, "time_deviation_seconds"),
    ],
)
def test_entry_payload_rejects_invalid_numeric_values(
    override: dict[str, float],
    message: str,
) -> None:
    values = {
        "expected_entry_point": "ENTRY-A",
        "expected_altitude_ft": 9_000.0,
        "expected_heading_deg": 210.0,
        "actual_altitude_ft": 7_400.0,
        "lateral_deviation_nm": 2.1,
        "time_deviation_seconds": 25.0,
    }
    values.update(override)

    with pytest.raises(ValueError, match=message):
        EntryConformanceDeviationPayload(**values)
