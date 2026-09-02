from datetime import UTC, datetime, timedelta, timezone

import pytest

from sentry_atm.domain import (
    POC_RISK_V1_POLICY_PROFILE,
    ConflictPair,
    ConflictRiskAssessment,
    RiskLevel,
    RiskPolicyProfile,
    RiskReasonCode,
)

EVALUATED_AT = datetime(2026, 9, 1, 3, 1, 10, tzinfo=UTC)


def _assessment(**overrides: object) -> ConflictRiskAssessment:
    values = {
        "risk_assessment_id": "RISK-001",
        "conflict_id": "CONFLICT-001",
        "pair": ConflictPair("MIL-F01", "CIV-A02"),
        "evaluated_at_utc": EVALUATED_AT,
        "risk_score": 72.5,
        "risk_level": RiskLevel.HIGH,
        "tcpa_seconds": 90.0,
        "horizontal_separation_ratio": 0.46,
        "vertical_separation_ratio": 0.5,
        "reason_codes": (
            RiskReasonCode.PREDICTED_SEPARATION_LOSS,
            RiskReasonCode.SHORT_TCPA,
        ),
        "policy_profile_id": "POC_RISK_V1",
    }
    values.update(overrides)
    return ConflictRiskAssessment(**values)  # type: ignore[arg-type]


def _profile(**overrides: object) -> RiskPolicyProfile:
    values = {
        "profile_id": "RISK-POLICY",
        "critical_tcpa_seconds": 30.0,
        "high_tcpa_seconds": 120.0,
        "medium_horizontal_ratio": 1.25,
        "medium_vertical_ratio": 1.25,
        "low_score": 0.0,
        "medium_score": 40.0,
        "high_score": 75.0,
        "critical_score": 100.0,
        "source_reference": "ASM-024",
    }
    values.update(overrides)
    return RiskPolicyProfile(**values)  # type: ignore[arg-type]


def test_risk_enums_have_stable_serialization_values() -> None:
    assert tuple(level.value for level in RiskLevel) == (
        "LOW",
        "MEDIUM",
        "HIGH",
        "CRITICAL",
    )
    assert RiskReasonCode.PREDICTED_SEPARATION_LOSS.value == ("PREDICTED_SEPARATION_LOSS")


def test_default_risk_policy_records_provisional_inputs() -> None:
    profile = POC_RISK_V1_POLICY_PROFILE

    assert profile.profile_id == "POC_RISK_V1"
    assert profile.critical_tcpa_seconds == 30.0
    assert profile.high_tcpa_seconds == 120.0
    assert profile.medium_horizontal_ratio == 1.25
    assert profile.medium_vertical_ratio == 1.25
    assert (
        profile.low_score,
        profile.medium_score,
        profile.high_score,
        profile.critical_score,
    ) == (0.0, 40.0, 75.0, 100.0)
    assert profile.source_reference.startswith("ASM-024")


def test_risk_policy_normalizes_values_and_rejects_invalid_order() -> None:
    profile = _profile(
        profile_id=" RISK-POLICY ",
        critical_tcpa_seconds=30,
        high_tcpa_seconds=120,
        medium_horizontal_ratio=1,
        medium_vertical_ratio=1,
        low_score=0,
        medium_score=40,
        high_score=75,
        critical_score=100,
        source_reference=" ASM-024 ",
    )

    assert profile.profile_id == "RISK-POLICY"
    assert profile.critical_tcpa_seconds == 30.0
    assert profile.source_reference == "ASM-024"

    with pytest.raises(ValueError, match="less than"):
        _profile(critical_tcpa_seconds=120.0)
    with pytest.raises(ValueError, match="must increase"):
        _profile(high_score=40.0)


@pytest.mark.parametrize(
    ("field_name", "invalid"),
    [
        ("critical_tcpa_seconds", 0.0),
        ("high_tcpa_seconds", -1.0),
        ("medium_horizontal_ratio", 0.99),
        ("medium_vertical_ratio", float("inf")),
        ("low_score", -1.0),
        ("critical_score", 100.1),
    ],
)
def test_risk_policy_rejects_invalid_numeric_inputs(
    field_name: str,
    invalid: object,
) -> None:
    with pytest.raises((TypeError, ValueError)):
        _profile(**{field_name: invalid})


def test_conflict_risk_assessment_is_immutable_normalized_and_auditable() -> None:
    local_time = datetime(2026, 9, 1, 12, 1, 10, tzinfo=timezone(timedelta(hours=9)))
    reasons = ["PREDICTED_SEPARATION_LOSS", "SHORT_TCPA"]

    assessment = _assessment(
        risk_assessment_id=" RISK-001 ",
        conflict_id=" CONFLICT-001 ",
        evaluated_at_utc=local_time,
        risk_score=72,
        risk_level="HIGH",
        reason_codes=reasons,
        policy_profile_id=" POC_RISK_V1 ",
    )
    reasons.clear()

    assert assessment.risk_assessment_id == "RISK-001"
    assert assessment.conflict_id == "CONFLICT-001"
    assert assessment.pair.aircraft_ids == ("CIV-A02", "MIL-F01")
    assert assessment.evaluated_at_utc == EVALUATED_AT
    assert assessment.risk_score == 72.0
    assert assessment.risk_level is RiskLevel.HIGH
    assert assessment.reason_codes == (
        RiskReasonCode.PREDICTED_SEPARATION_LOSS,
        RiskReasonCode.SHORT_TCPA,
    )
    assert assessment.policy_profile_id == "POC_RISK_V1"


@pytest.mark.parametrize("invalid", [-1.0, 100.1, float("nan"), float("inf"), True])
def test_conflict_risk_assessment_rejects_invalid_score(invalid: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        _assessment(risk_score=invalid)


@pytest.mark.parametrize(
    ("field_name", "invalid"),
    [
        ("tcpa_seconds", -1.0),
        ("horizontal_separation_ratio", -0.1),
        ("vertical_separation_ratio", float("nan")),
    ],
)
def test_conflict_risk_assessment_rejects_invalid_metrics(
    field_name: str,
    invalid: object,
) -> None:
    with pytest.raises((TypeError, ValueError)):
        _assessment(**{field_name: invalid})


def test_conflict_risk_assessment_rejects_wrong_pair_time_level_and_ids() -> None:
    with pytest.raises(TypeError, match="ConflictPair"):
        _assessment(pair=("CIV-A02", "MIL-F01"))
    with pytest.raises(ValueError):
        _assessment(risk_level="SEVERE")
    with pytest.raises(ValueError, match="timezone-aware"):
        _assessment(evaluated_at_utc=EVALUATED_AT.replace(tzinfo=None))
    with pytest.raises(ValueError, match="blank"):
        _assessment(conflict_id=" ")
    with pytest.raises(ValueError, match="blank"):
        _assessment(policy_profile_id=" ")


@pytest.mark.parametrize(
    "invalid",
    [
        (),
        "SHORT_TCPA",
        None,
        (1,),
        ("UNKNOWN",),
        (RiskReasonCode.SHORT_TCPA, RiskReasonCode.SHORT_TCPA),
    ],
)
def test_conflict_risk_assessment_rejects_invalid_reasons(invalid: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        _assessment(reason_codes=invalid)
