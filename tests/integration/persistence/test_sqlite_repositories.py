from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select, text

from sentry_atm.domain import (
    AircraftCategory,
    AircraftMetadata,
    AircraftPerformanceProfile,
    AircraftState,
    AircraftType,
    DataSource,
    PerformanceDataSource,
)
from sentry_atm.geo import RKTU_ARP_LATITUDE_DEG, RKTU_ARP_LONGITUDE_DEG
from sentry_atm.infrastructure.persistence import (
    DatabaseSettings,
    SqlAlchemyAircraftPerformanceProfileRepository,
    SqlAlchemyAircraftRepository,
    SqlAlchemyAircraftStateRepository,
    SqlAlchemyAircraftTypeRepository,
    create_database_engine,
    create_session_factory,
    initialize_database,
    seed_poc_reference_data,
)
from sentry_atm.infrastructure.persistence.models import AircraftStateRow

pytestmark = pytest.mark.integration


def test_sqlite_repository_round_trip_uses_real_file_database(tmp_path: Path) -> None:
    database_path = tmp_path / "sentry-test.db"
    engine = create_database_engine(DatabaseSettings(database_path=database_path))
    initialize_database(engine)
    session_factory = create_session_factory(engine)
    timestamp = datetime(2026, 9, 1, 3, 0, tzinfo=UTC)
    aircraft_type = AircraftType(
        type_code="A320",
        category=AircraftCategory.AIRLINER,
        manufacturer="Airbus",
        model="A320",
    )
    profile = AircraftPerformanceProfile(
        profile_id="A320-POC-V1",
        category=AircraftCategory.AIRLINER,
        source=PerformanceDataSource.SIMULATION_ASSUMPTION,
        source_reference="docs/assumptions.md#airliner-profile",
        min_speed_kt=130.0,
        max_speed_kt=350.0,
        max_climb_rate_fpm=2_500.0,
        max_descent_rate_fpm=3_000.0,
        max_turn_rate_deg_per_second=3.0,
        ceiling_ft=39_000.0,
        aircraft_type_code="A320",
    )
    aircraft = AircraftMetadata(
        aircraft_id="CIV-A01",
        aircraft_type="A320",
        category=AircraftCategory.AIRLINER,
        performance_class="A320-POC-V1",
    )
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
        aircraft_type_repository = SqlAlchemyAircraftTypeRepository(session)
        profile_repository = SqlAlchemyAircraftPerformanceProfileRepository(session)
        aircraft_repository = SqlAlchemyAircraftRepository(session)
        state_repository = SqlAlchemyAircraftStateRepository(session)
        aircraft_type_repository.upsert(aircraft_type)
        profile_repository.upsert(profile)
        aircraft_repository.upsert(aircraft)
        state_repository.append_many(states)

        assert aircraft_type_repository.get("a320") == aircraft_type
        assert aircraft_type_repository.list_all() == (
            aircraft_type,
            AircraftType(type_code="UNKNOWN", category=AircraftCategory.UNKNOWN),
        )
        assert profile_repository.get(profile.profile_id) == profile
        assert profile_repository.list_all() == (profile,)
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


def test_reference_seed_is_idempotent_and_preserves_existing_profile(tmp_path: Path) -> None:
    engine = create_database_engine(DatabaseSettings(database_path=tmp_path / "seed.db"))
    initialize_database(engine)
    session_factory = create_session_factory(engine)

    with session_factory.begin() as session:
        first_result = seed_poc_reference_data(session)
        profile_repository = SqlAlchemyAircraftPerformanceProfileRepository(session)
        existing = profile_repository.get("AIRLINER-POC-V1")
        assert existing is not None
        profile_repository.upsert(
            AircraftPerformanceProfile(
                profile_id=existing.profile_id,
                category=existing.category,
                source=existing.source,
                source_reference="locally-reviewed-profile",
                min_speed_kt=existing.min_speed_kt,
                max_speed_kt=existing.max_speed_kt,
                max_climb_rate_fpm=existing.max_climb_rate_fpm,
                max_descent_rate_fpm=existing.max_descent_rate_fpm,
                max_turn_rate_deg_per_second=existing.max_turn_rate_deg_per_second,
                ceiling_ft=existing.ceiling_ft,
                aircraft_type_code=existing.aircraft_type_code,
            )
        )

    with session_factory.begin() as session:
        second_result = seed_poc_reference_data(session)
        preserved = SqlAlchemyAircraftPerformanceProfileRepository(session).get("AIRLINER-POC-V1")

    assert first_result.aircraft_types_added == 3
    assert first_result.performance_profiles_added == 3
    assert second_result.aircraft_types_added == 0
    assert second_result.performance_profiles_added == 0
    assert preserved is not None
    assert preserved.source_reference == "locally-reviewed-profile"
    engine.dispose()
