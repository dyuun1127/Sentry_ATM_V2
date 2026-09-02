from datetime import timedelta
from math import hypot

import pytest

from sentry_atm.conflict import (
    ConflictAssessmentService,
    PairwiseConflictDetector,
    RollingConflictScheduler,
)
from sentry_atm.domain import ConflictStatus
from sentry_atm.scenario import (
    GOLDEN_DEMO_START_UTC,
    build_golden_demo_scenario,
    build_scenario_simulation,
)
from sentry_atm.simulation import SimulationClock, SyntheticAircraftRuntime

TARGET_PAIR = ("CIV-A02", "MIL-F01")


def _scheduler(simulation_clock: SimulationClock) -> RollingConflictScheduler:
    return RollingConflictScheduler(
        clock=simulation_clock,
        service=ConflictAssessmentService(PairwiseConflictDetector()),
    )


def test_t_plus_60_actual_state_matches_entry_deviation_contract() -> None:
    definition = build_golden_demo_scenario()
    mil_f01 = next(item for item in definition.aircraft if item.aircraft_id == "MIL-F01")
    actual_state = mil_f01.scheduled_states[0]
    clock = SimulationClock(start_time_utc=definition.start_time_utc)
    planned_runtime = SyntheticAircraftRuntime(
        clock=clock,
        initial_state=mil_f01.initial_state,
    )
    clock.play()
    clock.tick(steps=60)
    planned_state = planned_runtime.current_state

    assert planned_state is not None
    assert planned_state.timestamp_utc == actual_state.timestamp_utc
    assert planned_state.altitude_ft == pytest.approx(9_000.0)
    assert planned_state.heading_deg == pytest.approx(210.0)
    assert actual_state.altitude_ft == pytest.approx(7_400.0)
    assert actual_state.heading_deg == pytest.approx(180.0)
    assert hypot(
        actual_state.x_nm - planned_state.x_nm,
        actual_state.y_nm - planned_state.y_nm,
    ) == pytest.approx(2.1)


def test_t_plus_60_event_produces_calculated_golden_conflict() -> None:
    simulation = build_scenario_simulation(build_golden_demo_scenario())
    scheduler = _scheduler(simulation.clock)
    simulation.clock.play()

    initial_run = scheduler.run_if_due(simulation.engine.snapshot())
    assert initial_run is not None
    assert initial_run.predicted_events == ()

    for _ in range(11):
        pre_event_run = scheduler.run_if_due(simulation.engine.tick(steps=5))
        assert pre_event_run is not None
        assert pre_event_run.predicted_events == ()

    simulation.engine.tick(steps=5)
    assert simulation.timeline.poll_due_events() == (simulation.definition.events[0],)
    t_plus_60_run = scheduler.run_if_due(simulation.engine.snapshot())
    assert t_plus_60_run is not None
    assert len(t_plus_60_run.assessments) == 28
    assert len(t_plus_60_run.predicted_events) == 1
    conflict = t_plus_60_run.predicted_events[0]
    assert conflict.pair.aircraft_ids == TARGET_PAIR
    assert conflict.status is ConflictStatus.PREDICTED
    assert conflict.tcpa_seconds == pytest.approx(100.0)
    assert conflict.minimum_separation.horizontal_nm == pytest.approx(2.3)
    assert conflict.minimum_separation.vertical_ft == pytest.approx(500.0)
    assert conflict.closest_approach_time_utc == GOLDEN_DEMO_START_UTC + timedelta(seconds=160)
    t_plus_60_states = {state.aircraft_id: state for state in simulation.engine.snapshot().states}
    assert hypot(
        t_plus_60_states["MIL-F01"].x_nm - t_plus_60_states["CIV-A02"].x_nm,
        t_plus_60_states["MIL-F01"].y_nm - t_plus_60_states["CIV-A02"].y_nm,
    ) == pytest.approx(6.160703391789582)

    simulation.engine.tick(steps=10)
    t_plus_70_run = scheduler.run_if_due(simulation.engine.snapshot())
    assert t_plus_70_run is not None
    conflict = t_plus_70_run.predicted_events[0]
    assert conflict.pair.aircraft_ids == TARGET_PAIR
    assert conflict.tcpa_seconds == pytest.approx(90.0)
    assert conflict.minimum_separation.horizontal_nm == pytest.approx(2.3)
    assert conflict.minimum_separation.vertical_ft == pytest.approx(500.0)
    t_plus_70_states = {state.aircraft_id: state for state in simulation.engine.snapshot().states}
    assert hypot(
        t_plus_70_states["MIL-F01"].x_nm - t_plus_70_states["CIV-A02"].x_nm,
        t_plus_70_states["MIL-F01"].y_nm - t_plus_70_states["CIV-A02"].y_nm,
    ) == pytest.approx(5.634541302369005)


def test_golden_conflict_replays_identically_after_clock_reset() -> None:
    simulation = build_scenario_simulation(build_golden_demo_scenario())
    scheduler = _scheduler(simulation.clock)
    simulation.clock.play()
    simulation.engine.tick(steps=70)
    first_event = simulation.timeline.poll_due_events()
    first_run = scheduler.run_if_due(simulation.engine.snapshot())

    simulation.clock.reset()
    simulation.clock.play()
    simulation.engine.tick(steps=70)
    replayed_event = simulation.timeline.poll_due_events()
    replayed_run = scheduler.run_if_due(simulation.engine.snapshot())

    assert replayed_event == first_event
    assert replayed_run == first_run
