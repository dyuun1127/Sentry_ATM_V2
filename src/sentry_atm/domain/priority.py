"""Persistence-independent contracts for operational handling priority."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from numbers import Real

from sentry_atm.domain.enums import OperationalPriorityLevel, PriorityReasonCode
from sentry_atm.domain.time_policy import to_utc
from sentry_atm.domain.units import as_finite_float
from sentry_atm.domain.validation import require_identifier


def _as_bounded_score(value: Real, *, field_name: str) -> float:
    score = as_finite_float(value, field_name=field_name)
    if not 0.0 <= score <= 100.0:
        raise ValueError(f"{field_name} must be in [0, 100]")
    return score


def _normalize_reason_codes(
    values: Iterable[PriorityReasonCode],
) -> tuple[PriorityReasonCode, ...]:
    if isinstance(values, (str, bytes)):
        raise TypeError("reason_codes must be an iterable of PriorityReasonCode instances")
    try:
        materialized = tuple(values)
    except TypeError:
        raise TypeError(
            "reason_codes must be an iterable of PriorityReasonCode instances"
        ) from None
    if not materialized:
        raise ValueError("reason_codes must not be empty")
    if not all(isinstance(item, (str, PriorityReasonCode)) for item in materialized):
        raise TypeError("reason_codes must contain only PriorityReasonCode instances")
    normalized = tuple(PriorityReasonCode(item) for item in materialized)
    if len(set(normalized)) != len(normalized):
        raise ValueError("reason_codes must be unique")
    return normalized


def _normalize_event_ids(values: Iterable[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise TypeError("source_event_ids must be an iterable of strings")
    try:
        materialized = tuple(values)
    except TypeError:
        raise TypeError("source_event_ids must be an iterable of strings") from None
    normalized = tuple(
        require_identifier(value, field_name="source_event_id") for value in materialized
    )
    if len(set(normalized)) != len(normalized):
        raise ValueError("source_event_ids must be unique")
    return normalized


@dataclass(frozen=True, slots=True)
class OperationalPriorityPolicyProfile:
    """Injectable event-to-priority mapping for a later Priority Evaluator."""

    profile_id: str
    routine_score: float
    entry_deviation_score: float
    emergency_declared_score: float
    routine_level: OperationalPriorityLevel
    entry_deviation_level: OperationalPriorityLevel
    emergency_declared_level: OperationalPriorityLevel
    source_reference: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "profile_id",
            require_identifier(self.profile_id, field_name="profile_id"),
        )
        for field_name in (
            "routine_score",
            "entry_deviation_score",
            "emergency_declared_score",
        ):
            object.__setattr__(
                self,
                field_name,
                _as_bounded_score(getattr(self, field_name), field_name=field_name),
            )
        if not (self.routine_score < self.entry_deviation_score < self.emergency_declared_score):
            raise ValueError(
                "priority scores must increase from routine to entry deviation to emergency"
            )
        for field_name in (
            "routine_level",
            "entry_deviation_level",
            "emergency_declared_level",
        ):
            object.__setattr__(
                self,
                field_name,
                OperationalPriorityLevel(getattr(self, field_name)),
            )
        object.__setattr__(
            self,
            "source_reference",
            require_identifier(
                self.source_reference,
                field_name="source_reference",
            ),
        )


POC_OPERATIONAL_PRIORITY_V1_POLICY_PROFILE = OperationalPriorityPolicyProfile(
    profile_id="POC_OPERATIONAL_PRIORITY_V1",
    routine_score=0.0,
    entry_deviation_score=40.0,
    emergency_declared_score=100.0,
    routine_level=OperationalPriorityLevel.ROUTINE,
    entry_deviation_level=OperationalPriorityLevel.ATTENTION,
    emergency_declared_level=OperationalPriorityLevel.EMERGENCY,
    source_reference="ASM-023 AND ASM-026 PROJECT DECISION",
)


@dataclass(frozen=True, slots=True)
class OperationalPriorityAssessment:
    """Auditable Aircraft priority result independent from Conflict Risk."""

    priority_assessment_id: str
    aircraft_id: str
    evaluated_at_utc: datetime
    priority_score: float
    priority_level: OperationalPriorityLevel
    reason_codes: tuple[PriorityReasonCode, ...]
    policy_profile_id: str
    source_event_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "priority_assessment_id",
            require_identifier(
                self.priority_assessment_id,
                field_name="priority_assessment_id",
            ),
        )
        object.__setattr__(
            self,
            "aircraft_id",
            require_identifier(self.aircraft_id, field_name="aircraft_id"),
        )
        object.__setattr__(
            self,
            "evaluated_at_utc",
            to_utc(self.evaluated_at_utc, field_name="evaluated_at_utc"),
        )
        object.__setattr__(
            self,
            "priority_score",
            _as_bounded_score(self.priority_score, field_name="priority_score"),
        )
        object.__setattr__(
            self,
            "priority_level",
            OperationalPriorityLevel(self.priority_level),
        )
        object.__setattr__(
            self,
            "reason_codes",
            _normalize_reason_codes(self.reason_codes),
        )
        object.__setattr__(
            self,
            "policy_profile_id",
            require_identifier(
                self.policy_profile_id,
                field_name="policy_profile_id",
            ),
        )
        object.__setattr__(
            self,
            "source_event_ids",
            _normalize_event_ids(self.source_event_ids),
        )
