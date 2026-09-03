"""Injectable, source-labelled Candidate generation inputs."""

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from numbers import Real

from sentry_atm.domain import (
    CandidateCostEstimate,
    ResolutionManeuverType,
)
from sentry_atm.domain.units import as_non_negative_float
from sentry_atm.domain.validation import require_identifier


def _as_positive_float(value: Real, *, field_name: str) -> float:
    normalized = as_non_negative_float(value, field_name=field_name)
    if normalized == 0.0:
        raise ValueError(f"{field_name} must be greater than zero")
    return normalized


class CandidateTargetRole(StrEnum):
    """Select one of the two Conflict Pair members without Callsign rules."""

    PREFERRED = "PREFERRED"
    OTHER = "OTHER"


@dataclass(frozen=True, slots=True)
class ResolutionCandidateTemplate:
    """One ordered action slot in a generation profile."""

    candidate_id: str
    target_role: CandidateTargetRole
    maneuver_type: ResolutionManeuverType
    cost: CandidateCostEstimate = CandidateCostEstimate()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "candidate_id",
            require_identifier(self.candidate_id, field_name="candidate_id"),
        )
        object.__setattr__(self, "target_role", CandidateTargetRole(self.target_role))
        object.__setattr__(
            self,
            "maneuver_type",
            ResolutionManeuverType(self.maneuver_type),
        )
        if self.maneuver_type is ResolutionManeuverType.NO_ACTION:
            raise ValueError("NO_ACTION is added separately as the Batch baseline")
        if not isinstance(self.cost, CandidateCostEstimate):
            raise TypeError("cost must be a CandidateCostEstimate")


@dataclass(frozen=True, slots=True)
class ResolutionCandidateGenerationProfile:
    """Deterministic template and magnitude inputs for a Candidate Generator."""

    profile_id: str
    heading_change_deg: float
    altitude_change_ft: float
    speed_change_kt: float
    entry_delay_seconds: float
    target_sequence_position: int
    templates: tuple[ResolutionCandidateTemplate, ...]
    baseline_candidate_id: str
    source_reference: str

    def __post_init__(self) -> None:
        for field_name in ("profile_id", "baseline_candidate_id", "source_reference"):
            object.__setattr__(
                self,
                field_name,
                require_identifier(getattr(self, field_name), field_name=field_name),
            )
        for field_name in (
            "heading_change_deg",
            "altitude_change_ft",
            "speed_change_kt",
            "entry_delay_seconds",
        ):
            object.__setattr__(
                self,
                field_name,
                _as_positive_float(getattr(self, field_name), field_name=field_name),
            )
        if self.heading_change_deg >= 180.0:
            raise ValueError("heading_change_deg must be less than 180")
        if isinstance(self.target_sequence_position, bool) or not isinstance(
            self.target_sequence_position,
            int,
        ):
            raise TypeError("target_sequence_position must be an integer")
        if self.target_sequence_position < 1:
            raise ValueError("target_sequence_position must be at least 1")

        templates = _materialize_templates(self.templates)
        if not templates:
            raise ValueError("templates must not be empty")
        candidate_ids = tuple(template.candidate_id for template in templates)
        if len(set(candidate_ids)) != len(candidate_ids):
            raise ValueError("template candidate IDs must be unique")
        if self.baseline_candidate_id in candidate_ids:
            raise ValueError("baseline candidate ID must be unique")
        template_keys = tuple(
            (template.target_role, template.maneuver_type) for template in templates
        )
        if len(set(template_keys)) != len(template_keys):
            raise ValueError("template target role and maneuver pairs must be unique")
        object.__setattr__(self, "templates", templates)


def _materialize_templates(
    values: Iterable[ResolutionCandidateTemplate],
) -> tuple[ResolutionCandidateTemplate, ...]:
    if isinstance(values, (str, bytes)):
        raise TypeError("templates must be an iterable of ResolutionCandidateTemplate instances")
    try:
        materialized = tuple(values)
    except TypeError:
        raise TypeError(
            "templates must be an iterable of ResolutionCandidateTemplate instances"
        ) from None
    if not all(isinstance(value, ResolutionCandidateTemplate) for value in materialized):
        raise TypeError("templates must contain only ResolutionCandidateTemplate instances")
    return materialized


POC_RESOLUTION_V1_GENERATION_PROFILE = ResolutionCandidateGenerationProfile(
    profile_id="POC_RESOLUTION_V1",
    heading_change_deg=20.0,
    altitude_change_ft=1_000.0,
    speed_change_kt=30.0,
    entry_delay_seconds=30.0,
    target_sequence_position=1,
    templates=(
        ResolutionCandidateTemplate(
            candidate_id="CAND-A",
            target_role=CandidateTargetRole.PREFERRED,
            maneuver_type=ResolutionManeuverType.ALTITUDE,
            cost=CandidateCostEstimate(operational_cost_score=10.0),
        ),
        ResolutionCandidateTemplate(
            candidate_id="CAND-B",
            target_role=CandidateTargetRole.PREFERRED,
            maneuver_type=ResolutionManeuverType.HEADING,
            cost=CandidateCostEstimate(
                estimated_path_extension_nm=1.5,
                operational_cost_score=25.0,
            ),
        ),
        ResolutionCandidateTemplate(
            candidate_id="CAND-C",
            target_role=CandidateTargetRole.OTHER,
            maneuver_type=ResolutionManeuverType.SPEED,
            cost=CandidateCostEstimate(
                estimated_delay_seconds=30.0,
                operational_cost_score=20.0,
            ),
        ),
        ResolutionCandidateTemplate(
            candidate_id="CAND-D",
            target_role=CandidateTargetRole.OTHER,
            maneuver_type=ResolutionManeuverType.ALTITUDE,
            cost=CandidateCostEstimate(operational_cost_score=30.0),
        ),
    ),
    baseline_candidate_id="CAND-E",
    source_reference="ASM-027 POC GENERATION INPUTS",
)
