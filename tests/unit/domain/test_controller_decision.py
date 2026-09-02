from datetime import UTC, datetime, timedelta, timezone

import pytest

from sentry_atm.domain import (
    AltitudeManeuver,
    CandidateCostEstimate,
    CandidateSafetyValidationResult,
    ConflictEvent,
    ConflictPair,
    ConflictStatus,
    ControllerDecisionAuditEntry,
    ControllerDecisionAuditLog,
    ControllerDecisionType,
    HeadingManeuver,
    NoActionManeuver,
    RecommendationReasonCode,
    ResolutionCandidate,
    ResolutionObjective,
    ResolutionRecommendation,
    ResolutionValidationReasonCode,
    ResolutionValidationVerdict,
    SeparationMinimum,
)

EVALUATED_AT = datetime(2026, 9, 1, 3, 1, 15, tzinfo=UTC)
RECOMMENDED_AT = EVALUATED_AT + timedelta(seconds=5)
DECIDED_AT = RECOMMENDED_AT + timedelta(seconds=5)


def _recommendation(
    suffix: str = "A",
    *,
    maneuver=None,
    objective=ResolutionObjective.VERTICAL_SEPARATION,
) -> ResolutionRecommendation:
    candidate_id = f"CAND-{suffix}"
    candidate = ResolutionCandidate(
        candidate_id=candidate_id,
        target_aircraft_id="MIL-F01",
        maneuver=AltitudeManeuver(9_000) if maneuver is None else maneuver,
        objective=objective,
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
    return ResolutionRecommendation(
        recommendation_id=f"RECOMMENDATION-{suffix}",
        rank=1,
        candidate=candidate,
        validation_result=validation,
        generated_at_utc=RECOMMENDED_AT,
        reason_codes=tuple(RecommendationReasonCode),
        explanation="Validated safe recommendation",
    )


def _entry(
    suffix: str = "A",
    *,
    decision_type=ControllerDecisionType.ACCEPT,
    recommendation=None,
    recommendation_set_id: str | None = None,
    decided_at=DECIDED_AT,
    rationale=None,
    modified_maneuver=None,
) -> ControllerDecisionAuditEntry:
    return ControllerDecisionAuditEntry(
        decision_id=f"DECISION-{suffix}",
        recommendation_set_id=(
            f"RECOMMENDATION-SET-{suffix}"
            if recommendation_set_id is None
            else recommendation_set_id
        ),
        recommendation=(_recommendation(suffix) if recommendation is None else recommendation),
        decision_type=decision_type,
        decided_at_utc=decided_at,
        controller_position_id="RKTU-DEMO-CONTROLLER",
        rationale=rationale,
        modified_maneuver=modified_maneuver,
    )


def _log(entries=(), **overrides) -> ControllerDecisionAuditLog:
    values = {
        "audit_log_id": "CONTROLLER-AUDIT-001",
        "revision": 1,
        "generated_at_utc": DECIDED_AT + timedelta(seconds=10),
        "entries": entries,
    }
    values.update(overrides)
    return ControllerDecisionAuditLog(**values)


def test_controller_decision_enum_has_stable_values() -> None:
    assert tuple(item.value for item in ControllerDecisionType) == (
        "ACCEPT",
        "MODIFY",
        "REJECT",
    )


def test_accept_normalizes_audit_metadata_and_authorizes_candidate() -> None:
    recommendation = _recommendation()
    original = recommendation
    local_time = DECIDED_AT.astimezone(timezone(timedelta(hours=9)))
    entry = ControllerDecisionAuditEntry(
        decision_id=" DECISION-A ",
        recommendation_set_id=" RECOMMENDATION-SET-A ",
        recommendation=recommendation,
        decision_type="ACCEPT",  # type: ignore[arg-type]
        decided_at_utc=local_time,
        controller_position_id=" RKTU-DEMO-CONTROLLER ",
        rationale=" Nominal safe option selected ",
    )

    assert recommendation == original
    assert entry.decision_id == "DECISION-A"
    assert entry.recommendation_set_id == "RECOMMENDATION-SET-A"
    assert entry.decision_type is ControllerDecisionType.ACCEPT
    assert entry.decided_at_utc == DECIDED_AT
    assert entry.controller_position_id == "RKTU-DEMO-CONTROLLER"
    assert entry.rationale == "Nominal safe option selected"
    assert entry.recommendation_id == "RECOMMENDATION-A"
    assert entry.candidate_id == "CAND-A"
    assert entry.authorizes_application
    assert not entry.requires_revalidation
    assert entry.approved_candidate is recommendation.candidate


def test_reject_requires_rationale_and_never_authorizes_application() -> None:
    entry = _entry(
        decision_type=ControllerDecisionType.REJECT,
        rationale="Operational context requires manual vectoring",
    )

    assert not entry.authorizes_application
    assert not entry.requires_revalidation
    assert entry.approved_candidate is None

    with pytest.raises(ValueError, match="REJECT.*rationale"):
        _entry(decision_type=ControllerDecisionType.REJECT)


def test_modify_records_changed_maneuver_and_requires_revalidation() -> None:
    changed = HeadingManeuver(190)
    entry = _entry(
        decision_type=ControllerDecisionType.MODIFY,
        rationale="Use a smaller vector for adjacent traffic",
        modified_maneuver=changed,
    )

    assert entry.modified_maneuver is changed
    assert entry.requires_revalidation
    assert not entry.authorizes_application
    assert entry.approved_candidate is None


def test_modify_requires_rationale_supported_action_and_actual_change() -> None:
    with pytest.raises(ValueError, match="MODIFY.*rationale"):
        _entry(
            decision_type=ControllerDecisionType.MODIFY,
            modified_maneuver=HeadingManeuver(190),
        )
    with pytest.raises(TypeError, match="supported action"):
        _entry(
            decision_type=ControllerDecisionType.MODIFY,
            rationale="Do nothing",
            modified_maneuver=NoActionManeuver(),
        )
    with pytest.raises(TypeError, match="supported action"):
        _entry(
            decision_type=ControllerDecisionType.MODIFY,
            rationale="Invalid object",
            modified_maneuver="maneuver",
        )
    with pytest.raises(ValueError, match="must change"):
        _entry(
            decision_type=ControllerDecisionType.MODIFY,
            rationale="No effective change",
            modified_maneuver=AltitudeManeuver(9_000),
        )


@pytest.mark.parametrize(
    "decision_type",
    [ControllerDecisionType.ACCEPT, ControllerDecisionType.REJECT],
)
def test_only_modify_can_contain_modified_maneuver(decision_type) -> None:
    with pytest.raises(ValueError, match="only MODIFY"):
        _entry(
            decision_type=decision_type,
            rationale="Rationale" if decision_type is ControllerDecisionType.REJECT else None,
            modified_maneuver=HeadingManeuver(190),
        )


def test_entry_validates_recommendation_time_and_rationale_boundaries() -> None:
    with pytest.raises(TypeError, match="ResolutionRecommendation"):
        _entry(recommendation="recommendation")
    with pytest.raises(ValueError, match="cannot precede"):
        _entry(decided_at=RECOMMENDED_AT - timedelta(seconds=1))
    with pytest.raises(ValueError, match="rationale"):
        _entry(rationale=" ")


def test_empty_audit_log_is_valid_and_has_no_latest_entry() -> None:
    log = _log()

    assert log.entries == ()
    assert log.latest_entry is None
    assert log.accepted_entries == ()
    assert log.modified_entries == ()
    assert log.rejected_entries == ()


@pytest.mark.parametrize(
    ("revision", "error_type", "message"),
    [
        (True, TypeError, "integer"),
        (1.5, TypeError, "integer"),
        (0, ValueError, "at least 1"),
    ],
)
def test_audit_log_requires_positive_integer_revision(revision, error_type, message) -> None:
    with pytest.raises(error_type, match=message):
        _log(revision=revision)


def test_audit_log_sorts_entries_and_exposes_decision_views() -> None:
    accepted = _entry("A", decided_at=DECIDED_AT)
    modified = _entry(
        "B",
        decision_type=ControllerDecisionType.MODIFY,
        decided_at=DECIDED_AT + timedelta(seconds=1),
        rationale="Change heading",
        modified_maneuver=HeadingManeuver(190),
    )
    rejected = _entry(
        "C",
        decision_type=ControllerDecisionType.REJECT,
        decided_at=DECIDED_AT + timedelta(seconds=2),
        rationale="Reject option",
    )

    log = _log((rejected, accepted, modified))

    assert log.entries == (accepted, modified, rejected)
    assert log.latest_entry is rejected
    assert log.accepted_entries == (accepted,)
    assert log.modified_entries == (modified,)
    assert log.rejected_entries == (rejected,)


@pytest.mark.parametrize("duplicate_field", ["decision", "set", "recommendation"])
def test_audit_log_requires_unique_audit_identities(duplicate_field) -> None:
    first = _entry("A")
    second_recommendation = _recommendation("B")
    values = {
        "decision_id": "DECISION-B",
        "recommendation_set_id": "RECOMMENDATION-SET-B",
        "recommendation": second_recommendation,
    }
    if duplicate_field == "decision":
        values["decision_id"] = first.decision_id
    elif duplicate_field == "set":
        values["recommendation_set_id"] = first.recommendation_set_id
    else:
        values["recommendation"] = first.recommendation
    second = ControllerDecisionAuditEntry(
        **values,
        decision_type=ControllerDecisionType.ACCEPT,
        decided_at_utc=DECIDED_AT + timedelta(seconds=1),
        controller_position_id="RKTU-DEMO-CONTROLLER",
    )

    with pytest.raises(ValueError, match="must be unique"):
        _log((first, second))


def test_audit_log_rejects_future_decision_and_normalizes_utc() -> None:
    entry = _entry()
    with pytest.raises(ValueError, match="cannot precede"):
        _log((entry,), generated_at_utc=entry.decided_at_utc - timedelta(seconds=1))

    local_time = (DECIDED_AT + timedelta(seconds=10)).astimezone(timezone(timedelta(hours=9)))
    log = _log((entry,), audit_log_id=" AUDIT ", generated_at_utc=local_time)
    assert log.audit_log_id == "AUDIT"
    assert log.generated_at_utc == DECIDED_AT + timedelta(seconds=10)


@pytest.mark.parametrize("entries", ["entries", None, ("entry",)])
def test_audit_log_validates_entry_collection(entries) -> None:
    expected = "iterable" if entries in ("entries", None) else "contain"
    with pytest.raises(TypeError, match=expected):
        _log(entries)
