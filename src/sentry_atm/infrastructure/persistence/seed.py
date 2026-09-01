"""Idempotent, non-sensitive reference data for local PoC databases."""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from sentry_atm.domain import (
    AircraftCategory,
    AircraftPerformanceProfile,
    AircraftType,
    PerformanceDataSource,
)
from sentry_atm.infrastructure.persistence.repositories import (
    SqlAlchemyAircraftPerformanceProfileRepository,
    SqlAlchemyAircraftTypeRepository,
)

POC_SOURCE_REFERENCE = "ASM-013:SENTRY_POC_CATEGORY_ENVELOPE_V1"

POC_AIRCRAFT_TYPES = (
    AircraftType(
        type_code="SYN-AIRLINER",
        category=AircraftCategory.AIRLINER,
        manufacturer="SENTRY",
        model="Synthetic Airliner",
    ),
    AircraftType(
        type_code="SYN-FAST-JET",
        category=AircraftCategory.FAST_JET,
        manufacturer="SENTRY",
        model="Synthetic Fast Jet",
    ),
    AircraftType(
        type_code="SYN-TRANSPORT",
        category=AircraftCategory.TRANSPORT,
        manufacturer="SENTRY",
        model="Synthetic Transport",
    ),
)

POC_PERFORMANCE_PROFILES = (
    AircraftPerformanceProfile(
        profile_id="AIRLINER-POC-V1",
        category=AircraftCategory.AIRLINER,
        source=PerformanceDataSource.SIMULATION_ASSUMPTION,
        source_reference=POC_SOURCE_REFERENCE,
        min_speed_kt=130.0,
        max_speed_kt=350.0,
        max_climb_rate_fpm=2_500.0,
        max_descent_rate_fpm=3_000.0,
        max_turn_rate_deg_per_second=3.0,
        ceiling_ft=39_000.0,
        aircraft_type_code="SYN-AIRLINER",
    ),
    AircraftPerformanceProfile(
        profile_id="FAST-JET-POC-V1",
        category=AircraftCategory.FAST_JET,
        source=PerformanceDataSource.SIMULATION_ASSUMPTION,
        source_reference=POC_SOURCE_REFERENCE,
        min_speed_kt=160.0,
        max_speed_kt=480.0,
        max_climb_rate_fpm=6_000.0,
        max_descent_rate_fpm=6_000.0,
        max_turn_rate_deg_per_second=6.0,
        ceiling_ft=50_000.0,
        aircraft_type_code="SYN-FAST-JET",
    ),
    AircraftPerformanceProfile(
        profile_id="TRANSPORT-POC-V1",
        category=AircraftCategory.TRANSPORT,
        source=PerformanceDataSource.SIMULATION_ASSUMPTION,
        source_reference=POC_SOURCE_REFERENCE,
        min_speed_kt=110.0,
        max_speed_kt=320.0,
        max_climb_rate_fpm=2_000.0,
        max_descent_rate_fpm=2_500.0,
        max_turn_rate_deg_per_second=3.0,
        ceiling_ft=35_000.0,
        aircraft_type_code="SYN-TRANSPORT",
    ),
)


@dataclass(frozen=True, slots=True)
class ReferenceSeedResult:
    aircraft_types_added: int
    performance_profiles_added: int


def seed_poc_reference_data(session: Session) -> ReferenceSeedResult:
    """Insert missing PoC reference records without replacing existing rows."""

    type_repository = SqlAlchemyAircraftTypeRepository(session)
    profile_repository = SqlAlchemyAircraftPerformanceProfileRepository(session)
    types_added = 0
    profiles_added = 0

    for aircraft_type in POC_AIRCRAFT_TYPES:
        if type_repository.get(aircraft_type.type_code) is None:
            type_repository.upsert(aircraft_type)
            types_added += 1

    for profile in POC_PERFORMANCE_PROFILES:
        if profile_repository.get(profile.profile_id) is None:
            profile_repository.upsert(profile)
            profiles_added += 1

    return ReferenceSeedResult(
        aircraft_types_added=types_added,
        performance_profiles_added=profiles_added,
    )
