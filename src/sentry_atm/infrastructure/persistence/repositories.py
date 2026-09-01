"""SQLAlchemy implementations of the initial repository ports."""

from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from sentry_atm.domain import AircraftMetadata, AircraftState
from sentry_atm.domain.time_policy import to_utc
from sentry_atm.domain.validation import require_identifier
from sentry_atm.infrastructure.persistence.mappers import (
    aircraft_from_row,
    aircraft_state_from_row,
    aircraft_state_to_row,
    aircraft_to_row,
)
from sentry_atm.infrastructure.persistence.models import AircraftRow, AircraftStateRow


def _require_session(session: Session) -> Session:
    if not isinstance(session, Session):
        raise TypeError("session must be a SQLAlchemy Session")
    return session


class SqlAlchemyAircraftRepository:
    """Aircraft metadata adapter; the caller owns commit and rollback."""

    __slots__ = ("_session",)

    def __init__(self, session: Session) -> None:
        self._session = _require_session(session)

    def get(self, aircraft_id: str) -> AircraftMetadata | None:
        identifier = require_identifier(aircraft_id, field_name="aircraft_id")
        row = self._session.get(AircraftRow, identifier)
        return aircraft_from_row(row) if row is not None else None

    def list_all(self) -> tuple[AircraftMetadata, ...]:
        rows = self._session.scalars(select(AircraftRow).order_by(AircraftRow.aircraft_id)).all()
        return tuple(aircraft_from_row(row) for row in rows)

    def upsert(self, aircraft: AircraftMetadata) -> None:
        incoming = aircraft_to_row(aircraft)
        existing = self._session.get(AircraftRow, incoming.aircraft_id)
        if existing is None:
            self._session.add(incoming)
        else:
            existing.aircraft_type = incoming.aircraft_type
            existing.category = incoming.category
            existing.callsign = incoming.callsign
            existing.icao24 = incoming.icao24
            existing.performance_profile_id = incoming.performance_profile_id
        self._session.flush()


class SqlAlchemyAircraftStateRepository:
    """Append-only state adapter; the caller owns commit and rollback."""

    __slots__ = ("_session",)

    def __init__(self, session: Session) -> None:
        self._session = _require_session(session)

    def append(self, state: AircraftState) -> None:
        self._session.add(aircraft_state_to_row(state))
        self._session.flush()

    def append_many(self, states: Iterable[AircraftState]) -> None:
        rows = tuple(aircraft_state_to_row(state) for state in states)
        self._session.add_all(rows)
        self._session.flush()

    def latest_at_or_before(
        self,
        aircraft_id: str,
        timestamp_utc: datetime,
    ) -> AircraftState | None:
        identifier = require_identifier(aircraft_id, field_name="aircraft_id")
        timestamp = to_utc(timestamp_utc, field_name="timestamp_utc")
        row = self._session.scalars(
            select(AircraftStateRow)
            .where(
                AircraftStateRow.aircraft_id == identifier,
                AircraftStateRow.timestamp_utc <= timestamp,
            )
            .order_by(AircraftStateRow.timestamp_utc.desc())
            .limit(1)
        ).first()
        return aircraft_state_from_row(row) if row is not None else None

    def list_between(
        self,
        aircraft_id: str,
        start_time_utc: datetime,
        end_time_utc: datetime,
    ) -> tuple[AircraftState, ...]:
        identifier = require_identifier(aircraft_id, field_name="aircraft_id")
        start = to_utc(start_time_utc, field_name="start_time_utc")
        end = to_utc(end_time_utc, field_name="end_time_utc")
        if end < start:
            raise ValueError("end_time_utc must not be earlier than start_time_utc")
        rows = self._session.scalars(
            select(AircraftStateRow)
            .where(
                AircraftStateRow.aircraft_id == identifier,
                AircraftStateRow.timestamp_utc >= start,
                AircraftStateRow.timestamp_utc <= end,
            )
            .order_by(AircraftStateRow.timestamp_utc)
        ).all()
        return tuple(aircraft_state_from_row(row) for row in rows)
