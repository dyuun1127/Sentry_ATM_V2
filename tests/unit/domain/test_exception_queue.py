from datetime import UTC, datetime, timedelta, timezone

import pytest

from sentry_atm.domain import (
    POC_EXCEPTION_QUEUE_V1_POLICY,
    ConflictExceptionItem,
    ConflictPair,
    ConflictRiskAssessment,
    ExceptionKind,
    ExceptionQueuePolicy,
    ExceptionQueueSnapshot,
    ExceptionStatus,
    OperationalPriorityAssessment,
    OperationalPriorityExceptionItem,
    OperationalPriorityLevel,
    PriorityReasonCode,
    RiskLevel,
    RiskReasonCode,
)

START_UTC = datetime(2026, 9, 1, 3, 0, tzinfo=UTC)
UPDATED_AT = START_UTC + timedelta(seconds=70)


def _risk_assessment(
    suffix: str = "001",
    *,
    level: RiskLevel = RiskLevel.HIGH,
    score: float = 75.0,
    tcpa_seconds: float = 90.0,
) -> ConflictRiskAssessment:
    return ConflictRiskAssessment(
        risk_assessment_id=f"RISK-{suffix}",
        conflict_id=f"CONFLICT-{suffix}",
        pair=ConflictPair(f"CIV-{suffix}", f"MIL-{suffix}"),
        evaluated_at_utc=UPDATED_AT,
        risk_score=score,
        risk_level=level,
        tcpa_seconds=tcpa_seconds,
        horizontal_separation_ratio=0.46,
        vertical_separation_ratio=0.5,
        reason_codes=(RiskReasonCode.PREDICTED_SEPARATION_LOSS,),
        policy_profile_id="POC_RISK_V1",
    )


def _priority_assessment(
    suffix: str = "001",
    *,
    level: OperationalPriorityLevel = OperationalPriorityLevel.EMERGENCY,
    score: float = 100.0,
) -> OperationalPriorityAssessment:
    return OperationalPriorityAssessment(
        priority_assessment_id=f"PRIORITY-{suffix}",
        aircraft_id=f"AIRCRAFT-{suffix}",
        evaluated_at_utc=UPDATED_AT,
        priority_score=score,
        priority_level=level,
        reason_codes=(PriorityReasonCode.EMERGENCY_DECLARED,),
        policy_profile_id="POC_OPERATIONAL_PRIORITY_V1",
    )


def _conflict_item(
    suffix: str = "001",
    *,
    level: RiskLevel = RiskLevel.HIGH,
    score: float = 75.0,
    tcpa_seconds: float = 90.0,
    status: ExceptionStatus = ExceptionStatus.OPEN,
) -> ConflictExceptionItem:
    return ConflictExceptionItem(
        exception_id=f"EXCEPTION-CONFLICT-{suffix}",
        assessment=_risk_assessment(
            suffix,
            level=level,
            score=score,
            tcpa_seconds=tcpa_seconds,
        ),
        opened_at_utc=START_UTC + timedelta(seconds=60),
        updated_at_utc=UPDATED_AT,
        status=status,
    )


def _priority_item(
    suffix: str = "001",
    *,
    level: OperationalPriorityLevel = OperationalPriorityLevel.EMERGENCY,
    score: float = 100.0,
    status: ExceptionStatus = ExceptionStatus.OPEN,
) -> OperationalPriorityExceptionItem:
    return OperationalPriorityExceptionItem(
        exception_id=f"EXCEPTION-PRIORITY-{suffix}",
        assessment=_priority_assessment(suffix, level=level, score=score),
        opened_at_utc=START_UTC + timedelta(seconds=60),
        updated_at_utc=UPDATED_AT,
        status=status,
    )


def _policy(**overrides: object) -> ExceptionQueuePolicy:
    values = {
        "profile_id": "QUEUE-POLICY",
        "emergency_priority_rank": 0,
        "critical_risk_rank": 1,
        "urgent_priority_rank": 2,
        "high_risk_rank": 3,
        "attention_priority_rank": 4,
        "medium_risk_rank": 5,
        "routine_priority_rank": 6,
        "low_risk_rank": 7,
        "source_reference": "TEST POLICY",
    }
    values.update(overrides)
    return ExceptionQueuePolicy(**values)  # type: ignore[arg-type]


def test_exception_enums_have_stable_values() -> None:
    assert tuple(kind.value for kind in ExceptionKind) == (
        "CONFLICT_RISK",
        "OPERATIONAL_PRIORITY",
    )
    assert tuple(status.value for status in ExceptionStatus) == (
        "OPEN",
        "ACKNOWLEDGED",
        "RESOLVED",
    )


