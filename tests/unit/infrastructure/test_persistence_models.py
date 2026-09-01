from datetime import UTC, datetime

import pytest
from sqlalchemy import CheckConstraint, Index
from sqlalchemy.dialects.sqlite import dialect as sqlite_dialect
from sqlalchemy.orm import Session

from sentry_atm.infrastructure.persistence.models import (
    AircraftStateRow,
    Base,
    UTCDateTime,
)
from sentry_atm.infrastructure.persistence.repositories import (
    SqlAlchemyAircraftRepository,
    SqlAlchemyAircraftStateRepository,
)
from sentry_atm.ports import AircraftRepository, AircraftStateRepository


def test_initial_metadata_contains_reference_and_traffic_tables() -> None:
    assert set(Base.metadata.tables) == {
        "aircraft_type",
        "aircraft_performance_profile",
        "aircraft",
        "aircraft_state",
    }


def test_aircraft_state_has_geodetic_columns_and_composite_index() -> None:
    columns = AircraftStateRow.__table__.c
    indexes = {index.name: index for index in AircraftStateRow.__table__.indexes}

    assert columns.latitude_deg.nullable is False
    assert columns.longitude_deg.nullable is False
    assert isinstance(indexes["ix_aircraft_state_aircraft_time"], Index)


def test_database_checks_invalid_state_values_and_coordinates() -> None:
    constraint_names = {
        constraint.name
        for constraint in AircraftStateRow.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    }

    assert "ck_aircraft_state_heading_range" in constraint_names
    assert "ck_aircraft_state_emergency_consistency" in constraint_names
    assert "ck_aircraft_state_latitude_range" in constraint_names
    assert "ck_aircraft_state_longitude_range" in constraint_names


def test_utc_datetime_serializes_fixed_width_utc_and_restores_awareness() -> None:
    timestamp_type = UTCDateTime()
    timestamp = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
    dialect = sqlite_dialect()

    stored = timestamp_type.process_bind_param(timestamp, dialect)
    restored = timestamp_type.process_result_value(stored, dialect)

    assert stored == "2026-09-01T12:00:00.000000Z"
    assert restored == timestamp
    assert restored is not None and restored.tzinfo is UTC


def test_utc_datetime_accepts_null_but_rejects_naive_datetime() -> None:
    timestamp_type = UTCDateTime()
    dialect = sqlite_dialect()

    assert timestamp_type.process_bind_param(None, dialect) is None
    assert timestamp_type.process_result_value(None, dialect) is None
    with pytest.raises(ValueError, match="timezone-aware"):
        timestamp_type.process_bind_param(datetime(2026, 9, 1, 12, 0), dialect)


def test_sqlalchemy_repositories_implement_domain_ports_structurally() -> None:
    session = Session()

    aircraft_repository = SqlAlchemyAircraftRepository(session)
    state_repository = SqlAlchemyAircraftStateRepository(session)

    assert isinstance(aircraft_repository, AircraftRepository)
    assert isinstance(state_repository, AircraftStateRepository)
    session.close()
