from datetime import UTC, datetime, timedelta
from typing import cast
from unittest.mock import MagicMock, create_autospec

import pytest
from sqlalchemy.orm import Session

from sentry_atm.domain import AircraftMetadata, AircraftState, DataSource
from sentry_atm.infrastructure.persistence.models import AircraftRow, AircraftStateRow
from sentry_atm.infrastructure.persistence.repositories import (
    SqlAlchemyAircraftRepository,
    SqlAlchemyAircraftStateRepository,
)

TIMESTAMP_UTC = datetime(2026, 9, 1, 3, 0, tzinfo=UTC)


def _session() -> tuple[Session, MagicMock]:
    session_mock = create_autospec(Session, instance=True)
    return cast(Session, session_mock), cast(MagicMock, session_mock)


def _aircraft_row(**overrides: object) -> AircraftRow:
    values: dict[str, object] = {
        "aircraft_id": "CIV-A01",
        "aircraft_type": "UNKNOWN",
        "category": "UNKNOWN",
        "callsign": None,
        "icao24": None,
        "performance_profile_id": None,
    }
    values.update(overrides)
    return AircraftRow(**values)  # type: ignore[arg-type]


def _state(seconds: int = 0) -> AircraftState:
    return AircraftState(
        aircraft_id="CIV-A01",
        timestamp_utc=TIMESTAMP_UTC + timedelta(seconds=seconds),
        x_nm=float(seconds),
        y_nm=0.0,
        altitude_ft=8_000.0,
        ground_speed_kt=250.0,
        heading_deg=90.0,
        vertical_speed_fpm=0.0,
        source=DataSource.SYNTHETIC,
    )


def _state_row(seconds: int = 0) -> AircraftStateRow:
    state = _state(seconds)
    return AircraftStateRow(
        aircraft_id=state.aircraft_id,
        timestamp_utc=state.timestamp_utc,
        x_nm=state.x_nm,
        y_nm=state.y_nm,
        latitude_deg=36.7,
        longitude_deg=127.5,
        altitude_ft=state.altitude_ft,
        ground_speed_kt=state.ground_speed_kt,
        heading_deg=state.heading_deg,
        vertical_speed_fpm=state.vertical_speed_fpm,
        source=state.source.value,
        flight_phase=state.flight_phase.value,
        emergency_status=state.emergency_status.value,
        emergency_type=None,
    )


def test_aircraft_repository_get_and_list_map_rows_to_domain() -> None:
    session, session_mock = _session()
    first = _aircraft_row()
    second = _aircraft_row(aircraft_id="MIL-F01")
    session_mock.get.return_value = first
    session_mock.scalars.return_value.all.return_value = [first, second]
    repository = SqlAlchemyAircraftRepository(session)

    assert repository.get("CIV-A01") == AircraftMetadata(aircraft_id="CIV-A01")
    assert tuple(item.aircraft_id for item in repository.list_all()) == (
        "CIV-A01",
        "MIL-F01",
    )


def test_aircraft_repository_returns_none_when_missing() -> None:
    session, session_mock = _session()
    session_mock.get.return_value = None

    assert SqlAlchemyAircraftRepository(session).get("CIV-A01") is None


def test_aircraft_repository_inserts_and_flushes_new_row() -> None:
    session, session_mock = _session()
    session_mock.get.return_value = None
    aircraft = AircraftMetadata(aircraft_id="CIV-A01")

    SqlAlchemyAircraftRepository(session).upsert(aircraft)

    inserted = session_mock.add.call_args.args[0]
    assert isinstance(inserted, AircraftRow)
    assert inserted.aircraft_id == "CIV-A01"
    session_mock.flush.assert_called_once_with()


def test_aircraft_repository_updates_existing_row_without_inserting() -> None:
    session, session_mock = _session()
    existing = _aircraft_row()
    session_mock.get.return_value = existing
    aircraft = AircraftMetadata(
        aircraft_id="CIV-A01",
        aircraft_type="A320",
        callsign="CIV-A01",
        icao24="abc123",
    )

    SqlAlchemyAircraftRepository(session).upsert(aircraft)

    assert existing.aircraft_type == "A320"
    assert existing.callsign == "CIV-A01"
    assert existing.icao24 == "abc123"
    session_mock.add.assert_not_called()
    session_mock.flush.assert_called_once_with()


def test_aircraft_state_repository_appends_one_or_many_rows() -> None:
    session, session_mock = _session()
    repository = SqlAlchemyAircraftStateRepository(session)

    repository.append(_state())
    repository.append_many(state for state in (_state(10), _state(20)))

    assert isinstance(session_mock.add.call_args.args[0], AircraftStateRow)
    added_rows = session_mock.add_all.call_args.args[0]
    assert tuple(row.timestamp_utc for row in added_rows) == (
        TIMESTAMP_UTC + timedelta(seconds=10),
        TIMESTAMP_UTC + timedelta(seconds=20),
    )
    assert session_mock.flush.call_count == 2


def test_aircraft_state_repository_queries_latest_and_inclusive_range() -> None:
    session, session_mock = _session()
    latest_result = MagicMock()
    latest_result.first.return_value = _state_row(20)
    range_result = MagicMock()
    range_result.all.return_value = [_state_row(0), _state_row(20)]
    session_mock.scalars.side_effect = [latest_result, range_result]
    repository = SqlAlchemyAircraftStateRepository(session)

    latest = repository.latest_at_or_before(
        "CIV-A01",
        TIMESTAMP_UTC + timedelta(seconds=30),
    )
    states = repository.list_between(
        "CIV-A01",
        TIMESTAMP_UTC,
        TIMESTAMP_UTC + timedelta(seconds=20),
    )

    assert latest == _state(20)
    assert states == (_state(0), _state(20))


def test_aircraft_state_repository_returns_none_when_no_prior_state() -> None:
    session, session_mock = _session()
    session_mock.scalars.return_value.first.return_value = None

    result = SqlAlchemyAircraftStateRepository(session).latest_at_or_before(
        "CIV-A01",
        TIMESTAMP_UTC,
    )

    assert result is None


def test_aircraft_state_repository_rejects_reversed_range() -> None:
    session, session_mock = _session()

    with pytest.raises(ValueError, match="must not be earlier"):
        SqlAlchemyAircraftStateRepository(session).list_between(
            "CIV-A01",
            TIMESTAMP_UTC + timedelta(seconds=1),
            TIMESTAMP_UTC,
        )

    session_mock.scalars.assert_not_called()


def test_repositories_require_real_sqlalchemy_session() -> None:
    with pytest.raises(TypeError, match="SQLAlchemy Session"):
        SqlAlchemyAircraftRepository(cast(Session, "not-session"))
    with pytest.raises(TypeError, match="SQLAlchemy Session"):
        SqlAlchemyAircraftStateRepository(cast(Session, "not-session"))
