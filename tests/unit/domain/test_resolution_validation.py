from datetime import UTC, datetime, timedelta, timezone

import pytest

from sentry_atm.domain import (
    CandidateSafetyValidationResult,
    ConflictEvent,
    ConflictPair,
    ConflictStatus,
    ResolutionSafetyValidationRun,
    ResolutionValidationReasonCode,
    ResolutionValidationVerdict,
    SafetyRuleViolation,
    SafetyRuleViolationType,
    SeparationMinimum,
)

EVALUATED_AT = datetime(2026, 9, 1, 3, 1, 20, tzinfo=UTC)
_DEFAULT_SECONDARY = object()
_DEFAULT_VIOLATIONS = object()
_DEFAULT_REASONS = object()
_DEFAULT_RESULTS = object()


def _conflict(
    suffix: str = "PRIMARY",
    *,
    pair: tuple[str, str] = ("CIV-A02", "MIL-F01"),
    status: ConflictStatus = ConflictStatus.SAFE,
    evaluated_at=EVALUATED_AT,
) -> ConflictEvent:
    return ConflictEvent(
        conflict_id=f"CONFLICT-{suffix}",
        pair=ConflictPair(*pair),
        status=status,
        evaluated_at_utc=evaluated_at,
        closest_approach_time_utc=evaluated_at + timedelta(seconds=90),
        minimum_separation=(
            SeparationMinimum(6.0, 1_500.0)
            if status is ConflictStatus.SAFE
            else SeparationMinimum(2.3, 500.0)
        ),
        rule_profile_id="POC_TERMINAL_V1",
    )


def _violation(suffix: str = "001") -> SafetyRuleViolation:
    return SafetyRuleViolation(
        violation_id=f"VIOLATION-{suffix}",
        rule_id="POC-MINIMUM-ALTITUDE",
        violation_type=SafetyRuleViolationType.MINIMUM_ALTITUDE,
        aircraft_id="CIV-A02",
        description="Candidate descends below configured PoC minimum altitude",
        source_reference="ASM-020 POC RULE",
    )


def _result(
    candidate_id: str = "CAND-A",
    *,
    verdict: ResolutionValidationVerdict = ResolutionValidationVerdict.SAFE,
    primary=None,
    secondary_conflicts=_DEFAULT_SECONDARY,
    performance_feasible: bool = True,
    rule_violations=_DEFAULT_VIOLATIONS,
    reason_codes=_DEFAULT_REASONS,
    evaluated_at=EVALUATED_AT,
    validation_profile_id="POC_SAFETY_V1",
) -> CandidateSafetyValidationResult:
    selected_primary = _conflict(evaluated_at=evaluated_at) if primary is None else primary
    selected_secondary = () if secondary_conflicts is _DEFAULT_SECONDARY else secondary_conflicts
    selected_violations = () if rule_violations is _DEFAULT_VIOLATIONS else rule_violations
    selected_reasons = (
        (ResolutionValidationReasonCode.PRIMARY_CONFLICT_RESOLVED,)
        if reason_codes is _DEFAULT_REASONS
        else reason_codes
    )
    return CandidateSafetyValidationResult(
        validation_result_id=f"VALIDATION-{candidate_id}",
        candidate_id=candidate_id,
        evaluated_at_utc=evaluated_at,
        verdict=verdict,
        primary_conflict=selected_primary,
        secondary_conflicts=selected_secondary,
        performance_feasible=performance_feasible,
        rule_violations=selected_violations,
        reason_codes=selected_reasons,
        validation_profile_id=validation_profile_id,
    )


def _run(results=_DEFAULT_RESULTS, **overrides) -> ResolutionSafetyValidationRun:
    values = {
        "validation_run_id": "SAFETY-RUN-001",
        "source_candidate_batch_id": "BATCH-001",
        "evaluated_at_utc": EVALUATED_AT,
        "horizon_seconds": 120.0,
        "validation_profile_id": "POC_SAFETY_V1",
        "results": (_result(),) if results is _DEFAULT_RESULTS else results,
    }
    values.update(overrides)
    return ResolutionSafetyValidationRun(**values)


