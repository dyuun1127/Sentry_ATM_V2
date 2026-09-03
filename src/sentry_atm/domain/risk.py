"""Persistence-independent contracts for explainable conflict risk."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from numbers import Real

from sentry_atm.domain.conflict import ConflictPair
from sentry_atm.domain.enums import RiskLevel, RiskReasonCode
from sentry_atm.domain.time_policy import to_utc
from sentry_atm.domain.units import as_finite_float, as_non_negative_float
from sentry_atm.domain.validation import require_identifier


def _as_bounded_score(value: Real, *, field_name: str) -> float:
    score = as_finite_float(value, field_name=field_name)
    if not 0.0 <= score <= 100.0:
        raise ValueError(f"{field_name} must be in [0, 100]")
    return score


def _as_positive_float(value: Real, *, field_name: str) -> float:
    normalized = as_non_negative_float(value, field_name=field_name)
    if normalized == 0.0:
        raise ValueError(f"{field_name} must be greater than zero")
    return normalized


def _normalize_reason_codes(
    values: Iterable[RiskReasonCode],
) -> tuple[RiskReasonCode, ...]:
    if isinstance(values, (str, bytes)):
        raise TypeError("reason_codes must be an iterable of RiskReasonCode instances")
    try:
        materialized = tuple(values)
    except TypeError:
        raise TypeError("reason_codes must be an iterable of RiskReasonCode instances") from None
    if not materialized:
        raise ValueError("reason_codes must not be empty")
    if not all(isinstance(item, (str, RiskReasonCode)) for item in materialized):
        raise TypeError("reason_codes must contain only RiskReasonCode instances")
    normalized = tuple(RiskReasonCode(item) for item in materialized)
    if len(set(normalized)) != len(normalized):
        raise ValueError("reason_codes must be unique")
    return normalized


@dataclass(frozen=True, slots=True)
class RiskPolicyProfile:
    """Injectable PoC inputs for a later deterministic Risk Evaluator."""

    profile_id: str
    critical_tcpa_seconds: float
    high_tcpa_seconds: float
    medium_horizontal_ratio: float
    medium_vertical_ratio: float
    low_score: float
    medium_score: float
    high_score: float
    critical_score: float
    source_reference: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "profile_id",
            require_identifier(self.profile_id, field_name="profile_id"),
        )
        object.__setattr__(
            self,
            "critical_tcpa_seconds",
            _as_positive_float(
                self.critical_tcpa_seconds,
                field_name="critical_tcpa_seconds",
            ),
        )
        object.__setattr__(
            self,
            "high_tcpa_seconds",
            _as_positive_float(
                self.high_tcpa_seconds,
                field_name="high_tcpa_seconds",
            ),
        )
        if self.critical_tcpa_seconds >= self.high_tcpa_seconds:
            raise ValueError("critical_tcpa_seconds must be less than high_tcpa_seconds")
        for field_name in ("medium_horizontal_ratio", "medium_vertical_ratio"):
            ratio = _as_positive_float(getattr(self, field_name), field_name=field_name)
            if ratio < 1.0:
                raise ValueError(f"{field_name} must be at least 1.0")
            object.__setattr__(self, field_name, ratio)
        for field_name in ("low_score", "medium_score", "high_score", "critical_score"):
            object.__setattr__(
                self,
                field_name,
                _as_bounded_score(getattr(self, field_name), field_name=field_name),
            )
        if not (self.low_score < self.medium_score < self.high_score < self.critical_score):
            raise ValueError("risk scores must increase from low to medium to high to critical")
        object.__setattr__(
            self,
            "source_reference",
            require_identifier(
                self.source_reference,
                field_name="source_reference",
            ),
        )


POC_RISK_V1_POLICY_PROFILE = RiskPolicyProfile(
    profile_id="POC_RISK_V1",
    critical_tcpa_seconds=30.0,
    high_tcpa_seconds=120.0,
    medium_horizontal_ratio=1.25,
    medium_vertical_ratio=1.25,
    low_score=0.0,
    medium_score=40.0,
    high_score=75.0,
    critical_score=100.0,
    source_reference="ASM-024 PROVISIONAL POC ASSUMPTION",
)


@dataclass(frozen=True, slots=True)
class ConflictRiskAssessment:
    """Auditable Risk result kept separate from a ConflictEvent."""

    risk_assessment_id: str
    conflict_id: str
    pair: ConflictPair
    evaluated_at_utc: datetime
    risk_score: float
    risk_level: RiskLevel
    tcpa_seconds: float
    horizontal_separation_ratio: float
    vertical_separation_ratio: float
    reason_codes: tuple[RiskReasonCode, ...]
    policy_profile_id: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "risk_assessment_id",
            require_identifier(
                self.risk_assessment_id,
                field_name="risk_assessment_id",
            ),
        )
        object.__setattr__(
            self,
            "conflict_id",
            require_identifier(self.conflict_id, field_name="conflict_id"),
        )
        if not isinstance(self.pair, ConflictPair):
            raise TypeError("pair must be a ConflictPair")
        object.__setattr__(
            self,
            "evaluated_at_utc",
            to_utc(self.evaluated_at_utc, field_name="evaluated_at_utc"),
        )
        object.__setattr__(
            self,
            "risk_score",
            _as_bounded_score(self.risk_score, field_name="risk_score"),
        )
        object.__setattr__(self, "risk_level", RiskLevel(self.risk_level))
        for field_name in (
            "tcpa_seconds",
            "horizontal_separation_ratio",
            "vertical_separation_ratio",
        ):
            object.__setattr__(
                self,
                field_name,
                as_non_negative_float(getattr(self, field_name), field_name=field_name),
            )
        object.__setattr__(
            self,
            "reason_codes",
            _normalize_reason_codes(self.reason_codes),
        )
        object.__setattr__(
            self,
            "policy_profile_id",
            require_identifier(
                self.policy_profile_id,
                field_name="policy_profile_id",
            ),
        )
