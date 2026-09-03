"""Source-labelled deterministic Recommendation ranking inputs."""

from dataclasses import dataclass

from sentry_atm.domain.validation import require_identifier


@dataclass(frozen=True, slots=True)
class RecommendationRankingProfile:
    """Versioned ranking policy with an explicit display limit."""

    profile_id: str
    max_recommendations: int
    source_reference: str

    def __post_init__(self) -> None:
        for field_name in ("profile_id", "source_reference"):
            object.__setattr__(
                self,
                field_name,
                require_identifier(getattr(self, field_name), field_name=field_name),
            )
        if isinstance(self.max_recommendations, bool) or not isinstance(
            self.max_recommendations,
            int,
        ):
            raise TypeError("max_recommendations must be an integer")
        if self.max_recommendations < 1:
            raise ValueError("max_recommendations must be at least 1")


POC_RECOMMENDATION_V1_RANKING_PROFILE = RecommendationRankingProfile(
    profile_id="POC_RECOMMENDATION_V1",
    max_recommendations=3,
    source_reference="ASM-027 ASM-038 POC RANKING POLICY",
)
