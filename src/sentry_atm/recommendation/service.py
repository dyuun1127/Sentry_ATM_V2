"""Deterministic ranking of validated Resolution Candidates."""

from datetime import datetime

from sentry_atm.domain import (
    AltitudeManeuver,
    EntryDelayManeuver,
    HeadingManeuver,
    NoActionManeuver,
    RecommendationAvailability,
    RecommendationReasonCode,
    ResolutionCandidate,
    ResolutionCandidateBatch,
    ResolutionRecommendation,
    ResolutionRecommendationSet,
    ResolutionSafetyValidationRun,
    SequenceChangeManeuver,
    SpeedManeuver,
)
from sentry_atm.domain.time_policy import to_utc
from sentry_atm.recommendation.profile import (
    POC_RECOMMENDATION_V1_RANKING_PROFILE,
    RecommendationRankingProfile,
)

_POSITIVE_REASONS = tuple(RecommendationReasonCode)


class DeterministicRecommendationRankingService:
    """Select and rank SAFE action Candidates without changing Runtime state."""

    __slots__ = ("_profile",)

    def __init__(
        self,
        profile: RecommendationRankingProfile = POC_RECOMMENDATION_V1_RANKING_PROFILE,
    ) -> None:
        if not isinstance(profile, RecommendationRankingProfile):
            raise TypeError("profile must be a RecommendationRankingProfile")
        self._profile = profile

    @property
    def profile(self) -> RecommendationRankingProfile:
        return self._profile

    def recommend(
        self,
        candidate_batch: ResolutionCandidateBatch,
        validation_run: ResolutionSafetyValidationRun,
        *,
        generated_at_utc: datetime,
    ) -> ResolutionRecommendationSet:
        """Return cost-ranked SAFE options tied to one complete validation run."""

        if not isinstance(candidate_batch, ResolutionCandidateBatch):
            raise TypeError("candidate_batch must be a ResolutionCandidateBatch")
        if not isinstance(validation_run, ResolutionSafetyValidationRun):
            raise TypeError("validation_run must be a ResolutionSafetyValidationRun")
        generated_at = to_utc(generated_at_utc, field_name="generated_at_utc")
        self._validate_sources(candidate_batch, validation_run, generated_at)

        candidate_by_id = {
            candidate.candidate_id: candidate for candidate in candidate_batch.candidates
        }
        validation_by_id = {result.candidate_id: result for result in validation_run.results}
        safe_candidates = tuple(
            candidate
            for candidate in candidate_batch.actionable_candidates
            if validation_by_id[candidate.candidate_id].is_safe
        )
        selected = tuple(sorted(safe_candidates, key=_ranking_key))[
            : self._profile.max_recommendations
        ]
        timestamp_token = generated_at.strftime("%Y%m%dT%H%M%S%fZ")
        recommendations = tuple(
            ResolutionRecommendation(
                recommendation_id=(
                    f"RECOMMENDATION-{self._profile.profile_id}-{timestamp_token}-"
                    f"{candidate.candidate_id}"
                ),
                rank=rank,
                candidate=candidate_by_id[candidate.candidate_id],
                validation_result=validation_by_id[candidate.candidate_id],
                generated_at_utc=generated_at,
                reason_codes=_POSITIVE_REASONS,
                explanation=_explanation(candidate),
            )
            for rank, candidate in enumerate(selected, start=1)
        )
        availability = (
            RecommendationAvailability.AVAILABLE
            if recommendations
            else RecommendationAvailability.NO_SAFE_CANDIDATE
        )
        return ResolutionRecommendationSet(
            recommendation_set_id=(
                f"RECOMMENDATION-SET-{self._profile.profile_id}-{timestamp_token}-"
                f"{candidate_batch.candidate_batch_id}"
            ),
            source_exception_id=candidate_batch.source_exception_id,
            source_candidate_batch_id=candidate_batch.candidate_batch_id,
            source_validation_run_id=validation_run.validation_run_id,
            generated_at_utc=generated_at,
            ranking_policy_id=self._profile.profile_id,
            availability=availability,
            recommendations=recommendations,
        )

    @staticmethod
    def _validate_sources(
        candidate_batch: ResolutionCandidateBatch,
        validation_run: ResolutionSafetyValidationRun,
        generated_at_utc: datetime,
    ) -> None:
        if validation_run.source_candidate_batch_id != candidate_batch.candidate_batch_id:
            raise ValueError("validation_run must reference candidate_batch")
        candidate_ids = {candidate.candidate_id for candidate in candidate_batch.candidates}
        validation_candidate_ids = {result.candidate_id for result in validation_run.results}
        if validation_candidate_ids != candidate_ids:
            raise ValueError("validation_run must contain every Candidate exactly once")
        if validation_run.evaluated_at_utc < candidate_batch.generated_at_utc:
            raise ValueError("Safety Validation cannot precede Candidate generation")
        if generated_at_utc < validation_run.evaluated_at_utc:
            raise ValueError("Recommendation generation cannot precede Safety Validation")


def _ranking_key(candidate: ResolutionCandidate) -> tuple[float, float, float, str]:
    cost = candidate.cost
    return (
        cost.operational_cost_score,
        cost.estimated_delay_seconds,
        cost.estimated_path_extension_nm,
        candidate.candidate_id,
    )


def _explanation(candidate: ResolutionCandidate) -> str:
    maneuver = candidate.maneuver
    if isinstance(maneuver, HeadingManeuver):
        action = f"set heading to {maneuver.target_heading_deg:.1f} deg"
    elif isinstance(maneuver, AltitudeManeuver):
        action = f"set altitude to {maneuver.target_altitude_ft:.1f} ft"
    elif isinstance(maneuver, SpeedManeuver):
        action = f"set ground speed to {maneuver.target_ground_speed_kt:.1f} kt"
    elif isinstance(maneuver, EntryDelayManeuver):
        action = f"delay entry by {maneuver.delay_seconds:.1f} s"
    elif isinstance(maneuver, SequenceChangeManeuver):
        action = f"set sequence position to {maneuver.target_sequence_position}"
    elif isinstance(maneuver, NoActionManeuver):  # defensive; actions are filtered above
        raise ValueError("NO_ACTION baseline cannot be explained as a recommendation")
    else:  # pragma: no cover - ResolutionCandidate rejects unsupported maneuvers
        raise TypeError("unsupported Resolution Maneuver")
    cost = candidate.cost
    return (
        f"Validated safe: {action}; primary conflict resolved, no secondary conflict, "
        f"performance feasible, no rule violation. Cost score {cost.operational_cost_score:.1f}, "
        f"delay {cost.estimated_delay_seconds:.1f} s, path extension "
        f"{cost.estimated_path_extension_nm:.1f} NM."
    )
