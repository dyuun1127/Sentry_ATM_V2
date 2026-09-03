from datetime import UTC, datetime, timedelta, timezone

import pytest

from sentry_atm.domain import (
    AltitudeManeuver,
    CandidateCostEstimate,
    CandidateSafetyValidationResult,
    ConflictEvent,
    ConflictPair,
    ConflictStatus,
    NoActionManeuver,
    RecommendationAvailability,
    RecommendationReasonCode,
    ResolutionCandidate,
    ResolutionObjective,
    ResolutionRecommendation,
    ResolutionRecommendationSet,
    ResolutionValidationReasonCode,
    ResolutionValidationVerdict,
    SeparationMinimum,
)

EVALUATED_AT = datetime(2026, 9, 1, 3, 1, 15, tzinfo=UTC)
GENERATED_AT = EVALUATED_AT + timedelta(seconds=5)
POSITIVE_REASONS = tuple(RecommendationReasonCode)
_DEFAULT_RECOMMENDATIONS = object()


def _candidate(candidate_id: str = "CAND-A", *, effective_at=EVALUATED_AT):
    return ResolutionCandidate(
        candidate_id=candidate_id,
        target_aircraft_id="MIL-F01",
        maneuver=AltitudeManeuver(9_000),
        objective=ResolutionObjective.VERTICAL_SEPARATION,
        effective_from_utc=effective_at,
        cost=CandidateCostEstimate(operational_cost_score=10),
    )


def _baseline() -> ResolutionCandidate:
    return ResolutionCandidate(
        candidate_id="CAND-E",
        target_aircraft_id=None,
        maneuver=NoActionManeuver(),
        objective=ResolutionObjective.BASELINE_COMPARISON,
        effective_from_utc=EVALUATED_AT,
        cost=CandidateCostEstimate(),
    )


def _conflict(status: ConflictStatus = ConflictStatus.SAFE) -> ConflictEvent:
    return ConflictEvent(
        conflict_id="CONFLICT-001",
        pair=ConflictPair("CIV-A02", "MIL-F01"),
        status=status,
        evaluated_at_utc=EVALUATED_AT,
        closest_approach_time_utc=EVALUATED_AT + timedelta(seconds=90),
        minimum_separation=(
            SeparationMinimum(2.3, 1_016.25)
            if status is ConflictStatus.SAFE
            else SeparationMinimum(2.3, 500)
        ),
        rule_profile_id="POC_TERMINAL_V1",
    )


def _validation(
    candidate_id: str = "CAND-A",
    *,
    validation_result_id: str | None = None,
    verdict: ResolutionValidationVerdict = ResolutionValidationVerdict.SAFE,
) -> CandidateSafetyValidationResult:
    is_safe = verdict is ResolutionValidationVerdict.SAFE
    return CandidateSafetyValidationResult(
        validation_result_id=(
            f"VALIDATION-{candidate_id}" if validation_result_id is None else validation_result_id
        ),
        candidate_id=candidate_id,
        evaluated_at_utc=EVALUATED_AT,
        verdict=verdict,
        primary_conflict=_conflict(ConflictStatus.SAFE if is_safe else ConflictStatus.PREDICTED),
        secondary_conflicts=(),
        performance_feasible=True,
        rule_violations=(),
        reason_codes=(
            (ResolutionValidationReasonCode.PRIMARY_CONFLICT_RESOLVED,)
            if is_safe
            else (ResolutionValidationReasonCode.PRIMARY_CONFLICT_REMAINS,)
        ),
        validation_profile_id="POC_SAFETY_V1",
    )


def _recommendation(
    recommendation_id: str = "RECOMMENDATION-A",
    *,
    rank: int = 1,
    candidate: ResolutionCandidate | None = None,
    validation: CandidateSafetyValidationResult | None = None,
    generated_at=GENERATED_AT,
    reasons=POSITIVE_REASONS,
) -> ResolutionRecommendation:
    selected_candidate = _candidate() if candidate is None else candidate
    default_candidate_id = (
        selected_candidate.candidate_id
        if isinstance(selected_candidate, ResolutionCandidate)
        else "CAND-A"
    )
    selected_validation = _validation(default_candidate_id) if validation is None else validation
    return ResolutionRecommendation(
        recommendation_id=recommendation_id,
        rank=rank,
        candidate=selected_candidate,
        validation_result=selected_validation,
        generated_at_utc=generated_at,
        reason_codes=reasons,
        explanation="Resolves the predicted conflict without additional safety failures",
    )


