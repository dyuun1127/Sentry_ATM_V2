"""Immutable typed events for deterministic scenario playback."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from sentry_atm.domain import EmergencyType
from sentry_atm.domain.time_policy import to_utc
from sentry_atm.domain.units import (
    as_finite_float,
    as_heading_deg,
    as_non_negative_float,
)
from sentry_atm.domain.validation import require_identifier


class ScenarioEventType(StrEnum):
    """Stable categories supported by the Phase 5-B timeline."""

    ENTRY_CONFORMANCE_DEVIATION = "ENTRY_CONFORMANCE_DEVIATION"
    EMERGENCY_DECLARED = "EMERGENCY_DECLARED"


class EmergencyReasonCategory(StrEnum):
    """Non-sensitive reason categories used by Synthetic emergency events."""

    AIRCRAFT_CONDITION = "AIRCRAFT_CONDITION"


@dataclass(frozen=True, slots=True)
class EntryConformanceDeviationPayload:
    """Expected-versus-actual entry values for one Synthetic handoff deviation."""

    expected_entry_point: str
    expected_altitude_ft: float
    expected_heading_deg: float
    actual_altitude_ft: float
    lateral_deviation_nm: float
    time_deviation_seconds: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "expected_entry_point",
            require_identifier(
                self.expected_entry_point,
                field_name="expected_entry_point",
            ),
        )
        object.__setattr__(
            self,
            "expected_altitude_ft",
            as_finite_float(
                self.expected_altitude_ft,
                field_name="expected_altitude_ft",
            ),
        )
        object.__setattr__(
            self,
            "expected_heading_deg",
            as_heading_deg(
                self.expected_heading_deg,
                field_name="expected_heading_deg",
            ),
        )
        object.__setattr__(
            self,
            "actual_altitude_ft",
            as_finite_float(
                self.actual_altitude_ft,
                field_name="actual_altitude_ft",
            ),
        )
        object.__setattr__(
            self,
            "lateral_deviation_nm",
            as_non_negative_float(
                self.lateral_deviation_nm,
                field_name="lateral_deviation_nm",
            ),
        )
        object.__setattr__(
            self,
            "time_deviation_seconds",
            as_finite_float(
                self.time_deviation_seconds,
                field_name="time_deviation_seconds",
            ),
        )


@dataclass(frozen=True, slots=True)
class EmergencyDeclaredPayload:
    """Abstract non-sensitive emergency declaration data."""

    emergency_type: EmergencyType
    reason_category: EmergencyReasonCategory

    def __post_init__(self) -> None:
        object.__setattr__(self, "emergency_type", EmergencyType(self.emergency_type))
        object.__setattr__(
            self,
            "reason_category",
            EmergencyReasonCategory(self.reason_category),
        )


type ScenarioEventPayload = EntryConformanceDeviationPayload | EmergencyDeclaredPayload


@dataclass(frozen=True, slots=True)
class ScenarioEvent:
    """One typed event scheduled at an absolute UTC simulation time."""

    event_id: str
    event_type: ScenarioEventType
    scheduled_time_utc: datetime
    target_aircraft_id: str
    payload: ScenarioEventPayload

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "event_id",
            require_identifier(self.event_id, field_name="event_id"),
        )
        object.__setattr__(self, "event_type", ScenarioEventType(self.event_type))
        object.__setattr__(
            self,
            "scheduled_time_utc",
            to_utc(self.scheduled_time_utc, field_name="scheduled_time_utc"),
        )
        object.__setattr__(
            self,
            "target_aircraft_id",
            require_identifier(
                self.target_aircraft_id,
                field_name="target_aircraft_id",
            ),
        )

        expected_payload_type = {
            ScenarioEventType.ENTRY_CONFORMANCE_DEVIATION: (EntryConformanceDeviationPayload),
            ScenarioEventType.EMERGENCY_DECLARED: EmergencyDeclaredPayload,
        }[self.event_type]
        if not isinstance(self.payload, expected_payload_type):
            raise TypeError(
                f"payload for {self.event_type.value} must be {expected_payload_type.__name__}"
            )
