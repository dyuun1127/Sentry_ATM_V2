from datetime import UTC, datetime, timedelta, timezone

import pytest

import sentry_atm.recommendation.service as recommendation_service
from sentry_atm.conflict import PairwiseConflictDetector
from sentry_atm.domain import (
    AircraftPerformanceProfile,
    AltitudeManeuver,
    CandidateCostEstimate,
    CandidateSafetyValidationResult,
    ConflictEvent,
    ConflictExceptionItem,
    ConflictPair,
    ConflictStatus,
    EntryDelayManeuver,
    HeadingManeuver,
    NoActionManeuver,
    RecommendationAvailability,
    ResolutionCandidate,
    ResolutionCandidateBatch,
    ResolutionObjective,
    ResolutionSafetyValidationRun,
    ResolutionValidationReasonCode,
    ResolutionValidationVerdict,
    SeparationMinimum,
    SequenceChangeManeuver,
    SpeedManeuver,
)
from sentry_atm.infrastructure.persistence.seed import POC_PERFORMANCE_PROFILES
from sentry_atm.recommendation import (
    POC_RECOMMENDATION_V1_RANKING_PROFILE,
    DeterministicRecommendationRankingService,
    RecommendationRankingProfile,
)
from sentry_atm.resolution import (
    DeterministicResolutionCandidateGenerator,
    IsolatedResolutionSafetyValidator,
)
from sentry_atm.risk import ConflictRiskEvaluator
from sentry_atm.scenario import build_golden_demo_scenario, build_scenario_simulation

BATCH_AT = datetime(2026, 9, 1, 3, 1, 15, tzinfo=UTC)
EVALUATED_AT = BATCH_AT + timedelta(seconds=1)
GENERATED_AT = EVALUATED_AT + timedelta(seconds=4)


def _candidate(
    candidate_id: str,
    maneuver,
    objective: ResolutionObjective,
    *,
    score: float,
    delay: float = 0,
    path: float = 0,
) -> ResolutionCandidate:
    return ResolutionCandidate(
        candidate_id=candidate_id,
        target_aircraft_id="MIL-F01",
        maneuver=maneuver,
        objective=objective,
        effective_from_utc=BATCH_AT,
        cost=CandidateCostEstimate(delay, path, score),
    )


def _baseline() -> ResolutionCandidate:
    return ResolutionCandidate(
        candidate_id="CAND-E",
        target_aircraft_id=None,
        maneuver=NoActionManeuver(),
        objective=ResolutionObjective.BASELINE_COMPARISON,
        effective_from_utc=BATCH_AT,
        cost=CandidateCostEstimate(),
    )


def _default_actions() -> tuple[ResolutionCandidate, ...]:
    return (
        _candidate(
            "CAND-A",
            AltitudeManeuver(9_000),
            ResolutionObjective.VERTICAL_SEPARATION,
            score=10,
        ),
        _candidate(
            "CAND-B",
            HeadingManeuver(200),
            ResolutionObjective.LATERAL_SEPARATION,
            score=10,
            path=1.5,
        ),
        _candidate(
            "CAND-C",
            SpeedManeuver(220),
            ResolutionObjective.TIME_SEPARATION,
            score=10,
            delay=30,
        ),
        _candidate(
            "CAND-D",
            AltitudeManeuver(7_200),
            ResolutionObjective.VERTICAL_SEPARATION,
            score=20,
        ),
    )


def _batch(actions=None, *, generated_at=BATCH_AT) -> ResolutionCandidateBatch:
    selected_actions = _default_actions() if actions is None else tuple(actions)
    baseline = _baseline()
    if generated_at != BATCH_AT:
        selected_actions = tuple(
            ResolutionCandidate(
                candidate_id=item.candidate_id,
                target_aircraft_id=item.target_aircraft_id,
                maneuver=item.maneuver,
                objective=item.objective,
                effective_from_utc=generated_at,
                cost=item.cost,
            )
            for item in selected_actions
        )
        baseline = ResolutionCandidate(
            candidate_id=baseline.candidate_id,
            target_aircraft_id=None,
            maneuver=baseline.maneuver,
            objective=baseline.objective,
            effective_from_utc=generated_at,
            cost=baseline.cost,
        )
    return ResolutionCandidateBatch(
        candidate_batch_id="BATCH-001",
        source_exception_id="EXCEPTION-001",
        source_conflict_id="CONFLICT-SOURCE",
        conflict_pair=ConflictPair("CIV-A02", "MIL-F01"),
        generated_at_utc=generated_at,
        generator_profile_id="POC_RESOLUTION_V1",
        candidates=(*selected_actions, baseline),
    )


