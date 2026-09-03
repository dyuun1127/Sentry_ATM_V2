"""Persistence-independent contracts for restricted Resolution Candidates."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from numbers import Real

from sentry_atm.domain.conflict import ConflictPair
from sentry_atm.domain.enums import ResolutionManeuverType, ResolutionObjective
from sentry_atm.domain.time_policy import to_utc
from sentry_atm.domain.units import (
    as_finite_float,
    as_heading_deg,
    as_non_negative_float,
)
from sentry_atm.domain.validation import require_identifier


def _as_positive_float(value: Real, *, field_name: str) -> float:
    normalized = as_non_negative_float(value, field_name=field_name)
    if normalized == 0.0:
        raise ValueError(f"{field_name} must be greater than zero")
    return normalized


@dataclass(frozen=True, slots=True)
class HeadingManeuver:
    """Command an absolute true heading in project heading units."""

    target_heading_deg: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "target_heading_deg",
            as_heading_deg(self.target_heading_deg),
        )

    @property
    def maneuver_type(self) -> ResolutionManeuverType:
        return ResolutionManeuverType.HEADING


@dataclass(frozen=True, slots=True)
class AltitudeManeuver:
    """Command a target altitude in feet."""

    target_altitude_ft: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "target_altitude_ft",
            as_non_negative_float(
                self.target_altitude_ft,
                field_name="target_altitude_ft",
            ),
        )

    @property
    def maneuver_type(self) -> ResolutionManeuverType:
        return ResolutionManeuverType.ALTITUDE


@dataclass(frozen=True, slots=True)
class SpeedManeuver:
    """Command a target ground speed in knots."""

    target_ground_speed_kt: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "target_ground_speed_kt",
            _as_positive_float(
                self.target_ground_speed_kt,
                field_name="target_ground_speed_kt",
            ),
        )

    @property
    def maneuver_type(self) -> ResolutionManeuverType:
        return ResolutionManeuverType.SPEED


@dataclass(frozen=True, slots=True)
class EntryDelayManeuver:
    """Delay entry into the modeled Terminal area by a positive duration."""

    delay_seconds: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "delay_seconds",
            _as_positive_float(self.delay_seconds, field_name="delay_seconds"),
        )

    @property
    def maneuver_type(self) -> ResolutionManeuverType:
        return ResolutionManeuverType.ENTRY_DELAY


@dataclass(frozen=True, slots=True)
class SequenceChangeManeuver:
    """Move the target Aircraft to an explicit one-based sequence position."""

    target_sequence_position: int

    def __post_init__(self) -> None:
        if isinstance(self.target_sequence_position, bool) or not isinstance(
            self.target_sequence_position,
            int,
        ):
            raise TypeError("target_sequence_position must be an integer")
        if self.target_sequence_position < 1:
            raise ValueError("target_sequence_position must be at least 1")

    @property
    def maneuver_type(self) -> ResolutionManeuverType:
        return ResolutionManeuverType.SEQUENCE_CHANGE


@dataclass(frozen=True, slots=True)
class NoActionManeuver:
    """Baseline used to compare intervention Candidates."""

    @property
    def maneuver_type(self) -> ResolutionManeuverType:
        return ResolutionManeuverType.NO_ACTION


type ResolutionManeuver = (
    HeadingManeuver
    | AltitudeManeuver
    | SpeedManeuver
    | EntryDelayManeuver
    | SequenceChangeManeuver
    | NoActionManeuver
)


@dataclass(frozen=True, slots=True)
class CandidateCostEstimate:
    """Comparable PoC cost fields without claiming fuel-model precision."""

    estimated_delay_seconds: float = 0.0
    estimated_path_extension_nm: float = 0.0
    operational_cost_score: float = 0.0

    def __post_init__(self) -> None:
        for field_name in ("estimated_delay_seconds", "estimated_path_extension_nm"):
            object.__setattr__(
                self,
                field_name,
                as_non_negative_float(getattr(self, field_name), field_name=field_name),
            )
        score = as_finite_float(
            self.operational_cost_score,
            field_name="operational_cost_score",
        )
        if not 0.0 <= score <= 100.0:
            raise ValueError("operational_cost_score must be in [0, 100]")
        object.__setattr__(self, "operational_cost_score", score)

    @property
    def is_zero(self) -> bool:
        return (
            self.estimated_delay_seconds == 0.0
            and self.estimated_path_extension_nm == 0.0
            and self.operational_cost_score == 0.0
        )


_OBJECTIVE_BY_MANEUVER_TYPE = {
    ResolutionManeuverType.HEADING: ResolutionObjective.LATERAL_SEPARATION,
    ResolutionManeuverType.ALTITUDE: ResolutionObjective.VERTICAL_SEPARATION,
    ResolutionManeuverType.SPEED: ResolutionObjective.TIME_SEPARATION,
    ResolutionManeuverType.ENTRY_DELAY: ResolutionObjective.TIME_SEPARATION,
    ResolutionManeuverType.SEQUENCE_CHANGE: ResolutionObjective.SEQUENCE_MANAGEMENT,
    ResolutionManeuverType.NO_ACTION: ResolutionObjective.BASELINE_COMPARISON,
}


@dataclass(frozen=True, slots=True)
class ResolutionCandidate:
    """One proposed maneuver that has not yet passed Safety Validation."""

    candidate_id: str
    target_aircraft_id: str | None
    maneuver: ResolutionManeuver
    objective: ResolutionObjective
    effective_from_utc: datetime
    cost: CandidateCostEstimate

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "candidate_id",
            require_identifier(self.candidate_id, field_name="candidate_id"),
        )
        if not isinstance(
            self.maneuver,
            (
                HeadingManeuver,
                AltitudeManeuver,
                SpeedManeuver,
                EntryDelayManeuver,
                SequenceChangeManeuver,
                NoActionManeuver,
            ),
        ):
            raise TypeError("maneuver must be a supported Resolution Maneuver")
        object.__setattr__(self, "objective", ResolutionObjective(self.objective))
        expected_objective = _OBJECTIVE_BY_MANEUVER_TYPE[self.maneuver.maneuver_type]
        if self.objective is not expected_objective:
            raise ValueError("objective must match maneuver type")
        object.__setattr__(
            self,
            "effective_from_utc",
            to_utc(self.effective_from_utc, field_name="effective_from_utc"),
        )
        if not isinstance(self.cost, CandidateCostEstimate):
            raise TypeError("cost must be a CandidateCostEstimate")

        if isinstance(self.maneuver, NoActionManeuver):
            if self.target_aircraft_id is not None:
                raise ValueError("NO_ACTION candidate must not have a target Aircraft")
            if not self.cost.is_zero:
                raise ValueError("NO_ACTION candidate must have zero estimated cost")
        else:
            object.__setattr__(
                self,
                "target_aircraft_id",
                require_identifier(
                    self.target_aircraft_id,
                    field_name="target_aircraft_id",
                ),
            )

    @property
    def maneuver_type(self) -> ResolutionManeuverType:
        return self.maneuver.maneuver_type


@dataclass(frozen=True, slots=True)
class ResolutionCandidateBatch:
    """Deterministic Candidate set for one source Conflict Exception."""

    candidate_batch_id: str
    source_exception_id: str
    source_conflict_id: str
    conflict_pair: ConflictPair
    generated_at_utc: datetime
    generator_profile_id: str
    candidates: tuple[ResolutionCandidate, ...]

    def __post_init__(self) -> None:
        for field_name in (
            "candidate_batch_id",
            "source_exception_id",
            "source_conflict_id",
            "generator_profile_id",
        ):
            object.__setattr__(
                self,
                field_name,
                require_identifier(getattr(self, field_name), field_name=field_name),
            )
        if not isinstance(self.conflict_pair, ConflictPair):
            raise TypeError("conflict_pair must be a ConflictPair")
        object.__setattr__(
            self,
            "generated_at_utc",
            to_utc(self.generated_at_utc, field_name="generated_at_utc"),
        )
        materialized = _materialize_candidates(self.candidates)
        if not materialized:
            raise ValueError("candidates must not be empty")
        candidate_ids = tuple(candidate.candidate_id for candidate in materialized)
        if len(set(candidate_ids)) != len(candidate_ids):
            raise ValueError("candidate IDs must be unique")
        no_action_count = sum(
            candidate.maneuver_type is ResolutionManeuverType.NO_ACTION
            for candidate in materialized
        )
        if no_action_count != 1:
            raise ValueError("candidates must contain exactly one NO_ACTION baseline")
        pair_ids = set(self.conflict_pair.aircraft_ids)
        if any(
            candidate.target_aircraft_id is not None
            and candidate.target_aircraft_id not in pair_ids
            for candidate in materialized
        ):
            raise ValueError("candidate target Aircraft must belong to conflict_pair")
        if any(candidate.effective_from_utc < self.generated_at_utc for candidate in materialized):
            raise ValueError("candidate effective time must not precede generated_at_utc")
        object.__setattr__(
            self,
            "candidates",
            tuple(sorted(materialized, key=lambda candidate: candidate.candidate_id)),
        )

    @property
    def actionable_candidates(self) -> tuple[ResolutionCandidate, ...]:
        return tuple(
            candidate
            for candidate in self.candidates
            if candidate.maneuver_type is not ResolutionManeuverType.NO_ACTION
        )

    @property
    def baseline_candidate(self) -> ResolutionCandidate:
        return next(
            candidate
            for candidate in self.candidates
            if candidate.maneuver_type is ResolutionManeuverType.NO_ACTION
        )


def _materialize_candidates(
    candidates: Iterable[ResolutionCandidate],
) -> tuple[ResolutionCandidate, ...]:
    if isinstance(candidates, (str, bytes)):
        raise TypeError("candidates must be an iterable of ResolutionCandidate instances")
    try:
        materialized = tuple(candidates)
    except TypeError:
        raise TypeError("candidates must be an iterable of ResolutionCandidate instances") from None
    if not all(isinstance(candidate, ResolutionCandidate) for candidate in materialized):
        raise TypeError("candidates must contain only ResolutionCandidate instances")
    return materialized
