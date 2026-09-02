from sentry_atm.conflict import PairwiseConflictDetector
from sentry_atm.domain import (
    OperationalPriorityLevel,
    PriorityReasonCode,
    RiskLevel,
)
from sentry_atm.priority import OperationalPriorityEvaluator
from sentry_atm.risk import ConflictRiskEvaluator
from sentry_atm.scenario import build_golden_demo_scenario, build_scenario_simulation


def test_golden_t_plus_70_conflict_is_high_and_entry_priority_is_attention() -> None:
    simulation = build_scenario_simulation(build_golden_demo_scenario())
    simulation.clock.play()
    snapshot = simulation.engine.tick(steps=70)
    due_events = simulation.timeline.poll_due_events()
    conflict = PairwiseConflictDetector().detect(snapshot.states)[0]
    mil_f01 = next(state for state in snapshot.states if state.aircraft_id == "MIL-F01")

    risk = ConflictRiskEvaluator().evaluate(conflict)
    priority = OperationalPriorityEvaluator().evaluate(mil_f01, due_events)

    assert conflict.pair.aircraft_ids == ("CIV-A02", "MIL-F01")
    assert risk.risk_level is RiskLevel.HIGH
    assert risk.risk_score == 75.0
    assert risk.tcpa_seconds == 90.0
    assert priority.priority_level is OperationalPriorityLevel.ATTENTION
    assert priority.priority_score == 40.0
    assert priority.reason_codes == (PriorityReasonCode.ENTRY_CONFORMANCE_DEVIATION,)


def test_golden_t_plus_240_emergency_is_independent_priority() -> None:
    simulation = build_scenario_simulation(build_golden_demo_scenario())
    simulation.clock.play()
    simulation.engine.tick(steps=70)
    earlier_events = simulation.timeline.poll_due_events()
    snapshot = simulation.engine.tick(steps=170)
    emergency_events = simulation.timeline.poll_due_events()
    mil_t01 = next(state for state in snapshot.states if state.aircraft_id == "MIL-T01")

    priority = OperationalPriorityEvaluator().evaluate(
        mil_t01,
        (*earlier_events, *emergency_events),
    )

    assert priority.priority_level is OperationalPriorityLevel.EMERGENCY
    assert priority.priority_score == 100.0
    assert priority.source_event_ids == ("EVT-MIL-T01-EMERGENCY",)
    assert PriorityReasonCode.AIRCRAFT_CONDITION in priority.reason_codes
