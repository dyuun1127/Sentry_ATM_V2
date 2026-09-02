import json
from datetime import UTC, datetime, timedelta

import pytest

from sentry_atm.api import (
    InProcessRecommendationApi,
    RecommendationApiContract,
    RecommendationReadModelMapper,
    RecommendationSetSource,
)
from sentry_atm.domain import (
    AltitudeManeuver,
    CandidateCostEstimate,
    CandidateSafetyValidationResult,
    ConflictEvent,
    ConflictPair,
    ConflictStatus,
    EntryDelayManeuver,
    HeadingManeuver,
    RecommendationAvailability,
    RecommendationReasonCode,
    ResolutionCandidate,
    ResolutionObjective,
    ResolutionRecommendation,
    ResolutionRecommendationSet,
    ResolutionValidationReasonCode,
    ResolutionValidationVerdict,
    SeparationMinimum,
    SequenceChangeManeuver,
    SpeedManeuver,
)

EVALUATED_AT = datetime(2026, 9, 1, 3, 1, 15, tzinfo=UTC)
GENERATED_AT = EVALUATED_AT + timedelta(seconds=5)


def _candidate(
    candidate_id: str = "CAND-A",
    maneuver=None,
    objective: ResolutionObjective = ResolutionObjective.VERTICAL_SEPARATION,
    *,
    score: float = 10,
) -> ResolutionCandidate:
    return ResolutionCandidate(
        candidate_id=candidate_id,
        target_aircraft_id="MIL-F01",
        maneuver=AltitudeManeuver(9_000) if maneuver is None else maneuver,
        objective=objective,
        effective_from_utc=EVALUATED_AT,
        cost=CandidateCostEstimate(
            estimated_delay_seconds=5,
            estimated_path_extension_nm=1.5,
            operational_cost_score=score,
        ),
    )


def _validation(candidate_id: str) -> CandidateSafetyValidationResult:
    conflict = ConflictEvent(
        conflict_id=f"CONFLICT-{candidate_id}",
        pair=ConflictPair("CIV-A02", "MIL-F01"),
        status=ConflictStatus.SAFE,
        evaluated_at_utc=EVALUATED_AT,
        closest_approach_time_utc=EVALUATED_AT + timedelta(seconds=120),
        minimum_separation=SeparationMinimum(1.356, 1_016.25),
        rule_profile_id="POC_TERMINAL_V1",
    )
    return CandidateSafetyValidationResult(
        validation_result_id=f"VALIDATION-{candidate_id}",
        candidate_id=candidate_id,
        evaluated_at_utc=EVALUATED_AT,
        verdict=ResolutionValidationVerdict.SAFE,
        primary_conflict=conflict,
        secondary_conflicts=(),
        performance_feasible=True,
        rule_violations=(),
        reason_codes=(ResolutionValidationReasonCode.PRIMARY_CONFLICT_RESOLVED,),
        validation_profile_id="POC_SAFETY_V1",
    )


def _recommendation(
    candidate_id: str = "CAND-A",
    *,
    rank: int = 1,
    maneuver=None,
    objective: ResolutionObjective = ResolutionObjective.VERTICAL_SEPARATION,
) -> ResolutionRecommendation:
    candidate = _candidate(candidate_id, maneuver, objective, score=rank * 10)
    return ResolutionRecommendation(
        recommendation_id=f"RECOMMENDATION-{candidate_id}",
        rank=rank,
        candidate=candidate,
        validation_result=_validation(candidate_id),
        generated_at_utc=GENERATED_AT,
        reason_codes=tuple(RecommendationReasonCode),
        explanation=f"Validated safe recommendation for {candidate_id}",
    )


def _set(recommendations=None) -> ResolutionRecommendationSet:
    items = (_recommendation(),) if recommendations is None else tuple(recommendations)
    return ResolutionRecommendationSet(
        recommendation_set_id="RECOMMENDATION-SET-001",
        source_exception_id="EXCEPTION-001",
        source_candidate_batch_id="BATCH-001",
        source_validation_run_id="SAFETY-RUN-001",
        generated_at_utc=GENERATED_AT,
        ranking_policy_id="POC_RECOMMENDATION_V1",
        availability=(
            RecommendationAvailability.AVAILABLE
            if items
            else RecommendationAvailability.NO_SAFE_CANDIDATE
        ),
        recommendations=items,
    )


class _Source:
    def __init__(self, current):
        self.current = current

    def get_current_recommendation(self):
        return self.current


