from datetime import UTC, datetime, timedelta
from typing import cast
from unittest.mock import MagicMock, create_autospec

import pytest
from sqlalchemy.orm import Session

from sentry_atm.domain import (
    AircraftCategory,
    AircraftMetadata,
    AircraftPerformanceProfile,
    AircraftState,
    AircraftType,
    DataSource,
    PerformanceDataSource,
)
from sentry_atm.infrastructure.persistence.models import (
    AircraftPerformanceProfileRow,
    AircraftRow,
    AircraftStateRow,
    AircraftTypeRow,
)
from sentry_atm.infrastructure.persistence.repositories import (
    SqlAlchemyAircraftPerformanceProfileRepository,
    SqlAlchemyAircraftRepository,
    SqlAlchemyAircraftStateRepository,
    SqlAlchemyAircraftTypeRepository,
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


def _aircraft_type(**overrides: object) -> AircraftType:
    values: dict[str, object] = {
        "type_code": "A320",
        "category": AircraftCategory.AIRLINER,
        "manufacturer": "Airbus",
        "model": "A320",
    }
    values.update(overrides)
    return AircraftType(**values)  # type: ignore[arg-type]


def _aircraft_type_row(**overrides: object) -> AircraftTypeRow:
    values: dict[str, object] = {
        "type_code": "A320",
        "category": "AIRLINER",
        "manufacturer": "Airbus",
        "model": "A320",
    }
    values.update(overrides)
    return AircraftTypeRow(**values)  # type: ignore[arg-type]


def _performance_profile(**overrides: object) -> AircraftPerformanceProfile:
    values: dict[str, object] = {
        "profile_id": "A320-POC-V1",
        "category": AircraftCategory.AIRLINER,
        "source": PerformanceDataSource.SIMULATION_ASSUMPTION,
        "source_reference": "docs/assumptions.md#airliner-profile",
        "min_speed_kt": 130.0,
        "max_speed_kt": 350.0,
        "max_climb_rate_fpm": 2_500.0,
        "max_descent_rate_fpm": 3_000.0,
        "max_turn_rate_deg_per_second": 3.0,
        "ceiling_ft": 39_000.0,
        "aircraft_type_code": "A320",
    }
    values.update(overrides)
    return AircraftPerformanceProfile(**values)  # type: ignore[arg-type]


def _performance_profile_row(**overrides: object) -> AircraftPerformanceProfileRow:
    values: dict[str, object] = {
        "profile_id": "A320-POC-V1",
        "category": "AIRLINER",
        "source": "SIMULATION_ASSUMPTION",
        "source_reference": "docs/assumptions.md#airliner-profile",
        "min_speed_kt": 130.0,
        "max_speed_kt": 350.0,
        "max_climb_rate_fpm": 2_500.0,
        "max_descent_rate_fpm": 3_000.0,
        "max_turn_rate_deg_per_second": 3.0,
        "ceiling_ft": 39_000.0,
        "aircraft_type_code": "A320",
    }
    values.update(overrides)
    return AircraftPerformanceProfileRow(**values)  # type: ignore[arg-type]


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


def test_aircraft_type_repository_get_list_and_missing_result() -> None:
    session, session_mock = _session()
    first = _aircraft_type_row()
    second = _aircraft_type_row(type_code="B738", manufacturer="Boeing", model="737-800")
    session_mock.get.side_effect = [first, None]
    session_mock.scalars.return_value.all.return_value = [first, second]
    repository = SqlAlchemyAircraftTypeRepository(session)

    assert repository.get("a320") == _aircraft_type()
    assert repository.get("missing") is None
    assert tuple(item.type_code for item in repository.list_all()) == ("A320", "B738")
    assert session_mock.get.call_args_list[0].args == (AircraftTypeRow, "A320")


def test_aircraft_type_repository_inserts_and_updates_rows() -> None:
    session, session_mock = _session()
    existing = _aircraft_type_row(manufacturer=None, model=None)
    session_mock.get.side_effect = [None, existing]
    repository = SqlAlchemyAircraftTypeRepository(session)

    repository.upsert(_aircraft_type())
    inserted = session_mock.add.call_args.args[0]
    assert isinstance(inserted, AircraftTypeRow)
    assert inserted.type_code == "A320"

    repository.upsert(_aircraft_type(manufacturer="Updated", model="Updated model"))
    assert existing.manufacturer == "Updated"
    assert existing.model == "Updated model"
    assert session_mock.flush.call_count == 2


def test_performance_profile_repository_get_list_and_missing_result() -> None:
    session, session_mock = _session()
    first = _performance_profile_row()
    second = _performance_profile_row(profile_id="TRANSPORT-POC-V1", aircraft_type_code=None)
    session_mock.get.side_effect = [first, None]
    session_mock.scalars.return_value.all.return_value = [first, second]
    repository = SqlAlchemyAircraftPerformanceProfileRepository(session)

    assert repository.get("A320-POC-V1") == _performance_profile()
    assert repository.get("missing") is None
    assert tuple(item.profile_id for item in repository.list_all()) == (
        "A320-POC-V1",
        "TRANSPORT-POC-V1",
    )


def test_performance_profile_repository_inserts_and_updates_every_field() -> None:
    session, session_mock = _session()
    existing = _performance_profile_row()
    session_mock.get.side_effect = [None, existing]
    repository = SqlAlchemyAircraftPerformanceProfileRepository(session)

    repository.upsert(_performance_profile())
    inserted = session_mock.add.call_args.args[0]
    assert isinstance(inserted, AircraftPerformanceProfileRow)
    assert inserted.profile_id == "A320-POC-V1"

    updated = _performance_profile(
        source=PerformanceDataSource.PUBLIC_REFERENCE,
        source_reference="public-test-reference",
        min_speed_kt=140.0,
        max_speed_kt=360.0,
        max_climb_rate_fpm=2_600.0,
        max_descent_rate_fpm=3_100.0,
        max_turn_rate_deg_per_second=2.5,
        ceiling_ft=40_000.0,
        aircraft_type_code=None,
    )
    repository.upsert(updated)

    assert existing.source == "PUBLIC_REFERENCE"
    assert existing.source_reference == "public-test-reference"
    assert existing.min_speed_kt == 140.0
    assert existing.max_speed_kt == 360.0
    assert existing.max_climb_rate_fpm == 2_600.0
    assert existing.max_descent_rate_fpm == 3_100.0
    assert existing.max_turn_rate_deg_per_second == 2.5
    assert existing.ceiling_ft == 40_000.0
    assert existing.aircraft_type_code is None
    assert session_mock.flush.call_count == 2


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
        SqlAlchemyAircraftTypeRepository(cast(Session, "not-session"))
    with pytest.raises(TypeError, match="SQLAlchemy Session"):
        SqlAlchemyAircraftPerformanceProfileRepository(cast(Session, "not-session"))
    with pytest.raises(TypeError, match="SQLAlchemy Session"):
        SqlAlchemyAircraftRepository(cast(Session, "not-session"))
    with pytest.raises(TypeError, match="SQLAlchemy Session"):
        SqlAlchemyAircraftStateRepository(cast(Session, "not-session"))
