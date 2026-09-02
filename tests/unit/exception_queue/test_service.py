from datetime import UTC, datetime, timedelta

import pytest

from sentry_atm.domain import (
    ConflictPair,
    ConflictRiskAssessment,
    ExceptionQueuePolicy,
    ExceptionStatus,
    OperationalPriorityAssessment,
    OperationalPriorityLevel,
    PriorityReasonCode,
    RiskLevel,
    RiskReasonCode,
)
from sentry_atm.exception_queue import ExceptionQueueService

START = datetime(2026, 9, 1, 3, 0, tzinfo=UTC)


def _risk(
    at: datetime,
    *,
    level: RiskLevel = RiskLevel.HIGH,
    pair: tuple[str, str] = ("CIV-A02", "MIL-F01"),
    suffix: str = "001",
) -> ConflictRiskAssessment:
    scores = {
        RiskLevel.LOW: 0.0,
        RiskLevel.MEDIUM: 40.0,
        RiskLevel.HIGH: 75.0,
        RiskLevel.CRITICAL: 100.0,
    }
    return ConflictRiskAssessment(
        risk_assessment_id=f"RISK-{suffix}",
        conflict_id=f"CONFLICT-{suffix}",
        pair=ConflictPair(*pair),
        evaluated_at_utc=at,
        risk_score=scores[level],
        risk_level=level,
        tcpa_seconds=70.0,
        horizontal_separation_ratio=0.5,
        vertical_separation_ratio=0.5,
        reason_codes=(RiskReasonCode.PREDICTED_SEPARATION_LOSS,),
        policy_profile_id="POC_RISK_V1",
    )


def _priority(
    at: datetime,
    *,
    level: OperationalPriorityLevel = OperationalPriorityLevel.ATTENTION,
    aircraft_id: str = "MIL-F01",
    suffix: str = "001",
) -> OperationalPriorityAssessment:
    scores = {
        OperationalPriorityLevel.ROUTINE: 0.0,
        OperationalPriorityLevel.ATTENTION: 40.0,
        OperationalPriorityLevel.URGENT: 80.0,
        OperationalPriorityLevel.EMERGENCY: 100.0,
    }
    reasons = {
        OperationalPriorityLevel.ROUTINE: (PriorityReasonCode.ROUTINE_OPERATION,),
        OperationalPriorityLevel.ATTENTION: (PriorityReasonCode.ENTRY_CONFORMANCE_DEVIATION,),
        OperationalPriorityLevel.URGENT: (PriorityReasonCode.AIRCRAFT_CONDITION,),
        OperationalPriorityLevel.EMERGENCY: (PriorityReasonCode.EMERGENCY_DECLARED,),
    }
    return OperationalPriorityAssessment(
        priority_assessment_id=f"PRIORITY-{suffix}",
        aircraft_id=aircraft_id,
        evaluated_at_utc=at,
        priority_score=scores[level],
        priority_level=level,
        reason_codes=reasons[level],
        policy_profile_id="POC_OPERATIONAL_PRIORITY_V1",
    )


def test_refresh_filters_low_and_routine_assessments() -> None:
    service = ExceptionQueueService()

    snapshot = service.refresh(
        START,
        risk_assessments=(_risk(START, level=RiskLevel.LOW),),
        priority_assessments=(_priority(START, level=OperationalPriorityLevel.ROUTINE),),
    )

    assert snapshot.items == ()
    assert snapshot.top_item is None
    assert service.current_items == ()
    assert service.last_snapshot is snapshot


def test_refresh_creates_stable_ids_and_orders_cross_type_items() -> None:
    service = ExceptionQueueService()

    snapshot = service.refresh(
        START,
        risk_assessments=(_risk(START),),
        priority_assessments=(_priority(START),),
    )

    assert tuple(item.exception_id for item in snapshot.items) == (
        "EXCEPTION-CONFLICT-7-CIV-A02-7-MIL-F01",
        "EXCEPTION-PRIORITY-MIL-F01",
    )
    assert all(item.status is ExceptionStatus.OPEN for item in snapshot.items)
    assert all(item.opened_at_utc == START for item in snapshot.items)
    assert snapshot.queue_snapshot_id == "QUEUE-20260901T030000000000Z-000001"