def _conflict(status: ConflictStatus, *, evaluated_at=EVALUATED_AT) -> ConflictEvent:
    return ConflictEvent(
        conflict_id=f"CONFLICT-{status.value}",
        pair=ConflictPair("CIV-A02", "MIL-F01"),
        status=status,
        evaluated_at_utc=evaluated_at,
        closest_approach_time_utc=evaluated_at + timedelta(seconds=90),
        minimum_separation=(
            SeparationMinimum(2.3, 1_100)
            if status is ConflictStatus.SAFE
            else SeparationMinimum(2.3, 500)
        ),
        rule_profile_id="POC_TERMINAL_V1",
    )


def _validation(
    candidate_id: str,
    *,
    safe: bool,
    evaluated_at=EVALUATED_AT,
) -> CandidateSafetyValidationResult:
    is_baseline = candidate_id == "CAND-E"
    reasons = [
        ResolutionValidationReasonCode.PRIMARY_CONFLICT_RESOLVED
        if safe
        else ResolutionValidationReasonCode.PRIMARY_CONFLICT_REMAINS
    ]
    if is_baseline:
        reasons.append(ResolutionValidationReasonCode.NO_ACTION_BASELINE)
    return CandidateSafetyValidationResult(
        validation_result_id=f"VALIDATION-{candidate_id}",
        candidate_id=candidate_id,
        evaluated_at_utc=evaluated_at,
        verdict=(
            ResolutionValidationVerdict.SAFE
            if safe
            else (
                ResolutionValidationVerdict.UNSAFE
                if is_baseline
                else ResolutionValidationVerdict.INEFFECTIVE
            )
        ),
        primary_conflict=_conflict(
            ConflictStatus.SAFE if safe else ConflictStatus.PREDICTED,
            evaluated_at=evaluated_at,
        ),
        secondary_conflicts=(),
        performance_feasible=True,
        rule_violations=(),
        reason_codes=tuple(reasons),
        validation_profile_id="POC_SAFETY_V1",
    )


def _run(
    batch: ResolutionCandidateBatch,
    *,
    safe_ids=("CAND-A",),
    candidate_ids=None,
    evaluated_at=EVALUATED_AT,
    source_batch_id=None,
) -> ResolutionSafetyValidationRun:
    selected_ids = (
        tuple(candidate.candidate_id for candidate in batch.candidates)
        if candidate_ids is None
        else tuple(candidate_ids)
    )
    return ResolutionSafetyValidationRun(
        validation_run_id="SAFETY-RUN-001",
        source_candidate_batch_id=(
            batch.candidate_batch_id if source_batch_id is None else source_batch_id
        ),
        evaluated_at_utc=evaluated_at,
        horizon_seconds=120,
        validation_profile_id="POC_SAFETY_V1",
        results=tuple(
            _validation(
                candidate_id,
                safe=candidate_id in safe_ids,
                evaluated_at=evaluated_at,
            )
            for candidate_id in selected_ids
        ),
    )


def test_default_ranking_profile_is_source_labelled() -> None:
    profile = POC_RECOMMENDATION_V1_RANKING_PROFILE

    assert profile.profile_id == "POC_RECOMMENDATION_V1"
    assert profile.max_recommendations == 3
    assert profile.source_reference == "ASM-027 ASM-038 POC RANKING POLICY"


def test_ranking_profile_normalizes_and_validates_limit() -> None:
    profile = RecommendationRankingProfile(" PROFILE ", 2, " SOURCE ")
    assert profile.profile_id == "PROFILE"
    assert profile.source_reference == "SOURCE"

    for invalid in (True, 1.5, "1"):
        with pytest.raises(TypeError, match="integer"):
            RecommendationRankingProfile("PROFILE", invalid, "SOURCE")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="at least 1"):
        RecommendationRankingProfile("PROFILE", 0, "SOURCE")


def test_service_ranks_only_safe_actions_by_explicit_cost_order() -> None:
    batch = _batch()
    run = _run(batch, safe_ids=("CAND-A", "CAND-B", "CAND-C", "CAND-E"))
    original_batch = batch
    original_run = run
    service = DeterministicRecommendationRankingService()

    outcome = service.recommend(batch, run, generated_at_utc=GENERATED_AT)

    assert batch == original_batch
    assert run == original_run
    assert service.profile is POC_RECOMMENDATION_V1_RANKING_PROFILE
    assert outcome.availability is RecommendationAvailability.AVAILABLE
    assert tuple(item.candidate_id for item in outcome.recommendations) == (
        "CAND-A",
        "CAND-B",
        "CAND-C",
    )
    assert tuple(item.rank for item in outcome.recommendations) == (1, 2, 3)
    assert all(item.candidate_id != "CAND-E" for item in outcome.recommendations)
    assert outcome.source_candidate_batch_id == batch.candidate_batch_id
    assert outcome.source_validation_run_id == run.validation_run_id
    assert service.recommend(batch, run, generated_at_utc=GENERATED_AT) == outcome


