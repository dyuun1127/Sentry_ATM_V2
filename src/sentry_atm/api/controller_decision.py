"""Transport-neutral Controller Decision command and JSON-ready response contracts."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from sentry_atm.controller_decision import DeterministicControllerDecisionService
from sentry_atm.domain import (
    AltitudeManeuver,
    ControllerDecisionAuditEntry,
    ControllerDecisionAuditLog,
    ControllerDecisionType,
    EntryDelayManeuver,
    HeadingManeuver,
    ResolutionManeuver,
    ResolutionManeuverType,
    ResolutionRecommendationSet,
    SequenceChangeManeuver,
    SpeedManeuver,
)
from sentry_atm.domain.time_policy import to_utc
from sentry_atm.domain.validation import require_identifier


def _utc_text(value: datetime) -> str:
    return to_utc(value).isoformat(timespec="microseconds").replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class ControllerDecisionManeuverModel:
    """Stable JSON-compatible schema for one modified action Maneuver."""

    maneuver_type: ResolutionManeuverType
    target_heading_deg: float | None = None
    target_altitude_ft: float | None = None
    target_ground_speed_kt: float | None = None
    delay_seconds: float | None = None
    target_sequence_position: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "maneuver_type",
            ResolutionManeuverType(self.maneuver_type),
        )
        maneuver = self.to_domain()
        field_name, value = _maneuver_field_and_value(maneuver)
        for candidate_field in _MANEUVER_FIELDS:
            object.__setattr__(
                self,
                candidate_field,
                value if candidate_field == field_name else None,
            )

    def to_domain(self) -> ResolutionManeuver:
        provided = {
            field_name: getattr(self, field_name)
            for field_name in _MANEUVER_FIELDS
            if getattr(self, field_name) is not None
        }
        expected_field = _FIELD_BY_MANEUVER_TYPE.get(self.maneuver_type)
        if expected_field is None:
            raise ValueError("modified Maneuver must be an action Maneuver")
        if set(provided) != {expected_field}:
            raise ValueError(f"{self.maneuver_type.value} requires only {expected_field}")
        value = provided[expected_field]
        if self.maneuver_type is ResolutionManeuverType.HEADING:
            return HeadingManeuver(value)  # type: ignore[arg-type]
        if self.maneuver_type is ResolutionManeuverType.ALTITUDE:
            return AltitudeManeuver(value)  # type: ignore[arg-type]
        if self.maneuver_type is ResolutionManeuverType.SPEED:
            return SpeedManeuver(value)  # type: ignore[arg-type]
        if self.maneuver_type is ResolutionManeuverType.ENTRY_DELAY:
            return EntryDelayManeuver(value)  # type: ignore[arg-type]
        return SequenceChangeManeuver(value)  # type: ignore[arg-type]

    def to_dict(self) -> dict[str, object]:
        return {
            "maneuver_type": self.maneuver_type.value,
            "target_heading_deg": self.target_heading_deg,
            "target_altitude_ft": self.target_altitude_ft,
            "target_ground_speed_kt": self.target_ground_speed_kt,
            "delay_seconds": self.delay_seconds,
            "target_sequence_position": self.target_sequence_position,
        }

    @classmethod
    def from_domain(cls, maneuver: ResolutionManeuver) -> "ControllerDecisionManeuverModel":
        field_name, value = _maneuver_field_and_value(maneuver)
        return cls(
            maneuver_type=maneuver.maneuver_type,
            **{field_name: value},
        )


_MANEUVER_FIELDS = (
    "target_heading_deg",
    "target_altitude_ft",
    "target_ground_speed_kt",
    "delay_seconds",
    "target_sequence_position",
)

_FIELD_BY_MANEUVER_TYPE = {
    ResolutionManeuverType.HEADING: "target_heading_deg",
    ResolutionManeuverType.ALTITUDE: "target_altitude_ft",
    ResolutionManeuverType.SPEED: "target_ground_speed_kt",
    ResolutionManeuverType.ENTRY_DELAY: "delay_seconds",
    ResolutionManeuverType.SEQUENCE_CHANGE: "target_sequence_position",
}


@dataclass(frozen=True, slots=True)
class SubmitControllerDecisionRequest:
    """Validated transport-neutral command for one final controller Decision."""

    recommendation_set_id: str
    recommendation_id: str
    decision_type: ControllerDecisionType
    decided_at_utc: datetime
    controller_position_id: str
    rationale: str | None = None
    modified_maneuver: ControllerDecisionManeuverModel | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "recommendation_set_id",
            "recommendation_id",
            "controller_position_id",
        ):
            object.__setattr__(
                self,
                field_name,
                require_identifier(getattr(self, field_name), field_name=field_name),
            )
        object.__setattr__(
            self,
            "decision_type",
            ControllerDecisionType(self.decision_type),
        )
        object.__setattr__(
            self,
            "decided_at_utc",
            to_utc(self.decided_at_utc, field_name="decided_at_utc"),
        )
        if self.rationale is not None:
            object.__setattr__(
                self,
                "rationale",
                require_identifier(self.rationale, field_name="rationale"),
            )
        if self.modified_maneuver is not None and not isinstance(
            self.modified_maneuver,
            ControllerDecisionManeuverModel,
        ):
            raise TypeError("modified_maneuver must be a ControllerDecisionManeuverModel")


@dataclass(frozen=True, slots=True)
class ControllerDecisionEntryReadModel:
    """JSON-ready audit evidence for one final Decision."""

    decision_id: str
    recommendation_set_id: str
    recommendation_id: str
    candidate_id: str
    decision_type: str
    decided_at_utc: str
    controller_position_id: str
    rationale: str | None
    modified_maneuver: ControllerDecisionManeuverModel | None
    authorizes_application: bool
    requires_revalidation: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "decision_id": self.decision_id,
            "recommendation_set_id": self.recommendation_set_id,
            "recommendation_id": self.recommendation_id,
            "candidate_id": self.candidate_id,
            "decision_type": self.decision_type,
            "decided_at_utc": self.decided_at_utc,
            "controller_position_id": self.controller_position_id,
            "rationale": self.rationale,
            "modified_maneuver": (
                self.modified_maneuver.to_dict() if self.modified_maneuver is not None else None
            ),
            "authorizes_application": self.authorizes_application,
            "requires_revalidation": self.requires_revalidation,
        }


@dataclass(frozen=True, slots=True)
class ControllerDecisionAuditLogReadModel:
    """JSON-ready immutable response for one Audit Log revision."""

    audit_log_id: str
    revision: int
    generated_at_utc: str
    latest_decision_id: str | None
    entries: tuple[ControllerDecisionEntryReadModel, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "audit_log_id": self.audit_log_id,
            "revision": self.revision,
            "generated_at_utc": self.generated_at_utc,
            "latest_decision_id": self.latest_decision_id,
            "entries": [entry.to_dict() for entry in self.entries],
        }


class ControllerDecisionReadModelMapper:
    """Map Domain Audit Logs without exposing Domain objects to clients."""

    @staticmethod
    def map(audit_log: ControllerDecisionAuditLog) -> ControllerDecisionAuditLogReadModel:
        if not isinstance(audit_log, ControllerDecisionAuditLog):
            raise TypeError("audit_log must be a ControllerDecisionAuditLog")
        entries = tuple(_map_entry(entry) for entry in audit_log.entries)
        latest = audit_log.latest_entry
        return ControllerDecisionAuditLogReadModel(
            audit_log_id=audit_log.audit_log_id,
            revision=audit_log.revision,
            generated_at_utc=_utc_text(audit_log.generated_at_utc),
            latest_decision_id=latest.decision_id if latest is not None else None,
            entries=entries,
        )


@runtime_checkable
class RecommendationSetLookup(Protocol):
    """Application-owned lookup for immutable Recommendation Sets."""

    def get_recommendation_set(
        self,
        recommendation_set_id: str,
    ) -> ResolutionRecommendationSet | None: ...


@runtime_checkable
class ControllerDecisionApiContract(Protocol):
    """Synchronous command/read API implemented later by an HTTP adapter."""

    def get_current(self) -> ControllerDecisionAuditLogReadModel | None: ...

    def submit(
        self,
        request: SubmitControllerDecisionRequest,
    ) -> ControllerDecisionAuditLogReadModel: ...


class InProcessControllerDecisionApi:
    """Resolve commands against Recommendation Sets and delegate to the Service."""

    __slots__ = ("_lookup", "_service")

    def __init__(
        self,
        service: DeterministicControllerDecisionService,
        lookup: RecommendationSetLookup,
    ) -> None:
        if not isinstance(service, DeterministicControllerDecisionService):
            raise TypeError("service must be a DeterministicControllerDecisionService")
        if not isinstance(lookup, RecommendationSetLookup):
            raise TypeError("lookup must implement RecommendationSetLookup")
        self._service = service
        self._lookup = lookup

    def get_current(self) -> ControllerDecisionAuditLogReadModel | None:
        current = self._service.last_audit_log
        if current is None:
            return None
        return ControllerDecisionReadModelMapper.map(current)

    def submit(
        self,
        request: SubmitControllerDecisionRequest,
    ) -> ControllerDecisionAuditLogReadModel:
        if not isinstance(request, SubmitControllerDecisionRequest):
            raise TypeError("request must be a SubmitControllerDecisionRequest")
        recommendation_set = self._lookup.get_recommendation_set(request.recommendation_set_id)
        if recommendation_set is None:
            raise KeyError(f"unknown recommendation_set_id: {request.recommendation_set_id!r}")
        if not isinstance(recommendation_set, ResolutionRecommendationSet):
            raise TypeError("RecommendationSetLookup returned an unsupported value")
        modified_maneuver = (
            request.modified_maneuver.to_domain() if request.modified_maneuver is not None else None
        )
        audit_log = self._service.decide(
            recommendation_set,
            request.recommendation_id,
            request.decision_type,
            decided_at_utc=request.decided_at_utc,
            controller_position_id=request.controller_position_id,
            rationale=request.rationale,
            modified_maneuver=modified_maneuver,
        )
        return ControllerDecisionReadModelMapper.map(audit_log)


def _map_entry(entry: ControllerDecisionAuditEntry) -> ControllerDecisionEntryReadModel:
    return ControllerDecisionEntryReadModel(
        decision_id=entry.decision_id,
        recommendation_set_id=entry.recommendation_set_id,
        recommendation_id=entry.recommendation_id,
        candidate_id=entry.candidate_id,
        decision_type=entry.decision_type.value,
        decided_at_utc=_utc_text(entry.decided_at_utc),
        controller_position_id=entry.controller_position_id,
        rationale=entry.rationale,
        modified_maneuver=(
            ControllerDecisionManeuverModel.from_domain(entry.modified_maneuver)
            if entry.modified_maneuver is not None
            else None
        ),
        authorizes_application=entry.authorizes_application,
        requires_revalidation=entry.requires_revalidation,
    )


def _maneuver_field_and_value(
    maneuver: ResolutionManeuver,
) -> tuple[str, float | int]:
    if isinstance(maneuver, HeadingManeuver):
        return "target_heading_deg", maneuver.target_heading_deg
    if isinstance(maneuver, AltitudeManeuver):
        return "target_altitude_ft", maneuver.target_altitude_ft
    if isinstance(maneuver, SpeedManeuver):
        return "target_ground_speed_kt", maneuver.target_ground_speed_kt
    if isinstance(maneuver, EntryDelayManeuver):
        return "delay_seconds", maneuver.delay_seconds
    if isinstance(maneuver, SequenceChangeManeuver):
        return "target_sequence_position", maneuver.target_sequence_position
    raise TypeError("modified Maneuver must be a supported action Maneuver")
