from datetime import UTC, datetime, timedelta, timezone

import pytest

from sentry_atm.controller_decision import DeterministicControllerDecisionService
from sentry_atm.domain import (
    AltitudeManeuver,
    CandidateCostEstimate,
    CandidateSafetyValidationResult,
    ConflictEvent,
    ConflictPair,
    ConflictStatus,
    ControllerDecisionType,
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
)

EVALUATED_AT = datetime(2026, 9, 1, 3, 1, 15, tzinfo=UTC)
RECOMMENDED_AT = EVALUATED_AT + timedelta(seconds=5)
DECIDED_AT = RECOMMENDED_AT + timedelta(seconds=5)


def _recommendation_set(suffix: str = "A") -> ResolutionRecommendationSet:
    candidate = ResolutionCandidate(
        candidate_id=f"CAND-{suffix}",
        target_aircraft_id="MIL-F01",
        maneuver=AltitudeManeuver(9_000),
        objective=ResolutionObjective.VERTICAL_SEPARATION,
        effective_from_utc=EVALUATED_AT,
        cost=CandidateCostEstimate(operational_cost_score=10),
    )
    conflict = ConflictEvent(
        conflict_id=f"CONFLICT-{suffix}",
        pair=ConflictPair("CIV-A02", "MIL-F01"),
        status=ConflictStatus.SAFE,
        evaluated_at_utc=EVALUATED_AT,
        closest_approach_time_utc=EVALUATED_AT + timedelta(seconds=120),
        minimum_separation=SeparationMinimum(1.356, 1_016.25),
        rule_profile_id="POC_TERMINAL_V1",
    )
    validation = CandidateSafetyValidationResult(
        validation_result_id=f"VALIDATION-{suffix}",
        candidate_id=candidate.candidate_id,
        evaluated_at_utc=EVALUATED_AT,
        verdict=ResolutionValidationVerdict.SAFE,
        primary_conflict=conflict,
        secondary_conflicts=(),
        performance_feasible=True,
        rule_violations=(),
        reason_codes=(ResolutionValidationReasonCode.PRIMARY_CONFLICT_RESOLVED,),
        validation_profile_id="POC_SAFETY_V1",
    )
    recommendation = ResolutionRecommendation(
        recommendation_id=f"RECOMMENDATION-{suffix}",
        rank=1,
        candidate=candidate,
        validation_result=validation,
        generated_at_utc=RECOMMENDED_AT,
        reason_codes=tuple(RecommendationReasonCode),
        explanation="Validated safe recommendation",
    )
    return ResolutionRecommendationSet(
        recommendation_set_id=f"RECOMMENDATION-SET-{suffix}",
        source_exception_id=f"EXCEPTION-{suffix}",
        source_candidate_batch_id=f"BATCH-{suffix}",
        source_validation_run_id=f"RUN-{suffix}",
        generated_at_utc=RECOMMENDED_AT,
        ranking_policy_id="POC_RECOMMENDATION_V1",
        availability=RecommendationAvailability.AVAILABLE,
        recommendations=(recommendation,),
    )


def _decide(
    service: DeterministicControllerDecisionService,
    recommendation_set: ResolutionRecommendationSet,
    *,
    decision_type=ControllerDecisionType.ACCEPT,
    decided_at=DECIDED_AT,
    rationale=None,
    modified_maneuver=None,
):
    return service.decide(
        recommendation_set,
        recommendation_set.recommendations[0].recommendation_id,
        decision_type,
        decided_at_utc=decided_at,
        controller_position_id="RKTU-DEMO-CONTROLLER",
        rationale=rationale,
        modified_maneuver=modified_maneuver,
    )


def test_accept_publishes_first_deterministic_revision_without_applying_runtime() -> None:
    service = DeterministicControllerDecisionService()
    recommendation_set = _recommendation_set()

    log = _decide(service, recommendation_set)

    assert log.audit_log_id == "CONTROLLER-AUDIT-20260901T030125000000Z-000001"
    assert log.revision == 1
    assert service.revision == 1
    assert service.last_audit_log is log
    assert service.current_entries == log.entries
    assert len(log.entries) == 1
    entry = log.entries[0]
    assert entry.decision_id == (
        "DECISION-20260901T030125000000Z-000001-RECOMMENDATION-SET-A-RECOMMENDATION-A"
    )
    assert entry.recommendation is recommendation_set.recommendations[0]
    assert entry.authorizes_application
    assert entry.approved_candidate is recommendation_set.recommendations[0].candidate


