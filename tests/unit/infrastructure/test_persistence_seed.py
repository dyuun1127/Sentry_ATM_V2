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
    # 포락선은 범주 단위다(`CATEGORY_ENVELOPE`). 기종마다 만들면 같은 범주 안에서
    # 같은 수치가 복제될 뿐이므로, 기종 코드와 1:1 로 대응하지 않는다. 대신 모든
    # 기종이 자기 범주의 포락선을 찾을 수 있어야 한다.
    profiles_by_category = {item.category: item for item in POC_PERFORMANCE_PROFILES}
    assert len(profiles_by_category) == len(POC_PERFORMANCE_PROFILES)
    for aircraft_type in POC_AIRCRAFT_TYPES:
        assert aircraft_type.category in profiles_by_category


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