def _recommendation_set(
    recommendations=_DEFAULT_RECOMMENDATIONS,
    **overrides,
) -> ResolutionRecommendationSet:
    values = {
        "recommendation_set_id": "RECOMMENDATION-SET-001",
        "source_exception_id": "EXCEPTION-001",
        "source_candidate_batch_id": "BATCH-001",
        "source_validation_run_id": "SAFETY-RUN-001",
        "generated_at_utc": GENERATED_AT,
        "ranking_policy_id": "POC-RECOMMENDATION-V1",
        "availability": RecommendationAvailability.AVAILABLE,
        "recommendations": (
            (_recommendation(),) if recommendations is _DEFAULT_RECOMMENDATIONS else recommendations
        ),
    }
    values.update(overrides)
    return ResolutionRecommendationSet(**values)


def test_recommendation_enums_have_stable_values() -> None:
    assert tuple(item.value for item in RecommendationAvailability) == (
        "AVAILABLE",
        "NO_SAFE_CANDIDATE",
    )
    assert tuple(item.value for item in RecommendationReasonCode) == (
        "VALIDATED_SAFE",
        "PRIMARY_CONFLICT_RESOLVED",
        "NO_SECONDARY_CONFLICT",
        "PERFORMANCE_FEASIBLE",
        "NO_RULE_VIOLATION",
    )


def test_recommendation_normalizes_metadata_and_positive_evidence() -> None:
    local_time = GENERATED_AT.astimezone(timezone(timedelta(hours=9)))
    recommendation = ResolutionRecommendation(
        recommendation_id=" RECOMMENDATION-A ",
        rank=1,
        candidate=_candidate(),
        validation_result=_validation(),
        generated_at_utc=local_time,
        reason_codes=tuple(reversed(POSITIVE_REASONS)),
        explanation=" Explanation ",
    )

    assert recommendation.recommendation_id == "RECOMMENDATION-A"
    assert recommendation.generated_at_utc == GENERATED_AT
    assert recommendation.reason_codes == POSITIVE_REASONS
    assert recommendation.explanation == "Explanation"
    assert recommendation.candidate_id == "CAND-A"
    assert recommendation.validation_result_id == "VALIDATION-CAND-A"


@pytest.mark.parametrize("rank", [True, 1.5, "1"])
def test_recommendation_rank_must_be_an_integer(rank) -> None:
    with pytest.raises(TypeError, match="integer"):
        _recommendation(rank=rank)


def test_recommendation_rank_must_be_positive() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        _recommendation(rank=0)


def test_recommendation_requires_typed_action_candidate() -> None:
    with pytest.raises(TypeError, match="ResolutionCandidate"):
        _recommendation(candidate="candidate")  # type: ignore[arg-type]
    safe_baseline = _validation("CAND-E")
    with pytest.raises(ValueError, match="NO_ACTION"):
        _recommendation(candidate=_baseline(), validation=safe_baseline)


def test_recommendation_requires_matching_safe_validation() -> None:
    with pytest.raises(TypeError, match="CandidateSafetyValidationResult"):
        _recommendation(validation="validation")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="recommended Candidate"):
        _recommendation(validation=_validation("CAND-X"))
    with pytest.raises(ValueError, match="SAFE"):
        _recommendation(
            validation=_validation(
                verdict=ResolutionValidationVerdict.INEFFECTIVE,
            )
        )


def test_recommendation_cannot_precede_validation_or_candidate() -> None:
    with pytest.raises(ValueError, match="Safety Validation"):
        _recommendation(generated_at=EVALUATED_AT - timedelta(seconds=1))
    future_candidate = _candidate(effective_at=GENERATED_AT + timedelta(seconds=1))
    with pytest.raises(ValueError, match="effective"):
        _recommendation(candidate=future_candidate)


@pytest.mark.parametrize("reasons", [(), POSITIVE_REASONS[:-1]])
def test_recommendation_requires_all_positive_reason_codes(reasons) -> None:
    with pytest.raises(ValueError, match="all positive"):
        _recommendation(reasons=reasons)


def test_recommendation_rejects_duplicate_or_invalid_reason_codes() -> None:
    with pytest.raises(ValueError, match="unique"):
        _recommendation(reasons=(*POSITIVE_REASONS, POSITIVE_REASONS[0]))
    with pytest.raises(ValueError):
        _recommendation(reasons=(*POSITIVE_REASONS[:-1], "NOT-A-REASON"))
    with pytest.raises(TypeError, match="iterable"):
        _recommendation(reasons=None)
    with pytest.raises(TypeError, match="iterable"):
        _recommendation(reasons="VALIDATED_SAFE")
    with pytest.raises(TypeError, match="contain"):
        _recommendation(reasons=(*POSITIVE_REASONS[:-1], object()))


