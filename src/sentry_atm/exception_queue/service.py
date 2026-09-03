"""Stateful deterministic lifecycle assembly for Exception Queue snapshots."""

from collections.abc import Iterable
from datetime import datetime

from sentry_atm.domain import (
    POC_EXCEPTION_QUEUE_V1_POLICY,
    ConflictExceptionItem,
    ConflictRiskAssessment,
    ExceptionQueueItem,
    ExceptionQueuePolicy,
    ExceptionQueueSnapshot,
    ExceptionStatus,
    OperationalPriorityAssessment,
    OperationalPriorityExceptionItem,
    OperationalPriorityLevel,
    RiskLevel,
)
from sentry_atm.domain.time_policy import to_utc


class ExceptionQueueService:
    """Build snapshots while preserving stable IDs and operator acknowledgement."""

    __slots__ = ("_items", "_last_snapshot", "_policy", "_revision")

    def __init__(
        self,
        policy: ExceptionQueuePolicy = POC_EXCEPTION_QUEUE_V1_POLICY,
    ) -> None:
        if not isinstance(policy, ExceptionQueuePolicy):
            raise TypeError("policy must be an ExceptionQueuePolicy")
        self._policy = policy
        self._items: dict[str, ExceptionQueueItem] = {}
        self._last_snapshot: ExceptionQueueSnapshot | None = None
        self._revision = 0

    @property
    def policy(self) -> ExceptionQueuePolicy:
        return self._policy

    @property
    def current_items(self) -> tuple[ExceptionQueueItem, ...]:
        """Return all current items in Queue policy order."""

        return self._policy.order(self._items.values())

    @property
    def last_snapshot(self) -> ExceptionQueueSnapshot | None:
        return self._last_snapshot

    def refresh(
        self,
        generated_at_utc: datetime,
        *,
        risk_assessments: Iterable[ConflictRiskAssessment] = (),
        priority_assessments: Iterable[OperationalPriorityAssessment] = (),
    ) -> ExceptionQueueSnapshot:
        """Apply evaluated sources and return one immutable Queue snapshot.

        An omitted source is retained unchanged. A source is resolved only when a
        new LOW/ROUTINE assessment for the same stable subject is supplied.
        """

        generated_at = self._normalize_operation_time(generated_at_utc)
        risks = _materialize_risks(risk_assessments)
        priorities = _materialize_priorities(priority_assessments)
        _validate_refresh_inputs(generated_at, risks, priorities)

        candidate_items = dict(self._items)
        for assessment in sorted(risks, key=_risk_subject_key):
            exception_id = _risk_exception_id(assessment)
            existing = candidate_items.get(exception_id)
            active = assessment.risk_level is not RiskLevel.LOW
            updated = _updated_risk_item(exception_id, assessment, existing, active=active)
            if updated is not None:
                candidate_items[exception_id] = updated

        for assessment in sorted(priorities, key=_priority_subject_key):
            exception_id = _priority_exception_id(assessment)
            existing = candidate_items.get(exception_id)
            active = assessment.priority_level is not OperationalPriorityLevel.ROUTINE
            updated = _updated_priority_item(
                exception_id,
                assessment,
                existing,
                active=active,
            )
            if updated is not None:
                candidate_items[exception_id] = updated

        return self._publish(generated_at, candidate_items)

    def acknowledge(
        self,
        exception_id: str,
        acknowledged_at_utc: datetime,
    ) -> ExceptionQueueSnapshot:
        """Acknowledge one active item without changing its source assessment."""

        acknowledged_at = self._normalize_operation_time(acknowledged_at_utc)
        try:
            item = self._items[exception_id]
        except (KeyError, TypeError):
            raise KeyError(f"unknown exception_id: {exception_id!r}") from None
        if item.status is ExceptionStatus.RESOLVED:
            raise ValueError("resolved exception items cannot be acknowledged")
        if item.status is ExceptionStatus.ACKNOWLEDGED:
            return self._publish(acknowledged_at, dict(self._items))

        candidate_items = dict(self._items)
        if isinstance(item, ConflictExceptionItem):
            acknowledged_item: ExceptionQueueItem = ConflictExceptionItem(
                exception_id=item.exception_id,
                assessment=item.assessment,
                opened_at_utc=item.opened_at_utc,
                updated_at_utc=acknowledged_at,
                status=ExceptionStatus.ACKNOWLEDGED,
            )
        else:
            acknowledged_item = OperationalPriorityExceptionItem(
                exception_id=item.exception_id,
                assessment=item.assessment,
                opened_at_utc=item.opened_at_utc,
                updated_at_utc=acknowledged_at,
                status=ExceptionStatus.ACKNOWLEDGED,
            )
        candidate_items[exception_id] = acknowledged_item
        return self._publish(acknowledged_at, candidate_items)

    def reset(self) -> None:
        """Return the service to its deterministic initial state."""

        self._items.clear()
        self._last_snapshot = None
        self._revision = 0

    def _normalize_operation_time(self, value: datetime) -> datetime:
        normalized = to_utc(value, field_name="operation_time_utc")
        if self._last_snapshot is not None and normalized < self._last_snapshot.generated_at_utc:
            raise ValueError("operation time must not precede the last snapshot")
        return normalized

    def _publish(
        self,
        generated_at_utc: datetime,
        candidate_items: dict[str, ExceptionQueueItem],
    ) -> ExceptionQueueSnapshot:
        revision = self._revision + 1
        timestamp_token = generated_at_utc.strftime("%Y%m%dT%H%M%S%fZ")
        snapshot = ExceptionQueueSnapshot(
            queue_snapshot_id=f"QUEUE-{timestamp_token}-{revision:06d}",
            generated_at_utc=generated_at_utc,
            items=tuple(candidate_items.values()),
            policy=self._policy,
        )
        self._items = candidate_items
        self._last_snapshot = snapshot
        self._revision = revision
        return snapshot