def test_safety_enums_have_stable_values() -> None:
    assert tuple(item.value for item in ResolutionValidationVerdict) == (
        "SAFE",
        "UNSAFE",
        "INEFFECTIVE",
    )
    assert tuple(item.value for item in ResolutionValidationReasonCode) == (
        "PRIMARY_CONFLICT_RESOLVED",
        "PRIMARY_CONFLICT_REMAINS",
        "SECONDARY_CONFLICT_DETECTED",
        "PERFORMANCE_ENVELOPE_EXCEEDED",
        "RULE_VIOLATION",
        "NO_ACTION_BASELINE",
    )
    assert tuple(item.value for item in SafetyRuleViolationType) == (
        "MINIMUM_ALTITUDE",
        "AIRSPACE",
        "PROCEDURE",
        "OTHER",
    )


def test_rule_violation_normalizes_auditable_fields() -> None:
    violation = SafetyRuleViolation(
        violation_id=" VIOLATION-001 ",
        rule_id=" RULE-001 ",
        violation_type="MINIMUM_ALTITUDE",  # type: ignore[arg-type]
        aircraft_id=" CIV-A02 ",
        description=" Description ",
        source_reference=" TEST SOURCE ",
    )

    assert violation.violation_id == "VIOLATION-001"
    assert violation.rule_id == "RULE-001"
    assert violation.violation_type is SafetyRuleViolationType.MINIMUM_ALTITUDE
    assert violation.aircraft_id == "CIV-A02"
    assert violation.description == "Description"
    assert violation.source_reference == "TEST SOURCE"


def test_safe_result_normalizes_time_reasons_and_exposes_views() -> None:
    local_time = EVALUATED_AT.astimezone(timezone(timedelta(hours=9)))
    result = _result(
        verdict="SAFE",  # type: ignore[arg-type]
        evaluated_at=local_time,
        primary=_conflict(evaluated_at=local_time),
        reason_codes=("PRIMARY_CONFLICT_RESOLVED",),  # type: ignore[arg-type]
    )

    assert result.evaluated_at_utc == EVALUATED_AT
    assert result.verdict is ResolutionValidationVerdict.SAFE
    assert result.primary_resolved
    assert result.is_safe
    assert result.reason_codes == (ResolutionValidationReasonCode.PRIMARY_CONFLICT_RESOLVED,)


def test_ineffective_action_requires_only_remaining_primary_conflict() -> None:
    result = _result(
        "CAND-C",
        verdict=ResolutionValidationVerdict.INEFFECTIVE,
        primary=_conflict(status=ConflictStatus.PREDICTED),
        reason_codes=(ResolutionValidationReasonCode.PRIMARY_CONFLICT_REMAINS,),
    )

    assert not result.primary_resolved
    assert not result.is_safe
    assert result.verdict is ResolutionValidationVerdict.INEFFECTIVE


def test_unsafe_baseline_can_record_remaining_primary_conflict() -> None:
    result = _result(
        "CAND-E",
        verdict=ResolutionValidationVerdict.UNSAFE,
        primary=_conflict(status=ConflictStatus.PREDICTED),
        reason_codes=(
            ResolutionValidationReasonCode.PRIMARY_CONFLICT_REMAINS,
            ResolutionValidationReasonCode.NO_ACTION_BASELINE,
        ),
    )

    assert result.verdict is ResolutionValidationVerdict.UNSAFE
    assert not result.primary_resolved


def test_unsafe_result_preserves_sorted_secondary_conflict_evidence() -> None:
    secondary_b = _conflict(
        "SECONDARY-B",
        pair=("MIL-F01", "MIL-F03"),
        status=ConflictStatus.PREDICTED,
    )
    secondary_a = _conflict(
        "SECONDARY-A",
        pair=("MIL-F01", "MIL-F02"),
        status=ConflictStatus.PREDICTED,
    )

    result = _result(
        "CAND-B",
        verdict=ResolutionValidationVerdict.UNSAFE,
        secondary_conflicts=[secondary_b, secondary_a],
        reason_codes=(
            ResolutionValidationReasonCode.PRIMARY_CONFLICT_RESOLVED,
            ResolutionValidationReasonCode.SECONDARY_CONFLICT_DETECTED,
        ),
    )

    assert tuple(conflict.conflict_id for conflict in result.secondary_conflicts) == (
        "CONFLICT-SECONDARY-A",
        "CONFLICT-SECONDARY-B",
    )


