import json
from datetime import UTC, datetime, timedelta, timezone

import pytest

from sentry_atm.api import (
    AcknowledgeExceptionRequest,
    ConflictExceptionReadModel,
    ExceptionQueueApiContract,
    ExceptionQueueReadModelMapper,
    InProcessExceptionQueueApi,
    OperationalPriorityExceptionReadModel,
)
from sentry_atm.domain import (
    ConflictPair,
    ConflictRiskAssessment,
    OperationalPriorityAssessment,
    OperationalPriorityLevel,
    PriorityReasonCode,
    RiskLevel,
    RiskReasonCode,
)
from sentry_atm.exception_queue import ExceptionQueueService

START = datetime(2026, 9, 1, 3, 1, 10, tzinfo=UTC)


def _risk(
    at: datetime,
    *,
    level: RiskLevel = RiskLevel.HIGH,
    suffix: str = "001",
) -> ConflictRiskAssessment:
    return ConflictRiskAssessment(
        risk_assessment_id=f"RISK-{suffix}",
        conflict_id=f"CONFLICT-{suffix}",
        pair=ConflictPair("CIV-A02", "MIL-F01"),
        evaluated_at_utc=at,
        risk_score={RiskLevel.LOW: 0.0, RiskLevel.HIGH: 75.0}[level],
        risk_level=level,
        tcpa_seconds=90.0,
        horizontal_separation_ratio=0.46,
        vertical_separation_ratio=0.5,
        reason_codes=(
            RiskReasonCode.NO_PREDICTED_CONFLICT
            if level is RiskLevel.LOW
            else RiskReasonCode.PREDICTED_SEPARATION_LOSS,
        ),
        policy_profile_id="POC_RISK_V1",
    )


def _priority(at: datetime) -> OperationalPriorityAssessment:
    return OperationalPriorityAssessment(
        priority_assessment_id="PRIORITY-001",
        aircraft_id="MIL-F01",
        evaluated_at_utc=at,
        priority_score=40.0,
        priority_level=OperationalPriorityLevel.ATTENTION,
        reason_codes=(PriorityReasonCode.ENTRY_CONFORMANCE_DEVIATION,),
        policy_profile_id="POC_OPERATIONAL_PRIORITY_V1",
        source_event_ids=("EVT-MIL-F01-ENTRY-DEVIATION",),
    )


def _active_service() -> ExceptionQueueService:
    service = ExceptionQueueService()
    service.refresh(
        START,
        risk_assessments=(_risk(START),),
        priority_assessments=(_priority(START),),
    )
    return service


def test_mapper_builds_typed_ordered_json_ready_read_models() -> None:
    snapshot = _active_service().last_snapshot

    view = ExceptionQueueReadModelMapper.map(snapshot)  # type: ignore[arg-type]

    assert view.queue_snapshot_id == "QUEUE-20260901T030110000000Z-000001"
    assert view.generated_at_utc == "2026-09-01T03:01:10.000000Z"
    assert view.policy_profile_id == "POC_EXCEPTION_QUEUE_V1"
    assert view.active_count == 2
    assert view.top_exception_id == view.items[0].exception_id
    assert isinstance(view.items[0], ConflictExceptionReadModel)
    assert isinstance(view.items[1], OperationalPriorityExceptionReadModel)
    assert view.items[0].severity == "HIGH"
    assert view.items[0].tcpa_seconds == 90.0
    assert view.items[1].severity == "ATTENTION"
    assert view.items[1].source_event_ids == ("EVT-MIL-F01-ENTRY-DEVIATION",)

    payload = view.to_dict()
    assert payload["items"][0]["subject_aircraft_ids"] == ["CIV-A02", "MIL-F01"]  # type: ignore[index]
    assert payload["items"][1]["reason_codes"] == [  # type: ignore[index]
        "ENTRY_CONFORMANCE_DEVIATION"
    ]
    assert json.loads(json.dumps(payload))["active_count"] == 2


