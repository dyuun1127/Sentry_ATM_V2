"""Strict deterministic Golden Demo Session command composition."""

from dataclasses import dataclass

from sentry_atm.api import (
    GoldenDemoSessionCommand,
    GoldenDemoSessionCommandValidationError,
    GoldenDemoSessionReadModel,
    GoldenDemoSessionStage,
    InProcessGoldenDemoSessionApi,
)
from sentry_atm.domain import (
    AltitudeManeuver,
    EntryDelayManeuver,
    HeadingManeuver,
    ResolutionManeuver,
    SequenceChangeManeuver,
    SpeedManeuver,
)
from sentry_atm.domain.validation import require_identifier
from sentry_atm.infrastructure.http import GoldenDemoSessionWsgiApp
from sentry_atm.runtime.application_orchestrator import (
    GoldenDemoApprovedManeuverOrchestrator,
)
from sentry_atm.runtime.composition import GoldenDemoRuntime, build_golden_demo_runtime
from sentry_atm.runtime.decision_orchestrator import (
    GoldenDemoControllerDecisionOrchestrator,
)
from sentry_atm.runtime.modified_application_orchestrator import (
    GoldenDemoValidatedModifiedManeuverApplicationOrchestrator,
)
from sentry_atm.runtime.modified_revalidation_orchestrator import (
    GoldenDemoModifiedManeuverRevalidationOrchestrator,
)
from sentry_atm.runtime.orchestrator import GoldenDemoStepOrchestrator
from sentry_atm.runtime.resolution_orchestrator import GoldenDemoResolutionOrchestrator