def test_unsafe_result_preserves_performance_and_rule_evidence() -> None:
    violation_b = _violation("B")
    violation_a = _violation("A")
    result = _result(
        "CAND-D",
        verdict=ResolutionValidationVerdict.UNSAFE,
        performance_feasible=False,
        rule_violations=[violation_b, violation_a],
        reason_codes=(
            ResolutionValidationReasonCode.PRIMARY_CONFLICT_RESOLVED,
            ResolutionValidationReasonCode.PERFORMANCE_ENVELOPE_EXCEEDED,
            ResolutionValidationReasonCode.RULE_VIOLATION,
        ),
    )

    assert not result.performance_feasible
    assert tuple(item.violation_id for item in result.rule_violations) == (
        "VIOLATION-A",
        "VIOLATION-B",
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {
            "primary": _conflict(),
            "reason_codes": (ResolutionValidationReasonCode.PRIMARY_CONFLICT_REMAINS,),
        },
        {
            "secondary_conflicts": (
                _conflict(
                    "SECONDARY",
                    pair=("MIL-F01", "MIL-F02"),
                    status=ConflictStatus.PREDICTED,
                ),
            ),
        },
        {
            "reason_codes": (
                ResolutionValidationReasonCode.PRIMARY_CONFLICT_RESOLVED,
                ResolutionValidationReasonCode.SECONDARY_CONFLICT_DETECTED,
            ),
        },
        {"performance_feasible": False},
        {
            "reason_codes": (
                ResolutionValidationReasonCode.PRIMARY_CONFLICT_RESOLVED,
                ResolutionValidationReasonCode.PERFORMANCE_ENVELOPE_EXCEEDED,
            ),
        },
        {"rule_violations": (_violation(),)},
        {
            "reason_codes": (
                ResolutionValidationReasonCode.PRIMARY_CONFLICT_RESOLVED,
                ResolutionValidationReasonCode.RULE_VIOLATION,
            ),
        },
    ],
)
def test_result_rejects_reason_and_evidence_mismatch(overrides) -> None:
    with pytest.raises(ValueError, match="must match"):
        _result(**overrides)


def test_verdict_must_match_evidence_combination() -> None:
    with pytest.raises(ValueError, match="SAFE verdict"):
        _result(
            verdict=ResolutionValidationVerdict.SAFE,
            primary=_conflict(status=ConflictStatus.PREDICTED),
            reason_codes=(ResolutionValidationReasonCode.PRIMARY_CONFLICT_REMAINS,),
        )
    with pytest.raises(ValueError, match="INEFFECTIVE verdict"):
        _result(
            verdict=ResolutionValidationVerdict.INEFFECTIVE,
            reason_codes=(ResolutionValidationReasonCode.PRIMARY_CONFLICT_RESOLVED,),
        )
    with pytest.raises(ValueError, match="INEFFECTIVE verdict"):
        _result(
            verdict=ResolutionValidationVerdict.INEFFECTIVE,
            primary=_conflict(status=ConflictStatus.PREDICTED),
            reason_codes=(
                ResolutionValidationReasonCode.PRIMARY_CONFLICT_REMAINS,
                ResolutionValidationReasonCode.NO_ACTION_BASELINE,
            ),
        )
    with pytest.raises(ValueError, match="UNSAFE verdict"):
        _result(verdict=ResolutionValidationVerdict.UNSAFE)


def test_result_validates_primary_and_secondary_conflict_contracts() -> None:
    with pytest.raises(TypeError, match="primary_conflict"):
        _result(primary="conflict")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="share evaluated"):
        _result(primary=_conflict(evaluated_at=EVALUATED_AT + timedelta(seconds=1)))
    with pytest.raises(ValueError, match="share evaluated"):
        _result(
            secondary_conflicts=(
                _conflict(
                    "SECONDARY",
                    pair=("MIL-F01", "MIL-F02"),
                    status=ConflictStatus.PREDICTED,
                    evaluated_at=EVALUATED_AT + timedelta(seconds=1),
                ),
            )
        )
    with pytest.raises(ValueError, match="PREDICTED"):
        _result(secondary_conflicts=(_conflict("SECONDARY", pair=("MIL-F01", "MIL-F02")),))
    with pytest.raises(ValueError, match="primary Conflict Pair"):
        _result(secondary_conflicts=(_conflict("SECONDARY", status=ConflictStatus.PREDICTED),))


