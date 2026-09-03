"""Immutable audit contracts for controller Recommendation decisions."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from sentry_atm.domain.enums import ControllerDecisionType
from sentry_atm.domain.recommendation import ResolutionRecommendation
from sentry_atm.domain.resolution import (
    AltitudeManeuver,
    EntryDelayManeuver,
    HeadingManeuver,
    ResolutionCandidate,
    ResolutionManeuver,
    SequenceChangeManeuver,
    SpeedManeuver,
)
from sentry_atm.domain.time_policy import to_utc
from sentry_atm.domain.validation import require_identifier

_SUPPORTED_ACTION_MANEUVERS = (
    HeadingManeuver,
    AltitudeManeuver,
    SpeedManeuver,
    EntryDelayManeuver,
    SequenceChangeManeuver,
)


@dataclass(frozen=True, slots=True)
class ControllerDecisionAuditEntry:
    """One controller response that does not itself mutate Aircraft Runtime."""

    decision_id: str
    recommendation_set_id: str
    recommendation: ResolutionRecommendation
    decision_type: ControllerDecisionType
    decided_at_utc: datetime
    controller_position_id: str
    rationale: str | None = None
    modified_maneuver: ResolutionManeuver | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "decision_id",
            "recommendation_set_id",
            "controller_position_id",
        ):
            object.__setattr__(
                self,
                field_name,
                require_identifier(getattr(self, field_name), field_name=field_name),
            )
        if not isinstance(self.recommendation, ResolutionRecommendation):
            raise TypeError("recommendation must be a ResolutionRecommendation")
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
        if self.decided_at_utc < self.recommendation.generated_at_utc:
            raise ValueError("controller decision cannot precede Recommendation generation")
        rationale = self.rationale
        if rationale is not None:
            rationale = require_identifier(rationale, field_name="rationale")
            object.__setattr__(self, "rationale", rationale)

        if self.decision_type is ControllerDecisionType.MODIFY:
            if rationale is None:
                raise ValueError("MODIFY decision requires a rationale")
            if not isinstance(self.modified_maneuver, _SUPPORTED_ACTION_MANEUVERS):
                raise TypeError("MODIFY decision requires a supported action Maneuver")
            if self.modified_maneuver == self.recommendation.candidate.maneuver:
                raise ValueError("MODIFY decision must change the recommended Maneuver")
        else:
            if self.modified_maneuver is not None:
                raise ValueError("only MODIFY decision can contain a modified Maneuver")
            if self.decision_type is ControllerDecisionType.REJECT and rationale is None:
                raise ValueError("REJECT decision requires a rationale")

    @property
    def recommendation_id(self) -> str:
        return self.recommendation.recommendation_id

    @property
    def candidate_id(self) -> str:
        return self.recommendation.candidate_id

    @property
    def authorizes_application(self) -> bool:
        return self.decision_type is ControllerDecisionType.ACCEPT

    @property
    def requires_revalidation(self) -> bool:
        return self.decision_type is ControllerDecisionType.MODIFY

    @property
    def approved_candidate(self) -> ResolutionCandidate | None:
        return self.recommendation.candidate if self.authorizes_application else None


@dataclass(frozen=True, slots=True)
class ControllerDecisionAuditLog:
    """Immutable, deterministically ordered snapshot of controller decisions."""

    audit_log_id: str
    revision: int
    generated_at_utc: datetime
    entries: tuple[ControllerDecisionAuditEntry, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "audit_log_id",
            require_identifier(self.audit_log_id, field_name="audit_log_id"),
        )
        if isinstance(self.revision, bool) or not isinstance(self.revision, int):
            raise TypeError("revision must be an integer")
        if self.revision < 1:
            raise ValueError("revision must be at least 1")
        object.__setattr__(
            self,
            "generated_at_utc",
            to_utc(self.generated_at_utc, field_name="generated_at_utc"),
        )
        entries = _materialize_entries(self.entries)
        for field_name, values in (
            ("decision IDs", tuple(item.decision_id for item in entries)),
            (
                "Recommendation Set IDs",
                tuple(item.recommendation_set_id for item in entries),
            ),
            ("Recommendation IDs", tuple(item.recommendation_id for item in entries)),
        ):
            if len(set(values)) != len(values):
                raise ValueError(f"{field_name} must be unique")
        if any(item.decided_at_utc > self.generated_at_utc for item in entries):
            raise ValueError("Audit Log generation cannot precede a controller decision")
        object.__setattr__(
            self,
            "entries",
            tuple(sorted(entries, key=lambda item: (item.decided_at_utc, item.decision_id))),
        )

    @property
    def latest_entry(self) -> ControllerDecisionAuditEntry | None:
        return self.entries[-1] if self.entries else None

    @property
    def accepted_entries(self) -> tuple[ControllerDecisionAuditEntry, ...]:
        return self._by_type(ControllerDecisionType.ACCEPT)

    @property
    def modified_entries(self) -> tuple[ControllerDecisionAuditEntry, ...]:
        return self._by_type(ControllerDecisionType.MODIFY)

    @property
    def rejected_entries(self) -> tuple[ControllerDecisionAuditEntry, ...]:
        return self._by_type(ControllerDecisionType.REJECT)

    def _by_type(
        self,
        decision_type: ControllerDecisionType,
    ) -> tuple[ControllerDecisionAuditEntry, ...]:
        return tuple(item for item in self.entries if item.decision_type is decision_type)


def _materialize_entries(
    values: Iterable[ControllerDecisionAuditEntry],
) -> tuple[ControllerDecisionAuditEntry, ...]:
    if isinstance(values, (str, bytes)):
        raise TypeError("entries must be an iterable of ControllerDecisionAuditEntry")
    try:
        materialized = tuple(values)
    except TypeError:
        raise TypeError("entries must be an iterable of ControllerDecisionAuditEntry") from None
    if not all(isinstance(value, ControllerDecisionAuditEntry) for value in materialized):
        raise TypeError("entries must contain ControllerDecisionAuditEntry values")
    return materialized
