"""Deterministic restricted Candidate generation without Safety claims."""

from collections.abc import Iterable, Mapping
from math import ceil, floor
from numbers import Real

from sentry_atm.domain import (
    AircraftPerformanceProfile,
    AircraftState,
    AltitudeManeuver,
    CandidateCostEstimate,
    ConflictExceptionItem,
    EntryDelayManeuver,
    ExceptionStatus,
    HeadingManeuver,
    NoActionManeuver,
    ResolutionCandidate,
    ResolutionCandidateBatch,
    ResolutionManeuver,
    ResolutionManeuverType,
    ResolutionObjective,
    RiskLevel,
    SequenceChangeManeuver,
    SpeedManeuver,
)
from sentry_atm.domain.units import as_non_negative_float, normalize_heading_deg
from sentry_atm.domain.validation import require_identifier
from sentry_atm.resolution.profile import (
    POC_RESOLUTION_V1_GENERATION_PROFILE,
    CandidateTargetRole,
    ResolutionCandidateGenerationProfile,
    ResolutionCandidateTemplate,
)

_OBJECTIVE_BY_MANEUVER_TYPE = {
    ResolutionManeuverType.HEADING: ResolutionObjective.LATERAL_SEPARATION,
    ResolutionManeuverType.ALTITUDE: ResolutionObjective.VERTICAL_SEPARATION,
    ResolutionManeuverType.SPEED: ResolutionObjective.TIME_SEPARATION,
    ResolutionManeuverType.ENTRY_DELAY: ResolutionObjective.TIME_SEPARATION,
    ResolutionManeuverType.SEQUENCE_CHANGE: ResolutionObjective.SEQUENCE_MANAGEMENT,
}


