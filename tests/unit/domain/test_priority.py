from datetime import UTC, datetime, timedelta, timezone

import pytest

from sentry_atm.domain import (
    POC_OPERATIONAL_PRIORITY_V1_POLICY_PROFILE,
    OperationalPriorityAssessment,
    OperationalPriorityLevel,
    OperationalPriorityPolicyProfile,
    PriorityReasonCode,
)

EVALUATED_AT = datetime(2026, 9, 1, 3, 4, tzinfo=UTC)


def _assessment(**overrides: object) -> OperationalPriorityAssessment:
    values = {
        "priority_assessment_id": "PRIORITY-001",
        "aircraft_id": "MIL-T01",
        "evaluated_at_utc": EVALUATED_AT,
        "priority_score": 100.0,
        "priority_level": OperationalPriorityLevel.EMERGENCY,
        "reason_codes": (
            PriorityReasonCode.EMERGENCY_DECLARED,
            PriorityReasonCode.AIRCRAFT_CONDITION,
        ),
        "policy_profile_id": "POC_OPERATIONAL_PRIORITY_V1",
        "source_event_ids": ("EVT-MIL-T01-EMERGENCY",),
    }
    values.update(overrides)
    return OperationalPriorityAssessment(**values)  # type: ignore[arg-type]


def _profile(**overrides: object) -> OperationalPriorityPolicyProfile:
    values = {
        "profile_id": "PRIORITY-POLICY",
        "routine_score": 0.0,
        "entry_deviation_score": 40.0,
        "emergency_declared_score": 100.0,
        "routine_level": OperationalPriorityLevel.ROUTINE,
        "entry_deviation_level": OperationalPriorityLevel.ATTENTION,
        "emergency_declared_level": OperationalPriorityLevel.EMERGENCY,
        "source_reference": "ASM-023",
    }
    values.update(overrides)
    return OperationalPriorityPolicyProfile(**values)  # type: ignore[arg-type]


def test_priority_enums_have_stable_serialization_values() -> None:
    assert tuple(level.value for level in OperationalPriorityLevel) == (
        "ROUTINE",
        "ATTENTION",
        "URGENT",
        "EMERGENCY",
    )
    assert PriorityReasonCode.EMERGENCY_DECLARED.value == "EMERGENCY_DECLARED"


def test_default_priority_policy_records_event_mappings() -> None:
    profile = POC_OPERATIONAL_PRIORITY_V1_POLICY_PROFILE

    assert profile.profile_id == "POC_OPERATIONAL_PRIORITY_V1"
    assert profile.routine_score == 0.0
    assert profile.entry_deviation_score == 40.0
    assert profile.emergency_declared_score == 100.0
    assert profile.routine_level is OperationalPriorityLevel.ROUTINE
    assert profile.entry_deviation_level is OperationalPriorityLevel.ATTENTION
    assert profile.emergency_declared_level is OperationalPriorityLevel.EMERGENCY
    assert profile.source_reference.startswith("ASM-023")


def test_priority_policy_normalizes_values_and_enums() -> None:
    profile = _profile(
        profile_id=" PRIORITY-POLICY ",
        routine_score=0,
        entry_deviation_score=40,
        emergency_declared_score=100,
        routine_level="ROUTINE",
        entry_deviation_level="ATTENTION",
        emergency_declared_level="EMERGENCY",
        source_reference=" ASM-023 ",
    )

    assert profile.profile_id == "PRIORITY-POLICY"
    assert profile.entry_deviation_score == 40.0
    assert profile.entry_deviation_level is OperationalPriorityLevel.ATTENTION
    assert profile.source_reference == "ASM-023"


@pytest.mark.parametrize(
    ("field_name", "invalid"),
    [
        ("routine_score", -1.0),
        ("entry_deviation_score", 101.0),
        ("emergency_declared_score", float("nan")),
    ],
)
def test_priority_policy_rejects_invalid_scores(field_name: str, invalid: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        _profile(**{field_name: invalid})


def test_priority_policy_rejects_unordered_scores_and_invalid_level() -> None:
    with pytest.raises(ValueError, match="must increase"):
        _profile(entry_deviation_score=0.0)
    with pytest.raises(ValueError):
        _profile(entry_deviation_level="HIGH")
    with pytest.raises(ValueError, match="blank"):
        _profile(source_reference=" ")


def test_operational_priority_assessment_is_normalized_and_auditable() -> None:
    local_time = datetime(2026, 9, 1, 12, 4, tzinfo=timezone(timedelta(hours=9)))
    reasons = ["EMERGENCY_DECLARED", "AIRCRAFT_CONDITION"]
    event_ids = [" EVT-MIL-T01-EMERGENCY "]

    assessment = _assessment(
        priority_assessment_id=" PRIORITY-001 ",
        aircraft_id=" MIL-T01 ",
        evaluated_at_utc=local_time,
        priority_score=100,
        priority_level="EMERGENCY",
        reason_codes=reasons,
        policy_profile_id=" POC_OPERATIONAL_PRIORITY_V1 ",
        source_event_ids=event_ids,
    )
    reasons.clear()
    event_ids.clear()

    assert assessment.priority_assessment_id == "PRIORITY-001"
    assert assessment.aircraft_id == "MIL-T01"
    assert assessment.evaluated_at_utc == EVALUATED_AT
    assert assessment.priority_score == 100.0
    assert assessment.priority_level is OperationalPriorityLevel.EMERGENCY
    assert assessment.reason_codes == (
        PriorityReasonCode.EMERGENCY_DECLARED,
        PriorityReasonCode.AIRCRAFT_CONDITION,
    )
    assert assessment.policy_profile_id == "POC_OPERATIONAL_PRIORITY_V1"
    assert assessment.source_event_ids == ("EVT-MIL-T01-EMERGENCY",)


def test_routine_priority_can_have_no_source_event() -> None:
    assessment = _assessment(
        priority_score=0.0,
        priority_level=OperationalPriorityLevel.ROUTINE,
        reason_codes=(PriorityReasonCode.ROUTINE_OPERATION,),
        source_event_ids=(),
    )

    assert assessment.source_event_ids == ()


@pytest.mark.parametrize("invalid", [-1.0, 100.1, float("nan"), float("inf"), True])
def test_operational_priority_assessment_rejects_invalid_score(invalid: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        _assessment(priority_score=invalid)


def test_operational_priority_assessment_rejects_invalid_core_fields() -> None:
    with pytest.raises(ValueError, match="blank"):
        _assessment(aircraft_id=" ")
    with pytest.raises(ValueError):
        _assessment(priority_level="HIGH")
    with pytest.raises(ValueError, match="timezone-aware"):
        _assessment(evaluated_at_utc=EVALUATED_AT.replace(tzinfo=None))
    with pytest.raises(ValueError, match="blank"):
        _assessment(policy_profile_id=" ")


@pytest.mark.parametrize(
    "invalid",
    [
        (),
        "EMERGENCY_DECLARED",
        None,
        (1,),
        ("UNKNOWN",),
        (PriorityReasonCode.EMERGENCY_DECLARED, PriorityReasonCode.EMERGENCY_DECLARED),
    ],
)
def test_operational_priority_assessment_rejects_invalid_reasons(invalid: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        _assessment(reason_codes=invalid)


@pytest.mark.parametrize(
    "invalid",
    [
        "EVT-001",
        None,
        (1,),
        (" ",),
        ("EVT-001", "EVT-001"),
    ],
)
def test_operational_priority_assessment_rejects_invalid_event_ids(invalid: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        _assessment(source_event_ids=invalid)
