"""Isolated deterministic Candidate Safety Validation."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from math import cos, radians, sin
from numbers import Real

from sentry_atm.conflict import (
    ConstantVelocityClosestApproachCalculator,
    PairwiseConflictDetector,
)
from sentry_atm.domain import (
    AircraftPerformanceProfile,
    AircraftState,
    AltitudeManeuver,
    CandidateSafetyValidationResult,
    ConflictStatus,
    EntryDelayManeuver,
    HeadingManeuver,
    NoActionManeuver,
    ResolutionCandidate,
    ResolutionCandidateBatch,
    ResolutionSafetyValidationRun,
    ResolutionValidationReasonCode,
    ResolutionValidationVerdict,
    SafetyRuleViolation,
    SafetyRuleViolationType,
    SequenceChangeManeuver,
    SpeedManeuver,
)
from sentry_atm.domain.units import (
    as_non_negative_float,
    fpm_to_ft_per_second,
    knots_to_nm_per_second,
)
from sentry_atm.domain.validation import require_identifier


def _as_positive_float(value: Real, *, field_name: str) -> float:
    normalized = as_non_negative_float(value, field_name=field_name)
    if normalized == 0.0:
        raise ValueError(f"{field_name} must be greater than zero")
    return normalized


@dataclass(frozen=True, slots=True)
class ResolutionSafetyValidationProfile:
    """Source-labelled PoC inputs for isolated Candidate checks."""

    profile_id: str
    horizon_seconds: float
    command_execution_seconds: float
    minimum_candidate_altitude_ft: float
    max_speed_change_kt: float
    minimum_altitude_rule_id: str
    source_reference: str

    def __post_init__(self) -> None:
        for field_name in (
            "profile_id",
            "minimum_altitude_rule_id",
            "source_reference",
        ):
            object.__setattr__(
                self,
                field_name,
                require_identifier(getattr(self, field_name), field_name=field_name),
            )
        for field_name in (
            "horizon_seconds",
            "command_execution_seconds",
            "max_speed_change_kt",
        ):
            object.__setattr__(
                self,
                field_name,
                _as_positive_float(getattr(self, field_name), field_name=field_name),
            )
        object.__setattr__(
            self,
            "minimum_candidate_altitude_ft",
            as_non_negative_float(
                self.minimum_candidate_altitude_ft,
                field_name="minimum_candidate_altitude_ft",
            ),
        )


POC_SAFETY_V1_VALIDATION_PROFILE = ResolutionSafetyValidationProfile(
    profile_id="POC_SAFETY_V1",
    horizon_seconds=120.0,
    command_execution_seconds=60.0,
    minimum_candidate_altitude_ft=7_500.0,
    max_speed_change_kt=50.0,
    minimum_altitude_rule_id="POC-MINIMUM-CANDIDATE-ALTITUDE-V1",
    source_reference="ASM-037 POC VALIDATION INPUTS",
)


class IsolatedResolutionSafetyValidator:
    """Apply each Candidate to copied States and evaluate all traffic pairs."""

    __slots__ = ("_detector", "_profile")

    def __init__(
        self,
        profile: ResolutionSafetyValidationProfile = POC_SAFETY_V1_VALIDATION_PROFILE,
        *,
        detector: PairwiseConflictDetector | None = None,
    ) -> None:
        if not isinstance(profile, ResolutionSafetyValidationProfile):
            raise TypeError("profile must be a ResolutionSafetyValidationProfile")
        selected_detector = (
            PairwiseConflictDetector(
                calculator=ConstantVelocityClosestApproachCalculator(
                    horizon_seconds=profile.horizon_seconds
                )
            )
            if detector is None
            else detector
        )
        if not isinstance(selected_detector, PairwiseConflictDetector):
            raise TypeError("detector must be a PairwiseConflictDetector")
        if selected_detector.calculator.horizon_seconds != profile.horizon_seconds:
            raise ValueError("detector horizon must match validation profile")
        self._profile = profile
        self._detector = selected_detector

    @property
    def profile(self) -> ResolutionSafetyValidationProfile:
        return self._profile

    @property
    def detector(self) -> PairwiseConflictDetector:
        return self._detector

    def validate(
        self,
        batch: ResolutionCandidateBatch,
        traffic_states: Iterable[AircraftState],
        performance_profiles: Mapping[str, AircraftPerformanceProfile],
    ) -> ResolutionSafetyValidationRun:
        """Return isolated evidence without changing Candidate or source States."""

        if not isinstance(batch, ResolutionCandidateBatch):
            raise TypeError("batch must be a ResolutionCandidateBatch")
        state_by_id = _validate_traffic_states(batch, traffic_states)
        profile_by_id = _validate_performance_profiles(batch, performance_profiles)
        evaluated_at_utc = next(iter(state_by_id.values())).timestamp_utc
        if batch.generated_at_utc != evaluated_at_utc:
            raise ValueError("Candidate Batch and traffic States must share one timestamp")
        if any(candidate.effective_from_utc != evaluated_at_utc for candidate in batch.candidates):
            raise ValueError("Candidates must be effective at the validation timestamp")

        results = tuple(
            self._validate_candidate(
                batch,
                candidate,
                state_by_id=state_by_id,
                performance_by_id=profile_by_id,
            )
            for candidate in batch.candidates
        )
        timestamp_token = evaluated_at_utc.strftime("%Y%m%dT%H%M%S%fZ")
        return ResolutionSafetyValidationRun(
            validation_run_id=(
                f"SAFETY-{self._profile.profile_id}-{timestamp_token}-{batch.candidate_batch_id}"
            ),
            source_candidate_batch_id=batch.candidate_batch_id,
            evaluated_at_utc=evaluated_at_utc,
            horizon_seconds=self._profile.horizon_seconds,
            validation_profile_id=self._profile.profile_id,
            results=results,
        )

    def _validate_candidate(
        self,
        batch: ResolutionCandidateBatch,
        candidate: ResolutionCandidate,
        *,
        state_by_id: dict[str, AircraftState],
        performance_by_id: dict[str, AircraftPerformanceProfile],
    ) -> CandidateSafetyValidationResult:
        isolated_states = dict(state_by_id)
        if candidate.target_aircraft_id is not None:
            target_state = isolated_states[candidate.target_aircraft_id]
            isolated_states[candidate.target_aircraft_id] = apply_candidate_maneuver_to_state(
                target_state,
                candidate,
            )

        assessments = self._detector.assess(isolated_states.values())
        primary_conflict = next(
            assessment for assessment in assessments if assessment.pair == batch.conflict_pair
        )
        secondary_conflicts = tuple(
            assessment
            for assessment in assessments
            if assessment.pair != batch.conflict_pair
            and assessment.status is ConflictStatus.PREDICTED
        )
        performance_feasible = _is_performance_feasible(
            candidate,
            state_by_id,
            performance_by_id,
            self._profile,
        )
        rule_violations = _minimum_altitude_violations(candidate, self._profile)
        reasons = _reason_codes(
            candidate,
            primary_conflict=primary_conflict,
            secondary_conflicts=secondary_conflicts,
            performance_feasible=performance_feasible,
            rule_violations=rule_violations,
        )
        verdict = _verdict(
            candidate,
            primary_conflict=primary_conflict,
            secondary_conflicts=secondary_conflicts,
            performance_feasible=performance_feasible,
            rule_violations=rule_violations,
        )
        timestamp_token = primary_conflict.evaluated_at_utc.strftime("%Y%m%dT%H%M%S%fZ")
        return CandidateSafetyValidationResult(
            validation_result_id=(
                f"VALIDATION-{self._profile.profile_id}-{timestamp_token}-{candidate.candidate_id}"
            ),
            candidate_id=candidate.candidate_id,
            evaluated_at_utc=primary_conflict.evaluated_at_utc,
            verdict=verdict,
            primary_conflict=primary_conflict,
            secondary_conflicts=secondary_conflicts,
            performance_feasible=performance_feasible,
            rule_violations=rule_violations,
            reason_codes=reasons,
            validation_profile_id=self._profile.profile_id,
        )


def apply_candidate_maneuver_to_state(
    state: AircraftState,
    candidate: ResolutionCandidate,
) -> AircraftState:
    """Return the candidate-applied state used by validation and authorized application."""

    if not isinstance(state, AircraftState):
        raise TypeError("state must be an AircraftState")
    if not isinstance(candidate, ResolutionCandidate):
        raise TypeError("candidate must be a ResolutionCandidate")
    if candidate.target_aircraft_id != state.aircraft_id:
        raise ValueError("candidate target must match the Aircraft State")
    maneuver = candidate.maneuver
    if isinstance(maneuver, HeadingManeuver):
        return replace(state, heading_deg=maneuver.target_heading_deg)
    if isinstance(maneuver, AltitudeManeuver):
        return replace(
            state,
            altitude_ft=maneuver.target_altitude_ft,
            vertical_speed_fpm=0.0,
        )
    if isinstance(maneuver, SpeedManeuver):
        return replace(state, ground_speed_kt=maneuver.target_ground_speed_kt)
    if isinstance(maneuver, EntryDelayManeuver):
        heading_rad = radians(state.heading_deg)
        distance_nm = knots_to_nm_per_second(state.ground_speed_kt) * maneuver.delay_seconds
        altitude_change_ft = fpm_to_ft_per_second(state.vertical_speed_fpm) * maneuver.delay_seconds
        return replace(
            state,
            x_nm=state.x_nm - distance_nm * sin(heading_rad),
            y_nm=state.y_nm - distance_nm * cos(heading_rad),
            altitude_ft=state.altitude_ft - altitude_change_ft,
        )
    if isinstance(maneuver, (SequenceChangeManeuver, NoActionManeuver)):
        return state
    raise TypeError("candidate contains an unsupported maneuver")


def _is_performance_feasible(
    candidate: ResolutionCandidate,
    state_by_id: dict[str, AircraftState],
    performance_by_id: dict[str, AircraftPerformanceProfile],
    validation_profile: ResolutionSafetyValidationProfile,
) -> bool:
    if candidate.target_aircraft_id is None:
        return True
    state = state_by_id[candidate.target_aircraft_id]
    performance = performance_by_id[candidate.target_aircraft_id]
    maneuver = candidate.maneuver
    if isinstance(maneuver, HeadingManeuver):
        difference = abs(maneuver.target_heading_deg - state.heading_deg)
        shortest_difference = min(difference, 360.0 - difference)
        return shortest_difference <= (
            performance.max_turn_rate_deg_per_second * validation_profile.command_execution_seconds
        )
    if isinstance(maneuver, AltitudeManeuver):
        if maneuver.target_altitude_ft > performance.ceiling_ft:
            return False
        required_rate_fpm = (
            abs(maneuver.target_altitude_ft - state.altitude_ft)
            / validation_profile.command_execution_seconds
            * 60.0
        )
        maximum_rate = (
            performance.max_climb_rate_fpm
            if maneuver.target_altitude_ft >= state.altitude_ft
            else performance.max_descent_rate_fpm
        )
        return required_rate_fpm <= maximum_rate
    if isinstance(maneuver, SpeedManeuver):
        return (
            performance.min_speed_kt <= maneuver.target_ground_speed_kt <= performance.max_speed_kt
            and abs(maneuver.target_ground_speed_kt - state.ground_speed_kt)
            <= validation_profile.max_speed_change_kt
        )
    return True


def _minimum_altitude_violations(
    candidate: ResolutionCandidate,
    profile: ResolutionSafetyValidationProfile,
) -> tuple[SafetyRuleViolation, ...]:
    maneuver = candidate.maneuver
    if not isinstance(maneuver, AltitudeManeuver) or (
        maneuver.target_altitude_ft >= profile.minimum_candidate_altitude_ft
    ):
        return ()
    return (
        SafetyRuleViolation(
            violation_id=(f"VIOLATION-{candidate.candidate_id}-{profile.minimum_altitude_rule_id}"),
            rule_id=profile.minimum_altitude_rule_id,
            violation_type=SafetyRuleViolationType.MINIMUM_ALTITUDE,
            aircraft_id=candidate.target_aircraft_id,
            description=(
                f"target altitude {maneuver.target_altitude_ft:.1f} ft is below "
                f"configured minimum {profile.minimum_candidate_altitude_ft:.1f} ft"
            ),
            source_reference=profile.source_reference,
        ),
    )


def _reason_codes(
    candidate: ResolutionCandidate,
    *,
    primary_conflict,
    secondary_conflicts,
    performance_feasible: bool,
    rule_violations,
) -> tuple[ResolutionValidationReasonCode, ...]:
    reasons = [
        ResolutionValidationReasonCode.PRIMARY_CONFLICT_RESOLVED
        if primary_conflict.status is ConflictStatus.SAFE
        else ResolutionValidationReasonCode.PRIMARY_CONFLICT_REMAINS
    ]
    if secondary_conflicts:
        reasons.append(ResolutionValidationReasonCode.SECONDARY_CONFLICT_DETECTED)
    if not performance_feasible:
        reasons.append(ResolutionValidationReasonCode.PERFORMANCE_ENVELOPE_EXCEEDED)
    if rule_violations:
        reasons.append(ResolutionValidationReasonCode.RULE_VIOLATION)
    if isinstance(candidate.maneuver, NoActionManeuver):
        reasons.append(ResolutionValidationReasonCode.NO_ACTION_BASELINE)
    return tuple(reasons)


def _verdict(
    candidate: ResolutionCandidate,
    *,
    primary_conflict,
    secondary_conflicts,
    performance_feasible: bool,
    rule_violations,
) -> ResolutionValidationVerdict:
    if secondary_conflicts or not performance_feasible or rule_violations:
        return ResolutionValidationVerdict.UNSAFE
    if primary_conflict.status is ConflictStatus.SAFE:
        return ResolutionValidationVerdict.SAFE
    if isinstance(candidate.maneuver, NoActionManeuver):
        return ResolutionValidationVerdict.UNSAFE
    return ResolutionValidationVerdict.INEFFECTIVE


def _validate_traffic_states(
    batch: ResolutionCandidateBatch,
    states: Iterable[AircraftState],
) -> dict[str, AircraftState]:
    if isinstance(states, (str, bytes)):
        raise TypeError("traffic_states must be an iterable of AircraftState instances")
    try:
        materialized = tuple(states)
    except TypeError:
        raise TypeError("traffic_states must be an iterable of AircraftState instances") from None
    if not all(isinstance(state, AircraftState) for state in materialized):
        raise TypeError("traffic_states must contain only AircraftState instances")
    if len(materialized) < 2:
        raise ValueError("traffic_states must contain at least two Aircraft")
    aircraft_ids = tuple(state.aircraft_id for state in materialized)
    if len(set(aircraft_ids)) != len(aircraft_ids):
        raise ValueError("traffic_states must have unique Aircraft IDs")
    if not set(batch.conflict_pair.aircraft_ids).issubset(aircraft_ids):
        raise ValueError("traffic_states must contain the Candidate Conflict Pair")
    if len({state.timestamp_utc for state in materialized}) != 1:
        raise ValueError("traffic_states must share one timestamp")
    return {state.aircraft_id: state for state in materialized}


def _validate_performance_profiles(
    batch: ResolutionCandidateBatch,
    profiles: Mapping[str, AircraftPerformanceProfile],
) -> dict[str, AircraftPerformanceProfile]:
    if not isinstance(profiles, Mapping):
        raise TypeError("performance_profiles must be an Aircraft ID mapping")
    materialized = dict(profiles)
    if not set(batch.conflict_pair.aircraft_ids).issubset(materialized):
        raise ValueError("performance_profiles must contain the Candidate Conflict Pair")
    if not all(isinstance(value, AircraftPerformanceProfile) for value in materialized.values()):
        raise TypeError("performance_profiles must contain AircraftPerformanceProfile values")
    return materialized