def test_profile_limit_truncates_after_deterministic_ranking() -> None:
    batch = _batch()
    run = _run(batch, safe_ids=("CAND-A", "CAND-B", "CAND-C", "CAND-D"))
    profile = RecommendationRankingProfile("TOP-TWO", 2, "TEST POLICY")

    outcome = DeterministicRecommendationRankingService(profile).recommend(
        batch,
        run,
        generated_at_utc=GENERATED_AT,
    )

    assert tuple(item.candidate_id for item in outcome.recommendations) == (
        "CAND-A",
        "CAND-B",
    )
    assert outcome.ranking_policy_id == "TOP-TWO"


def test_candidate_id_is_the_stable_final_tie_breaker() -> None:
    actions = tuple(
        _candidate(
            candidate_id,
            AltitudeManeuver(9_000),
            ResolutionObjective.VERTICAL_SEPARATION,
            score=10,
        )
        for candidate_id in ("CAND-G", "CAND-F")
    )
    batch = _batch(actions)
    run = _run(batch, safe_ids=("CAND-F", "CAND-G"))

    outcome = DeterministicRecommendationRankingService().recommend(
        batch,
        run,
        generated_at_utc=GENERATED_AT,
    )

    assert tuple(item.candidate_id for item in outcome.recommendations) == (
        "CAND-F",
        "CAND-G",
    )


def test_no_safe_action_returns_explicit_empty_outcome() -> None:
    batch = _batch()

    outcome = DeterministicRecommendationRankingService().recommend(
        batch,
        _run(batch, safe_ids=()),
        generated_at_utc=GENERATED_AT,
    )

    assert outcome.availability is RecommendationAvailability.NO_SAFE_CANDIDATE
    assert outcome.recommendations == ()
    assert outcome.primary_recommendation is None


def test_service_builds_explanations_for_every_action_maneuver() -> None:
    actions = (
        _candidate(
            "CAND-A",
            HeadingManeuver(200),
            ResolutionObjective.LATERAL_SEPARATION,
            score=1,
        ),
        _candidate(
            "CAND-B",
            AltitudeManeuver(9_000),
            ResolutionObjective.VERTICAL_SEPARATION,
            score=2,
        ),
        _candidate(
            "CAND-C",
            SpeedManeuver(220),
            ResolutionObjective.TIME_SEPARATION,
            score=3,
        ),
        _candidate(
            "CAND-D",
            EntryDelayManeuver(30),
            ResolutionObjective.TIME_SEPARATION,
            score=4,
        ),
        _candidate(
            "CAND-F",
            SequenceChangeManeuver(1),
            ResolutionObjective.SEQUENCE_MANAGEMENT,
            score=5,
        ),
    )
    batch = _batch(actions)
    profile = RecommendationRankingProfile("ALL-ACTIONS", 5, "TEST POLICY")
    run = _run(batch, safe_ids=tuple(item.candidate_id for item in actions))

    outcome = DeterministicRecommendationRankingService(profile).recommend(
        batch,
        run,
        generated_at_utc=GENERATED_AT,
    )

    explanations = {item.candidate_id: item.explanation for item in outcome.recommendations}
    assert "heading to 200.0 deg" in explanations["CAND-A"]
    assert "altitude to 9000.0 ft" in explanations["CAND-B"]
    assert "ground speed to 220.0 kt" in explanations["CAND-C"]
    assert "delay entry by 30.0 s" in explanations["CAND-D"]
    assert "sequence position to 1" in explanations["CAND-F"]
    assert all("no secondary conflict" in value for value in explanations.values())

    with pytest.raises(ValueError, match="NO_ACTION"):
        recommendation_service._explanation(_baseline())


def test_service_validates_constructor_and_input_types() -> None:
    with pytest.raises(TypeError, match="RecommendationRankingProfile"):
        DeterministicRecommendationRankingService("profile")  # type: ignore[arg-type]
    service = DeterministicRecommendationRankingService()
    batch = _batch()
    run = _run(batch)
    with pytest.raises(TypeError, match="ResolutionCandidateBatch"):
        service.recommend("batch", run, generated_at_utc=GENERATED_AT)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="ResolutionSafetyValidationRun"):
        service.recommend(batch, "run", generated_at_utc=GENERATED_AT)  # type: ignore[arg-type]