def test_acknowledge_preserves_source_and_open_time() -> None:
    service = ExceptionQueueService()
    opened = service.refresh(START, risk_assessments=(_risk(START),)).top_item
    acknowledged_at = START + timedelta(seconds=5)

    snapshot = service.acknowledge(opened.exception_id, acknowledged_at)  # type: ignore[union-attr]
    item = snapshot.top_item

    assert item is not None
    assert item.status is ExceptionStatus.ACKNOWLEDGED
    assert item.opened_at_utc == START
    assert item.updated_at_utc == acknowledged_at
    assert item.source_assessment_id == opened.source_assessment_id  # type: ignore[union-attr]


def test_priority_item_can_be_acknowledged() -> None:
    service = ExceptionQueueService()
    item = service.refresh(START, priority_assessments=(_priority(START),)).top_item

    acknowledged = service.acknowledge(
        item.exception_id,  # type: ignore[union-attr]
        START + timedelta(seconds=1),
    ).top_item

    assert acknowledged is not None
    assert acknowledged.status is ExceptionStatus.ACKNOWLEDGED
    assert acknowledged.subject_aircraft_ids == ("MIL-F01",)


def test_active_refresh_preserves_acknowledgement_and_stable_id() -> None:
    service = ExceptionQueueService()
    first = service.refresh(START, risk_assessments=(_risk(START),)).top_item
    service.acknowledge(first.exception_id, START + timedelta(seconds=1))  # type: ignore[union-attr]
    updated_at = START + timedelta(seconds=10)

    updated = service.refresh(
        updated_at,
        risk_assessments=(_risk(updated_at, level=RiskLevel.CRITICAL, suffix="002"),),
    ).top_item

    assert updated is not None
    assert updated.exception_id == first.exception_id  # type: ignore[union-attr]
    assert updated.status is ExceptionStatus.ACKNOWLEDGED
    assert updated.opened_at_utc == START
    assert updated.updated_at_utc == updated_at
    assert updated.source_assessment_id == "RISK-002"


def test_low_assessment_resolves_then_active_assessment_reopens() -> None:
    service = ExceptionQueueService()
    service.refresh(START, risk_assessments=(_risk(START),))
    resolved_at = START + timedelta(seconds=10)

    resolved_snapshot = service.refresh(
        resolved_at,
        risk_assessments=(_risk(resolved_at, level=RiskLevel.LOW, suffix="002"),),
    )

    assert resolved_snapshot.active_items == ()
    resolved = resolved_snapshot.items[0]
    assert resolved.status is ExceptionStatus.RESOLVED
    assert resolved.opened_at_utc == START
    assert resolved.updated_at_utc == resolved_at

    reopened_at = START + timedelta(seconds=20)
    reopened = service.refresh(
        reopened_at,
        risk_assessments=(_risk(reopened_at, level=RiskLevel.MEDIUM, suffix="003"),),
    ).top_item
    assert reopened is not None
    assert reopened.exception_id == resolved.exception_id
    assert reopened.status is ExceptionStatus.OPEN
    assert reopened.opened_at_utc == reopened_at


def test_routine_assessment_resolves_priority_item() -> None:
    service = ExceptionQueueService()
    service.refresh(START, priority_assessments=(_priority(START),))
    resolved_at = START + timedelta(seconds=10)

    item = service.refresh(
        resolved_at,
        priority_assessments=(
            _priority(
                resolved_at,
                level=OperationalPriorityLevel.ROUTINE,
                suffix="002",
            ),
        ),
    ).items[0]

    assert item.status is ExceptionStatus.RESOLVED
    assert item.source_assessment_id == "PRIORITY-002"


def test_omitted_sources_are_retained_without_implicit_resolution() -> None:
    service = ExceptionQueueService()
    original = service.refresh(START, risk_assessments=(_risk(START),)).top_item

    later = service.refresh(START + timedelta(seconds=10))

    assert later.top_item == original
    assert later.top_item.status is ExceptionStatus.OPEN  # type: ignore[union-attr]


def test_acknowledge_is_idempotent_and_snapshot_revisions_are_unique() -> None:
    service = ExceptionQueueService()
    item = service.refresh(START, risk_assessments=(_risk(START),)).top_item

    first = service.acknowledge(item.exception_id, START)  # type: ignore[union-attr]
    second = service.acknowledge(item.exception_id, START)  # type: ignore[union-attr]

    assert first.items == second.items
    assert first.queue_snapshot_id.endswith("-000002")
    assert second.queue_snapshot_id.endswith("-000003")