class DeterministicResolutionCandidateGenerator:
    """Generate configured action slots plus one zero-cost baseline."""

    __slots__ = ("_profile",)

    def __init__(
        self,
        profile: ResolutionCandidateGenerationProfile = (POC_RESOLUTION_V1_GENERATION_PROFILE),
    ) -> None:
        if not isinstance(profile, ResolutionCandidateGenerationProfile):
            raise TypeError("profile must be a ResolutionCandidateGenerationProfile")
        self._profile = profile

    @property
    def profile(self) -> ResolutionCandidateGenerationProfile:
        return self._profile

    def generate(
        self,
        exception: ConflictExceptionItem,
        states: Iterable[AircraftState],
        performance_profiles: Mapping[str, AircraftPerformanceProfile],
        *,
        preferred_target_aircraft_id: str,
        preferred_altitude_ft: Real | None = None,
    ) -> ResolutionCandidateBatch:
        """Return deterministic unvalidated Candidates without mutating inputs."""

        _validate_exception(exception)
        state_by_id = _validate_states(exception, states)
        profile_by_id = _validate_performance_profiles(exception, performance_profiles)
        preferred_id = require_identifier(
            preferred_target_aircraft_id,
            field_name="preferred_target_aircraft_id",
        )
        pair_ids = exception.assessment.pair.aircraft_ids
        if preferred_id not in pair_ids:
            raise ValueError("preferred target Aircraft must belong to the Conflict Pair")
        other_id = pair_ids[1] if preferred_id == pair_ids[0] else pair_ids[0]
        generated_at_utc = state_by_id[preferred_id].timestamp_utc
        if exception.assessment.evaluated_at_utc > generated_at_utc:
            raise ValueError("Conflict assessment must not be newer than Candidate states")

        preferred_altitude = _normalize_preferred_altitude(
            preferred_altitude_ft,
            profile_by_id[preferred_id],
        )
        candidates = tuple(
            self._build_candidate(
                template,
                preferred_id=preferred_id,
                other_id=other_id,
                state_by_id=state_by_id,
                profile_by_id=profile_by_id,
                preferred_altitude_ft=preferred_altitude,
            )
            for template in self._profile.templates
        )
        baseline = ResolutionCandidate(
            candidate_id=self._profile.baseline_candidate_id,
            target_aircraft_id=None,
            maneuver=NoActionManeuver(),
            objective=ResolutionObjective.BASELINE_COMPARISON,
            effective_from_utc=generated_at_utc,
            cost=CandidateCostEstimate(),
        )
        timestamp_token = generated_at_utc.strftime("%Y%m%dT%H%M%S%fZ")
        return ResolutionCandidateBatch(
            candidate_batch_id=(
                f"RESOLUTION-{self._profile.profile_id}-{timestamp_token}-"
                f"{exception.assessment.conflict_id}"
            ),
            source_exception_id=exception.exception_id,
            source_conflict_id=exception.assessment.conflict_id,
            conflict_pair=exception.assessment.pair,
            generated_at_utc=generated_at_utc,
            generator_profile_id=self._profile.profile_id,
            candidates=(*candidates, baseline),
        )

    def _build_candidate(
        self,
        template: ResolutionCandidateTemplate,
        *,
        preferred_id: str,
        other_id: str,
        state_by_id: dict[str, AircraftState],
        profile_by_id: dict[str, AircraftPerformanceProfile],
        preferred_altitude_ft: float | None,
    ) -> ResolutionCandidate:
        target_id = (
            preferred_id if template.target_role is CandidateTargetRole.PREFERRED else other_id
        )
        target_state = state_by_id[target_id]
        target_profile = profile_by_id[target_id]
        maneuver = self._build_maneuver(
            template,
            target_state=target_state,
            target_profile=target_profile,
            preferred_altitude_ft=(preferred_altitude_ft if target_id == preferred_id else None),
        )
        return ResolutionCandidate(
            candidate_id=template.candidate_id,
            target_aircraft_id=target_id,
            maneuver=maneuver,
            objective=_OBJECTIVE_BY_MANEUVER_TYPE[template.maneuver_type],
            effective_from_utc=target_state.timestamp_utc,
            cost=template.cost,
        )

    def _build_maneuver(
        self,
        template: ResolutionCandidateTemplate,
        *,
        target_state: AircraftState,
        target_profile: AircraftPerformanceProfile,
        preferred_altitude_ft: float | None,
    ) -> ResolutionManeuver:
        maneuver_type = template.maneuver_type
        if maneuver_type is ResolutionManeuverType.HEADING:
            return HeadingManeuver(
                normalize_heading_deg(target_state.heading_deg + self._profile.heading_change_deg)
            )
        if maneuver_type is ResolutionManeuverType.ALTITUDE:
            if preferred_altitude_ft is not None:
                # 호출자가 고도를 지정했으면 그대로 쓴다. 지정한 쪽이 사다리나
                # 규정 제약을 이미 반영했을 수 있으므로 여기서 다시 반올림하면
                # 그 의도를 덮어쓴다.
                return AltitudeManeuver(preferred_altitude_ft)
            if template.target_role is CandidateTargetRole.PREFERRED:
                target_altitude_ft = _assignable_altitude_ft(
                    min(
                        target_state.altitude_ft + self._profile.altitude_change_ft,
                        target_profile.ceiling_ft,
                    ),
                    climbing=True,
                    ceiling_ft=target_profile.ceiling_ft,
                )
            else:
                target_altitude_ft = _assignable_altitude_ft(
                    max(0.0, target_state.altitude_ft - self._profile.altitude_change_ft),
                    climbing=False,
                    ceiling_ft=target_profile.ceiling_ft,
                )
            return AltitudeManeuver(target_altitude_ft)
        if maneuver_type is ResolutionManeuverType.SPEED:
            return SpeedManeuver(
                max(
                    target_profile.min_speed_kt,
                    target_state.ground_speed_kt - self._profile.speed_change_kt,
                )
            )
        if maneuver_type is ResolutionManeuverType.ENTRY_DELAY:
            return EntryDelayManeuver(self._profile.entry_delay_seconds)
        return SequenceChangeManeuver(self._profile.target_sequence_position)


def _validate_exception(exception: ConflictExceptionItem) -> None:
    if not isinstance(exception, ConflictExceptionItem):
        raise TypeError("exception must be a ConflictExceptionItem")
    if exception.status is ExceptionStatus.RESOLVED:
        raise ValueError("resolved Conflict Exception cannot generate Candidates")
    if exception.assessment.risk_level is RiskLevel.LOW:
        raise ValueError("LOW Risk Conflict Exception cannot generate Candidates")


