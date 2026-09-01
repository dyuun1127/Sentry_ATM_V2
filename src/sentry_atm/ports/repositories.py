"""Synchronous persistence contracts for domain aggregates.

The contracts intentionally contain no SQLAlchemy, PostgreSQL, or PostGIS types.
Infrastructure adapters translate between these domain objects and database rows.
"""

from collections.abc import Iterable
from datetime import datetime
from typing import Protocol, runtime_checkable

from sentry_atm.domain import (
    AircraftMetadata,
    AircraftPerformanceProfile,
    AircraftState,
    AircraftType,
    Flight,
    PredictionRun,
    Trajectory,
    TrajectoryType,
)


@runtime_checkable
class AircraftRepository(Protocol):
    """Store and retrieve stable aircraft identity metadata."""

    def get(self, aircraft_id: str) -> AircraftMetadata | None: ...

    def list_all(self) -> tuple[AircraftMetadata, ...]: ...

    def upsert(self, aircraft: AircraftMetadata) -> None: ...


@runtime_checkable
class AircraftTypeRepository(Protocol):
    """Store public aircraft-type reference records."""

    def get(self, type_code: str) -> AircraftType | None: ...

    def list_all(self) -> tuple[AircraftType, ...]: ...

    def upsert(self, aircraft_type: AircraftType) -> None: ...


@runtime_checkable
class AircraftPerformanceProfileRepository(Protocol):
    """Store versionable, source-labelled performance envelopes."""

    def get(self, profile_id: str) -> AircraftPerformanceProfile | None: ...

    def list_all(self) -> tuple[AircraftPerformanceProfile, ...]: ...

    def upsert(self, profile: AircraftPerformanceProfile) -> None: ...


@runtime_checkable
class AircraftStateRepository(Protocol):
    """Append and query immutable observed or simulated states."""

    def append(self, state: AircraftState) -> None: ...

    def append_many(self, states: Iterable[AircraftState]) -> None: ...

    def latest_at_or_before(
        self,
        aircraft_id: str,
        timestamp_utc: datetime,
    ) -> AircraftState | None: ...

    def list_between(
        self,
        aircraft_id: str,
        start_time_utc: datetime,
        end_time_utc: datetime,
    ) -> tuple[AircraftState, ...]: ...


@runtime_checkable
class FlightRepository(Protocol):
    """Store flight lifecycle aggregates."""

    def get(self, flight_id: str) -> Flight | None: ...

    def list_for_aircraft(self, aircraft_id: str) -> tuple[Flight, ...]: ...

    def upsert(self, flight: Flight) -> None: ...


@runtime_checkable
class TrajectoryRepository(Protocol):
    """Store planned, actual, and predicted 4D trajectories separately."""

    def save(self, trajectory: Trajectory) -> None: ...

    def list_for_aircraft(
        self,
        aircraft_id: str,
        trajectory_type: TrajectoryType | None = None,
    ) -> tuple[Trajectory, ...]: ...


@runtime_checkable
class PredictionRunRepository(Protocol):
    """Store a predictor run and its trajectories as one aggregate."""

    def get(self, prediction_run_id: str) -> PredictionRun | None: ...

    def save(self, prediction_run: PredictionRun) -> None: ...

    def list_between(
        self,
        start_time_utc: datetime,
        end_time_utc: datetime,
    ) -> tuple[PredictionRun, ...]: ...