def test_service_requires_validation_to_reference_complete_batch() -> None:
    batch = _batch()
    service = DeterministicRecommendationRankingService()
    with pytest.raises(ValueError, match="reference candidate_batch"):
        service.recommend(
            batch,
            _run(batch, source_batch_id="OTHER-BATCH"),
            generated_at_utc=GENERATED_AT,
        )
    with pytest.raises(ValueError, match="every Candidate"):
        service.recommend(
            batch,
            _run(batch, candidate_ids=("CAND-A", "CAND-E")),
            generated_at_utc=GENERATED_AT,
        )
    all_ids = tuple(candidate.candidate_id for candidate in batch.candidates)
    with pytest.raises(ValueError, match="every Candidate"):
        service.recommend(
            batch,
            _run(batch, candidate_ids=(*all_ids, "CAND-X")),
            generated_at_utc=GENERATED_AT,
        )


def test_service_rejects_impossible_time_order_and_normalizes_utc() -> None:
    service = DeterministicRecommendationRankingService()
    future_batch = _batch(generated_at=EVALUATED_AT + timedelta(seconds=1))
    with pytest.raises(ValueError, match="cannot precede Candidate"):
        service.recommend(
            future_batch,
            _run(future_batch, evaluated_at=EVALUATED_AT),
            generated_at_utc=GENERATED_AT,
        )
    batch = _batch()
    run = _run(batch)
    with pytest.raises(ValueError, match="cannot precede Safety"):
        service.recommend(
            batch,
            run,
            generated_at_utc=EVALUATED_AT - timedelta(seconds=1),
        )

    local_time = GENERATED_AT.astimezone(timezone(timedelta(hours=9)))
    outcome = service.recommend(batch, run, generated_at_utc=local_time)
    assert outcome.generated_at_utc == GENERATED_AT


def _golden_inputs():
    simulation = build_scenario_simulation(build_golden_demo_scenario())
    simulation.clock.play()
    at_70 = simulation.engine.tick(steps=70)
    conflict = next(
        event
        for event in PairwiseConflictDetector().detect(at_70.states)
        if event.pair.aircraft_ids == ("CIV-A02", "MIL-F01")
    )
    risk = ConflictRiskEvaluator().evaluate(conflict)
    exception = ConflictExceptionItem(
        exception_id="EXCEPTION-CONFLICT-7-CIV-A02-7-MIL-F01",
        assessment=risk,
        opened_at_utc=risk.evaluated_at_utc,
        updated_at_utc=risk.evaluated_at_utc,
    )
    at_75 = simulation.engine.tick(steps=5)
    profile_by_id = {profile.profile_id: profile for profile in POC_PERFORMANCE_PROFILES}
    metadata_by_id = {item.aircraft_id: item.metadata for item in simulation.definition.aircraft}
    pair_profiles: dict[str, AircraftPerformanceProfile] = {
        aircraft_id: profile_by_id[metadata_by_id[aircraft_id].performance_class]
        for aircraft_id in exception.assessment.pair.aircraft_ids
    }
    pair_states = tuple(
        state
        for state in at_75.states
        if state.aircraft_id in exception.assessment.pair.aircraft_ids
    )
    batch = DeterministicResolutionCandidateGenerator().generate(
        exception,
        pair_states,
        pair_profiles,
        preferred_target_aircraft_id="MIL-F01",
        preferred_altitude_ft=9_000,
    )
    run = IsolatedResolutionSafetyValidator().validate(
        batch,
        at_75.states,
        pair_profiles,
    )
    return at_75.states, batch, run


def test_golden_pipeline_recommends_only_calculated_safe_candidate_a() -> None:
    states, batch, run = _golden_inputs()
    original_states = states

    outcome = DeterministicRecommendationRankingService().recommend(
        batch,
        run,
        generated_at_utc=BATCH_AT + timedelta(seconds=5),
    )

    assert states == original_states
    assert outcome.availability is RecommendationAvailability.AVAILABLE
    assert tuple(item.candidate_id for item in outcome.recommendations) == ("CAND-A",)
    assert outcome.primary_recommendation is not None
    assert outcome.primary_recommendation.candidate.target_aircraft_id == "MIL-F01"
    assert "altitude to 9000.0 ft" in outcome.primary_recommendation.explanation
