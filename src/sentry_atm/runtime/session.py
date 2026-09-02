"""Strict deterministic Golden Demo Session command composition."""

from dataclasses import dataclass

from sentry_atm.api import (
    GoldenDemoSessionCommand,
    GoldenDemoSessionReadModel,
    GoldenDemoSessionStage,
    InProcessGoldenDemoSessionApi,
)
from sentry_atm.infrastructure.http import GoldenDemoSessionWsgiApp
from sentry_atm.runtime.application_orchestrator import (
    GoldenDemoApprovedManeuverOrchestrator,
)
from sentry_atm.runtime.composition import GoldenDemoRuntime, build_golden_demo_runtime
from sentry_atm.runtime.decision_orchestrator import (
    GoldenDemoControllerDecisionOrchestrator,
)
from sentry_atm.runtime.orchestrator import GoldenDemoStepOrchestrator
from sentry_atm.runtime.resolution_orchestrator import GoldenDemoResolutionOrchestrator


class GoldenDemoSessionCommandService:
    """Execute only the calibrated Golden Demo checkpoint sequence."""

    __slots__ = ("_application_orchestrator", "_read_api")

    def __init__(
        self,
        application_orchestrator: GoldenDemoApprovedManeuverOrchestrator,
        read_api: InProcessGoldenDemoSessionApi,
    ) -> None:
        if not isinstance(
            application_orchestrator,
            GoldenDemoApprovedManeuverOrchestrator,
        ):
            raise TypeError(
                "application_orchestrator must be a GoldenDemoApprovedManeuverOrchestrator"
            )
        if not isinstance(read_api, InProcessGoldenDemoSessionApi):
            raise TypeError("read_api must be an InProcessGoldenDemoSessionApi")
        if read_api.application_orchestrator is not application_orchestrator:
            raise ValueError("read_api must use the same Application Orchestrator")
        self._application_orchestrator = application_orchestrator
        self._read_api = read_api

    @property
    def read_api(self) -> InProcessGoldenDemoSessionApi:
        return self._read_api

    def execute(
        self,
        command: GoldenDemoSessionCommand,
    ) -> GoldenDemoSessionReadModel:
        """Execute one validated checkpoint and return its resulting Session view."""

        if not isinstance(command, (str, GoldenDemoSessionCommand)):
            raise TypeError("command must be a GoldenDemoSessionCommand")
        selected = GoldenDemoSessionCommand(command)
        current = self._read_api.get_current()
        runtime, steps, resolution, decision = self._components()

        if selected is GoldenDemoSessionCommand.RESET:
            runtime.simulation.clock.reset()
            return self._read_api.get_current()
        if selected is GoldenDemoSessionCommand.START:
            _require_checkpoint(current, GoldenDemoSessionStage.READY, elapsed_seconds=0.0)
            runtime.simulation.clock.play()
            steps.step(0)
        elif selected is GoldenDemoSessionCommand.ADVANCE_TO_CONFLICT:
            _require_checkpoint(current, GoldenDemoSessionStage.MONITORING, elapsed_seconds=0.0)
            steps.step(70)
        elif selected is GoldenDemoSessionCommand.GENERATE_RECOMMENDATION:
            _require_checkpoint(
                current,
                GoldenDemoSessionStage.CONFLICT_DETECTED,
                elapsed_seconds=70.0,
            )
            steps.step(5)
            resolution.resolve()
        elif selected is GoldenDemoSessionCommand.ACCEPT_RECOMMENDATION:
            _require_checkpoint(
                current,
                GoldenDemoSessionStage.RECOMMENDATION_AVAILABLE,
                elapsed_seconds=75.0,
            )
            steps.step(15)
            decision.accept()
        else:
            _require_checkpoint(
                current,
                GoldenDemoSessionStage.DECISION_ACCEPTED,
                elapsed_seconds=90.0,
            )
            self._application_orchestrator.apply_and_revalidate()
        return self._read_api.get_current()

    def _components(self):
        decision = self._application_orchestrator.decision_orchestrator
        resolution = decision.resolution_orchestrator
        steps = resolution.step_orchestrator
        return steps.runtime, steps, resolution, decision


def _require_checkpoint(
    current: GoldenDemoSessionReadModel,
    expected_stage: GoldenDemoSessionStage,
    *,
    elapsed_seconds: float,
) -> None:
    if current.stage is not expected_stage:
        raise ValueError(
            f"command requires Session stage {expected_stage.value}; "
            f"current stage is {current.stage.value}"
        )
    if current.elapsed_seconds != elapsed_seconds:
        raise ValueError(
            f"command requires elapsed_seconds={elapsed_seconds:.1f}; "
            f"current value is {current.elapsed_seconds:.1f}"
        )


@dataclass(frozen=True, slots=True)
class GoldenDemoSessionRuntime:
    """Fully wired process-local Golden Demo Session and its public facades."""

    runtime: GoldenDemoRuntime
    step_orchestrator: GoldenDemoStepOrchestrator
    resolution_orchestrator: GoldenDemoResolutionOrchestrator
    decision_orchestrator: GoldenDemoControllerDecisionOrchestrator
    application_orchestrator: GoldenDemoApprovedManeuverOrchestrator
    read_api: InProcessGoldenDemoSessionApi
    command_service: GoldenDemoSessionCommandService
    http_app: GoldenDemoSessionWsgiApp


def build_golden_demo_session_runtime() -> GoldenDemoSessionRuntime:
    """Wire one unstarted Session without running any command or calculation."""

    runtime = build_golden_demo_runtime()
    steps = GoldenDemoStepOrchestrator(runtime)
    resolution = GoldenDemoResolutionOrchestrator(steps)
    decision = GoldenDemoControllerDecisionOrchestrator(resolution)
    application = GoldenDemoApprovedManeuverOrchestrator(decision)
    read_api = InProcessGoldenDemoSessionApi(application)
    command_service = GoldenDemoSessionCommandService(application, read_api)
    http_app = GoldenDemoSessionWsgiApp(read_api, command_service)
    return GoldenDemoSessionRuntime(
        runtime=runtime,
        step_orchestrator=steps,
        resolution_orchestrator=resolution,
        decision_orchestrator=decision,
        application_orchestrator=application,
        read_api=read_api,
        command_service=command_service,
        http_app=http_app,
    )