def test_same_input_sequence_produces_equal_audit_logs() -> None:
    first_service = DeterministicControllerDecisionService()
    second_service = DeterministicControllerDecisionService()
    recommendation_sets = (_recommendation_set("A"), _recommendation_set("B"))

    first_logs = tuple(
        _decide(first_service, item, decided_at=DECIDED_AT) for item in recommendation_sets
    )
    second_logs = tuple(
        _decide(second_service, item, decided_at=DECIDED_AT) for item in recommendation_sets
    )

    assert first_logs == second_logs
    assert first_logs[1].revision == 2
    assert first_logs[1].audit_log_id.endswith("-000002")
    assert tuple(item.recommendation_set_id for item in first_logs[1].entries) == (
        "RECOMMENDATION-SET-A",
        "RECOMMENDATION-SET-B",
    )


def test_modify_is_audited_for_revalidation_and_never_authorized() -> None:
    service = DeterministicControllerDecisionService()

    log = _decide(
        service,
        _recommendation_set(),
        decision_type=ControllerDecisionType.MODIFY,
        rationale="Use a smaller vector for adjacent traffic",
        modified_maneuver=HeadingManeuver(190),
    )

    entry = log.entries[0]
    assert entry.requires_revalidation
    assert not entry.authorizes_application
    assert entry.approved_candidate is None


def test_reject_is_audited_without_an_approved_candidate() -> None:
    log = _decide(
        DeterministicControllerDecisionService(),
        _recommendation_set(),
        decision_type=ControllerDecisionType.REJECT,
        rationale="Operational context requires manual vectoring",
    )

    assert log.rejected_entries[0].approved_candidate is None


def test_duplicate_recommendation_set_is_rejected_atomically() -> None:
    service = DeterministicControllerDecisionService()
    recommendation_set = _recommendation_set()
    first = _decide(service, recommendation_set)

    with pytest.raises(ValueError, match="already has a final"):
        _decide(
            service,
            recommendation_set,
            decision_type=ControllerDecisionType.REJECT,
            rationale="Changed decision",
            decided_at=DECIDED_AT + timedelta(seconds=1),
        )

    assert service.revision == 1
    assert service.last_audit_log is first
    assert service.current_entries == first.entries


def test_unknown_recommendation_and_wrong_set_type_do_not_change_state() -> None:
    service = DeterministicControllerDecisionService()
    recommendation_set = _recommendation_set()

    with pytest.raises(KeyError, match="does not belong"):
        service.decide(
            recommendation_set,
            "RECOMMENDATION-UNKNOWN",
            ControllerDecisionType.ACCEPT,
            decided_at_utc=DECIDED_AT,
            controller_position_id="RKTU-DEMO-CONTROLLER",
        )
    with pytest.raises(TypeError, match="ResolutionRecommendationSet"):
        service.decide(  # type: ignore[arg-type]
            "set",
            "RECOMMENDATION-A",
            ControllerDecisionType.ACCEPT,
            decided_at_utc=DECIDED_AT,
            controller_position_id="RKTU-DEMO-CONTROLLER",
        )

    assert service.revision == 0
    assert service.current_entries == ()
    assert service.last_audit_log is None


def test_decision_time_is_utc_and_must_be_monotonic() -> None:
    service = DeterministicControllerDecisionService()
    local_time = DECIDED_AT.astimezone(timezone(timedelta(hours=9)))
    first = _decide(service, _recommendation_set("A"), decided_at=local_time)

    assert first.generated_at_utc == DECIDED_AT
    with pytest.raises(ValueError, match="must not precede"):
        _decide(
            service,
            _recommendation_set("B"),
            decided_at=DECIDED_AT - timedelta(seconds=1),
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        _decide(
            service,
            _recommendation_set("B"),
            decided_at=DECIDED_AT.replace(tzinfo=None),
        )

    assert service.revision == 1


def test_domain_validation_failure_does_not_consume_revision() -> None:
    service = DeterministicControllerDecisionService()

    with pytest.raises(ValueError, match="REJECT.*rationale"):
        _decide(
            service,
            _recommendation_set(),
            decision_type=ControllerDecisionType.REJECT,
        )

    assert service.revision == 0
    assert service.last_audit_log is None


def test_reset_restores_deterministic_initial_state() -> None:
    service = DeterministicControllerDecisionService()
    recommendation_set = _recommendation_set()
    first = _decide(service, recommendation_set)

    service.reset()

    assert service.revision == 0
    assert service.current_entries == ()
    assert service.last_audit_log is None
    assert _decide(service, recommendation_set) == first