def test_acknowledge_rejects_unknown_and_resolved_items() -> None:
    service = ExceptionQueueService()
    with pytest.raises(KeyError, match="unknown"):
        service.acknowledge("MISSING", START)
    with pytest.raises(KeyError, match="unknown"):
        service.acknowledge([], START)  # type: ignore[arg-type]

    service.refresh(START, risk_assessments=(_risk(START),))
    resolved_at = START + timedelta(seconds=1)
    resolved = service.refresh(
        resolved_at,
        risk_assessments=(_risk(resolved_at, level=RiskLevel.LOW, suffix="002"),),
    ).items[0]
    with pytest.raises(ValueError, match="resolved"):
        service.acknowledge(resolved.exception_id, resolved_at)


def test_operations_reject_time_regression_or_mismatched_evaluation_time() -> None:
    service = ExceptionQueueService()
    service.refresh(START)
    with pytest.raises(ValueError, match="must not precede"):
        service.refresh(START - timedelta(seconds=1))
    with pytest.raises(ValueError, match="generated_at"):
        service.refresh(START, risk_assessments=(_risk(START + timedelta(seconds=1)),))


@pytest.mark.parametrize("field_name", ["risk_assessments", "priority_assessments"])
@pytest.mark.parametrize("invalid", ["invalid", None, (object(),)])
def test_refresh_rejects_invalid_assessment_collections(
    field_name: str,
    invalid: object,
) -> None:
    service = ExceptionQueueService()
    arguments = {field_name: invalid}
    with pytest.raises(TypeError, match=field_name):
        service.refresh(START, **arguments)  # type: ignore[arg-type]


def test_refresh_rejects_duplicate_ids_or_subjects() -> None:
    service = ExceptionQueueService()
    first = _risk(START)
    duplicate_subject = _risk(START, suffix="002")
    with pytest.raises(ValueError, match="Aircraft pairs"):
        service.refresh(START, risk_assessments=(first, duplicate_subject))

    first_priority = _priority(START, aircraft_id="ONE", suffix="SAME")
    second_priority = _priority(START, aircraft_id="TWO", suffix="SAME")
    with pytest.raises(ValueError, match="assessment IDs"):
        service.refresh(START, priority_assessments=(first_priority, second_priority))

    with pytest.raises(ValueError, match="Aircraft IDs"):
        service.refresh(
            START,
            priority_assessments=(
                _priority(START, suffix="001"),
                _priority(START, suffix="002"),
            ),
        )


def test_conflict_stable_ids_are_unambiguous_for_hyphenated_aircraft_ids() -> None:
    service = ExceptionQueueService()

    snapshot = service.refresh(
        START,
        risk_assessments=(
            _risk(START, pair=("A-B", "C"), suffix="ONE"),
            _risk(START, pair=("A", "B-C"), suffix="TWO"),
        ),
    )

    assert len(snapshot.items) == 2
    assert len({item.exception_id for item in snapshot.items}) == 2


def test_input_order_does_not_change_snapshot_and_reset_replays_ids() -> None:
    risks = (
        _risk(START, pair=("A", "B"), suffix="A"),
        _risk(START, pair=("C", "D"), suffix="B"),
    )
    priorities = (
        _priority(START, aircraft_id="A", suffix="A"),
        _priority(START, aircraft_id="C", suffix="B"),
    )
    first_service = ExceptionQueueService()
    second_service = ExceptionQueueService()

    first = first_service.refresh(
        START,
        risk_assessments=risks,
        priority_assessments=priorities,
    )
    second = second_service.refresh(
        START,
        risk_assessments=reversed(risks),
        priority_assessments=reversed(priorities),
    )

    assert first == second
    first_service.reset()
    assert first_service.last_snapshot is None
    assert first_service.current_items == ()
    replay = first_service.refresh(
        START,
        risk_assessments=risks,
        priority_assessments=priorities,
    )
    assert replay == first


def test_constructor_validates_policy_and_exposes_it() -> None:
    service = ExceptionQueueService()
    assert isinstance(service.policy, ExceptionQueuePolicy)
    with pytest.raises(TypeError, match="ExceptionQueuePolicy"):
        ExceptionQueueService(policy="policy")  # type: ignore[arg-type]