class GoldenDemoSessionCommandService:
    """Execute only the calibrated Golden Demo checkpoint sequence."""

    __slots__ = (
        "_application_orchestrator",
        "_modified_application_orchestrator",
        "_modified_revalidation_orchestrator",
        "_read_api",
    )

    def __init__(
        self,
        application_orchestrator: GoldenDemoApprovedManeuverOrchestrator,
        modified_revalidation_orchestrator: GoldenDemoModifiedManeuverRevalidationOrchestrator,
        modified_application_orchestrator: (
            GoldenDemoValidatedModifiedManeuverApplicationOrchestrator
        ),
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
        if not isinstance(
            modified_revalidation_orchestrator,
            GoldenDemoModifiedManeuverRevalidationOrchestrator,
        ):
            raise TypeError(
                "modified_revalidation_orchestrator must be a "
                "GoldenDemoModifiedManeuverRevalidationOrchestrator"
            )
        if read_api.application_orchestrator is not application_orchestrator:
            raise ValueError("read_api must use the same Application Orchestrator")
        if (
            read_api.modified_revalidation_orchestrator
            is not modified_revalidation_orchestrator
        ):
            raise ValueError("read_api must use the same Modified Revalidation Orchestrator")
        if (
            modified_revalidation_orchestrator.decision_orchestrator
            is not application_orchestrator.decision_orchestrator
        ):
            raise ValueError("Session Orchestrators must share one Controller Decision source")
        if not isinstance(
            modified_application_orchestrator,
            GoldenDemoValidatedModifiedManeuverApplicationOrchestrator,
        ):
            raise TypeError(
                "modified_application_orchestrator must be a "
                "GoldenDemoValidatedModifiedManeuverApplicationOrchestrator"
            )
        if (
            modified_application_orchestrator.modified_revalidation_orchestrator
            is not modified_revalidation_orchestrator
        ):
            raise ValueError(
                "Session Orchestrators must share one Modified Revalidation source"
            )
        if read_api.modified_application_orchestrator is not modified_application_orchestrator:
            raise ValueError("read_api must use the same Modified Application Orchestrator")
        self._application_orchestrator = application_orchestrator
        self._modified_revalidation_orchestrator = modified_revalidation_orchestrator
        self._modified_application_orchestrator = modified_application_orchestrator
        self._read_api = read_api

    @property
    def read_api(self) -> InProcessGoldenDemoSessionApi:
        return self._read_api

    def execute(
        self,
        command: GoldenDemoSessionCommand,
        *,
        rationale: str | None = None,
        modified_maneuver: ResolutionManeuver | None = None,
        seconds: int | None = None,
    ) -> GoldenDemoSessionReadModel:
        """Execute one validated checkpoint and return its resulting Session view."""

        if not isinstance(command, (str, GoldenDemoSessionCommand)):
            raise TypeError("command must be a GoldenDemoSessionCommand")
        selected = GoldenDemoSessionCommand(command)
        current = self._read_api.get_current()
        (
            runtime,
            steps,
            resolution,
            decision,
            modified_revalidation,
            modified_application,
        ) = self._components()

        _validate_command_inputs(
            selected,
            rationale=rationale,
            modified_maneuver=modified_maneuver,
            current=current,
        )

        if selected is GoldenDemoSessionCommand.RESET:
            runtime.simulation.clock.reset()
            return self._read_api.get_current()
        if selected is GoldenDemoSessionCommand.ADVANCE:
            if seconds is None:
                raise GoldenDemoSessionCommandValidationError(
                    "ADVANCE must state how many seconds to advance"
                )
            if type(seconds) is not int or not 1 <= seconds <= 3_600:
                raise GoldenDemoSessionCommandValidationError(
                    "seconds must be an integer from 1 through 3600"
                )
            # 시계가 아직 서 있으면 먼저 돌린다. 세워 둔 채로 진행하면 단계는
            # 계산되지만 시각이 그대로라 화면이 멈춘 것처럼 보인다.
            if not runtime.simulation.clock.is_running:
                runtime.simulation.clock.play()
            steps.step(seconds)
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
        elif selected is GoldenDemoSessionCommand.MODIFY_RECOMMENDATION:
            _require_checkpoint(
                current,
                GoldenDemoSessionStage.RECOMMENDATION_AVAILABLE,
                elapsed_seconds=75.0,
            )
            steps.step(15)
            decision.modify(
                rationale=rationale,  # type: ignore[arg-type]
                modified_maneuver=modified_maneuver,  # type: ignore[arg-type]
            )
        elif selected is GoldenDemoSessionCommand.REJECT_RECOMMENDATION:
            _require_checkpoint(
                current,
                GoldenDemoSessionStage.RECOMMENDATION_AVAILABLE,
                elapsed_seconds=75.0,
            )
            steps.step(15)
            decision.reject(rationale=rationale)  # type: ignore[arg-type]
        elif selected is GoldenDemoSessionCommand.REVALIDATE_MODIFIED_MANEUVER:
            _require_checkpoint(
                current,
                GoldenDemoSessionStage.DECISION_MODIFIED,
                elapsed_seconds=90.0,
            )
            modified_revalidation.revalidate()
        elif selected is GoldenDemoSessionCommand.APPLY_VALIDATED_MODIFIED_MANEUVER:
            _require_checkpoint(
                current,
                GoldenDemoSessionStage.MODIFICATION_REVALIDATED,
                elapsed_seconds=90.0,
            )
            modified_application.authorize_apply_and_revalidate()
        elif selected is GoldenDemoSessionCommand.APPLY_APPROVED_MANEUVER:
            _require_checkpoint(
                current,
                GoldenDemoSessionStage.DECISION_ACCEPTED,
                elapsed_seconds=90.0,
            )
            self._application_orchestrator.apply_and_revalidate()
        else:  # pragma: no cover - exhaustive StrEnum dispatch
            raise AssertionError(f"unsupported Session command: {selected.value}")
        return self._read_api.get_current()

    def _components(self):
        decision = self._application_orchestrator.decision_orchestrator
        resolution = decision.resolution_orchestrator
        steps = resolution.step_orchestrator
        return (
            steps.runtime,
            steps,
            resolution,
            decision,
            self._modified_revalidation_orchestrator,
            self._modified_application_orchestrator,
        )


_ACTION_MANEUVERS = (
    HeadingManeuver,
    AltitudeManeuver,
    SpeedManeuver,
    EntryDelayManeuver,
    SequenceChangeManeuver,
)


def _validate_command_inputs(
    command: GoldenDemoSessionCommand,
    *,
    rationale: str | None,
    modified_maneuver: ResolutionManeuver | None,
    current: GoldenDemoSessionReadModel,
) -> None:
    decision_commands = {
        GoldenDemoSessionCommand.ACCEPT_RECOMMENDATION,
        GoldenDemoSessionCommand.MODIFY_RECOMMENDATION,
        GoldenDemoSessionCommand.REJECT_RECOMMENDATION,
    }
    if command not in decision_commands:
        if rationale is not None or modified_maneuver is not None:
            raise GoldenDemoSessionCommandValidationError(
                "decision inputs are only allowed for Recommendation decisions"
            )
        return
    if command is GoldenDemoSessionCommand.ACCEPT_RECOMMENDATION:
        if rationale is not None or modified_maneuver is not None:
            raise GoldenDemoSessionCommandValidationError(
                "ACCEPT_RECOMMENDATION does not accept decision inputs"
            )
        return
    try:
        require_identifier(rationale, field_name="rationale")  # type: ignore[arg-type]
    except (TypeError, ValueError) as error:
        raise GoldenDemoSessionCommandValidationError(str(error)) from None
    if command is GoldenDemoSessionCommand.REJECT_RECOMMENDATION:
        if modified_maneuver is not None:
            raise GoldenDemoSessionCommandValidationError(
                "REJECT_RECOMMENDATION cannot contain a modified Maneuver"
            )
        return
    if not isinstance(modified_maneuver, _ACTION_MANEUVERS):
        raise GoldenDemoSessionCommandValidationError(
            "MODIFY_RECOMMENDATION requires a supported action Maneuver"
        )
    recommendation = current.recommendation
    if recommendation is not None:
        primary = next(
            (
                item
                for item in recommendation.recommendations
                if item.recommendation_id == recommendation.primary_recommendation_id
            ),
            None,
        )
        if primary is not None and _matches_read_maneuver(
            primary.maneuver,
            modified_maneuver,
        ):
            raise GoldenDemoSessionCommandValidationError(
                "MODIFY_RECOMMENDATION must change the recommended Maneuver"
            )


def _matches_read_maneuver(read_model, maneuver: ResolutionManeuver) -> bool:
    if isinstance(maneuver, HeadingManeuver):
        return (
            read_model.maneuver_type == "HEADING"
            and read_model.target_heading_deg == maneuver.target_heading_deg
        )
    if isinstance(maneuver, AltitudeManeuver):
        return (
            read_model.maneuver_type == "ALTITUDE"
            and read_model.target_altitude_ft == maneuver.target_altitude_ft
        )
    if isinstance(maneuver, SpeedManeuver):
        return (
            read_model.maneuver_type == "SPEED"
            and read_model.target_ground_speed_kt == maneuver.target_ground_speed_kt
        )
    if isinstance(maneuver, EntryDelayManeuver):
        return (
            read_model.maneuver_type == "ENTRY_DELAY"
            and read_model.delay_seconds == maneuver.delay_seconds
        )
    return (
        isinstance(maneuver, SequenceChangeManeuver)
        and read_model.maneuver_type == "SEQUENCE_CHANGE"
        and read_model.target_sequence_position == maneuver.target_sequence_position
    )


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
    modified_revalidation_orchestrator: GoldenDemoModifiedManeuverRevalidationOrchestrator
    modified_application_orchestrator: GoldenDemoValidatedModifiedManeuverApplicationOrchestrator
    application_orchestrator: GoldenDemoApprovedManeuverOrchestrator
    read_api: InProcessGoldenDemoSessionApi
    command_service: GoldenDemoSessionCommandService
    http_app: GoldenDemoSessionWsgiApp


def build_golden_demo_session_runtime() -> GoldenDemoSessionRuntime:
    """Wire one unstarted Session without running any command or calculation."""

    return build_session_runtime(build_golden_demo_runtime())


def build_sortie_session_runtime(**kwargs) -> GoldenDemoSessionRuntime:
    """같은 배선을 13단계 소티에 붙인다.

    소티용 세션을 따로 만들지 않는 이유는 5·6단계와 같다 — 두 벌이 되면 시험에서
    도는 코드와 시연에서 도는 코드가 서로 달라진다.
    """

    from sentry_atm.runtime.composition import build_sortie_runtime

    return build_session_runtime(build_sortie_runtime(**kwargs))


def build_session_runtime(runtime) -> GoldenDemoSessionRuntime:
    """어떤 시나리오 런타임이든 같은 세션 구성으로 감싼다."""

    steps = GoldenDemoStepOrchestrator(runtime)
    resolution = GoldenDemoResolutionOrchestrator(steps)
    decision = GoldenDemoControllerDecisionOrchestrator(resolution)
    modified_revalidation = GoldenDemoModifiedManeuverRevalidationOrchestrator(decision)
    modified_application = GoldenDemoValidatedModifiedManeuverApplicationOrchestrator(
        modified_revalidation
    )
    application = GoldenDemoApprovedManeuverOrchestrator(decision)
    read_api = InProcessGoldenDemoSessionApi(
        application,
        modified_revalidation,
        modified_application,
    )
    command_service = GoldenDemoSessionCommandService(
        application,
        modified_revalidation,
        modified_application,
        read_api,
    )
    http_app = GoldenDemoSessionWsgiApp(
        read_api,
        command_service,
        runtime.playback_api,
    )
    return GoldenDemoSessionRuntime(
        runtime=runtime,
        step_orchestrator=steps,
        resolution_orchestrator=resolution,
        decision_orchestrator=decision,
        modified_revalidation_orchestrator=modified_revalidation,
        modified_application_orchestrator=modified_application,
        application_orchestrator=application,
        read_api=read_api,
        command_service=command_service,
        http_app=http_app,
    )
