"""Deterministic scenario definitions and simulation builders."""

from sentry_atm.scenario.builder import (
    GOLDEN_DEMO_SCENARIO_ID,
    GOLDEN_DEMO_START_UTC,
    ScenarioSimulation,
    build_golden_demo_events,
    build_golden_demo_scenario,
    build_scenario_simulation,
)
from sentry_atm.scenario.event import (
    EmergencyDeclaredPayload,
    EmergencyReasonCategory,
    EntryConformanceDeviationPayload,
    ScenarioEvent,
    ScenarioEventPayload,
    ScenarioEventType,
)
from sentry_atm.scenario.model import ScenarioAircraft, ScenarioDefinition
from sentry_atm.scenario.timeline import ScenarioEventTimeline

__all__ = [
    "GOLDEN_DEMO_SCENARIO_ID",
    "GOLDEN_DEMO_START_UTC",
    "EmergencyDeclaredPayload",
    "EmergencyReasonCategory",
    "EntryConformanceDeviationPayload",
    "ScenarioAircraft",
    "ScenarioDefinition",
    "ScenarioEvent",
    "ScenarioEventPayload",
    "ScenarioEventTimeline",
    "ScenarioEventType",
    "ScenarioSimulation",
    "build_golden_demo_events",
    "build_golden_demo_scenario",
    "build_scenario_simulation",
]
