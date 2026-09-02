"""Persistence-independent contracts for predictive conflict assessments."""

from dataclasses import dataclass
from datetime import datetime

from sentry_atm.domain.enums import ConflictStatus
from sentry_atm.domain.time_policy import to_utc
from sentry_atm.domain.units import as_non_negative_float
from sentry_atm.domain.validation import require_identifier


def _as_positive_float(value: float, *, field_name: str) -> float:
    normalized = as_non_negative_float(value, field_name=field_name)
    if normalized == 0.0:
        raise ValueError(f"{field_name} must be greater than zero")
    return normalized


@dataclass(frozen=True, slots=True)
class ConflictPair:
    """Two distinct aircraft IDs stored in deterministic lexical order."""

    first_aircraft_id: str
    second_aircraft_id: str

    def __post_init__(self) -> None:
        first = require_identifier(
            self.first_aircraft_id,
            field_name="first_aircraft_id",
        )
        second = require_identifier(
            self.second_aircraft_id,
            field_name="second_aircraft_id",
        )
        if first == second:
            raise ValueError("conflict pair aircraft IDs must be distinct")
        normalized_first, normalized_second = sorted((first, second))
        object.__setattr__(self, "first_aircraft_id", normalized_first)
        object.__setattr__(self, "second_aircraft_id", normalized_second)

    @property
    def aircraft_ids(self) -> tuple[str, str]:
        """Return the normalized aircraft IDs as a stable pair key."""

        return self.first_aircraft_id, self.second_aircraft_id


@dataclass(frozen=True, slots=True)
class SeparationMinimum:
    """Horizontal and vertical separation at one predicted closest approach."""

    horizontal_nm: float
    vertical_ft: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "horizontal_nm",
            as_non_negative_float(self.horizontal_nm, field_name="horizontal_nm"),
        )
        object.__setattr__(
            self,
            "vertical_ft",
            as_non_negative_float(self.vertical_ft, field_name="vertical_ft"),
        )


@dataclass(frozen=True, slots=True)
class SeparationRuleProfile:
    """Injectable PoC thresholds with an explicit provenance reference."""

    profile_id: str
    horizontal_threshold_nm: float
    vertical_threshold_ft: float
    source_reference: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "profile_id",
            require_identifier(self.profile_id, field_name="profile_id"),
        )
        object.__setattr__(
            self,
            "horizontal_threshold_nm",
            _as_positive_float(
                self.horizontal_threshold_nm,
                field_name="horizontal_threshold_nm",
            ),
        )
        object.__setattr__(
            self,
            "vertical_threshold_ft",
            _as_positive_float(
                self.vertical_threshold_ft,
                field_name="vertical_threshold_ft",
            ),
        )
        object.__setattr__(
            self,
            "source_reference",
            require_identifier(
                self.source_reference,
                field_name="source_reference",
            ),
        )

    def classify(self, minimum: SeparationMinimum) -> ConflictStatus:
        """Classify a minimum using the profile's conjunctive PoC rule."""

        if not isinstance(minimum, SeparationMinimum):
            raise TypeError("minimum must be a SeparationMinimum")
        if (
            minimum.horizontal_nm < self.horizontal_threshold_nm
            and minimum.vertical_ft < self.vertical_threshold_ft
        ):
            return ConflictStatus.PREDICTED
        return ConflictStatus.SAFE


POC_TERMINAL_V1_RULE_PROFILE = SeparationRuleProfile(
    profile_id="POC_TERMINAL_V1",
    horizontal_threshold_nm=5.0,
    vertical_threshold_ft=1_000.0,
    source_reference="ASM-018 PROVISIONAL POC ASSUMPTION",
)


@dataclass(frozen=True, slots=True)
class ConflictEvent:
    """Immutable result describing one pair's predicted closest approach."""

    conflict_id: str
    pair: ConflictPair
    status: ConflictStatus
    evaluated_at_utc: datetime
    closest_approach_time_utc: datetime
    minimum_separation: SeparationMinimum
    rule_profile_id: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "conflict_id",
            require_identifier(self.conflict_id, field_name="conflict_id"),
        )
        if not isinstance(self.pair, ConflictPair):
            raise TypeError("pair must be a ConflictPair")
        object.__setattr__(self, "status", ConflictStatus(self.status))
        object.__setattr__(
            self,
            "evaluated_at_utc",
            to_utc(self.evaluated_at_utc, field_name="evaluated_at_utc"),
        )
        object.__setattr__(
            self,
            "closest_approach_time_utc",
            to_utc(
                self.closest_approach_time_utc,
                field_name="closest_approach_time_utc",
            ),
        )
        if self.closest_approach_time_utc < self.evaluated_at_utc:
            raise ValueError("closest_approach_time_utc must not precede evaluated_at_utc")
        if not isinstance(self.minimum_separation, SeparationMinimum):
            raise TypeError("minimum_separation must be a SeparationMinimum")
        object.__setattr__(
            self,
            "rule_profile_id",
            require_identifier(
                self.rule_profile_id,
                field_name="rule_profile_id",
            ),
        )

    @property
    def tcpa_seconds(self) -> float:
        """Return seconds from evaluation time to predicted closest approach."""

        return (self.closest_approach_time_utc - self.evaluated_at_utc).total_seconds()
