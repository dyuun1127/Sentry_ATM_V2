"""JSON-ready Recommendation views and a transport-neutral read API."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from sentry_atm.domain import (
    AltitudeManeuver,
    ConflictEvent,
    EntryDelayManeuver,
    HeadingManeuver,
    ResolutionCandidate,
    ResolutionRecommendation,
    ResolutionRecommendationSet,
    SequenceChangeManeuver,
    SpeedManeuver,
)
from sentry_atm.domain.time_policy import to_utc


def _utc_text(value: datetime) -> str:
    return to_utc(value).isoformat(timespec="microseconds").replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class RecommendationManeuverReadModel:
    """Stable schema for every supported action Maneuver."""

    maneuver_type: str
    target_heading_deg: float | None = None
    target_altitude_ft: float | None = None
    target_ground_speed_kt: float | None = None
    delay_seconds: float | None = None
    target_sequence_position: int | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "maneuver_type": self.maneuver_type,
            "target_heading_deg": self.target_heading_deg,
            "target_altitude_ft": self.target_altitude_ft,
            "target_ground_speed_kt": self.target_ground_speed_kt,
            "delay_seconds": self.delay_seconds,
            "target_sequence_position": self.target_sequence_position,
        }


@dataclass(frozen=True, slots=True)
class RecommendationCostReadModel:
    """JSON-ready Candidate Cost fields in project units."""

    estimated_delay_seconds: float
    estimated_path_extension_nm: float
    operational_cost_score: float

    def to_dict(self) -> dict[str, object]:
        return {
            "estimated_delay_seconds": self.estimated_delay_seconds,
            "estimated_path_extension_nm": self.estimated_path_extension_nm,
            "operational_cost_score": self.operational_cost_score,
        }


@dataclass(frozen=True, slots=True)
class RecommendationConflictEvidenceReadModel:
    """Presentation-safe post-Candidate Conflict assessment evidence."""

    conflict_id: str
    aircraft_ids: tuple[str, str]
    status: str
    evaluated_at_utc: str
    closest_approach_time_utc: str
    tcpa_seconds: float
    horizontal_separation_nm: float
    vertical_separation_ft: float
    rule_profile_id: str

    def to_dict(self) -> dict[str, object]:
        return {
            "conflict_id": self.conflict_id,
            "aircraft_ids": list(self.aircraft_ids),
            "status": self.status,
            "evaluated_at_utc": self.evaluated_at_utc,
            "closest_approach_time_utc": self.closest_approach_time_utc,
            "tcpa_seconds": self.tcpa_seconds,
            "horizontal_separation_nm": self.horizontal_separation_nm,
            "vertical_separation_ft": self.vertical_separation_ft,
            "rule_profile_id": self.rule_profile_id,
        }


@dataclass(frozen=True, slots=True)
class RecommendationSafetyReadModel:
    """Safety evidence retained for one recommended Candidate."""

    validation_result_id: str
    verdict: str
    evaluated_at_utc: str
    validation_profile_id: str
    primary_conflict: RecommendationConflictEvidenceReadModel
    secondary_conflicts: tuple[RecommendationConflictEvidenceReadModel, ...]
    performance_feasible: bool
    rule_violation_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "validation_result_id": self.validation_result_id,
            "verdict": self.verdict,
            "evaluated_at_utc": self.evaluated_at_utc,
            "validation_profile_id": self.validation_profile_id,
            "primary_conflict": self.primary_conflict.to_dict(),
            "secondary_conflicts": [item.to_dict() for item in self.secondary_conflicts],
            "performance_feasible": self.performance_feasible,
            "rule_violation_ids": list(self.rule_violation_ids),
            "reason_codes": list(self.reason_codes),
        }


@dataclass(frozen=True, slots=True)
class ResolutionRecommendationReadModel:
    """One ranked recommendation item for a controller-facing UI."""

    recommendation_id: str
    rank: int
    candidate_id: str
    target_aircraft_id: str
    objective: str
    effective_from_utc: str
    maneuver: RecommendationManeuverReadModel
    cost: RecommendationCostReadModel
    safety: RecommendationSafetyReadModel
    reason_codes: tuple[str, ...]
    explanation: str

    def to_dict(self) -> dict[str, object]:
        return {
            "recommendation_id": self.recommendation_id,
            "rank": self.rank,
            "candidate_id": self.candidate_id,
            "target_aircraft_id": self.target_aircraft_id,
            "objective": self.objective,
            "effective_from_utc": self.effective_from_utc,
            "maneuver": self.maneuver.to_dict(),
            "cost": self.cost.to_dict(),
            "safety": self.safety.to_dict(),
            "reason_codes": list(self.reason_codes),
            "explanation": self.explanation,
        }


@dataclass(frozen=True, slots=True)
class ResolutionRecommendationSetReadModel:
    """JSON-ready result for one deterministic Recommendation run."""

    recommendation_set_id: str
    source_exception_id: str
    source_candidate_batch_id: str
    source_validation_run_id: str
    generated_at_utc: str
    ranking_policy_id: str
    availability: str
    primary_recommendation_id: str | None
    recommendations: tuple[ResolutionRecommendationReadModel, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "recommendation_set_id": self.recommendation_set_id,
            "source_exception_id": self.source_exception_id,
            "source_candidate_batch_id": self.source_candidate_batch_id,
            "source_validation_run_id": self.source_validation_run_id,
            "generated_at_utc": self.generated_at_utc,
            "ranking_policy_id": self.ranking_policy_id,
            "availability": self.availability,
            "primary_recommendation_id": self.primary_recommendation_id,
            "recommendations": [item.to_dict() for item in self.recommendations],
        }


class RecommendationReadModelMapper:
    """Map immutable Recommendation Domain results to JSON-compatible DTOs."""

    @staticmethod
    def map(
        recommendation_set: ResolutionRecommendationSet,
    ) -> ResolutionRecommendationSetReadModel:
        if not isinstance(recommendation_set, ResolutionRecommendationSet):
            raise TypeError("recommendation_set must be a ResolutionRecommendationSet")
        recommendations = tuple(
            _map_recommendation(item) for item in recommendation_set.recommendations
        )
        primary = recommendation_set.primary_recommendation
        return ResolutionRecommendationSetReadModel(
            recommendation_set_id=recommendation_set.recommendation_set_id,
            source_exception_id=recommendation_set.source_exception_id,
            source_candidate_batch_id=recommendation_set.source_candidate_batch_id,
            source_validation_run_id=recommendation_set.source_validation_run_id,
            generated_at_utc=_utc_text(recommendation_set.generated_at_utc),
            ranking_policy_id=recommendation_set.ranking_policy_id,
            availability=recommendation_set.availability.value,
            primary_recommendation_id=(primary.recommendation_id if primary is not None else None),
            recommendations=recommendations,
        )


@runtime_checkable
class RecommendationSetSource(Protocol):
    """Application-owned source for the latest Domain Recommendation Set."""

    def get_current_recommendation(self) -> ResolutionRecommendationSet | None: ...


@runtime_checkable
class RecommendationApiContract(Protocol):
    """Synchronous read API implemented later by HTTP or desktop adapters."""

    def get_current(self) -> ResolutionRecommendationSetReadModel | None: ...


class InProcessRecommendationApi:
    """Read the current Domain result without owning its lifecycle."""

    __slots__ = ("_source",)

    def __init__(self, source: RecommendationSetSource) -> None:
        if not isinstance(source, RecommendationSetSource):
            raise TypeError("source must implement RecommendationSetSource")
        self._source = source

    def get_current(self) -> ResolutionRecommendationSetReadModel | None:
        current = self._source.get_current_recommendation()
        if current is None:
            return None
        if not isinstance(current, ResolutionRecommendationSet):
            raise TypeError("RecommendationSetSource returned an unsupported value")
        return RecommendationReadModelMapper.map(current)


def _map_recommendation(
    recommendation: ResolutionRecommendation,
) -> ResolutionRecommendationReadModel:
    candidate = recommendation.candidate
    validation = recommendation.validation_result
    return ResolutionRecommendationReadModel(
        recommendation_id=recommendation.recommendation_id,
        rank=recommendation.rank,
        candidate_id=candidate.candidate_id,
        target_aircraft_id=candidate.target_aircraft_id,
        objective=candidate.objective.value,
        effective_from_utc=_utc_text(candidate.effective_from_utc),
        maneuver=_map_maneuver(candidate),
        cost=RecommendationCostReadModel(
            estimated_delay_seconds=candidate.cost.estimated_delay_seconds,
            estimated_path_extension_nm=candidate.cost.estimated_path_extension_nm,
            operational_cost_score=candidate.cost.operational_cost_score,
        ),
        safety=RecommendationSafetyReadModel(
            validation_result_id=validation.validation_result_id,
            verdict=validation.verdict.value,
            evaluated_at_utc=_utc_text(validation.evaluated_at_utc),
            validation_profile_id=validation.validation_profile_id,
            primary_conflict=_map_conflict(validation.primary_conflict),
            secondary_conflicts=tuple(
                _map_conflict(item) for item in validation.secondary_conflicts
            ),
            performance_feasible=validation.performance_feasible,
            rule_violation_ids=tuple(item.violation_id for item in validation.rule_violations),
            reason_codes=tuple(item.value for item in validation.reason_codes),
        ),
        reason_codes=tuple(item.value for item in recommendation.reason_codes),
        explanation=recommendation.explanation,
    )


def _map_conflict(event: ConflictEvent) -> RecommendationConflictEvidenceReadModel:
    return RecommendationConflictEvidenceReadModel(
        conflict_id=event.conflict_id,
        aircraft_ids=event.pair.aircraft_ids,
        status=event.status.value,
        evaluated_at_utc=_utc_text(event.evaluated_at_utc),
        closest_approach_time_utc=_utc_text(event.closest_approach_time_utc),
        tcpa_seconds=event.tcpa_seconds,
        horizontal_separation_nm=event.minimum_separation.horizontal_nm,
        vertical_separation_ft=event.minimum_separation.vertical_ft,
        rule_profile_id=event.rule_profile_id,
    )


def _map_maneuver(candidate: ResolutionCandidate) -> RecommendationManeuverReadModel:
    maneuver = candidate.maneuver
    if isinstance(maneuver, HeadingManeuver):
        return RecommendationManeuverReadModel(
            maneuver_type=maneuver.maneuver_type.value,
            target_heading_deg=maneuver.target_heading_deg,
        )
    if isinstance(maneuver, AltitudeManeuver):
        return RecommendationManeuverReadModel(
            maneuver_type=maneuver.maneuver_type.value,
            target_altitude_ft=maneuver.target_altitude_ft,
        )
    if isinstance(maneuver, SpeedManeuver):
        return RecommendationManeuverReadModel(
            maneuver_type=maneuver.maneuver_type.value,
            target_ground_speed_kt=maneuver.target_ground_speed_kt,
        )
    if isinstance(maneuver, EntryDelayManeuver):
        return RecommendationManeuverReadModel(
            maneuver_type=maneuver.maneuver_type.value,
            delay_seconds=maneuver.delay_seconds,
        )
    if isinstance(maneuver, SequenceChangeManeuver):
        return RecommendationManeuverReadModel(
            maneuver_type=maneuver.maneuver_type.value,
            target_sequence_position=maneuver.target_sequence_position,
        )
    raise TypeError(  # pragma: no cover - ResolutionCandidate validates the union
        "recommendation contains an unsupported Maneuver"
    )
