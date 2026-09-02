"""Stateful deterministic assembly of Controller Decision audit snapshots."""

from datetime import datetime

from sentry_atm.domain import (
    ControllerDecisionAuditEntry,
    ControllerDecisionAuditLog,
    ControllerDecisionType,
    ResolutionManeuver,
    ResolutionRecommendationSet,
)
from sentry_atm.domain.time_policy import to_utc
from sentry_atm.domain.validation import require_identifier


class DeterministicControllerDecisionService:
    """Record one final controller Decision per Recommendation Set without applying it."""

    __slots__ = ("_entries_by_set", "_last_audit_log", "_revision")

    def __init__(self) -> None:
        self._entries_by_set: dict[str, ControllerDecisionAuditEntry] = {}
        self._last_audit_log: ControllerDecisionAuditLog | None = None
        self._revision = 0

    @property
    def revision(self) -> int:
        return self._revision

    @property
    def current_entries(self) -> tuple[ControllerDecisionAuditEntry, ...]:
        if self._last_audit_log is None:
            return ()
        return self._last_audit_log.entries

    @property
    def last_audit_log(self) -> ControllerDecisionAuditLog | None:
        return self._last_audit_log

    def decide(
        self,
        recommendation_set: ResolutionRecommendationSet,
        recommendation_id: str,
        decision_type: ControllerDecisionType,
        *,
        decided_at_utc: datetime,
        controller_position_id: str,
        rationale: str | None = None,
        modified_maneuver: ResolutionManeuver | None = None,
    ) -> ControllerDecisionAuditLog:
        """Append one audited final Decision and publish a new immutable Log revision."""

        if not isinstance(recommendation_set, ResolutionRecommendationSet):
            raise TypeError("recommendation_set must be a ResolutionRecommendationSet")
        normalized_recommendation_id = require_identifier(
            recommendation_id,
            field_name="recommendation_id",
        )
        decided_at = self._normalize_operation_time(decided_at_utc)
        set_id = recommendation_set.recommendation_set_id
        if set_id in self._entries_by_set:
            raise ValueError("Recommendation Set already has a final controller decision")

        recommendation_by_id = {
            item.recommendation_id: item for item in recommendation_set.recommendations
        }
        try:
            recommendation = recommendation_by_id[normalized_recommendation_id]
        except KeyError:
            raise KeyError(
                f"recommendation_id does not belong to Recommendation Set: "
                f"{normalized_recommendation_id!r}"
            ) from None

        revision = self._revision + 1
        timestamp_token = decided_at.strftime("%Y%m%dT%H%M%S%fZ")
        entry = ControllerDecisionAuditEntry(
            decision_id=(
                f"DECISION-{timestamp_token}-{revision:06d}-{set_id}-{normalized_recommendation_id}"
            ),
            recommendation_set_id=set_id,
            recommendation=recommendation,
            decision_type=decision_type,
            decided_at_utc=decided_at,
            controller_position_id=controller_position_id,
            rationale=rationale,
            modified_maneuver=modified_maneuver,
        )
        candidate_entries = (*self.current_entries, entry)
        audit_log = ControllerDecisionAuditLog(
            audit_log_id=f"CONTROLLER-AUDIT-{timestamp_token}-{revision:06d}",
            revision=revision,
            generated_at_utc=decided_at,
            entries=candidate_entries,
        )

        self._entries_by_set = {**self._entries_by_set, set_id: entry}
        self._last_audit_log = audit_log
        self._revision = revision
        return audit_log

    def reset(self) -> None:
        """Return the in-memory service to its deterministic initial state."""

        self._entries_by_set.clear()
        self._last_audit_log = None
        self._revision = 0

    def _normalize_operation_time(self, value: datetime) -> datetime:
        normalized = to_utc(value, field_name="decided_at_utc")
        if self._last_audit_log is not None and normalized < self._last_audit_log.generated_at_utc:
            raise ValueError("decision time must not precede the last Audit Log")
        return normalized
