"""Type-safe deterministic Exception Queue domain contracts."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from math import inf

from sentry_atm.domain.enums import (
    ExceptionKind,
    ExceptionStatus,
    OperationalPriorityLevel,
    RiskLevel,
)
from sentry_atm.domain.priority import OperationalPriorityAssessment
from sentry_atm.domain.risk import ConflictRiskAssessment
from sentry_atm.domain.time_policy import to_utc
from sentry_atm.domain.validation import require_identifier


@dataclass(frozen=True, slots=True)
class ConflictExceptionItem:
    """Queue item backed by exactly one Conflict Risk assessment."""

    exception_id: str
    assessment: ConflictRiskAssessment
    opened_at_utc: datetime
    updated_at_utc: datetime
    status: ExceptionStatus = ExceptionStatus.OPEN

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "exception_id",
            require_identifier(self.exception_id, field_name="exception_id"),
        )
        if not isinstance(self.assessment, ConflictRiskAssessment):
            raise TypeError("assessment must be a ConflictRiskAssessment")
        _normalize_item_times(self)
        object.__setattr__(self, "status", ExceptionStatus(self.status))

    @property
    def kind(self) -> ExceptionKind:
        return ExceptionKind.CONFLICT_RISK

    @property
    def source_assessment_id(self) -> str:
        return self.assessment.risk_assessment_id

    @property
    def subject_aircraft_ids(self) -> tuple[str, str]:
        return self.assessment.pair.aircraft_ids

    @property
    def score(self) -> float:
        return self.assessment.risk_score

    @property
    def tcpa_seconds(self) -> float:
        return self.assessment.tcpa_seconds


@dataclass(frozen=True, slots=True)
class OperationalPriorityExceptionItem:
    """Queue item backed by exactly one Aircraft Priority assessment."""

    exception_id: str
    assessment: OperationalPriorityAssessment
    opened_at_utc: datetime
    updated_at_utc: datetime
    status: ExceptionStatus = ExceptionStatus.OPEN

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "exception_id",
            require_identifier(self.exception_id, field_name="exception_id"),
        )
        if not isinstance(self.assessment, OperationalPriorityAssessment):
            raise TypeError("assessment must be an OperationalPriorityAssessment")
        _normalize_item_times(self)
        object.__setattr__(self, "status", ExceptionStatus(self.status))

    @property
    def kind(self) -> ExceptionKind:
        return ExceptionKind.OPERATIONAL_PRIORITY

    @property
    def source_assessment_id(self) -> str:
        return self.assessment.priority_assessment_id

    @property
    def subject_aircraft_ids(self) -> tuple[str]:
        return (self.assessment.aircraft_id,)

    @property
    def score(self) -> float:
        return self.assessment.priority_score


type ExceptionQueueItem = ConflictExceptionItem | OperationalPriorityExceptionItem


def _normalize_item_times(item: ExceptionQueueItem) -> None:
    opened_at_utc = to_utc(item.opened_at_utc, field_name="opened_at_utc")
    updated_at_utc = to_utc(item.updated_at_utc, field_name="updated_at_utc")
    if updated_at_utc < opened_at_utc:
        raise ValueError("updated_at_utc must not precede opened_at_utc")
    if not opened_at_utc <= item.assessment.evaluated_at_utc <= updated_at_utc:
        raise ValueError("assessment evaluated_at_utc must be within the item lifecycle interval")
    object.__setattr__(item, "opened_at_utc", opened_at_utc)
    object.__setattr__(item, "updated_at_utc", updated_at_utc)


@dataclass(frozen=True, slots=True)
class ExceptionQueuePolicy:
    """Injectable cross-type ranks and deterministic Queue ordering."""

    profile_id: str
    emergency_priority_rank: int
    critical_risk_rank: int
    urgent_priority_rank: int
    high_risk_rank: int
    attention_priority_rank: int
    medium_risk_rank: int
    routine_priority_rank: int
    low_risk_rank: int
    source_reference: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "profile_id",
            require_identifier(self.profile_id, field_name="profile_id"),
        )
        rank_field_names = (
            "emergency_priority_rank",
            "critical_risk_rank",
            "urgent_priority_rank",
            "high_risk_rank",
            "attention_priority_rank",
            "medium_risk_rank",
            "routine_priority_rank",
            "low_risk_rank",
        )
        ranks = tuple(getattr(self, field_name) for field_name in rank_field_names)
        if any(isinstance(rank, bool) or not isinstance(rank, int) for rank in ranks):
            raise TypeError("exception ranks must be integers")
        if any(rank < 0 for rank in ranks):
            raise ValueError("exception ranks must be non-negative")
        if len(set(ranks)) != len(ranks):
            raise ValueError("exception ranks must be unique")
        object.__setattr__(
            self,
            "source_reference",
            require_identifier(
                self.source_reference,
                field_name="source_reference",
            ),
        )

    def rank(self, item: ExceptionQueueItem) -> int:
        """Return the configured cross-type severity rank for one item."""

        _require_queue_item(item)
        if isinstance(item, ConflictExceptionItem):
            return {
                RiskLevel.CRITICAL: self.critical_risk_rank,
                RiskLevel.HIGH: self.high_risk_rank,
                RiskLevel.MEDIUM: self.medium_risk_rank,
                RiskLevel.LOW: self.low_risk_rank,
            }[item.assessment.risk_level]
        return {
            OperationalPriorityLevel.EMERGENCY: self.emergency_priority_rank,
            OperationalPriorityLevel.URGENT: self.urgent_priority_rank,
            OperationalPriorityLevel.ATTENTION: self.attention_priority_rank,
            OperationalPriorityLevel.ROUTINE: self.routine_priority_rank,
        }[item.assessment.priority_level]

    def sort_key(self, item: ExceptionQueueItem) -> tuple[int, int, int, float, float, str]:
        """Return a total ordering independent from iterable input order."""

        severity_rank = self.rank(item)
        resolved_rank = 1 if item.status is ExceptionStatus.RESOLVED else 0
        acknowledgement_rank = 1 if item.status is ExceptionStatus.ACKNOWLEDGED else 0
        tcpa_seconds = item.tcpa_seconds if isinstance(item, ConflictExceptionItem) else inf
        return (
            resolved_rank,
            severity_rank,
            acknowledgement_rank,
            tcpa_seconds,
            -item.score,
            item.exception_id,
        )

    def order(
        self,
        items: Iterable[ExceptionQueueItem],
    ) -> tuple[ExceptionQueueItem, ...]:
        """Materialize and sort supported Queue items deterministically."""

        materialized = _materialize_items(items)
        return tuple(sorted(materialized, key=self.sort_key))


POC_EXCEPTION_QUEUE_V1_POLICY = ExceptionQueuePolicy(
    profile_id="POC_EXCEPTION_QUEUE_V1",
    emergency_priority_rank=0,
    critical_risk_rank=1,
    urgent_priority_rank=2,
    high_risk_rank=3,
    attention_priority_rank=4,
    medium_risk_rank=5,
    routine_priority_rank=6,
    low_risk_rank=7,
    source_reference="ASM-036 PROVISIONAL POC ASSUMPTION",
)


@dataclass(frozen=True, slots=True)
class ExceptionQueueSnapshot:
    """Immutable deterministically ordered Queue state at one UTC time."""

    queue_snapshot_id: str
    generated_at_utc: datetime
    items: tuple[ExceptionQueueItem, ...]
    policy: ExceptionQueuePolicy = POC_EXCEPTION_QUEUE_V1_POLICY

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "queue_snapshot_id",
            require_identifier(
                self.queue_snapshot_id,
                field_name="queue_snapshot_id",
            ),
        )
        object.__setattr__(
            self,
            "generated_at_utc",
            to_utc(self.generated_at_utc, field_name="generated_at_utc"),
        )
        if not isinstance(self.policy, ExceptionQueuePolicy):
            raise TypeError("policy must be an ExceptionQueuePolicy")
        materialized = _materialize_items(self.items)
        exception_ids = tuple(item.exception_id for item in materialized)
        if len(set(exception_ids)) != len(exception_ids):
            raise ValueError("queue exception IDs must be unique")
        source_ids = tuple(item.source_assessment_id for item in materialized)
        if len(set(source_ids)) != len(source_ids):
            raise ValueError("queue source assessment IDs must be unique")
        if any(item.updated_at_utc > self.generated_at_utc for item in materialized):
            raise ValueError("queue items must not be newer than generated_at_utc")
        object.__setattr__(self, "items", self.policy.order(materialized))

    @property
    def policy_profile_id(self) -> str:
        return self.policy.profile_id

    @property
    def active_items(self) -> tuple[ExceptionQueueItem, ...]:
        return tuple(item for item in self.items if item.status is not ExceptionStatus.RESOLVED)

    @property
    def top_item(self) -> ExceptionQueueItem | None:
        return self.active_items[0] if self.active_items else None


def _materialize_items(
    items: Iterable[ExceptionQueueItem],
) -> tuple[ExceptionQueueItem, ...]:
    if isinstance(items, (str, bytes)):
        raise TypeError("items must be an iterable of Exception Queue items")
    try:
        materialized = tuple(items)
    except TypeError:
        raise TypeError("items must be an iterable of Exception Queue items") from None
    if not all(
        isinstance(item, (ConflictExceptionItem, OperationalPriorityExceptionItem))
        for item in materialized
    ):
        raise TypeError("items must contain only Exception Queue items")
    return materialized


def _require_queue_item(item: ExceptionQueueItem) -> None:
    if not isinstance(item, (ConflictExceptionItem, OperationalPriorityExceptionItem)):
        raise TypeError("item must be an Exception Queue item")
