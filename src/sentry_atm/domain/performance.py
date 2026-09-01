"""Aircraft type and non-sensitive performance profile models."""

from dataclasses import dataclass

from sentry_atm.domain.enums import AircraftCategory, PerformanceDataSource
from sentry_atm.domain.units import as_non_negative_float
from sentry_atm.domain.validation import normalize_optional_text, require_identifier


def _normalize_type_code(value: str, *, field_name: str = "type_code") -> str:
    return require_identifier(value, field_name=field_name).upper()


def _as_positive_float(value: float, *, field_name: str) -> float:
    normalized = as_non_negative_float(value, field_name=field_name)
    if normalized == 0.0:
        raise ValueError(f"{field_name} must be greater than zero")
    return normalized


@dataclass(frozen=True, slots=True)
class AircraftType:
    """Public, slowly changing classification of an aircraft type."""

    type_code: str
    category: AircraftCategory
    manufacturer: str | None = None
    model: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "type_code", _normalize_type_code(self.type_code))
        object.__setattr__(self, "category", AircraftCategory(self.category))
        object.__setattr__(
            self,
            "manufacturer",
            normalize_optional_text(self.manufacturer, field_name="manufacturer"),
        )
        object.__setattr__(
            self,
            "model",
            normalize_optional_text(self.model, field_name="model"),
        )


@dataclass(frozen=True, slots=True)
class AircraftPerformanceProfile:
    """Simple PoC kinematic envelope with explicit data provenance."""

    profile_id: str
    category: AircraftCategory
    source: PerformanceDataSource
    source_reference: str
    min_speed_kt: float
    max_speed_kt: float
    max_climb_rate_fpm: float
    max_descent_rate_fpm: float
    max_turn_rate_deg_per_second: float
    ceiling_ft: float
    aircraft_type_code: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "profile_id",
            require_identifier(self.profile_id, field_name="profile_id"),
        )
        object.__setattr__(self, "category", AircraftCategory(self.category))
        object.__setattr__(self, "source", PerformanceDataSource(self.source))
        object.__setattr__(
            self,
            "source_reference",
            require_identifier(self.source_reference, field_name="source_reference"),
        )
        object.__setattr__(
            self,
            "min_speed_kt",
            as_non_negative_float(self.min_speed_kt, field_name="min_speed_kt"),
        )
        object.__setattr__(
            self,
            "max_speed_kt",
            _as_positive_float(self.max_speed_kt, field_name="max_speed_kt"),
        )
        object.__setattr__(
            self,
            "max_climb_rate_fpm",
            _as_positive_float(
                self.max_climb_rate_fpm,
                field_name="max_climb_rate_fpm",
            ),
        )
        object.__setattr__(
            self,
            "max_descent_rate_fpm",
            _as_positive_float(
                self.max_descent_rate_fpm,
                field_name="max_descent_rate_fpm",
            ),
        )
        object.__setattr__(
            self,
            "max_turn_rate_deg_per_second",
            _as_positive_float(
                self.max_turn_rate_deg_per_second,
                field_name="max_turn_rate_deg_per_second",
            ),
        )
        object.__setattr__(
            self,
            "ceiling_ft",
            _as_positive_float(self.ceiling_ft, field_name="ceiling_ft"),
        )
        if self.aircraft_type_code is not None:
            object.__setattr__(
                self,
                "aircraft_type_code",
                _normalize_type_code(
                    self.aircraft_type_code,
                    field_name="aircraft_type_code",
                ),
            )
        if self.min_speed_kt > self.max_speed_kt:
            raise ValueError("min_speed_kt must not exceed max_speed_kt")