def test_conflict_exception_exposes_typed_assessment_views() -> None:
    item = _conflict_item()

    assert item.kind is ExceptionKind.CONFLICT_RISK
    assert item.source_assessment_id == "RISK-001"
    assert item.subject_aircraft_ids == ("CIV-001", "MIL-001")
    assert item.score == 75.0
    assert item.tcpa_seconds == 90.0
    assert item.status is ExceptionStatus.OPEN


def test_priority_exception_exposes_typed_assessment_views() -> None:
    item = _priority_item()

    assert item.kind is ExceptionKind.OPERATIONAL_PRIORITY
    assert item.source_assessment_id == "PRIORITY-001"
    assert item.subject_aircraft_ids == ("AIRCRAFT-001",)
    assert item.score == 100.0
    assert item.status is ExceptionStatus.OPEN


def test_exception_items_normalize_identifiers_times_and_status() -> None:
    local_updated = UPDATED_AT.astimezone(timezone(timedelta(hours=9)))
    item = ConflictExceptionItem(
        exception_id=" EXCEPTION-001 ",
        assessment=_risk_assessment(),
        opened_at_utc=START_UTC.astimezone(timezone(timedelta(hours=9))),
        updated_at_utc=local_updated,
        status="ACKNOWLEDGED",
    )

    assert item.exception_id == "EXCEPTION-001"
    assert item.opened_at_utc == START_UTC
    assert item.updated_at_utc == UPDATED_AT
    assert item.status is ExceptionStatus.ACKNOWLEDGED


def test_exception_items_reject_wrong_assessment_type() -> None:
    with pytest.raises(TypeError, match="ConflictRiskAssessment"):
        ConflictExceptionItem(
            exception_id="EXCEPTION-001",
            assessment=_priority_assessment(),  # type: ignore[arg-type]
            opened_at_utc=START_UTC,
            updated_at_utc=UPDATED_AT,
        )
    with pytest.raises(TypeError, match="OperationalPriorityAssessment"):
        OperationalPriorityExceptionItem(
            exception_id="EXCEPTION-001",
            assessment=_risk_assessment(),  # type: ignore[arg-type]
            opened_at_utc=START_UTC,
            updated_at_utc=UPDATED_AT,
        )


def test_exception_items_reject_inconsistent_timestamps() -> None:
    assessment = _risk_assessment()
    with pytest.raises(ValueError, match="must not precede"):
        ConflictExceptionItem(
            exception_id="EXCEPTION-001",
            assessment=assessment,
            opened_at_utc=UPDATED_AT,
            updated_at_utc=START_UTC,
        )
    with pytest.raises(ValueError, match="lifecycle interval"):
        ConflictExceptionItem(
            exception_id="EXCEPTION-001",
            assessment=assessment,
            opened_at_utc=UPDATED_AT + timedelta(seconds=1),
            updated_at_utc=UPDATED_AT + timedelta(seconds=2),
        )


def test_default_policy_has_expected_cross_type_order() -> None:
    policy = POC_EXCEPTION_QUEUE_V1_POLICY
    items = (
        _conflict_item("LOW", level=RiskLevel.LOW, score=0.0),
        _priority_item("ROUTINE", level=OperationalPriorityLevel.ROUTINE, score=0.0),
        _conflict_item("MEDIUM", level=RiskLevel.MEDIUM, score=40.0),
        _priority_item("ATTENTION", level=OperationalPriorityLevel.ATTENTION, score=40.0),
        _conflict_item("HIGH", level=RiskLevel.HIGH, score=75.0),
        _priority_item("URGENT", level=OperationalPriorityLevel.URGENT, score=80.0),
        _conflict_item("CRITICAL", level=RiskLevel.CRITICAL, score=100.0),
        _priority_item("EMERGENCY", level=OperationalPriorityLevel.EMERGENCY, score=100.0),
    )

    ordered = policy.order(items)

    assert tuple(item.exception_id for item in ordered) == (
        "EXCEPTION-PRIORITY-EMERGENCY",
        "EXCEPTION-CONFLICT-CRITICAL",
        "EXCEPTION-PRIORITY-URGENT",
        "EXCEPTION-CONFLICT-HIGH",
        "EXCEPTION-PRIORITY-ATTENTION",
        "EXCEPTION-CONFLICT-MEDIUM",
        "EXCEPTION-PRIORITY-ROUTINE",
        "EXCEPTION-CONFLICT-LOW",
    )


