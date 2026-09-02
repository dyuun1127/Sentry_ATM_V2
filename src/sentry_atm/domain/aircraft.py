"""Aircraft identity, metadata, and kinematic state models."""

from dataclasses import dataclass
from datetime import datetime
from string import hexdigits

from sentry_atm.domain.enums import (
    AircraftCategory,
    DataSource,
    EmergencyStatus,
    EmergencyType,
    FlightPhase,
)
from sentry_atm.domain.time_policy import to_kst, to_utc
from sentry_atm.domain.units import (
    as_finite_float,
    as_heading_deg,
    as_non_negative_float,
)
from sentry_atm.domain.validation import normalize_optional_text, require_identifier


def _normalize_icao24(value: str | None) -> str | None:
    normalized = normalize_optional_text(value, field_name="icao24")
    if normalized is None:
        return None
    lowered = normalized.lower()
    if len(lowered) != 6 or any(character not in hexdigits for character in lowered):
        raise ValueError("icao24 must contain exactly 6 hexadecimal characters")
    return lowered


@dataclass(frozen=True, slots=True)
class AircraftMetadata:
    """Relatively stable, non-kinematic aircraft information."""

    aircraft_id: str
    aircraft_type: str = "UNKNOWN"
    category: AircraftCategory = AircraftCategory.UNKNOWN
    callsign: str | None = None
    icao24: str | None = None
    performance_class: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "aircraft_id",
            require_identifier(self.aircraft_id, field_name="aircraft_id"),
        )
        object.__setattr__(
            self,
            "aircraft_type",
            require_identifier(self.aircraft_type, field_name="aircraft_type"),
        )
        object.__setattr__(self, "category", AircraftCategory(self.category))
        object.__setattr__(
            self,
            "callsign",
            normalize_optional_text(self.callsign, field_name="callsign"),
        )
        object.__setattr__(self, "icao24", _normalize_icao24(self.icao24))
        object.__setattr__(
            self,
            "performance_class",
            normalize_optional_text(
                self.performance_class,
                field_name="performance_class",
            ),
        )


@dataclass(frozen=True, slots=True)
class AircraftState:
    """An immutable aircraft state in the project's canonical units."""

    aircraft_id: str
    timestamp_utc: datetime
    x_nm: float
    y_nm: float
    altitude_ft: float
    ground_speed_kt: float
    heading_deg: float
    vertical_speed_fpm: float
    source: DataSource
    flight_phase: FlightPhase = FlightPhase.UNKNOWN
    emergency_status: EmergencyStatus = EmergencyStatus.NONE
    emergency_type: EmergencyType | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "aircraft_id",
            require_identifier(self.aircraft_id, field_name="aircraft_id"),
        )
        object.__setattr__(
            self,
            "timestamp_utc",
            to_utc(self.timestamp_utc, field_name="timestamp_utc"),
        )
        object.__setattr__(self, "x_nm", as_finite_float(self.x_nm, field_name="x_nm"))
        object.__setattr__(self, "y_nm", as_finite_float(self.y_nm, field_name="y_nm"))
        object.__setattr__(
            self,
            "altitude_ft",
            as_finite_float(self.altitude_ft, field_name="altitude_ft"),
        )
        object.__setattr__(
            self,
            "ground_speed_kt",
            as_non_negative_float(self.ground_speed_kt, field_name="ground_speed_kt"),
        )
        object.__setattr__(self, "heading_deg", as_heading_deg(self.heading_deg))
        object.__setattr__(
            self,
            "vertical_speed_fpm",
            as_finite_float(
                self.vertical_speed_fpm,
                field_name="vertical_speed_fpm",
            ),
        )
        object.__setattr__(self, "source", DataSource(self.source))
        object.__setattr__(self, "flight_phase", FlightPhase(self.flight_phase))
        object.__setattr__(
            self,
            "emergency_status",
            EmergencyStatus(self.emergency_status),
        )
        if self.emergency_type is not None:
            object.__setattr__(self, "emergency_type", EmergencyType(self.emergency_type))
        self._validate_emergency()

    def _validate_emergency(self) -> None:
        if self.emergency_status is EmergencyStatus.NONE and self.emergency_type is not None:
            raise ValueError("emergency_type must be None when emergency_status is NONE")
        if self.emergency_status is EmergencyStatus.DECLARED and self.emergency_type is None:
            raise ValueError("emergency_type is required when emergency_status is DECLARED")

    @property
    def timestamp_kst(self) -> datetime:
        """Return a presentation timestamp without duplicating stored time state."""

        return to_kst(self.timestamp_utc, field_name="timestamp_utc")