def test_mapper_excludes_resolved_by_default_and_can_include_history() -> None:
    service = _active_service()
    resolved_at = START + timedelta(seconds=10)
    snapshot = service.refresh(
        resolved_at,
        risk_assessments=(_risk(resolved_at, level=RiskLevel.LOW, suffix="002"),),
    )

    active_only = ExceptionQueueReadModelMapper.map(snapshot)
    with_history = ExceptionQueueReadModelMapper.map(snapshot, include_resolved=True)

    assert len(active_only.items) == 1
    assert active_only.items[0].kind == "OPERATIONAL_PRIORITY"
    assert active_only.active_count == 1
    assert len(with_history.items) == 2
    assert with_history.items[-1].status == "RESOLVED"
    assert with_history.active_count == 1


def test_empty_snapshot_read_model_has_no_top_item() -> None:
    service = ExceptionQueueService()
    snapshot = service.refresh(START)

    view = ExceptionQueueReadModelMapper.map(snapshot)

    assert view.items == ()
    assert view.active_count == 0
    assert view.top_exception_id is None


def test_acknowledge_request_normalizes_identifier_and_utc() -> None:
    kst = timezone(timedelta(hours=9))
    request = AcknowledgeExceptionRequest(
        exception_id=" EXCEPTION-001 ",
        acknowledged_at_utc=(START + timedelta(seconds=5)).astimezone(kst),
    )

    assert request.exception_id == "EXCEPTION-001"
    assert request.acknowledged_at_utc == START + timedelta(seconds=5)

    with pytest.raises(ValueError, match="timezone-aware"):
        AcknowledgeExceptionRequest("EXCEPTION-001", datetime(2026, 9, 1))


def test_in_process_api_reads_and_acknowledges_current_queue() -> None:
    service = _active_service()
    api = InProcessExceptionQueueApi(service)

    current = api.get_current()
    request = AcknowledgeExceptionRequest(
        exception_id=current.top_exception_id,  # type: ignore[arg-type,union-attr]
        acknowledged_at_utc=START + timedelta(seconds=1),
    )
    acknowledged = api.acknowledge(request)

    assert isinstance(api, ExceptionQueueApiContract)
    assert acknowledged.items[0].status == "ACKNOWLEDGED"
    assert acknowledged.items[0].updated_at_utc == "2026-09-01T03:01:11.000000Z"
    assert api.get_current() == acknowledged


def test_in_process_api_returns_none_before_first_snapshot() -> None:
    api = InProcessExceptionQueueApi(ExceptionQueueService())

    assert api.get_current() is None


def test_api_and_mapper_reject_wrong_boundary_types() -> None:
    with pytest.raises(TypeError, match="ExceptionQueueService"):
        InProcessExceptionQueueApi("service")  # type: ignore[arg-type]
    api = InProcessExceptionQueueApi(ExceptionQueueService())
    with pytest.raises(TypeError, match="include_resolved"):
        api.get_current(include_resolved="yes")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="AcknowledgeExceptionRequest"):
        api.acknowledge("request")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="ExceptionQueueSnapshot"):
        ExceptionQueueReadModelMapper.map("snapshot")  # type: ignore[arg-type]
    snapshot = ExceptionQueueService().refresh(START)
    with pytest.raises(TypeError, match="include_resolved"):
        ExceptionQueueReadModelMapper.map(
            snapshot,
            include_resolved="yes",  # type: ignore[arg-type]
        )


def test_invalid_acknowledge_option_does_not_mutate_service() -> None:
    service = _active_service()
    api = InProcessExceptionQueueApi(service)
    item = service.last_snapshot.top_item  # type: ignore[union-attr]
    request = AcknowledgeExceptionRequest(
        exception_id=item.exception_id,  # type: ignore[union-attr]
        acknowledged_at_utc=START + timedelta(seconds=1),
    )

    with pytest.raises(TypeError, match="include_resolved"):
        api.acknowledge(request, include_resolved="yes")  # type: ignore[arg-type]

    assert service.last_snapshot.top_item.status.value == "OPEN"  # type: ignore[union-attr]
