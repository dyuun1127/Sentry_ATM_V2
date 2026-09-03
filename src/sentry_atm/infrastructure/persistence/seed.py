"""Idempotent, non-sensitive reference data for local PoC databases."""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from sentry_atm.infrastructure.persistence.repositories import (
    SqlAlchemyAircraftPerformanceProfileRepository,
    SqlAlchemyAircraftTypeRepository,
)
from sentry_atm.reference_data import (
    POC_AIRCRAFT_TYPES,
    POC_PERFORMANCE_PROFILES,
)
from sentry_atm.reference_data import POC_SOURCE_REFERENCE as POC_SOURCE_REFERENCE


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
