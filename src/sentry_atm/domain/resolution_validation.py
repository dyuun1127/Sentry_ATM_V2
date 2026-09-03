"""Auditable Domain contracts for isolated Resolution Safety Validation."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from sentry_atm.domain.conflict import ConflictEvent
from sentry_atm.domain.enums import (
    ConflictStatus,
    ResolutionValidationReasonCode,
    ResolutionValidationVerdict,
    SafetyRuleViolationType,
)
from sentry_atm.domain.time_policy import to_utc
from sentry_atm.domain.units import as_non_negative_float
from sentry_atm.domain.validation import require_identifier


@dataclass(frozen=True, slots=True)
class SafetyRuleViolation:
    """One source-labelled Rule violation found in an isolated simulation."""

    violation_id: str
    rule_id: str
    violation_type: SafetyRuleViolationType
    aircraft_id: str
    description: str
    source_reference: str

    def __post_init__(self) -> None:
        for field_name in (
            "violation_id",
            "rule_id",
            "aircraft_id",
            "description",
            "source_reference",
        ):
            object.__setattr__(
                self,
                field_name,
                require_identifier(getattr(self, field_name), field_name=field_name),
            )
        object.__setattr__(
            self,
            "violation_type",
            SafetyRuleViolationType(self.violation_type),
        )


@dataclass(frozen=True, slots=True)
class CandidateSafetyValidationResult:
    """Evidence and verdict for one unmodified Candidate identity."""

    validation_result_id: str
    candidate_id: str
    evaluated_at_utc: datetime
    verdict: ResolutionValidationVerdict
    primary_conflict: ConflictEvent
    secondary_conflicts: tuple[ConflictEvent, ...]
    performance_feasible: bool
    rule_violations: tuple[SafetyRuleViolation, ...]
    reason_codes: tuple[ResolutionValidationReasonCode, ...]
    validation_profile_id: str

    def __post_init__(self) -> None:
        for field_name in (
            "validation_result_id",
            "candidate_id",
            "validation_profile_id",
        ):
            object.__setattr__(
                self,
                field_name,
                require_identifier(getattr(self, field_name), field_name=field_name),
            )
        object.__setattr__(
            self,
            "evaluated_at_utc",
            to_utc(self.evaluated_at_utc, field_name="evaluated_at_utc"),
        )
        object.__setattr__(self, "verdict", ResolutionValidationVerdict(self.verdict))
        if not isinstance(self.primary_conflict, ConflictEvent):
            raise TypeError("primary_conflict must be a ConflictEvent")
        if self.primary_conflict.evaluated_at_utc != self.evaluated_at_utc:
            raise ValueError("primary_conflict must share evaluated_at_utc")
        secondary_conflicts = _materialize_secondary_conflicts(self.secondary_conflicts)
        if any(
            conflict.evaluated_at_utc != self.evaluated_at_utc for conflict in secondary_conflicts
        ):
            raise ValueError("secondary conflicts must share evaluated_at_utc")
        if any(conflict.status is not ConflictStatus.PREDICTED for conflict in secondary_conflicts):
            raise ValueError("secondary conflicts must be PREDICTED")
        if any(conflict.pair == self.primary_conflict.pair for conflict in secondary_conflicts):
            raise ValueError("secondary conflicts must not repeat the primary Conflict Pair")
        secondary_ids = tuple(conflict.conflict_id for conflict in secondary_conflicts)
        secondary_pairs = tuple(conflict.pair for conflict in secondary_conflicts)
        if len(set(secondary_ids)) != len(secondary_ids):
            raise ValueError("secondary Conflict IDs must be unique")
        if len(set(secondary_pairs)) != len(secondary_pairs):
            raise ValueError("secondary Conflict Pairs must be unique")
        object.__setattr__(
            self,
            "secondary_conflicts",
            tuple(sorted(secondary_conflicts, key=lambda conflict: conflict.pair.aircraft_ids)),
        )

        if not isinstance(self.performance_feasible, bool):
            raise TypeError("performance_feasible must be a bool")
        rule_violations = _materialize_rule_violations(self.rule_violations)
        violation_ids = tuple(violation.violation_id for violation in rule_violations)
        if len(set(violation_ids)) != len(violation_ids):
            raise ValueError("Safety Rule violation IDs must be unique")
        object.__setattr__(
            self,
            "rule_violations",
            tuple(sorted(rule_violations, key=lambda violation: violation.violation_id)),
        )
        reasons = _normalize_reason_codes(self.reason_codes)
        object.__setattr__(self, "reason_codes", reasons)
        self._validate_evidence_consistency()

    @property
    def primary_resolved(self) -> bool:
        return self.primary_conflict.status is ConflictStatus.SAFE

    @property
    def is_safe(self) -> bool:
        return self.verdict is ResolutionValidationVerdict.SAFE

    def _validate_evidence_consistency(self) -> None:
        reasons = set(self.reason_codes)
        primary_resolved = self.primary_resolved
        _require_reason_matches(
            reasons,
            ResolutionValidationReasonCode.PRIMARY_CONFLICT_RESOLVED,
            primary_resolved,
            evidence_name="primary Conflict resolution",
        )
        _require_reason_matches(
            reasons,
            ResolutionValidationReasonCode.PRIMARY_CONFLICT_REMAINS,
            not primary_resolved,
            evidence_name="remaining primary Conflict",
        )
        _require_reason_matches(
            reasons,
            ResolutionValidationReasonCode.SECONDARY_CONFLICT_DETECTED,
            bool(self.secondary_conflicts),
            evidence_name="secondary Conflicts",
        )
        _require_reason_matches(
            reasons,
            ResolutionValidationReasonCode.PERFORMANCE_ENVELOPE_EXCEEDED,
            not self.performance_feasible,
            evidence_name="Performance Envelope result",
        )
        _require_reason_matches(
            reasons,
            ResolutionValidationReasonCode.RULE_VIOLATION,
            bool(self.rule_violations),
            evidence_name="Safety Rule violations",
        )

        has_safety_failure = (
            bool(self.secondary_conflicts)
            or not self.performance_feasible
            or bool(self.rule_violations)
        )
        is_baseline = ResolutionValidationReasonCode.NO_ACTION_BASELINE in reasons
        if self.verdict is ResolutionValidationVerdict.SAFE:
            if not primary_resolved or has_safety_failure:
                raise ValueError("SAFE verdict requires resolved primary Conflict and no failures")
        elif self.verdict is ResolutionValidationVerdict.INEFFECTIVE:
            if primary_resolved or has_safety_failure or is_baseline:
                raise ValueError(
                    "INEFFECTIVE verdict requires only a remaining primary Conflict action"
                )
        elif not has_safety_failure and not (not primary_resolved and is_baseline):
            raise ValueError("UNSAFE verdict requires a safety failure or unsafe baseline")


@dataclass(frozen=True, slots=True)
class ResolutionSafetyValidationRun:
    """Deterministically ordered result set for one Candidate Batch."""

    validation_run_id: str
    source_candidate_batch_id: str
    evaluated_at_utc: datetime
    horizon_seconds: float
    validation_profile_id: str
    results: tuple[CandidateSafetyValidationResult, ...]

    def __post_init__(self) -> None:
        for field_name in (
            "validation_run_id",
            "source_candidate_batch_id",
            "validation_profile_id",
        ):
            object.__setattr__(
                self,
                field_name,
                require_identifier(getattr(self, field_name), field_name=field_name),
            )
        object.__setattr__(
            self,
            "evaluated_at_utc",
            to_utc(self.evaluated_at_utc, field_name="evaluated_at_utc"),
        )
        horizon = as_non_negative_float(self.horizon_seconds, field_name="horizon_seconds")
        if horizon == 0.0:
            raise ValueError("horizon_seconds must be greater than zero")
        object.__setattr__(self, "horizon_seconds", horizon)
        results = _materialize_results(self.results)
        if not results:
            raise ValueError("results must not be empty")
        result_ids = tuple(result.validation_result_id for result in results)
        candidate_ids = tuple(result.candidate_id for result in results)
        if len(set(result_ids)) != len(result_ids):
            raise ValueError("validation result IDs must be unique")
        if len(set(candidate_ids)) != len(candidate_ids):
            raise ValueError("validated candidate IDs must be unique")
        if any(result.evaluated_at_utc != self.evaluated_at_utc for result in results):
            raise ValueError("results must share run evaluated_at_utc")
        if any(result.validation_profile_id != self.validation_profile_id for result in results):
            raise ValueError("results must use run validation_profile_id")
        object.__setattr__(
            self,
            "results",
            tuple(sorted(results, key=lambda result: result.candidate_id)),
        )

    @property
    def safe_results(self) -> tuple[CandidateSafetyValidationResult, ...]:
        return tuple(result for result in self.results if result.is_safe)


def _require_reason_matches(
    reasons: set[ResolutionValidationReasonCode],
    reason: ResolutionValidationReasonCode,
    evidence_present: bool,
    *,
    evidence_name: str,
) -> None:
    if (reason in reasons) is not evidence_present:
        raise ValueError(f"{reason.value} must match {evidence_name}")


def _normalize_reason_codes(
    values: Iterable[ResolutionValidationReasonCode],
) -> tuple[ResolutionValidationReasonCode, ...]:
    if isinstance(values, (str, bytes)):
        raise TypeError("reason_codes must be an iterable of ResolutionValidationReasonCode")
    try:
        materialized = tuple(values)
    except TypeError:
        raise TypeError(
            "reason_codes must be an iterable of ResolutionValidationReasonCode"
        ) from None
    if not materialized:
        raise ValueError("reason_codes must not be empty")
    if not all(isinstance(value, (str, ResolutionValidationReasonCode)) for value in materialized):
        raise TypeError("reason_codes must contain ResolutionValidationReasonCode values")
    normalized = tuple(ResolutionValidationReasonCode(value) for value in materialized)
    if len(set(normalized)) != len(normalized):
        raise ValueError("reason_codes must be unique")
    return normalized


def _materialize_secondary_conflicts(
    values: Iterable[ConflictEvent],
) -> tuple[ConflictEvent, ...]:
    return _materialize_typed(
        values,
        ConflictEvent,
        field_name="secondary_conflicts",
    )


def _materialize_rule_violations(
    values: Iterable[SafetyRuleViolation],
) -> tuple[SafetyRuleViolation, ...]:
    return _materialize_typed(
        values,
        SafetyRuleViolation,
        field_name="rule_violations",
    )


def _materialize_results(
    values: Iterable[CandidateSafetyValidationResult],
) -> tuple[CandidateSafetyValidationResult, ...]:
    return _materialize_typed(
        values,
        CandidateSafetyValidationResult,
        field_name="results",
    )


def _materialize_typed(values: Iterable[object], expected_type: type, *, field_name: str) -> tuple:
    if isinstance(values, (str, bytes)):
        raise TypeError(f"{field_name} must be an iterable")
    try:
        materialized = tuple(values)
    except TypeError:
        raise TypeError(f"{field_name} must be an iterable") from None
    if not all(isinstance(value, expected_type) for value in materialized):
        raise TypeError(f"{field_name} contains an unsupported value")
    return materialized
