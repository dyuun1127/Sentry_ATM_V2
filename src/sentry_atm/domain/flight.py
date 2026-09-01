"""Flight lifecycle model independent of routes and persistence technology."""

from dataclasses import dataclass
from datetime import datetime

from sentry_atm.domain.enums import FlightStatus
from sentry_atm.domain.time_policy import to_utc
from sentry_atm.domain.validation import normalize_optional_text, require_identifier


@dataclass(frozen=True, slots=True)
class Flight:
    """One aircraft's planned operational interval in the PoC."""

    flight_id: str
    aircraft_id: str
    status: FlightStatus
    planned_start_time_utc: datetime
    planned_end_time_utc: datetime | None = None
    departure: str | None = None
    destination: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "flight_id",
            require_identifier(self.flight_id, field_name="flight_id"),
        )
        object.__setattr__(
            self,
            "aircraft_id",
            require_identifier(self.aircraft_id, field_name="aircraft_id"),
        )
        object.__setattr__(self, "status", FlightStatus(self.status))
        object.__setattr__(
            self,
            "planned_start_time_utc",
            to_utc(self.planned_start_time_utc, field_name="planned_start_time_utc"),
        )
        if self.planned_end_time_utc is not None:
            object.__setattr__(
                self,
                "planned_end_time_utc",
                to_utc(self.planned_end_time_utc, field_name="planned_end_time_utc"),
            )
            if self.planned_end_time_utc <= self.planned_start_time_utc:
                raise ValueError("planned_end_time_utc must be later than planned_start_time_utc")
        object.__setattr__(
            self,
            "departure",
            normalize_optional_text(self.departure, field_name="departure"),
        )
        object.__setattr__(
            self,
            "destination",
            normalize_optional_text(self.destination, field_name="destination"),
        )
