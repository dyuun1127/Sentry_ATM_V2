"""JSON-ready Golden Demo Session views and a read-only in-process API."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from sentry_atm.api.controller_decision import ControllerDecisionAuditLogReadModel
from sentry_atm.api.exception_queue import ExceptionQueueSnapshotReadModel
from sentry_atm.api.recommendation import ResolutionRecommendationSetReadModel
from sentry_atm.domain import (
    AircraftState,
    ConflictStatus,
    ExceptionStatus,
    OperationalPriorityLevel,
    RiskLevel,
)
from sentry_atm.domain.time_policy import to_utc
from sentry_atm.scenario import ScenarioDefinition
from sentry_atm.simulation import TrafficSnapshot

if TYPE_CHECKING:
    from sentry_atm.runtime import GoldenDemoApprovedManeuverOrchestrator


def _utc_text(value: datetime) -> str:
    return to_utc(value).isoformat(timespec="microseconds").replace("+00:00", "Z")


class GoldenDemoSessionStage(StrEnum):
    """Presentation stages derived only from completed backend evidence."""

    READY = "READY"
    MONITORING = "MONITORING"
    DEVIATION_DETECTED = "DEVIATION_DETECTED"
    CONFLICT_DETECTED = "CONFLICT_DETECTED"
    RECOMMENDATION_AVAILABLE = "RECOMMENDATION_AVAILABLE"
    DECISION_ACCEPTED = "DECISION_ACCEPTED"
    CONFLICT_RESOLVED = "CONFLICT_RESOLVED"


class GoldenDemoSessionCommand(StrEnum):
    """Fixed commands accepted by the deterministic Session boundary."""

    START = "START"
    ADVANCE_TO_CONFLICT = "ADVANCE_TO_CONFLICT"
    GENERATE_RECOMMENDATION = "GENERATE_RECOMMENDATION"
    ACCEPT_RECOMMENDATION = "ACCEPT_RECOMMENDATION"
    APPLY_APPROVED_MANEUVER = "APPLY_APPROVED_MANEUVER"
    RESET = "RESET"


@dataclass(frozen=True, slots=True)
class GoldenDemoAircraftReadModel:
    """Metadata-enriched current Aircraft State for map and table views."""

    aircraft_id: str
    aircraft_type: str
    category: str
    source: str
    timestamp_utc: str
    x_nm: float
    y_nm: float
    altitude_ft: float
    ground_speed_kt: float
    heading_deg: float
    vertical_speed_fpm: float
    flight_phase: str
    emergency_status: str
    emergency_type: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "aircraft_id": self.aircraft_id,
            "aircraft_type": self.aircraft_type,
            "category": self.category,
            "source": self.source,
            "timestamp_utc": self.timestamp_utc,
            "x_nm": self.x_nm,
            "y_nm": self.y_nm,
            "altitude_ft": self.altitude_ft,
            "ground_speed_kt": self.ground_speed_kt,
            "heading_deg": self.heading_deg,
            "vertical_speed_fpm": self.vertical_speed_fpm,
            "flight_phase": self.flight_phase,
            "emergency_status": self.emergency_status,
            "emergency_type": self.emergency_type,
        }


@dataclass(frozen=True, slots=True)
class GoldenDemoRevalidationReadModel:
    """Compact post-application evidence for the original Golden Conflict."""

    application_step_id: str
    source_decision_step_id: str
    applied_aircraft_id: str
    before_altitude_ft: float
    applied_altitude_ft: float
    prediction_run_id: str
    conflict_run_id: str
    conflict_id: str
    aircraft_ids: tuple[str, str]
    conflict_status: str
    risk_level: str
    risk_score: float
    tcpa_seconds: float
    horizontal_separation_nm: float
    vertical_separation_ft: float
    source_exception_status: str
    resolved: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "application_step_id": self.application_step_id,
            "source_decision_step_id": self.source_decision_step_id,
            "applied_aircraft_id": self.applied_aircraft_id,
            "before_altitude_ft": self.before_altitude_ft,
            "applied_altitude_ft": self.applied_altitude_ft,
            "prediction_run_id": self.prediction_run_id,
            "conflict_run_id": self.conflict_run_id,
            "conflict_id": self.conflict_id,
            "aircraft_ids": list(self.aircraft_ids),
            "conflict_status": self.conflict_status,
            "risk_level": self.risk_level,
            "risk_score": self.risk_score,
            "tcpa_seconds": self.tcpa_seconds,
            "horizontal_separation_nm": self.horizontal_separation_nm,
            "vertical_separation_ft": self.vertical_separation_ft,
            "source_exception_status": self.source_exception_status,
            "resolved": self.resolved,
        }


@dataclass(frozen=True, slots=True)
class GoldenDemoSessionReadModel:
    """One complete JSON-compatible view of current Golden Demo backend state."""

    session_id: str
    scenario_id: str
    run_number: int
    stage: GoldenDemoSessionStage
    clock_state: str
    simulation_time_utc: str
    elapsed_seconds: float
    traffic: tuple[GoldenDemoAircraftReadModel, ...]
    active_exception_count: int
    step_id: str | None
    resolution_step_id: str | None
    decision_step_id: str | None
    application_step_id: str | None
    exception_queue: ExceptionQueueSnapshotReadModel | None
    recommendation: ResolutionRecommendationSetReadModel | None
    controller_decision: ControllerDecisionAuditLogReadModel | None
    revalidation: GoldenDemoRevalidationReadModel | None

    def to_dict(self) -> dict[str, object]:
        return {
            "session_id": self.session_id,
            "scenario_id": self.scenario_id,
            "run_number": self.run_number,
            "stage": self.stage.value,
            "clock_state": self.clock_state,
            "simulation_time_utc": self.simulation_time_utc,
            "elapsed_seconds": self.elapsed_seconds,
            "traffic_count": len(self.traffic),
            "active_exception_count": self.active_exception_count,
            "step_id": self.step_id,
            "resolution_step_id": self.resolution_step_id,
            "decision_step_id": self.decision_step_id,
            "application_step_id": self.application_step_id,
            "traffic": [item.to_dict() for item in self.traffic],
            "exception_queue": (
                self.exception_queue.to_dict() if self.exception_queue is not None else None
            ),
            "recommendation": (
                self.recommendation.to_dict() if self.recommendation is not None else None
            ),
            "controller_decision": (
                self.controller_decision.to_dict() if self.controller_decision is not None else None
            ),
            "revalidation": (
                self.revalidation.to_dict() if self.revalidation is not None else None
            ),
        }


@runtime_checkable
class GoldenDemoSessionApiContract(Protocol):
    """Synchronous read-only Session API for presentation adapters."""

    def get_current(self) -> GoldenDemoSessionReadModel: ...


@runtime_checkable
class GoldenDemoSessionCommandApiContract(Protocol):
    """Synchronous command API consumed by transport adapters."""

    @property
    def read_api(self) -> GoldenDemoSessionApiContract: ...

    def execute(
        self,
        command: GoldenDemoSessionCommand,
    ) -> GoldenDemoSessionReadModel: ...


class InProcessGoldenDemoSessionApi:
    """Project the current Orchestrator chain without owning its lifecycle."""

    __slots__ = ("_application_orchestrator",)

    def __init__(
        self,
        application_orchestrator: "GoldenDemoApprovedManeuverOrchestrator",
    ) -> None:
        from sentry_atm.runtime import GoldenDemoApprovedManeuverOrchestrator

        if not isinstance(application_orchestrator, GoldenDemoApprovedManeuverOrchestrator):
            raise TypeError(
                "application_orchestrator must be a GoldenDemoApprovedManeuverOrchestrator"
            )
        self._application_orchestrator = application_orchestrator

    @property
    def application_orchestrator(self) -> "GoldenDemoApprovedManeuverOrchestrator":
        return self._application_orchestrator

    def get_current(self) -> GoldenDemoSessionReadModel:
        application = self._application_orchestrator
        application_result = application.last_result
        decision = application.decision_orchestrator
        decision_result = decision.last_result
        resolution = decision.resolution_orchestrator
        resolution_result = resolution.last_result
        steps = resolution.step_orchestrator
        step_result = steps.last_result
        runtime = steps.runtime
        clock = runtime.simulation.clock

        traffic_snapshot = (
            application_result.traffic_snapshot
            if application_result is not None
            else (
                step_result.traffic_snapshot
                if step_result is not None
                else runtime.simulation.engine.snapshot()
            )
        )
        queue = runtime.exception_queue_api.get_current(include_resolved=True)
        recommendation = runtime.recommendation_api.get_current()
        controller_decision = runtime.controller_decision_api.get_current()
        return GoldenDemoSessionReadModel(
            session_id=f"{runtime.definition.scenario_id}-RUN-{clock.reset_count:06d}",
            scenario_id=runtime.definition.scenario_id,
            run_number=clock.reset_count,
            stage=_stage(
                step_result=step_result,
                resolution_result=resolution_result,
                decision_result=decision_result,
                application_result=application_result,
            ),
            clock_state=clock.state.value,
            simulation_time_utc=_utc_text(clock.current_time_utc),
            elapsed_seconds=clock.elapsed_seconds,
            traffic=_map_traffic(traffic_snapshot, runtime.definition),
            active_exception_count=queue.active_count if queue is not None else 0,
            step_id=step_result.step_id if step_result is not None else None,
            resolution_step_id=(
                resolution_result.resolution_step_id if resolution_result is not None else None
            ),
            decision_step_id=(
                decision_result.decision_step_id if decision_result is not None else None
            ),
            application_step_id=(
                application_result.application_step_id if application_result is not None else None
            ),
            exception_queue=queue,
            recommendation=recommendation,
            controller_decision=controller_decision,
            revalidation=(
                _map_revalidation(application_result) if application_result is not None else None
            ),
        )


def _stage(
    *,
    step_result,
    resolution_result,
    decision_result,
    application_result,
) -> GoldenDemoSessionStage:
    if application_result is not None:
        return GoldenDemoSessionStage.CONFLICT_RESOLVED
    if decision_result is not None:
        return GoldenDemoSessionStage.DECISION_ACCEPTED
    if resolution_result is not None:
        return GoldenDemoSessionStage.RECOMMENDATION_AVAILABLE
    if step_result is None:
        return GoldenDemoSessionStage.READY
    if any(
        item.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL)
        for item in step_result.risk_assessments
    ):
        return GoldenDemoSessionStage.CONFLICT_DETECTED
    if any(
        item.priority_level is not OperationalPriorityLevel.ROUTINE
        for item in step_result.priority_assessments
    ):
        return GoldenDemoSessionStage.DEVIATION_DETECTED
    return GoldenDemoSessionStage.MONITORING


def _map_traffic(
    snapshot: TrafficSnapshot,
    definition: ScenarioDefinition,
) -> tuple[GoldenDemoAircraftReadModel, ...]:
    metadata_by_id = {item.aircraft_id: item.metadata for item in definition.aircraft}
    return tuple(
        _map_aircraft(state, metadata_by_id[state.aircraft_id]) for state in snapshot.states
    )


def _map_aircraft(state: AircraftState, metadata) -> GoldenDemoAircraftReadModel:
    return GoldenDemoAircraftReadModel(
        aircraft_id=state.aircraft_id,
        aircraft_type=metadata.aircraft_type,
        category=metadata.category.value,
        source=state.source.value,
        timestamp_utc=_utc_text(state.timestamp_utc),
        x_nm=state.x_nm,
        y_nm=state.y_nm,
        altitude_ft=state.altitude_ft,
        ground_speed_kt=state.ground_speed_kt,
        heading_deg=state.heading_deg,
        vertical_speed_fpm=state.vertical_speed_fpm,
        flight_phase=state.flight_phase.value,
        emergency_status=state.emergency_status.value,
        emergency_type=(state.emergency_type.value if state.emergency_type is not None else None),
    )


def _map_revalidation(application_result) -> GoldenDemoRevalidationReadModel:
    conflict = application_result.primary_conflict_after_application
    risk = next(item for item in application_result.risk_assessments if item.pair == conflict.pair)
    source_exception = next(
        item
        for item in application_result.exception_queue_snapshot.items
        if item.subject_aircraft_ids == conflict.pair.aircraft_ids
    )
    resolved = (
        conflict.status is ConflictStatus.SAFE
        and risk.risk_level is RiskLevel.LOW
        and source_exception.status is ExceptionStatus.RESOLVED
    )
    return GoldenDemoRevalidationReadModel(
        application_step_id=application_result.application_step_id,
        source_decision_step_id=application_result.source_decision_step_id,
        applied_aircraft_id=application_result.applied_state.aircraft_id,
        before_altitude_ft=application_result.before_state.altitude_ft,
        applied_altitude_ft=application_result.applied_state.altitude_ft,
        prediction_run_id=application_result.prediction_run.prediction_run_id,
        conflict_run_id=application_result.conflict_run.assessment_run_id,
        conflict_id=conflict.conflict_id,
        aircraft_ids=conflict.pair.aircraft_ids,
        conflict_status=conflict.status.value,
        risk_level=risk.risk_level.value,
        risk_score=risk.risk_score,
        tcpa_seconds=conflict.tcpa_seconds,
        horizontal_separation_nm=conflict.minimum_separation.horizontal_nm,
        vertical_separation_ft=conflict.minimum_separation.vertical_ft,
        source_exception_status=source_exception.status.value,
        resolved=resolved,
    )
