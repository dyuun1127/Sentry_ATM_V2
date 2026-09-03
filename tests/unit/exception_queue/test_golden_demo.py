from sentry_atm.conflict import PairwiseConflictDetector
from sentry_atm.domain import (
    ConflictExceptionItem,
    ExceptionStatus,
    OperationalPriorityExceptionItem,
    OperationalPriorityLevel,
    RiskLevel,
)
from sentry_atm.exception_queue import ExceptionQueueService
from sentry_atm.priority import OperationalPriorityEvaluator
from sentry_atm.risk import ConflictRiskEvaluator
from sentry_atm.scenario import build_golden_demo_scenario, build_scenario_simulation


def _refresh_queue(service, states, events):
    detector = PairwiseConflictDetector()
    risk_evaluator = ConflictRiskEvaluator()
    priority_evaluator = OperationalPriorityEvaluator()
    risks = tuple(risk_evaluator.evaluate(event) for event in detector.assess(states))
    priorities = tuple(priority_evaluator.evaluate(state, events) for state in states)
    return service.refresh(
        states[0].timestamp_utc,
        risk_assessments=risks,
        priority_assessments=priorities,
    )


def test_golden_demo_exception_queue_progression_is_deterministic() -> None:
    scenario = build_golden_demo_scenario()
    simulation = build_scenario_simulation(scenario)
    service = ExceptionQueueService()

    at_start = _refresh_queue(service, scenario.initial_states, ())
    assert at_start.active_items == ()

    simulation.clock.play()
    at_70_state = simulation.engine.tick(steps=70)
    events = simulation.timeline.poll_due_events()
    at_70 = _refresh_queue(service, at_70_state.states, events)

    assert isinstance(at_70.top_item, ConflictExceptionItem)
    assert at_70.top_item.subject_aircraft_ids == ("CIV-A02", "MIL-F01")
    assert at_70.top_item.assessment.risk_level is RiskLevel.HIGH
    assert at_70.top_item.status is ExceptionStatus.OPEN
    attention = next(
        item for item in at_70.active_items if isinstance(item, OperationalPriorityExceptionItem)
    )
    assert attention.subject_aircraft_ids == ("MIL-F01",)
    assert attention.assessment.priority_level is OperationalPriorityLevel.ATTENTION

    at_240_state = simulation.engine.tick(steps=170)
    events = (*events, *simulation.timeline.poll_due_events())
    at_240 = _refresh_queue(service, at_240_state.states, events)

    assert isinstance(at_240.top_item, OperationalPriorityExceptionItem)
    assert at_240.top_item.subject_aircraft_ids == ("MIL-T01",)
    assert at_240.top_item.assessment.priority_level is OperationalPriorityLevel.EMERGENCY
