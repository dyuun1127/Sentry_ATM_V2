from datetime import UTC, datetime

import pytest
from sqlalchemy import CheckConstraint, Index
from sqlalchemy.dialects.sqlite import dialect as sqlite_dialect
from sqlalchemy.orm import Session

from sentry_atm.infrastructure.persistence.models import (
    AircraftStateRow,
    Base,
    TrajectoryPointRow,
    TrajectoryRow,
    UTCDateTime,
)
from sentry_atm.infrastructure.persistence.repositories import (
    SqlAlchemyAircraftRepository,
    SqlAlchemyAircraftStateRepository,
    SqlAlchemyPredictionRunRepository,
)
from sentry_atm.ports import (
    AircraftRepository,
    AircraftStateRepository,
    PredictionRunRepository,
)


def test_initial_metadata_contains_reference_and_traffic_tables() -> None:
    assert set(Base.metadata.tables) == {
        "aircraft_type",
        "aircraft_performance_profile",
        "aircraft",
        "aircraft_state",
        "prediction_run",
        "trajectory",
        "trajectory_point",
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


def test_prediction_tables_preserve_aggregate_and_point_order() -> None:
    trajectory_indexes = {index.name for index in TrajectoryRow.__table__.indexes}
    point_indexes = {index.name for index in TrajectoryPointRow.__table__.indexes}

    assert "ix_trajectory_prediction_run_sequence" in trajectory_indexes
    assert "ix_trajectory_point_trajectory_sequence" in point_indexes
    assert TrajectoryRow.__table__.c.prediction_run_id.foreign_keys
    assert TrajectoryPointRow.__table__.c.trajectory_id.foreign_keys


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
    prediction_repository = SqlAlchemyPredictionRunRepository(session)

    assert isinstance(aircraft_repository, AircraftRepository)
    assert isinstance(state_repository, AircraftStateRepository)
    assert isinstance(prediction_repository, PredictionRunRepository)
    session.close()
