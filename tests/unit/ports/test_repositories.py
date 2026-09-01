from typing import Any

import pytest
from sqlalchemy.orm import Session

from sentry_atm.infrastructure.persistence.repositories import (
    SqlAlchemyAircraftPerformanceProfileRepository,
    SqlAlchemyAircraftTypeRepository,
)
from sentry_atm.ports import (
    AircraftPerformanceProfileRepository,
    AircraftRepository,
    AircraftStateRepository,
    AircraftTypeRepository,
    FlightRepository,
    PredictionRunRepository,
    TrajectoryRepository,
)


class CompleteRepositoryDouble:
    """Structural double proving adapters do not need repository inheritance."""

    def get(self, *args: Any, **kwargs: Any) -> None:
        return None

    def list_all(self, *args: Any, **kwargs: Any) -> tuple[()]:
        return ()

    def upsert(self, *args: Any, **kwargs: Any) -> None:
        return None

    def append(self, *args: Any, **kwargs: Any) -> None:
        return None

    def append_many(self, *args: Any, **kwargs: Any) -> None:
        return None

    def latest_at_or_before(self, *args: Any, **kwargs: Any) -> None:
        return None

    def list_between(self, *args: Any, **kwargs: Any) -> tuple[()]:
        return ()

    def list_for_aircraft(self, *args: Any, **kwargs: Any) -> tuple[()]:
        return ()

    def save(self, *args: Any, **kwargs: Any) -> None:
        return None


@pytest.mark.parametrize(
    "repository_contract",
    [
        AircraftRepository,
        AircraftTypeRepository,
        AircraftPerformanceProfileRepository,
        AircraftStateRepository,
        FlightRepository,
        TrajectoryRepository,
        PredictionRunRepository,
    ],
)
def test_repository_contracts_support_structural_adapter_implementation(
    repository_contract: type,
) -> None:
    assert isinstance(CompleteRepositoryDouble(), repository_contract)


def test_reference_adapters_satisfy_repository_contracts() -> None:
    session = object.__new__(Session)

    assert isinstance(SqlAlchemyAircraftTypeRepository(session), AircraftTypeRepository)
    assert isinstance(
        SqlAlchemyAircraftPerformanceProfileRepository(session),
        AircraftPerformanceProfileRepository,
    )