def test_policy_orders_same_risk_by_tcpa_then_score_and_stable_id() -> None:
    items = (
        _conflict_item("B", tcpa_seconds=60.0, score=70.0),
        _conflict_item("A", tcpa_seconds=60.0, score=70.0),
        _conflict_item("SCORE", tcpa_seconds=60.0, score=80.0),
        _conflict_item("SOON", tcpa_seconds=30.0, score=70.0),
    )

    ordered = POC_EXCEPTION_QUEUE_V1_POLICY.order(reversed(items))

    assert tuple(item.exception_id for item in ordered) == (
        "EXCEPTION-CONFLICT-SOON",
        "EXCEPTION-CONFLICT-SCORE",
        "EXCEPTION-CONFLICT-A",
        "EXCEPTION-CONFLICT-B",
    )


def test_resolved_items_are_after_active_items_without_overriding_severity() -> None:
    emergency = _priority_item("EMERGENCY", status=ExceptionStatus.ACKNOWLEDGED)
    critical = _conflict_item("CRITICAL", level=RiskLevel.CRITICAL, score=100.0)
    resolved_emergency = _priority_item("RESOLVED", status=ExceptionStatus.RESOLVED)

    ordered = POC_EXCEPTION_QUEUE_V1_POLICY.order((resolved_emergency, critical, emergency))

    assert tuple(item.exception_id for item in ordered) == (
        "EXCEPTION-PRIORITY-EMERGENCY",
        "EXCEPTION-CONFLICT-CRITICAL",
        "EXCEPTION-PRIORITY-RESOLVED",
    )


def test_policy_normalizes_metadata_and_validates_ranks() -> None:
    policy = _policy(profile_id=" QUEUE-POLICY ", source_reference=" TEST POLICY ")
    assert policy.profile_id == "QUEUE-POLICY"
    assert policy.source_reference == "TEST POLICY"

    with pytest.raises(TypeError, match="integers"):
        _policy(low_risk_rank=True)
    with pytest.raises(ValueError, match="non-negative"):
        _policy(low_risk_rank=-1)
    with pytest.raises(ValueError, match="unique"):
        _policy(low_risk_rank=6)


def test_policy_rejects_wrong_items_or_iterables() -> None:
    policy = POC_EXCEPTION_QUEUE_V1_POLICY
    with pytest.raises(TypeError, match="item must"):
        policy.rank("item")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="iterable"):
        policy.order("items")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="iterable"):
        policy.order(None)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="contain"):
        policy.order(("item",))  # type: ignore[arg-type]


def test_snapshot_materializes_sorts_and_exposes_active_top_item() -> None:
    emergency = _priority_item("EMERGENCY")
    conflict = _conflict_item("HIGH")
    resolved = _priority_item("RESOLVED", status=ExceptionStatus.RESOLVED)
    source = [conflict, resolved, emergency]

    snapshot = ExceptionQueueSnapshot(
        queue_snapshot_id=" QUEUE-001 ",
        generated_at_utc=UPDATED_AT,
        items=source,
    )
    source.clear()

    assert snapshot.queue_snapshot_id == "QUEUE-001"
    assert snapshot.policy_profile_id == "POC_EXCEPTION_QUEUE_V1"
    assert snapshot.items == (emergency, conflict, resolved)
    assert snapshot.active_items == (emergency, conflict)
    assert snapshot.top_item is emergency


def test_empty_snapshot_has_no_top_item() -> None:
    snapshot = ExceptionQueueSnapshot(
        queue_snapshot_id="QUEUE-EMPTY",
        generated_at_utc=UPDATED_AT,
        items=(),
    )

    assert snapshot.active_items == ()
    assert snapshot.top_item is None


def test_snapshot_rejects_duplicate_ids_newer_items_and_wrong_policy() -> None:
    item = _conflict_item()
    with pytest.raises(ValueError, match="exception IDs"):
        ExceptionQueueSnapshot(
            queue_snapshot_id="QUEUE-001",
            generated_at_utc=UPDATED_AT,
            items=(item, item),
        )
    duplicate_source = ConflictExceptionItem(
        exception_id="EXCEPTION-OTHER",
        assessment=item.assessment,
        opened_at_utc=item.opened_at_utc,
        updated_at_utc=item.updated_at_utc,
    )
    with pytest.raises(ValueError, match="source assessment"):
        ExceptionQueueSnapshot(
            queue_snapshot_id="QUEUE-001",
            generated_at_utc=UPDATED_AT,
            items=(item, duplicate_source),
        )
    with pytest.raises(ValueError, match="newer"):
        ExceptionQueueSnapshot(
            queue_snapshot_id="QUEUE-001",
            generated_at_utc=UPDATED_AT - timedelta(seconds=1),
            items=(item,),
        )
    with pytest.raises(TypeError, match="ExceptionQueuePolicy"):
        ExceptionQueueSnapshot(
            queue_snapshot_id="QUEUE-001",
            generated_at_utc=UPDATED_AT,
            items=(item,),
            policy="policy",  # type: ignore[arg-type]
        )
