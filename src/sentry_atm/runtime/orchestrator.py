"""Deterministic Golden Demo traffic-to-exception step orchestration."""

from dataclasses import dataclass
from datetime import datetime

from sentry_atm.domain import (
    ConflictAssessmentRun,
    ConflictRiskAssessment,
    ExceptionQueueSnapshot,
    OperationalPriorityAssessment,
    PredictionRun,
)
from sentry_atm.runtime.composition import GoldenDemoRuntime
from sentry_atm.scenario import ScenarioEvent
from sentry_atm.simulation import TrafficSnapshot


@dataclass(frozen=True, slots=True)
class GoldenDemoStepResult:
    """Immutable outputs calculated during one Simulation Clock step."""

    step_id: str
    timestamp_utc: datetime
    traffic_snapshot: TrafficSnapshot
    due_events: tuple[ScenarioEvent, ...]
    prediction_run: PredictionRun | None
    conflict_run: ConflictAssessmentRun | None
    risk_assessments: tuple[ConflictRiskAssessment, ...]
    priority_assessments: tuple[OperationalPriorityAssessment, ...]
    exception_queue_snapshot: ExceptionQueueSnapshot


class GoldenDemoStepOrchestrator:
    """Advance and calculate the deterministic pre-resolution Golden Demo pipeline."""

    __slots__ = (
        "_last_result",
        "_last_tick_count",
        "_observed_reset_count",
        "_runtime",
    )

    def __init__(self, runtime: GoldenDemoRuntime) -> None:
        if not isinstance(runtime, GoldenDemoRuntime):
            raise TypeError("runtime must be a GoldenDemoRuntime")
        self._runtime = runtime
        self._observed_reset_count = runtime.simulation.clock.reset_count
        self._last_tick_count: int | None = None
        self._last_result: GoldenDemoStepResult | None = None

    @property
    def runtime(self) -> GoldenDemoRuntime:
        return self._runtime

    @property
    def last_result(self) -> GoldenDemoStepResult | None:
        self._synchronize_reset()
        return self._last_result

    def step(self, advance_steps: int = 1) -> GoldenDemoStepResult:
        """Advance by explicit ticks and calculate one ordered pipeline snapshot."""

        if isinstance(advance_steps, bool) or not isinstance(advance_steps, int):
            raise TypeError("advance_steps must be an integer")
        if advance_steps < 0:
            raise ValueError("advance_steps must be non-negative")
        self._synchronize_reset()

        simulation = self._runtime.simulation
        clock = simulation.clock
        if not clock.is_running:
            raise ValueError("Simulation Clock must be RUNNING before a Step")
        traffic_snapshot = (
            simulation.engine.tick(steps=advance_steps)
            if advance_steps > 0
            else simulation.engine.snapshot()
        )
        if self._last_tick_count == clock.tick_count:
            raise ValueError("a Golden Demo Step already exists for the current Tick")

        due_events = simulation.timeline.poll_due_events()
        prediction_run = self._runtime.prediction_scheduler.run_if_due(traffic_snapshot)
        conflict_run = self._runtime.conflict_scheduler.run_if_due(traffic_snapshot)
        risk_assessments = (
            tuple(
                self._runtime.risk_evaluator.evaluate(event) for event in conflict_run.assessments
            )
            if conflict_run is not None
            else ()
        )
        priority_assessments = tuple(
            self._runtime.priority_evaluator.evaluate(state, self._runtime.definition.events)
            for state in traffic_snapshot.states
        )
        queue_snapshot = self._runtime.exception_queue_service.refresh(
            traffic_snapshot.timestamp_utc,
            risk_assessments=risk_assessments,
            priority_assessments=priority_assessments,
        )
        result = GoldenDemoStepResult(
            step_id=f"GOLDEN-STEP-{clock.tick_count:012d}",
            timestamp_utc=traffic_snapshot.timestamp_utc,
            traffic_snapshot=traffic_snapshot,
            due_events=due_events,
            prediction_run=prediction_run,
            conflict_run=conflict_run,
            risk_assessments=risk_assessments,
            priority_assessments=priority_assessments,
            exception_queue_snapshot=queue_snapshot,
        )
        self._last_tick_count = clock.tick_count
        self._last_result = result
        return result

    def _synchronize_reset(self) -> None:
        reset_count = self._runtime.simulation.clock.reset_count
        if reset_count == self._observed_reset_count:
            return
        self._runtime.exception_queue_service.reset()
        self._runtime.recommendation_catalog.reset()
        self._runtime.controller_decision_service.reset()
        self._last_tick_count = None
        self._last_result = None
        self._observed_reset_count = reset_count
