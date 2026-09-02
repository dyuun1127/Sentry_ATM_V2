from datetime import UTC, datetime, timedelta

import pytest

from sentry_atm.domain import (
    AircraftState,
    DataSource,
    EmergencyStatus,
    EmergencyType,
    OperationalPriorityLevel,
    PriorityReasonCode,
)
from sentry_atm.priority import OperationalPriorityEvaluator
from sentry_atm.scenario import (
    EmergencyDeclaredPayload,
    EmergencyReasonCategory,
    EntryConformanceDeviationPayload,
    ScenarioEvent,
    ScenarioEventType,
)

START_UTC = datetime(2026, 9, 1, 3, 0, tzinfo=UTC)


def _state(
    aircraft_id: str = "MIL-T01",
    *,
    offset_seconds: int = 240,
    emergency_status: EmergencyStatus = EmergencyStatus.NONE,
    emergency_type: EmergencyType | None = None,
) -> AircraftState:
    return AircraftState(
        aircraft_id=aircraft_id,
        timestamp_utc=START_UTC + timedelta(seconds=offset_seconds),
        x_nm=0.0,
        y_nm=0.0,
        altitude_ft=7_000.0,
        ground_speed_kt=210.0,
        heading_deg=300.0,
        vertical_speed_fpm=0.0,
        source=DataSource.SYNTHETIC,
        emergency_status=emergency_status,
        emergency_type=emergency_type,
    )


def _entry_event(
    *,
    event_id: str = "EVT-ENTRY",
    target_aircraft_id: str = "MIL-T01",
    offset_seconds: int = 60,
) -> ScenarioEvent:
    return ScenarioEvent(
        event_id=event_id,
        event_type=ScenarioEventType.ENTRY_CONFORMANCE_DEVIATION,
        scheduled_time_utc=START_UTC + timedelta(seconds=offset_seconds),
        target_aircraft_id=target_aircraft_id,
        payload=EntryConformanceDeviationPayload(
            expected_entry_point="ENTRY-A",
            expected_altitude_ft=9_000.0,
            expected_heading_deg=210.0,
            actual_altitude_ft=7_400.0,
            lateral_deviation_nm=2.1,
            time_deviation_seconds=25.0,
        ),
    )


def _emergency_event(
    *,
    event_id: str = "EVT-EMERGENCY",
    target_aircraft_id: str = "MIL-T01",
    offset_seconds: int = 240,
) -> ScenarioEvent:
    return ScenarioEvent(
        event_id=event_id,
        event_type=ScenarioEventType.EMERGENCY_DECLARED,
        scheduled_time_utc=START_UTC + timedelta(seconds=offset_seconds),
        target_aircraft_id=target_aircraft_id,
        payload=EmergencyDeclaredPayload(
            emergency_type=EmergencyType.PRIORITY_RETURN,
            reason_category=EmergencyReasonCategory.AIRCRAFT_CONDITION,
        ),
    )


def test_routine_aircraft_has_routine_priority_without_source_event() -> None:
    evaluator = OperationalPriorityEvaluator()

    assessment = evaluator.evaluate(_state(offset_seconds=0))

    assert evaluator.policy.profile_id == "POC_OPERATIONAL_PRIORITY_V1"
    assert assessment.aircraft_id == "MIL-T01"
    assert assessment.priority_score == 0.0
    assert assessment.priority_level is OperationalPriorityLevel.ROUTINE
    assert assessment.reason_codes == (PriorityReasonCode.ROUTINE_OPERATION,)
    assert assessment.source_event_ids == ()


def test_due_entry_deviation_requires_attention() -> None:
    event = _entry_event()

    assessment = OperationalPriorityEvaluator().evaluate(
        _state(offset_seconds=70),
        (event,),
    )

    assert assessment.priority_score == 40.0
    assert assessment.priority_level is OperationalPriorityLevel.ATTENTION
    assert assessment.reason_codes == (PriorityReasonCode.ENTRY_CONFORMANCE_DEVIATION,)
    assert assessment.source_event_ids == ("EVT-ENTRY",)


def test_due_emergency_has_emergency_priority_and_reason() -> None:
    event = _emergency_event()

    assessment = OperationalPriorityEvaluator().evaluate(_state(), (event,))

    assert assessment.priority_assessment_id.startswith(
        "PRIORITY-POC_OPERATIONAL_PRIORITY_V1-20260901T030400"
    )
    assert assessment.priority_score == 100.0
    assert assessment.priority_level is OperationalPriorityLevel.EMERGENCY
    assert assessment.reason_codes == (
        PriorityReasonCode.EMERGENCY_DECLARED,
        PriorityReasonCode.AIRCRAFT_CONDITION,
    )
    assert assessment.source_event_ids == ("EVT-EMERGENCY",)


def test_declared_state_is_emergency_even_without_source_event() -> None:
    state = _state(
        emergency_status=EmergencyStatus.DECLARED,
        emergency_type=EmergencyType.PRIORITY_RETURN,
    )

    assessment = OperationalPriorityEvaluator().evaluate(state)

    assert assessment.priority_level is OperationalPriorityLevel.EMERGENCY
    assert assessment.reason_codes == (PriorityReasonCode.EMERGENCY_DECLARED,)
    assert assessment.source_event_ids == ()


def test_future_and_other_aircraft_events_do_not_leak_into_priority() -> None:
    events = (
        _emergency_event(offset_seconds=241),
        _emergency_event(event_id="EVT-OTHER", target_aircraft_id="CIV-A01"),
    )

    assessment = OperationalPriorityEvaluator().evaluate(_state(), events)

    assert assessment.priority_level is OperationalPriorityLevel.ROUTINE
    assert assessment.source_event_ids == ()


def test_active_events_are_sorted_and_all_supporting_reasons_are_preserved() -> None:
    entry = _entry_event(offset_seconds=60)
    emergency = _emergency_event(offset_seconds=240)

    first = OperationalPriorityEvaluator().evaluate(_state(), (emergency, entry))
    second = OperationalPriorityEvaluator().evaluate(_state(), (entry, emergency))

    assert first == second
    assert first.priority_level is OperationalPriorityLevel.EMERGENCY
    assert first.reason_codes == (
        PriorityReasonCode.EMERGENCY_DECLARED,
        PriorityReasonCode.AIRCRAFT_CONDITION,
        PriorityReasonCode.ENTRY_CONFORMANCE_DEVIATION,
    )
    assert first.source_event_ids == ("EVT-ENTRY", "EVT-EMERGENCY")


def test_evaluator_materializes_event_iterable() -> None:
    source = [_entry_event()]
    evaluator = OperationalPriorityEvaluator()

    assessment = evaluator.evaluate(_state(offset_seconds=70), source)
    source.clear()

    assert assessment.source_event_ids == ("EVT-ENTRY",)


def test_evaluator_rejects_wrong_policy_state_or_events() -> None:
    with pytest.raises(TypeError, match="OperationalPriorityPolicyProfile"):
        OperationalPriorityEvaluator("policy")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="AircraftState"):
        OperationalPriorityEvaluator().evaluate("state")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="iterable"):
        OperationalPriorityEvaluator().evaluate(_state(), "events")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="iterable"):
        OperationalPriorityEvaluator().evaluate(_state(), None)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="ScenarioEvent"):
        OperationalPriorityEvaluator().evaluate(_state(), ("event",))  # type: ignore[arg-type]


def test_evaluator_rejects_duplicate_event_ids() -> None:
    event = _entry_event()

    with pytest.raises(ValueError, match="unique"):
        OperationalPriorityEvaluator().evaluate(_state(), (event, event))
