"""Deterministic explainable Risk evaluation from Conflict results."""

from sentry_atm.domain import (
    POC_RISK_V1_POLICY_PROFILE,
    ConflictEvent,
    ConflictRiskAssessment,
    ConflictStatus,
    RiskLevel,
    RiskPolicyProfile,
    RiskReasonCode,
    SeparationRuleProfile,
)
from sentry_atm.regulation.policy import active_separation_profile


class ConflictRiskEvaluator:
    """Map one validated ConflictEvent to an auditable Risk assessment."""

    __slots__ = ("_risk_policy", "_separation_rule_profile")

    def __init__(
        self,
        *,
        risk_policy: RiskPolicyProfile = POC_RISK_V1_POLICY_PROFILE,
        separation_rule_profile: SeparationRuleProfile | None = None,
    ) -> None:
        if not isinstance(risk_policy, RiskPolicyProfile):
            raise TypeError("risk_policy must be a RiskPolicyProfile")
        if separation_rule_profile is None:
            separation_rule_profile = active_separation_profile()
        if not isinstance(separation_rule_profile, SeparationRuleProfile):
            raise TypeError("separation_rule_profile must be a SeparationRuleProfile")
        self._risk_policy = risk_policy
        self._separation_rule_profile = separation_rule_profile

    @property
    def risk_policy(self) -> RiskPolicyProfile:
        return self._risk_policy

    @property
    def separation_rule_profile(self) -> SeparationRuleProfile:
        return self._separation_rule_profile

    def evaluate(self, event: ConflictEvent) -> ConflictRiskAssessment:
        """Return a deterministic assessment without changing the ConflictEvent."""

        if not isinstance(event, ConflictEvent):
            raise TypeError("event must be a ConflictEvent")
        if event.rule_profile_id != self._separation_rule_profile.profile_id:
            raise ValueError("event rule_profile_id must match separation_rule_profile")
        expected_status = self._separation_rule_profile.classify(event.minimum_separation)
        if event.status is not expected_status:
            raise ValueError("event status must match separation_rule_profile classification")

        horizontal_ratio = (
            event.minimum_separation.horizontal_nm
            / self._separation_rule_profile.horizontal_threshold_nm
        )
        vertical_ratio = (
            event.minimum_separation.vertical_ft
            / self._separation_rule_profile.vertical_threshold_ft
        )
        risk_level, risk_score, reasons = self._classify(
            event,
            horizontal_ratio=horizontal_ratio,
            vertical_ratio=vertical_ratio,
        )
        return ConflictRiskAssessment(
            risk_assessment_id=(f"RISK-{self._risk_policy.profile_id}-{event.conflict_id}"),
            conflict_id=event.conflict_id,
            pair=event.pair,
            evaluated_at_utc=event.evaluated_at_utc,
            risk_score=risk_score,
            risk_level=risk_level,
            tcpa_seconds=event.tcpa_seconds,
            horizontal_separation_ratio=horizontal_ratio,
            vertical_separation_ratio=vertical_ratio,
            reason_codes=reasons,
            policy_profile_id=self._risk_policy.profile_id,
        )

    def _classify(
        self,
        event: ConflictEvent,
        *,
        horizontal_ratio: float,
        vertical_ratio: float,
    ) -> tuple[RiskLevel, float, tuple[RiskReasonCode, ...]]:
        if event.status is ConflictStatus.PREDICTED:
            reasons = [
                RiskReasonCode.PREDICTED_SEPARATION_LOSS,
                RiskReasonCode.HORIZONTAL_THRESHOLD_BREACH,
                RiskReasonCode.VERTICAL_THRESHOLD_BREACH,
            ]
            if event.tcpa_seconds == 0.0:
                reasons.append(RiskReasonCode.IMMEDIATE_SEPARATION_LOSS)
                return RiskLevel.CRITICAL, self._risk_policy.critical_score, tuple(reasons)
            if event.tcpa_seconds <= self._risk_policy.critical_tcpa_seconds:
                reasons.append(RiskReasonCode.SHORT_TCPA)
                return RiskLevel.CRITICAL, self._risk_policy.critical_score, tuple(reasons)
            if event.tcpa_seconds <= self._risk_policy.high_tcpa_seconds:
                reasons.append(RiskReasonCode.SHORT_TCPA)
                return RiskLevel.HIGH, self._risk_policy.high_score, tuple(reasons)
            return RiskLevel.MEDIUM, self._risk_policy.medium_score, tuple(reasons)

        if (
            horizontal_ratio < self._risk_policy.medium_horizontal_ratio
            and vertical_ratio < self._risk_policy.medium_vertical_ratio
        ):
            return (
                RiskLevel.MEDIUM,
                self._risk_policy.medium_score,
                (RiskReasonCode.NEAR_SEPARATION_THRESHOLD,),
            )
        return (
            RiskLevel.LOW,
            self._risk_policy.low_score,
            (RiskReasonCode.NO_PREDICTED_CONFLICT,),
        )