def _updated_risk_item(
    exception_id: str,
    assessment: ConflictRiskAssessment,
    existing: ExceptionQueueItem | None,
    *,
    active: bool,
) -> ConflictExceptionItem | None:
    if existing is not None and not isinstance(existing, ConflictExceptionItem):
        raise TypeError("stable conflict exception ID collided with a priority item")
    if not active and existing is None:
        return None
    if not active:
        return ConflictExceptionItem(
            exception_id=exception_id,
            assessment=assessment,
            opened_at_utc=existing.opened_at_utc,
            updated_at_utc=assessment.evaluated_at_utc,
            status=ExceptionStatus.RESOLVED,
        )
    reopened = existing is None or existing.status is ExceptionStatus.RESOLVED
    return ConflictExceptionItem(
        exception_id=exception_id,
        assessment=assessment,
        opened_at_utc=assessment.evaluated_at_utc if reopened else existing.opened_at_utc,
        updated_at_utc=assessment.evaluated_at_utc,
        status=ExceptionStatus.OPEN if reopened else existing.status,
    )


def _updated_priority_item(
    exception_id: str,
    assessment: OperationalPriorityAssessment,
    existing: ExceptionQueueItem | None,
    *,
    active: bool,
) -> OperationalPriorityExceptionItem | None:
    if existing is not None and not isinstance(existing, OperationalPriorityExceptionItem):
        raise TypeError("stable priority exception ID collided with a conflict item")
    if not active and existing is None:
        return None
    if not active:
        return OperationalPriorityExceptionItem(
            exception_id=exception_id,
            assessment=assessment,
            opened_at_utc=existing.opened_at_utc,
            updated_at_utc=assessment.evaluated_at_utc,
            status=ExceptionStatus.RESOLVED,
        )
    reopened = existing is None or existing.status is ExceptionStatus.RESOLVED
    return OperationalPriorityExceptionItem(
        exception_id=exception_id,
        assessment=assessment,
        opened_at_utc=assessment.evaluated_at_utc if reopened else existing.opened_at_utc,
        updated_at_utc=assessment.evaluated_at_utc,
        status=ExceptionStatus.OPEN if reopened else existing.status,
    )


def _risk_subject_key(assessment: ConflictRiskAssessment) -> tuple[str, str]:
    return assessment.pair.aircraft_ids


def _priority_subject_key(assessment: OperationalPriorityAssessment) -> str:
    return assessment.aircraft_id


def _risk_exception_id(assessment: ConflictRiskAssessment) -> str:
    first, second = _risk_subject_key(assessment)
    return f"EXCEPTION-CONFLICT-{len(first)}-{first}-{len(second)}-{second}"


def _priority_exception_id(assessment: OperationalPriorityAssessment) -> str:
    return f"EXCEPTION-PRIORITY-{assessment.aircraft_id}"


def _validate_refresh_inputs(
    generated_at_utc: datetime,
    risks: tuple[ConflictRiskAssessment, ...],
    priorities: tuple[OperationalPriorityAssessment, ...],
) -> None:
    assessments: tuple[ConflictRiskAssessment | OperationalPriorityAssessment, ...] = (
        *risks,
        *priorities,
    )
    if any(item.evaluated_at_utc != generated_at_utc for item in assessments):
        raise ValueError("all assessments must be evaluated at generated_at_utc")
    source_ids = tuple(
        item.risk_assessment_id
        if isinstance(item, ConflictRiskAssessment)
        else item.priority_assessment_id
        for item in assessments
    )
    if len(set(source_ids)) != len(source_ids):
        raise ValueError("assessment IDs must be unique")
    risk_keys = tuple(_risk_subject_key(item) for item in risks)
    if len(set(risk_keys)) != len(risk_keys):
        raise ValueError("risk assessments must have unique Aircraft pairs")
    priority_keys = tuple(_priority_subject_key(item) for item in priorities)
    if len(set(priority_keys)) != len(priority_keys):
        raise ValueError("priority assessments must have unique Aircraft IDs")


def _materialize_risks(
    values: Iterable[ConflictRiskAssessment],
) -> tuple[ConflictRiskAssessment, ...]:
    return _materialize(values, ConflictRiskAssessment, field_name="risk_assessments")


def _materialize_priorities(
    values: Iterable[OperationalPriorityAssessment],
) -> tuple[OperationalPriorityAssessment, ...]:
    return _materialize(values, OperationalPriorityAssessment, field_name="priority_assessments")


def _materialize(values: Iterable[object], expected_type: type, *, field_name: str) -> tuple:
    if isinstance(values, (str, bytes)):
        raise TypeError(f"{field_name} must be an iterable")
    try:
        materialized = tuple(values)
    except TypeError:
        raise TypeError(f"{field_name} must be an iterable") from None
    if not all(isinstance(value, expected_type) for value in materialized):
        raise TypeError(f"{field_name} contains an unsupported assessment")
    return materialized