def _validate_states(
    exception: ConflictExceptionItem,
    states: Iterable[AircraftState],
) -> dict[str, AircraftState]:
    if isinstance(states, (str, bytes)):
        raise TypeError("states must be an iterable of AircraftState instances")
    try:
        materialized = tuple(states)
    except TypeError:
        raise TypeError("states must be an iterable of AircraftState instances") from None
    if not all(isinstance(state, AircraftState) for state in materialized):
        raise TypeError("states must contain only AircraftState instances")
    state_ids = tuple(state.aircraft_id for state in materialized)
    if len(set(state_ids)) != len(state_ids):
        raise ValueError("states must have unique Aircraft IDs")
    if set(state_ids) != set(exception.assessment.pair.aircraft_ids):
        raise ValueError("states must contain exactly the Conflict Pair")
    if len({state.timestamp_utc for state in materialized}) != 1:
        raise ValueError("states must share one timestamp")
    return {state.aircraft_id: state for state in materialized}


def _validate_performance_profiles(
    exception: ConflictExceptionItem,
    profiles: Mapping[str, AircraftPerformanceProfile],
) -> dict[str, AircraftPerformanceProfile]:
    if not isinstance(profiles, Mapping):
        raise TypeError("performance_profiles must be an Aircraft ID mapping")
    materialized = dict(profiles)
    if set(materialized) != set(exception.assessment.pair.aircraft_ids):
        raise ValueError("performance_profiles must contain exactly the Conflict Pair")
    if not all(isinstance(value, AircraftPerformanceProfile) for value in materialized.values()):
        raise TypeError("performance_profiles must contain AircraftPerformanceProfile values")
    return materialized


# 배정고도 간격. 관제사는 "8,446 피트로 상승" 이라고 지시하지 않는다 — 고도는
# 1,000 ft 단위로 배정되고, AIP RKTU 의 배정고도 사다리(4,000·5,000·6,000)도 같은
# 간격이다. 현재고도에 증분을 더한 값을 그대로 내면 실제로 낼 수 없는 지시가
# 되고, 그것은 관제사가 화면을 신뢰하지 않을 이유가 된다.
_ALTITUDE_ASSIGNMENT_STEP_FT = 1_000.0


def _assignable_altitude_ft(
    value: float,
    *,
    climbing: bool,
    ceiling_ft: float,
    floor_ft: float = 0.0,
) -> float:
    """실제로 배정할 수 있는 고도로 맞춘다.

    기동 방향으로 맞춘다 — 상승 중인 항공기를 내림 반올림하면 요청한 것보다 낮은
    고도가 되어 분리가 의도보다 좁아진다.

    **맞춘 뒤 포락선 안으로 가둔다.** 상한에 붙은 값을 올림하면 상한을 넘고,
    그 고도는 항공기가 갈 수 없다. 넘으면 한 칸 내려 상한 이하의 배정 가능한
    고도를 쓴다. 그 고도가 포락선 밖이면 배정할 수 있는 값이 없다는 뜻이므로
    상한 자체를 낸다 — 반올림 때문에 후보가 사라지게 두지 않는다.
    """
    step = _ALTITUDE_ASSIGNMENT_STEP_FT
    if value % step == 0.0:
        snapped = value
    else:
        snapped = (ceil(value / step) if climbing else floor(value / step)) * step
    if snapped > ceiling_ft:
        lowered = floor(ceiling_ft / step) * step
        return lowered if lowered >= floor_ft else ceiling_ft
    if snapped < floor_ft:
        raised = ceil(floor_ft / step) * step
        return raised if raised <= ceiling_ft else floor_ft
    return snapped


def _normalize_preferred_altitude(
    value: Real | None,
    profile: AircraftPerformanceProfile,
) -> float | None:
    if value is None:
        return None
    altitude = as_non_negative_float(value, field_name="preferred_altitude_ft")
    if altitude > profile.ceiling_ft:
        raise ValueError("preferred_altitude_ft must not exceed the performance ceiling")
    return altitude
