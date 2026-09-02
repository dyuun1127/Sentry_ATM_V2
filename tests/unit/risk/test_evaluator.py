from datetime import UTC, datetime, timedelta

import pytest

from sentry_atm.domain import (
    POC_RISK_V1_POLICY_PROFILE,
    POC_TERMINAL_V1_RULE_PROFILE,
    ConflictEvent,
    ConflictPair,
    ConflictStatus,
    RiskLevel,
    RiskPolicyProfile,
    RiskReasonCode,
    SeparationMinimum,
    SeparationRuleProfile,
)
from sentry_atm.risk import ConflictRiskEvaluator

EVALUATED_AT = datetime(2026, 9, 1, 3, 1, 10, tzinfo=UTC)


def _event(
    *,
    status: ConflictStatus = ConflictStatus.PREDICTED,
    tcpa_seconds: float = 90.0,
    horizontal_nm: float = 2.3,
    vertical_ft: float = 500.0,
    rule_profile_id: str = "POC_TERMINAL_V1",
) -> ConflictEvent:
    return ConflictEvent(
        conflict_id="CONFLICT-001",
        pair=ConflictPair("MIL-F01", "CIV-A02"),
        status=status,
        evaluated_at_utc=EVALUATED_AT,
        closest_approach_time_utc=EVALUATED_AT + timedelta(seconds=tcpa_seconds),
        minimum_separation=SeparationMinimum(horizontal_nm, vertical_ft),
        rule_profile_id=rule_profile_id,
    )


def test_evaluator_exposes_injected_policies() -> None:
    evaluator = ConflictRiskEvaluator()

    assert evaluator.risk_policy is POC_RISK_V1_POLICY_PROFILE
    assert evaluator.separation_rule_profile is POC_TERMINAL_V1_RULE_PROFILE


def test_predicted_conflict_within_high_window_is_high_and_explainable() -> None:
    event = _event()

    assessment = ConflictRiskEvaluator().evaluate(event)

    assert assessment.risk_assessment_id == "RISK-POC_RISK_V1-CONFLICT-001"
    assert assessment.conflict_id == event.conflict_id
    assert assessment.pair is event.pair
    assert assessment.evaluated_at_utc == EVALUATED_AT
    assert assessment.risk_level is RiskLevel.HIGH
    assert assessment.risk_score == 75.0
    assert assessment.tcpa_seconds == 90.0
    assert assessment.horizontal_separation_ratio == pytest.approx(0.46)
    assert assessment.vertical_separation_ratio == pytest.approx(0.5)
    assert assessment.reason_codes == (
        RiskReasonCode.PREDICTED_SEPARATION_LOSS,
        RiskReasonCode.HORIZONTAL_THRESHOLD_BREACH,
        RiskReasonCode.VERTICAL_THRESHOLD_BREACH,
        RiskReasonCode.SHORT_TCPA,
    )
    assert assessment.policy_profile_id == "POC_RISK_V1"


@pytest.mark.parametrize("tcpa_seconds", [0.0, 15.0, 30.0])
def test_immediate_or_short_predicted_conflict_is_critical(tcpa_seconds: float) -> None:
    assessment = ConflictRiskEvaluator().evaluate(_event(tcpa_seconds=tcpa_seconds))

    assert assessment.risk_level is RiskLevel.CRITICAL
    assert assessment.risk_score == 100.0
    expected_reason = (
        RiskReasonCode.IMMEDIATE_SEPARATION_LOSS
        if tcpa_seconds == 0.0
        else RiskReasonCode.SHORT_TCPA
    )
    assert assessment.reason_codes[-1] is expected_reason


def test_predicted_conflict_beyond_high_window_is_medium() -> None:
    assessment = ConflictRiskEvaluator().evaluate(_event(tcpa_seconds=150.0))

    assert assessment.risk_level is RiskLevel.MEDIUM
    assert assessment.risk_score == 40.0
    assert RiskReasonCode.SHORT_TCPA not in assessment.reason_codes


def test_safe_near_threshold_pair_is_medium() -> None:
    assessment = ConflictRiskEvaluator().evaluate(
        _event(
            status=ConflictStatus.SAFE,
            horizontal_nm=6.0,
            vertical_ft=1_100.0,
        )
    )

    assert assessment.risk_level is RiskLevel.MEDIUM
    assert assessment.risk_score == 40.0
    assert assessment.reason_codes == (RiskReasonCode.NEAR_SEPARATION_THRESHOLD,)


def test_safe_pair_outside_near_threshold_is_low() -> None:
    assessment = ConflictRiskEvaluator().evaluate(
        _event(
            status=ConflictStatus.SAFE,
            horizontal_nm=7.0,
            vertical_ft=1_100.0,
        )
    )

    assert assessment.risk_level is RiskLevel.LOW
    assert assessment.risk_score == 0.0
    assert assessment.reason_codes == (RiskReasonCode.NO_PREDICTED_CONFLICT,)


def test_custom_policy_controls_risk_scores_and_windows() -> None:
    policy = RiskPolicyProfile(
        profile_id="CUSTOM_RISK",
        critical_tcpa_seconds=10.0,
        high_tcpa_seconds=60.0,
        medium_horizontal_ratio=1.1,
        medium_vertical_ratio=1.1,
        low_score=5.0,
        medium_score=25.0,
        high_score=70.0,
        critical_score=95.0,
        source_reference="TEST POLICY",
    )
    evaluator = ConflictRiskEvaluator(risk_policy=policy)

    assessment = evaluator.evaluate(_event(tcpa_seconds=90.0))

    assert assessment.risk_level is RiskLevel.MEDIUM
    assert assessment.risk_score == 25.0
    assert assessment.policy_profile_id == "CUSTOM_RISK"


def test_evaluator_rejects_inconsistent_event_or_rule_profile() -> None:
    evaluator = ConflictRiskEvaluator()

    with pytest.raises(ValueError, match="classification"):
        evaluator.evaluate(
            _event(
                status=ConflictStatus.PREDICTED,
                horizontal_nm=6.0,
                vertical_ft=1_200.0,
            )
        )
    with pytest.raises(ValueError, match="rule_profile_id"):
        evaluator.evaluate(_event(rule_profile_id="OTHER_RULE"))


def test_evaluator_supports_an_injected_separation_rule() -> None:
    rule = SeparationRuleProfile(
        profile_id="CUSTOM_RULE",
        horizontal_threshold_nm=4.0,
        vertical_threshold_ft=800.0,
        source_reference="TEST RULE",
    )
    evaluator = ConflictRiskEvaluator(separation_rule_profile=rule)
    event = _event(
        horizontal_nm=2.0,
        vertical_ft=400.0,
        rule_profile_id="CUSTOM_RULE",
    )

    assessment = evaluator.evaluate(event)

    assert assessment.horizontal_separation_ratio == 0.5
    assert assessment.vertical_separation_ratio == 0.5


def test_evaluator_rejects_wrong_dependencies_and_event_type() -> None:
    with pytest.raises(TypeError, match="RiskPolicyProfile"):
        ConflictRiskEvaluator(risk_policy="policy")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="SeparationRuleProfile"):
        ConflictRiskEvaluator(separation_rule_profile="rule")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="ConflictEvent"):
        ConflictRiskEvaluator().evaluate("event")  # type: ignore[arg-type]
