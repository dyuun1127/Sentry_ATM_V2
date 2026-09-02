"""JSON-ready Exception Queue views and a framework-independent API facade."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from sentry_atm.domain import (
    ConflictExceptionItem,
    ExceptionQueueSnapshot,
    ExceptionStatus,
    OperationalPriorityExceptionItem,
)
from sentry_atm.domain.time_policy import to_utc
from sentry_atm.domain.validation import require_identifier
from sentry_atm.exception_queue import ExceptionQueueService


def _utc_text(value: datetime) -> str:
    """Return a stable RFC 3339 UTC representation with microseconds."""

    return to_utc(value).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _require_include_resolved(value: bool) -> bool:
    if not isinstance(value, bool):
        raise TypeError("include_resolved must be a bool")
    return value


@dataclass(frozen=True, slots=True)
class ConflictExceptionReadModel:
    """Presentation-safe view of one Conflict Risk exception."""

    exception_id: str
    kind: str
    status: str
    subject_aircraft_ids: tuple[str, str]
    source_assessment_id: str
    opened_at_utc: str
    updated_at_utc: str
    score: float
    severity: str
    reason_codes: tuple[str, ...]
    conflict_id: str
    tcpa_seconds: float
    horizontal_separation_ratio: float
    vertical_separation_ratio: float

    def to_dict(self) -> dict[str, object]:
        """Return only JSON-compatible primitives."""

        return {
            "exception_id": self.exception_id,
            "kind": self.kind,
            "status": self.status,
            "subject_aircraft_ids": list(self.subject_aircraft_ids),
            "source_assessment_id": self.source_assessment_id,
            "opened_at_utc": self.opened_at_utc,
            "updated_at_utc": self.updated_at_utc,
            "score": self.score,
            "severity": self.severity,
            "reason_codes": list(self.reason_codes),
            "conflict_id": self.conflict_id,
            "tcpa_seconds": self.tcpa_seconds,
            "horizontal_separation_ratio": self.horizontal_separation_ratio,
            "vertical_separation_ratio": self.vertical_separation_ratio,
        }


@dataclass(frozen=True, slots=True)
class OperationalPriorityExceptionReadModel:
    """Presentation-safe view of one Operational Priority exception."""

    exception_id: str
    kind: str
    status: str
    subject_aircraft_ids: tuple[str]
    source_assessment_id: str
    opened_at_utc: str
    updated_at_utc: str
    score: float
    severity: str
    reason_codes: tuple[str, ...]
    source_event_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        """Return only JSON-compatible primitives."""

        return {
            "exception_id": self.exception_id,
            "kind": self.kind,
            "status": self.status,
            "subject_aircraft_ids": list(self.subject_aircraft_ids),
            "source_assessment_id": self.source_assessment_id,
            "opened_at_utc": self.opened_at_utc,
            "updated_at_utc": self.updated_at_utc,
            "score": self.score,
            "severity": self.severity,
            "reason_codes": list(self.reason_codes),
            "source_event_ids": list(self.source_event_ids),
        }


type ExceptionItemReadModel = ConflictExceptionReadModel | OperationalPriorityExceptionReadModel


@dataclass(frozen=True, slots=True)
class ExceptionQueueSnapshotReadModel:
    """Ordered Queue response DTO independent from mutable service state."""

    queue_snapshot_id: str
    generated_at_utc: str
    policy_profile_id: str
    items: tuple[ExceptionItemReadModel, ...]
    active_count: int
    top_exception_id: str | None

    def to_dict(self) -> dict[str, object]:
        """Return a stable JSON-ready response object."""

        return {
            "queue_snapshot_id": self.queue_snapshot_id,
            "generated_at_utc": self.generated_at_utc,
            "policy_profile_id": self.policy_profile_id,
            "active_count": self.active_count,
            "top_exception_id": self.top_exception_id,
            "items": [item.to_dict() for item in self.items],
        }


@dataclass(frozen=True, slots=True)
class AcknowledgeExceptionRequest:
    """Validated command body for an operator acknowledgement."""

    exception_id: str
    acknowledged_at_utc: datetime

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "exception_id",
            require_identifier(self.exception_id, field_name="exception_id"),
        )
        object.__setattr__(
            self,
            "acknowledged_at_utc",
            to_utc(self.acknowledged_at_utc, field_name="acknowledged_at_utc"),
        )


class ExceptionQueueReadModelMapper:
    """Map immutable Domain snapshots without leaking Domain objects to clients."""

    @staticmethod
    def map(
        snapshot: ExceptionQueueSnapshot,
        *,
        include_resolved: bool = False,
    ) -> ExceptionQueueSnapshotReadModel:
        if not isinstance(snapshot, ExceptionQueueSnapshot):
            raise TypeError("snapshot must be an ExceptionQueueSnapshot")
        include_resolved = _require_include_resolved(include_resolved)
        selected = (
            snapshot.items
            if include_resolved
            else tuple(
                item for item in snapshot.items if item.status is not ExceptionStatus.RESOLVED
            )
        )
        items = tuple(_map_item(item) for item in selected)
        active_count = len(snapshot.active_items)
        top_exception_id = snapshot.top_item.exception_id if snapshot.top_item is not None else None
        return ExceptionQueueSnapshotReadModel(
            queue_snapshot_id=snapshot.queue_snapshot_id,
            generated_at_utc=_utc_text(snapshot.generated_at_utc),
            policy_profile_id=snapshot.policy_profile_id,
            items=items,
            active_count=active_count,
            top_exception_id=top_exception_id,
        )


@runtime_checkable
class ExceptionQueueApiContract(Protocol):
    """Synchronous driving API implemented later by HTTP or desktop adapters."""

    def get_current(
        self,
        *,
        include_resolved: bool = False,
    ) -> ExceptionQueueSnapshotReadModel | None: ...

    def acknowledge(
        self,
        request: AcknowledgeExceptionRequest,
        *,
        include_resolved: bool = False,
    ) -> ExceptionQueueSnapshotReadModel: ...


class InProcessExceptionQueueApi:
    """Minimal adapter used by tests and a later web/desktop presentation layer."""

    __slots__ = ("_service",)

    def __init__(self, service: ExceptionQueueService) -> None:
        if not isinstance(service, ExceptionQueueService):
            raise TypeError("service must be an ExceptionQueueService")
        self._service = service

    def get_current(
        self,
        *,
        include_resolved: bool = False,
    ) -> ExceptionQueueSnapshotReadModel | None:
        include_resolved = _require_include_resolved(include_resolved)
        snapshot = self._service.last_snapshot
        if snapshot is None:
            return None
        return ExceptionQueueReadModelMapper.map(
            snapshot,
            include_resolved=include_resolved,
        )

    def acknowledge(
        self,
        request: AcknowledgeExceptionRequest,
        *,
        include_resolved: bool = False,
    ) -> ExceptionQueueSnapshotReadModel:
        if not isinstance(request, AcknowledgeExceptionRequest):
            raise TypeError("request must be an AcknowledgeExceptionRequest")
        include_resolved = _require_include_resolved(include_resolved)
        snapshot = self._service.acknowledge(
            request.exception_id,
            request.acknowledged_at_utc,
        )
        return ExceptionQueueReadModelMapper.map(
            snapshot,
            include_resolved=include_resolved,
        )


def _map_item(item: ConflictExceptionItem | OperationalPriorityExceptionItem):
    common = {
        "exception_id": item.exception_id,
        "kind": item.kind.value,
        "status": item.status.value,
        "subject_aircraft_ids": item.subject_aircraft_ids,
        "source_assessment_id": item.source_assessment_id,
        "opened_at_utc": _utc_text(item.opened_at_utc),
        "updated_at_utc": _utc_text(item.updated_at_utc),
        "score": item.score,
    }
    if isinstance(item, ConflictExceptionItem):
        assessment = item.assessment
        return ConflictExceptionReadModel(
            **common,
            severity=assessment.risk_level.value,
            reason_codes=tuple(code.value for code in assessment.reason_codes),
            conflict_id=assessment.conflict_id,
            tcpa_seconds=assessment.tcpa_seconds,
            horizontal_separation_ratio=assessment.horizontal_separation_ratio,
            vertical_separation_ratio=assessment.vertical_separation_ratio,
        )
    assessment = item.assessment
    return OperationalPriorityExceptionReadModel(
        **common,
        severity=assessment.priority_level.value,
        reason_codes=tuple(code.value for code in assessment.reason_codes),
        source_event_ids=assessment.source_event_ids,
    )
