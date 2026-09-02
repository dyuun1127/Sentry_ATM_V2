from datetime import datetime, timedelta

import pytest

from sentry_atm.domain import Flight, FlightStatus
from sentry_atm.domain.time_policy import KST, UTC

START_KST = datetime(2026, 9, 1, 12, 0, tzinfo=KST)


def test_flight_normalizes_time_status_and_optional_locations() -> None:
    flight = Flight(
        flight_id=" FLT-001 ",
        aircraft_id=" CIV-A01 ",
        status="PLANNED",
        planned_start_time_utc=START_KST,
        planned_end_time_utc=START_KST + timedelta(minutes=30),
        departure=" RKTU ",
        destination=" RKSI ",
    )

    assert flight.flight_id == "FLT-001"
    assert flight.aircraft_id == "CIV-A01"
    assert flight.status is FlightStatus.PLANNED
    assert flight.planned_start_time_utc == datetime(2026, 9, 1, 3, 0, tzinfo=UTC)
    assert flight.departure == "RKTU"
    assert flight.destination == "RKSI"


def test_flight_allows_unknown_end_time_and_locations() -> None:
    flight = Flight(
        flight_id="FLT-001",
        aircraft_id="CIV-A01",
        status=FlightStatus.ACTIVE,
        planned_start_time_utc=START_KST,
    )

    assert flight.planned_end_time_utc is None
    assert flight.departure is None
    assert flight.destination is None


def test_flight_rejects_end_not_later_than_start() -> None:
    with pytest.raises(ValueError, match="must be later"):
        Flight(
            flight_id="FLT-001",
            aircraft_id="CIV-A01",
            status=FlightStatus.PLANNED,
            planned_start_time_utc=START_KST,
            planned_end_time_utc=START_KST,
        )


def test_flight_rejects_naive_start_time() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        Flight(
            flight_id="FLT-001",
            aircraft_id="CIV-A01",
            status=FlightStatus.PLANNED,
            planned_start_time_utc=datetime(2026, 9, 1, 3, 0),
        )