def test_recommendation_requires_non_empty_explanation() -> None:
    with pytest.raises(ValueError, match="explanation"):
        ResolutionRecommendation(
            recommendation_id="RECOMMENDATION-A",
            rank=1,
            candidate=_candidate(),
            validation_result=_validation(),
            generated_at_utc=GENERATED_AT,
            reason_codes=POSITIVE_REASONS,
            explanation=" ",
        )


def test_available_set_sorts_ranks_and_exposes_primary_and_alternatives() -> None:
    candidate_b = _candidate("CAND-F")
    second = _recommendation(
        "RECOMMENDATION-F",
        rank=2,
        candidate=candidate_b,
    )
    first = _recommendation()

    recommendation_set = _recommendation_set((second, first))

    assert recommendation_set.has_recommendation
    assert recommendation_set.primary_recommendation is first
    assert recommendation_set.alternatives == (second,)
    assert recommendation_set.recommendations == (first, second)


def test_no_safe_candidate_set_is_an_explicit_empty_outcome() -> None:
    outcome = _recommendation_set(
        (),
        availability="NO_SAFE_CANDIDATE",
    )

    assert outcome.availability is RecommendationAvailability.NO_SAFE_CANDIDATE
    assert not outcome.has_recommendation
    assert outcome.primary_recommendation is None
    assert outcome.alternatives == ()


def test_set_availability_must_match_recommendation_presence() -> None:
    with pytest.raises(ValueError, match="AVAILABLE"):
        _recommendation_set(())
    with pytest.raises(ValueError, match="NO_SAFE_CANDIDATE"):
        _recommendation_set(
            (_recommendation(),),
            availability=RecommendationAvailability.NO_SAFE_CANDIDATE,
        )


@pytest.mark.parametrize(
    "ranks",
    [
        (1, 1),
        (1, 3),
    ],
)
def test_set_requires_unique_contiguous_ranks(ranks) -> None:
    second_candidate = _candidate("CAND-F")
    items = (
        _recommendation(rank=ranks[0]),
        _recommendation(
            "RECOMMENDATION-F",
            rank=ranks[1],
            candidate=second_candidate,
        ),
    )
    with pytest.raises(ValueError, match="contiguous"):
        _recommendation_set(items)


@pytest.mark.parametrize("duplicate_field", ["recommendation", "candidate", "validation"])
def test_set_requires_unique_recommendation_identities(duplicate_field) -> None:
    first = _recommendation()
    candidate = _candidate("CAND-F")
    kwargs = {
        "recommendation_id": "RECOMMENDATION-F",
        "rank": 2,
        "candidate": candidate,
        "validation": _validation("CAND-F"),
    }
    if duplicate_field == "recommendation":
        kwargs["recommendation_id"] = first.recommendation_id
    elif duplicate_field == "candidate":
        kwargs["candidate"] = first.candidate
        kwargs["validation"] = first.validation_result
    else:
        kwargs["validation"] = _validation(
            "CAND-F",
            validation_result_id=first.validation_result_id,
        )
    second = _recommendation(**kwargs)

    with pytest.raises(ValueError, match="must be unique"):
        _recommendation_set((first, second))


def test_set_requires_one_generation_time() -> None:
    second = _recommendation(
        "RECOMMENDATION-F",
        rank=2,
        candidate=_candidate("CAND-F"),
        generated_at=GENERATED_AT + timedelta(seconds=1),
    )
    with pytest.raises(ValueError, match="generation time"):
        _recommendation_set((_recommendation(), second))


@pytest.mark.parametrize("recommendations", ["items", None, ("item",)])
def test_set_validates_recommendation_collection(recommendations) -> None:
    expected = "iterable" if recommendations in ("items", None) else "contain"
    with pytest.raises(TypeError, match=expected):
        _recommendation_set(recommendations)


def test_set_normalizes_metadata_and_utc() -> None:
    local_time = GENERATED_AT.astimezone(timezone(timedelta(hours=9)))
    outcome = ResolutionRecommendationSet(
        recommendation_set_id=" SET-001 ",
        source_exception_id=" EXCEPTION-001 ",
        source_candidate_batch_id=" BATCH-001 ",
        source_validation_run_id=" RUN-001 ",
        generated_at_utc=local_time,
        ranking_policy_id=" POLICY-001 ",
        availability="AVAILABLE",  # type: ignore[arg-type]
        recommendations=(_recommendation(),),
    )

    assert outcome.recommendation_set_id == "SET-001"
    assert outcome.source_exception_id == "EXCEPTION-001"
    assert outcome.source_candidate_batch_id == "BATCH-001"
    assert outcome.source_validation_run_id == "RUN-001"
    assert outcome.ranking_policy_id == "POLICY-001"
    assert outcome.generated_at_utc == GENERATED_AT
