from typing import cast

import pytest
from sqlalchemy.orm import Session

from sentry_atm.domain import AircraftCategory, PerformanceDataSource
from sentry_atm.infrastructure.persistence.seed import (
    POC_AIRCRAFT_TYPES,
    POC_PERFORMANCE_PROFILES,
    POC_SOURCE_REFERENCE,
    seed_poc_reference_data,
)


def test_poc_reference_data_covers_each_supported_category() -> None:
    supported_categories = {
        AircraftCategory.AIRLINER,
        AircraftCategory.FAST_JET,
        AircraftCategory.TRANSPORT,
    }

    assert {item.category for item in POC_AIRCRAFT_TYPES} == supported_categories
    assert {item.category for item in POC_PERFORMANCE_PROFILES} == supported_categories
    assert {item.aircraft_type_code for item in POC_PERFORMANCE_PROFILES} == {
        item.type_code for item in POC_AIRCRAFT_TYPES
    }


def test_poc_profiles_are_explicit_simulation_assumptions() -> None:
    assert all(
        profile.source is PerformanceDataSource.SIMULATION_ASSUMPTION
        for profile in POC_PERFORMANCE_PROFILES
    )
    assert all(
        profile.source_reference == POC_SOURCE_REFERENCE for profile in POC_PERFORMANCE_PROFILES
    )


def test_seed_requires_sqlalchemy_session() -> None:
    with pytest.raises(TypeError, match="SQLAlchemy Session"):
        seed_poc_reference_data(cast(Session, "not-session"))
