from datetime import UTC, datetime, timedelta

import pytest

from sentry_atm.scenario import (
    EntryConformanceDeviationPayload,
    ScenarioEvent,
    ScenarioEventTimeline,
    ScenarioEventType,
)
from sentry_atm.simulation import SimulationClock

START_UTC = datetime(2026, 9, 2, 3, 0, tzinfo=UTC)


def _event(event_id: str, offset_seconds: int) -> ScenarioEvent:
    return ScenarioEvent(
        event_id=event_id,
        event_type=ScenarioEventType.ENTRY_CONFORMANCE_DEVIATION,
        scheduled_time_utc=START_UTC + timedelta(seconds=offset_seconds),
        target_aircraft_id="MIL-F01",
        payload=EntryConformanceDeviationPayload(
            expected_entry_point="ENTRY-A",
            expected_altitude_ft=9_000.0,
            expected_heading_deg=210.0,
            actual_altitude_ft=7_400.0,
            lateral_deviation_nm=2.1,
            time_deviation_seconds=25.0,
        ),
    )


def test_timeline_emits_due_events_once_in_declared_order() -> None:
    clock = SimulationClock(start_time_utc=START_UTC)
    first = _event("EVT-001", 60)
    second = _event("EVT-002", 240)
    timeline = ScenarioEventTimeline(clock=clock, events=(first, second))

    assert timeline.clock is clock
    assert timeline.events == (first, second)
    assert timeline.pending_events == (first, second)
    assert timeline.poll_due_events() == ()

    clock.play()
    clock.tick(steps=59)
    assert timeline.poll_due_events() == ()
    clock.tick()
    assert timeline.poll_due_events() == (first,)
    assert timeline.poll_due_events() == ()

    clock.tick(steps=180)
    assert timeline.poll_due_events() == (second,)
    assert timeline.pending_events == ()


def test_timeline_catches_up_all_due_events_after_clock_jump() -> None:
    clock = SimulationClock(start_time_utc=START_UTC)
    first = _event("EVT-001", 60)
    second = _event("EVT-002", 60)
    third = _event("EVT-003", 240)
    timeline = ScenarioEventTimeline(clock=clock, events=(first, second, third))

    clock.play()
    clock.tick(steps=240)

    assert timeline.poll_due_events() == (first, second, third)


def test_timeline_defers_due_event_while_paused() -> None:
    clock = SimulationClock(start_time_utc=START_UTC)
    event = _event("EVT-001", 60)
    timeline = ScenarioEventTimeline(clock=clock, events=(event,))

    clock.play()
    clock.tick(steps=60)
    clock.pause()
    assert timeline.poll_due_events() == ()

    clock.play()
    assert timeline.poll_due_events() == (event,)


def test_timeline_replays_events_after_clock_reset() -> None:
    clock = SimulationClock(start_time_utc=START_UTC)
    event = _event("EVT-001", 60)
    timeline = ScenarioEventTimeline(clock=clock, events=(event,))

    clock.play()
    clock.tick(steps=60)
    assert timeline.poll_due_events() == (event,)

    clock.reset()
    assert timeline.pending_events == (event,)
    assert timeline.poll_due_events() == ()
    clock.play()
    clock.tick(steps=60)
    assert timeline.poll_due_events() == (event,)


def test_timeline_rejects_invalid_clock_event_set_or_order() -> None:
    clock = SimulationClock(start_time_utc=START_UTC)
    event = _event("EVT-001", 60)

    with pytest.raises(TypeError, match="SimulationClock"):
        ScenarioEventTimeline(clock="clock", events=())  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="ScenarioEvent"):
        ScenarioEventTimeline(clock=clock, events=("event",))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="IDs must be unique"):
        ScenarioEventTimeline(clock=clock, events=(event, event))
    with pytest.raises(ValueError, match="precede"):
        ScenarioEventTimeline(clock=clock, events=(_event("EARLY", -1),))
    with pytest.raises(ValueError, match="ordered"):
        ScenarioEventTimeline(
            clock=clock,
            events=(_event("LATE", 61), _event("EARLIER", 60)),
        )