def test_mapper_builds_complete_json_ready_recommendation_view() -> None:
    outcome = _set()
    original = outcome

    view = RecommendationReadModelMapper.map(outcome)

    assert outcome == original
    assert view.recommendation_set_id == "RECOMMENDATION-SET-001"
    assert view.generated_at_utc == "2026-09-01T03:01:20.000000Z"
    assert view.availability == "AVAILABLE"
    assert view.primary_recommendation_id == "RECOMMENDATION-CAND-A"
    assert len(view.recommendations) == 1
    item = view.recommendations[0]
    assert item.rank == 1
    assert item.candidate_id == "CAND-A"
    assert item.target_aircraft_id == "MIL-F01"
    assert item.objective == "VERTICAL_SEPARATION"
    assert item.effective_from_utc == "2026-09-01T03:01:15.000000Z"
    assert item.maneuver.maneuver_type == "ALTITUDE"
    assert item.maneuver.target_altitude_ft == 9_000
    assert item.cost.estimated_delay_seconds == 5
    assert item.cost.estimated_path_extension_nm == 1.5
    assert item.cost.operational_cost_score == 10
    assert item.safety.verdict == "SAFE"
    assert item.safety.primary_conflict.aircraft_ids == ("CIV-A02", "MIL-F01")
    assert item.safety.primary_conflict.tcpa_seconds == 120
    assert item.safety.primary_conflict.horizontal_separation_nm == 1.356
    assert item.safety.primary_conflict.vertical_separation_ft == 1_016.25
    assert item.safety.secondary_conflicts == ()
    assert item.safety.rule_violation_ids == ()
    assert item.safety.reason_codes == ("PRIMARY_CONFLICT_RESOLVED",)

    payload = view.to_dict()
    assert payload["recommendations"][0]["maneuver"]["target_altitude_ft"] == 9_000  # type: ignore[index]
    assert payload["recommendations"][0]["safety"]["primary_conflict"][  # type: ignore[index]
        "aircraft_ids"
    ] == ["CIV-A02", "MIL-F01"]
    assert json.loads(json.dumps(payload))["availability"] == "AVAILABLE"


def test_mapper_uses_stable_nullable_schema_for_every_maneuver() -> None:
    recommendations = (
        _recommendation(
            "CAND-A",
            rank=1,
            maneuver=HeadingManeuver(200),
            objective=ResolutionObjective.LATERAL_SEPARATION,
        ),
        _recommendation(
            "CAND-B",
            rank=2,
            maneuver=AltitudeManeuver(9_000),
        ),
        _recommendation(
            "CAND-C",
            rank=3,
            maneuver=SpeedManeuver(220),
            objective=ResolutionObjective.TIME_SEPARATION,
        ),
        _recommendation(
            "CAND-D",
            rank=4,
            maneuver=EntryDelayManeuver(30),
            objective=ResolutionObjective.TIME_SEPARATION,
        ),
        _recommendation(
            "CAND-F",
            rank=5,
            maneuver=SequenceChangeManeuver(1),
            objective=ResolutionObjective.SEQUENCE_MANAGEMENT,
        ),
    )

    payloads = [
        item.maneuver.to_dict()
        for item in RecommendationReadModelMapper.map(_set(recommendations)).recommendations
    ]

    assert payloads[0]["target_heading_deg"] == 200
    assert payloads[1]["target_altitude_ft"] == 9_000
    assert payloads[2]["target_ground_speed_kt"] == 220
    assert payloads[3]["delay_seconds"] == 30
    assert payloads[4]["target_sequence_position"] == 1
    assert all(set(payload) == set(payloads[0]) for payload in payloads)


def test_empty_outcome_has_no_primary_and_is_json_serializable() -> None:
    view = RecommendationReadModelMapper.map(_set(()))

    assert view.availability == "NO_SAFE_CANDIDATE"
    assert view.primary_recommendation_id is None
    assert view.recommendations == ()
    assert view.to_dict()["recommendations"] == []


def test_mapper_rejects_non_domain_input() -> None:
    with pytest.raises(TypeError, match="ResolutionRecommendationSet"):
        RecommendationReadModelMapper.map("outcome")  # type: ignore[arg-type]


def test_in_process_api_reads_source_and_satisfies_contracts() -> None:
    outcome = _set()
    source = _Source(outcome)
    api = InProcessRecommendationApi(source)

    view = api.get_current()

    assert isinstance(source, RecommendationSetSource)
    assert isinstance(api, RecommendationApiContract)
    assert view == RecommendationReadModelMapper.map(outcome)


def test_in_process_api_returns_none_without_current_result() -> None:
    assert InProcessRecommendationApi(_Source(None)).get_current() is None


def test_in_process_api_rejects_invalid_source_boundaries() -> None:
    with pytest.raises(TypeError, match="RecommendationSetSource"):
        InProcessRecommendationApi(object())  # type: ignore[arg-type]
    api = InProcessRecommendationApi(_Source("outcome"))
    with pytest.raises(TypeError, match="unsupported"):
        api.get_current()