def test_result_rejects_duplicate_secondary_or_violation_evidence() -> None:
    secondary = _conflict(
        "SECONDARY",
        pair=("MIL-F01", "MIL-F02"),
        status=ConflictStatus.PREDICTED,
    )
    same_pair = _conflict(
        "OTHER-ID",
        pair=("MIL-F01", "MIL-F02"),
        status=ConflictStatus.PREDICTED,
    )
    with pytest.raises(ValueError, match="Conflict IDs"):
        _result(secondary_conflicts=(secondary, secondary))
    with pytest.raises(ValueError, match="Conflict Pairs"):
        _result(secondary_conflicts=(secondary, same_pair))
    violation = _violation()
    with pytest.raises(ValueError, match="violation IDs"):
        _result(rule_violations=(violation, violation))


@pytest.mark.parametrize(
    ("field_name", "invalid"),
    [
        ("secondary_conflicts", "conflicts"),
        ("secondary_conflicts", None),
        ("secondary_conflicts", ("conflict",)),
        ("rule_violations", "violations"),
        ("rule_violations", None),
        ("rule_violations", ("violation",)),
        ("reason_codes", "reasons"),
        ("reason_codes", None),
        ("reason_codes", (object(),)),
    ],
)
def test_result_rejects_invalid_evidence_iterables(field_name, invalid) -> None:
    with pytest.raises(TypeError):
        _result(**{field_name: invalid})


def test_result_rejects_empty_duplicate_reasons_and_non_boolean_performance() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        _result(reason_codes=())
    reason = ResolutionValidationReasonCode.PRIMARY_CONFLICT_RESOLVED
    with pytest.raises(ValueError, match="unique"):
        _result(reason_codes=(reason, reason))
    with pytest.raises(TypeError, match="bool"):
        _result(performance_feasible=1)  # type: ignore[arg-type]


def test_run_materializes_sorts_and_exposes_safe_results() -> None:
    safe = _result("CAND-A")
    ineffective = _result(
        "CAND-C",
        verdict=ResolutionValidationVerdict.INEFFECTIVE,
        primary=_conflict(status=ConflictStatus.PREDICTED),
        reason_codes=(ResolutionValidationReasonCode.PRIMARY_CONFLICT_REMAINS,),
    )
    source = [ineffective, safe]

    run = _run(
        source,
        validation_run_id=" SAFETY-RUN-001 ",
        source_candidate_batch_id=" BATCH-001 ",
        validation_profile_id=" POC_SAFETY_V1 ",
    )
    source.clear()

    assert run.validation_run_id == "SAFETY-RUN-001"
    assert run.source_candidate_batch_id == "BATCH-001"
    assert run.horizon_seconds == 120.0
    assert tuple(result.candidate_id for result in run.results) == ("CAND-A", "CAND-C")
    assert run.safe_results == (safe,)


def test_run_rejects_invalid_horizon_results_and_duplicates() -> None:
    with pytest.raises(ValueError, match="greater than zero"):
        _run(horizon_seconds=0)
    with pytest.raises(TypeError, match="iterable"):
        _run("results")
    with pytest.raises(TypeError, match="iterable"):
        _run(None)
    with pytest.raises(TypeError, match="unsupported"):
        _run(("result",))
    with pytest.raises(ValueError, match="must not be empty"):
        _run(())

    result = _result()
    with pytest.raises(ValueError, match="result IDs"):
        _run((result, result))
    duplicate_candidate = CandidateSafetyValidationResult(
        validation_result_id="VALIDATION-OTHER",
        candidate_id=result.candidate_id,
        evaluated_at_utc=result.evaluated_at_utc,
        verdict=result.verdict,
        primary_conflict=result.primary_conflict,
        secondary_conflicts=result.secondary_conflicts,
        performance_feasible=result.performance_feasible,
        rule_violations=result.rule_violations,
        reason_codes=result.reason_codes,
        validation_profile_id=result.validation_profile_id,
    )
    with pytest.raises(ValueError, match="candidate IDs"):
        _run((result, duplicate_candidate))


def test_run_requires_shared_time_and_profile() -> None:
    later_time = EVALUATED_AT + timedelta(seconds=1)
    later = _result(
        "CAND-B",
        evaluated_at=later_time,
        primary=_conflict(evaluated_at=later_time),
    )
    with pytest.raises(ValueError, match="evaluated_at"):
        _run((later,))
    other_profile = _result("CAND-B", validation_profile_id="OTHER")
    with pytest.raises(ValueError, match="validation_profile_id"):
        _run((other_profile,))
