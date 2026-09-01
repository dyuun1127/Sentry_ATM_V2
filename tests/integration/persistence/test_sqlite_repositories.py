from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select, text

from sentry_atm.domain import AircraftMetadata, AircraftState, DataSource
from sentry_atm.geo import RKTU_ARP_LATITUDE_DEG, RKTU_ARP_LONGITUDE_DEG
from sentry_atm.infrastructure.persistence import (
    DatabaseSettings,
    SqlAlchemyAircraftRepository,
    SqlAlchemyAircraftStateRepository,
    create_database_engine,
    create_session_factory,
    initialize_database,
)
from sentry_atm.infrastructure.persistence.models import AircraftStateRow

pytestmark = pytest.mark.integration


def test_sqlite_repository_round_trip_uses_real_file_database(tmp_path: Path) -> None:
    database_path = tmp_path / "sentry-test.db"
    engine = create_database_engine(DatabaseSettings(database_path=database_path))
    initialize_database(engine)
    session_factory = create_session_factory(engine)
    timestamp = datetime(2026, 9, 1, 3, 0, tzinfo=UTC)
    aircraft = AircraftMetadata(aircraft_id="CIV-A01")
    states = tuple(
        AircraftState(
            aircraft_id=aircraft.aircraft_id,
            timestamp_utc=timestamp + timedelta(seconds=seconds),
            x_nm=float(seconds) / 10.0,
            y_nm=0.0,
            altitude_ft=8_000.0,
            ground_speed_kt=250.0,
            heading_deg=90.0,
            vertical_speed_fpm=0.0,
            source=DataSource.SYNTHETIC,
        )
        for seconds in (0, 10)
    )

    with session_factory.begin() as session:
        aircraft_repository = SqlAlchemyAircraftRepository(session)
        state_repository = SqlAlchemyAircraftStateRepository(session)
        aircraft_repository.upsert(aircraft)
        state_repository.append_many(states)

        assert aircraft_repository.get(aircraft.aircraft_id) == aircraft
        assert (
            state_repository.latest_at_or_before(
                aircraft.aircraft_id,
                timestamp + timedelta(seconds=20),
            )
            == states[-1]
        )
        assert (
            state_repository.list_between(
                aircraft.aircraft_id,
                timestamp,
                timestamp + timedelta(seconds=10),
            )
            == states
        )

        longitude, latitude = session.execute(
            select(
                AircraftStateRow.longitude_deg,
                AircraftStateRow.latitude_deg,
            )
            .where(AircraftStateRow.aircraft_id == aircraft.aircraft_id)
            .order_by(AircraftStateRow.timestamp_utc)
            .limit(1)
        ).one()
        assert longitude == pytest.approx(RKTU_ARP_LONGITUDE_DEG)
        assert latitude == pytest.approx(RKTU_ARP_LATITUDE_DEG)

    with engine.connect() as connection:
        assert connection.scalar(text("PRAGMA foreign_keys")) == 1
        assert connection.scalar(select(func.count()).select_from(AircraftStateRow)) == 2

    assert database_path.is_file()
    engine.dispose()


def test_sqlite_initialization_is_idempotent_and_seeds_unknown_type(tmp_path: Path) -> None:
    engine = create_database_engine(DatabaseSettings(database_path=tmp_path / "idempotent.db"))

    initialize_database(engine)
    initialize_database(engine)

    with engine.connect() as connection:
        unknown_count = connection.scalar(
            text("SELECT COUNT(*) FROM aircraft_type WHERE type_code = 'UNKNOWN'")
        )
    assert unknown_count == 1
    engine.dispose()
