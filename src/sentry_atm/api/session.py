"""JSON-ready Golden Demo Session views and a read-only in-process API."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from sentry_atm.api.controller_decision import ControllerDecisionAuditLogReadModel
from sentry_atm.api.exception_queue import ExceptionQueueSnapshotReadModel
from sentry_atm.api.recommendation import ResolutionRecommendationSetReadModel
from sentry_atm.domain import (
    AircraftState,
    AltitudeManeuver,
    CandidateSafetyValidationResult,
    ConflictEvent,
    ConflictRiskAssessment,
    ConflictStatus,
    ControllerDecisionType,
    EntryDelayManeuver,
    ExceptionStatus,
    HeadingManeuver,
    OperationalPriorityLevel,
    ResolutionCandidate,
    ResolutionManeuver,
    RiskLevel,
    SeparationMinimum,
    SequenceChangeManeuver,
    SpeedManeuver,
)
from sentry_atm.domain.time_policy import to_utc
from sentry_atm.regulation.policy import active_separation_profile
from sentry_atm.scenario import (
    EntryConformanceDeviationPayload,
    ScenarioDefinition,
    ScenarioEvent,
    ScenarioEventType,
)
from sentry_atm.simulation import TrafficSnapshot

if TYPE_CHECKING:
    from sentry_atm.runtime.application_orchestrator import (
        GoldenDemoApprovedManeuverOrchestrator,
    )
    from sentry_atm.runtime.modified_application_orchestrator import (
        GoldenDemoValidatedModifiedManeuverApplicationOrchestrator,
    )
    from sentry_atm.runtime.modified_revalidation_orchestrator import (
        GoldenDemoModifiedManeuverRevalidationOrchestrator,
    )


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
    DECISION_MODIFIED = "DECISION_MODIFIED"
    MODIFICATION_REVALIDATED = "MODIFICATION_REVALIDATED"
    DECISION_REJECTED = "DECISION_REJECTED"
    CONFLICT_RESOLVED = "CONFLICT_RESOLVED"


class GoldenDemoSessionCommand(StrEnum):
    """Fixed commands accepted by the deterministic Session boundary."""

    START = "START"
    ADVANCE_TO_CONFLICT = "ADVANCE_TO_CONFLICT"
    GENERATE_RECOMMENDATION = "GENERATE_RECOMMENDATION"
    ACCEPT_RECOMMENDATION = "ACCEPT_RECOMMENDATION"
    MODIFY_RECOMMENDATION = "MODIFY_RECOMMENDATION"
    REVALIDATE_MODIFIED_MANEUVER = "REVALIDATE_MODIFIED_MANEUVER"
    APPLY_VALIDATED_MODIFIED_MANEUVER = "APPLY_VALIDATED_MODIFIED_MANEUVER"
    REJECT_RECOMMENDATION = "REJECT_RECOMMENDATION"
    APPLY_APPROVED_MANEUVER = "APPLY_APPROVED_MANEUVER"
    RESET = "RESET"
    ADVANCE = "ADVANCE"
    """시계를 주어진 초만큼 진행한다.

    나머지 명령은 골든 데모의 시간선(T+70 에 충돌, T+75 에 권고)에 맞춰져 있어
    다른 시나리오에서는 검문소를 통과하지 못한다. 75분짜리 소티는 대본이 아니라
    시계로 움직이므로 시나리오와 무관한 진행 수단이 따로 필요하다.
    """


class GoldenDemoSessionCommandValidationError(ValueError):
    """A well-formed Session request whose decision inputs are invalid."""


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
    application_source: str
    source_modified_revalidation_step_id: str | None
    authorization_id: str | None
    authorized_at_utc: str | None
    applied_maneuver_type: str
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
            "application_source": self.application_source,
            "source_modified_revalidation_step_id": (
                self.source_modified_revalidation_step_id
            ),
            "authorization_id": self.authorization_id,
            "authorized_at_utc": self.authorized_at_utc,
            "applied_maneuver_type": self.applied_maneuver_type,
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
class GoldenDemoConflictEvidenceReadModel:
    """Explainable baseline evidence for the Golden Demo's primary conflict."""

    conflict_id: str
    aircraft_ids: tuple[str, str]
    status: str
    evaluated_at_utc: str
    closest_approach_time_utc: str
    tcpa_seconds: float
    horizontal_separation_nm: float
    vertical_separation_ft: float
    horizontal_threshold_nm: float
    vertical_threshold_ft: float
    horizontal_separation_ratio: float
    vertical_separation_ratio: float
    risk_score: float
    risk_level: str
    risk_reason_codes: tuple[str, ...]
    rule_profile_id: str
    risk_policy_profile_id: str

    def to_dict(self) -> dict[str, object]:
        return {
            "conflict_id": self.conflict_id,
            "aircraft_ids": list(self.aircraft_ids),
            "status": self.status,
            "evaluated_at_utc": self.evaluated_at_utc,
            "closest_approach_time_utc": self.closest_approach_time_utc,
            "tcpa_seconds": self.tcpa_seconds,
            "horizontal_separation_nm": self.horizontal_separation_nm,
            "vertical_separation_ft": self.vertical_separation_ft,
            "horizontal_threshold_nm": self.horizontal_threshold_nm,
            "vertical_threshold_ft": self.vertical_threshold_ft,
            "horizontal_separation_ratio": self.horizontal_separation_ratio,
            "vertical_separation_ratio": self.vertical_separation_ratio,
            "risk_score": self.risk_score,
            "risk_level": self.risk_level,
            "risk_reason_codes": list(self.risk_reason_codes),
            "rule_profile_id": self.rule_profile_id,
            "risk_policy_profile_id": self.risk_policy_profile_id,
        }


@dataclass(frozen=True, slots=True)
class GoldenDemoDeviationReadModel:
    """Expected-versus-actual evidence for the emitted entry deviation."""

    event_id: str
    detected_at_utc: str
    aircraft_id: str
    expected_entry_point: str
    expected_altitude_ft: float
    actual_altitude_ft: float
    vertical_deviation_ft: float
    expected_heading_deg: float
    actual_heading_deg: float
    heading_deviation_deg: float
    lateral_deviation_nm: float
    time_deviation_seconds: float

    def to_dict(self) -> dict[str, object]:
        return {
            "event_id": self.event_id,
            "detected_at_utc": self.detected_at_utc,
            "aircraft_id": self.aircraft_id,
            "expected_entry_point": self.expected_entry_point,
            "expected_altitude_ft": self.expected_altitude_ft,
            "actual_altitude_ft": self.actual_altitude_ft,
            "vertical_deviation_ft": self.vertical_deviation_ft,
            "expected_heading_deg": self.expected_heading_deg,
            "actual_heading_deg": self.actual_heading_deg,
            "heading_deviation_deg": self.heading_deviation_deg,
            "lateral_deviation_nm": self.lateral_deviation_nm,
            "time_deviation_seconds": self.time_deviation_seconds,
        }


@dataclass(frozen=True, slots=True)
class GoldenDemoCandidateComparisonReadModel:
    """One candidate joined with its isolated Safety Validation evidence."""

    candidate_id: str
    target_aircraft_id: str | None
    maneuver_type: str
    target_heading_deg: float | None
    target_altitude_ft: float | None
    target_ground_speed_kt: float | None
    delay_seconds: float | None
    target_sequence_position: int | None
    operational_cost_score: float
    verdict: str
    primary_conflict_status: str
    primary_horizontal_separation_nm: float
    primary_vertical_separation_ft: float
    secondary_conflict_aircraft_ids: tuple[tuple[str, str], ...]
    performance_feasible: bool
    rule_violation_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]
    validation_profile_id: str
    recommended: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "target_aircraft_id": self.target_aircraft_id,
            "maneuver_type": self.maneuver_type,
            "target_heading_deg": self.target_heading_deg,
            "target_altitude_ft": self.target_altitude_ft,
            "target_ground_speed_kt": self.target_ground_speed_kt,
            "delay_seconds": self.delay_seconds,
            "target_sequence_position": self.target_sequence_position,
            "operational_cost_score": self.operational_cost_score,
            "verdict": self.verdict,
            "primary_conflict_status": self.primary_conflict_status,
            "primary_horizontal_separation_nm": self.primary_horizontal_separation_nm,
            "primary_vertical_separation_ft": self.primary_vertical_separation_ft,
            "secondary_conflict_aircraft_ids": [
                list(aircraft_ids) for aircraft_ids in self.secondary_conflict_aircraft_ids
            ],
            "performance_feasible": self.performance_feasible,
            "rule_violation_ids": list(self.rule_violation_ids),
            "reason_codes": list(self.reason_codes),
            "validation_profile_id": self.validation_profile_id,
            "recommended": self.recommended,
        }


@dataclass(frozen=True, slots=True)
class GoldenDemoModifiedRevalidationReadModel:
    """JSON-ready isolated validation evidence for a modified Maneuver."""

    revalidation_step_id: str
    source_decision_step_id: str
    candidate_id: str
    evaluated_at_utc: str
    validation_run_id: str
    verdict: str
    primary_conflict_status: str
    primary_horizontal_separation_nm: float
    primary_vertical_separation_ft: float
    tcpa_seconds: float
    secondary_conflict_aircraft_ids: tuple[tuple[str, str], ...]
    performance_feasible: bool
    rule_violation_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]
    validation_profile_id: str
    safe_to_apply: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "revalidation_step_id": self.revalidation_step_id,
            "source_decision_step_id": self.source_decision_step_id,
            "candidate_id": self.candidate_id,
            "evaluated_at_utc": self.evaluated_at_utc,
            "validation_run_id": self.validation_run_id,
            "verdict": self.verdict,
            "primary_conflict_status": self.primary_conflict_status,
            "primary_horizontal_separation_nm": self.primary_horizontal_separation_nm,
            "primary_vertical_separation_ft": self.primary_vertical_separation_ft,
            "tcpa_seconds": self.tcpa_seconds,
            "secondary_conflict_aircraft_ids": [
                list(aircraft_ids) for aircraft_ids in self.secondary_conflict_aircraft_ids
            ],
            "performance_feasible": self.performance_feasible,
            "rule_violation_ids": list(self.rule_violation_ids),
            "reason_codes": list(self.reason_codes),
            "validation_profile_id": self.validation_profile_id,
            "safe_to_apply": self.safe_to_apply,
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
    primary_conflict: GoldenDemoConflictEvidenceReadModel | None
    deviation: GoldenDemoDeviationReadModel | None
    candidate_comparisons: tuple[GoldenDemoCandidateComparisonReadModel, ...]
    exception_queue: ExceptionQueueSnapshotReadModel | None
    recommendation: ResolutionRecommendationSetReadModel | None
    controller_decision: ControllerDecisionAuditLogReadModel | None
    modified_revalidation: GoldenDemoModifiedRevalidationReadModel | None
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
            "primary_conflict": (
                self.primary_conflict.to_dict() if self.primary_conflict is not None else None
            ),
            "deviation": self.deviation.to_dict() if self.deviation is not None else None,
            "candidate_comparisons": [
                item.to_dict() for item in self.candidate_comparisons
            ],
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
            "modified_revalidation": (
                self.modified_revalidation.to_dict()
                if self.modified_revalidation is not None
                else None
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
        *,
        rationale: str | None = None,
        modified_maneuver: ResolutionManeuver | None = None,
    ) -> GoldenDemoSessionReadModel: ...


class InProcessGoldenDemoSessionApi:
    """Project the current Orchestrator chain without owning its lifecycle."""

    __slots__ = (
        "_application_orchestrator",
        "_modified_application_orchestrator",
        "_modified_revalidation_orchestrator",
    )

    def __init__(
        self,
        application_orchestrator: "GoldenDemoApprovedManeuverOrchestrator",
        modified_revalidation_orchestrator: (
            "GoldenDemoModifiedManeuverRevalidationOrchestrator"
        ),
        modified_application_orchestrator: (
            "GoldenDemoValidatedModifiedManeuverApplicationOrchestrator"
        ),
    ) -> None:
        from sentry_atm.runtime.application_orchestrator import (
            GoldenDemoApprovedManeuverOrchestrator,
        )
        from sentry_atm.runtime.modified_application_orchestrator import (
            GoldenDemoValidatedModifiedManeuverApplicationOrchestrator,
        )
        from sentry_atm.runtime.modified_revalidation_orchestrator import (
            GoldenDemoModifiedManeuverRevalidationOrchestrator,
        )

        if not isinstance(application_orchestrator, GoldenDemoApprovedManeuverOrchestrator):
            raise TypeError(
                "application_orchestrator must be a GoldenDemoApprovedManeuverOrchestrator"
            )
        self._application_orchestrator = application_orchestrator
        if not isinstance(
            modified_revalidation_orchestrator,
            GoldenDemoModifiedManeuverRevalidationOrchestrator,
        ):
            raise TypeError(
                "modified_revalidation_orchestrator must be a "
                "GoldenDemoModifiedManeuverRevalidationOrchestrator"
            )
        if (
            modified_revalidation_orchestrator.decision_orchestrator
            is not application_orchestrator.decision_orchestrator
        ):
            raise ValueError("Session Orchestrators must share one Controller Decision source")
        self._modified_revalidation_orchestrator = modified_revalidation_orchestrator
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
        self._modified_application_orchestrator = modified_application_orchestrator

    @property
    def application_orchestrator(self) -> "GoldenDemoApprovedManeuverOrchestrator":
        return self._application_orchestrator

    @property
    def modified_revalidation_orchestrator(
        self,
    ) -> "GoldenDemoModifiedManeuverRevalidationOrchestrator":
        return self._modified_revalidation_orchestrator

    @property
    def modified_application_orchestrator(
        self,
    ) -> "GoldenDemoValidatedModifiedManeuverApplicationOrchestrator":
        return self._modified_application_orchestrator

    def get_current(self) -> GoldenDemoSessionReadModel:
        application = self._application_orchestrator
        approved_application_result = application.last_result
        modified_revalidation_result = self._modified_revalidation_orchestrator.last_result
        modified_application_result = self._modified_application_orchestrator.last_result
        application_result = modified_application_result or approved_application_result
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
                modified_revalidation_result=modified_revalidation_result,
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
            primary_conflict=_map_primary_conflict(
                step_result=step_result,
                resolution_result=resolution_result,
            ),
            deviation=_map_deviation(
                step_result=step_result,
                scenario_events=runtime.simulation.timeline.events,
            ),
            candidate_comparisons=_map_candidate_comparisons(resolution_result),
            exception_queue=queue,
            recommendation=recommendation,
            controller_decision=controller_decision,
            modified_revalidation=(
                _map_modified_revalidation(modified_revalidation_result)
                if modified_revalidation_result is not None
                else None
            ),
            revalidation=(
                _map_revalidation(application_result) if application_result is not None else None
            ),
        )


def _stage(
    *,
    step_result,
    resolution_result,
    decision_result,
    modified_revalidation_result,
    application_result,
) -> GoldenDemoSessionStage:
    if application_result is not None:
        return GoldenDemoSessionStage.CONFLICT_RESOLVED
    if modified_revalidation_result is not None:
        return GoldenDemoSessionStage.MODIFICATION_REVALIDATED
    if decision_result is not None:
        decision_type = decision_result.decision_entry.decision_type
        if decision_type is ControllerDecisionType.MODIFY:
            return GoldenDemoSessionStage.DECISION_MODIFIED
        if decision_type is ControllerDecisionType.REJECT:
            return GoldenDemoSessionStage.DECISION_REJECTED
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


def _map_deviation(
    *,
    step_result,
    scenario_events: tuple[ScenarioEvent, ...],
) -> GoldenDemoDeviationReadModel | None:
    if step_result is None:
        return None
    event = next(
        (
            item
            for item in scenario_events
            if item.event_type is ScenarioEventType.ENTRY_CONFORMANCE_DEVIATION
            and item.scheduled_time_utc <= step_result.timestamp_utc
        ),
        None,
    )
    if event is None or not isinstance(event.payload, EntryConformanceDeviationPayload):
        return None
    state = next(
        item
        for item in step_result.traffic_snapshot.states
        if item.aircraft_id == event.target_aircraft_id
    )
    payload = event.payload
    return GoldenDemoDeviationReadModel(
        event_id=event.event_id,
        detected_at_utc=_utc_text(event.scheduled_time_utc),
        aircraft_id=event.target_aircraft_id,
        expected_entry_point=payload.expected_entry_point,
        expected_altitude_ft=payload.expected_altitude_ft,
        actual_altitude_ft=payload.actual_altitude_ft,
        vertical_deviation_ft=payload.actual_altitude_ft - payload.expected_altitude_ft,
        expected_heading_deg=payload.expected_heading_deg,
        actual_heading_deg=state.heading_deg,
        heading_deviation_deg=_signed_heading_delta(
            state.heading_deg,
            payload.expected_heading_deg,
        ),
        lateral_deviation_nm=payload.lateral_deviation_nm,
        time_deviation_seconds=payload.time_deviation_seconds,
    )


def _signed_heading_delta(actual_heading_deg: float, expected_heading_deg: float) -> float:
    delta = (actual_heading_deg - expected_heading_deg + 180.0) % 360.0 - 180.0
    return 180.0 if delta == -180.0 else delta


def _map_candidate_comparisons(
    resolution_result,
) -> tuple[GoldenDemoCandidateComparisonReadModel, ...]:
    if resolution_result is None:
        return ()
    result_by_id = {
        item.candidate_id: item for item in resolution_result.validation_run.results
    }
    primary_recommendation = resolution_result.recommendation_set.primary_recommendation
    primary_candidate_id = (
        primary_recommendation.candidate_id if primary_recommendation is not None else None
    )
    return tuple(
        _map_candidate_comparison(
            candidate,
            result_by_id[candidate.candidate_id],
            recommended=candidate.candidate_id == primary_candidate_id,
        )
        for candidate in resolution_result.candidate_batch.candidates
    )


def _map_candidate_comparison(
    candidate: ResolutionCandidate,
    validation: CandidateSafetyValidationResult,
    *,
    recommended: bool,
) -> GoldenDemoCandidateComparisonReadModel:
    maneuver = candidate.maneuver
    return GoldenDemoCandidateComparisonReadModel(
        candidate_id=candidate.candidate_id,
        target_aircraft_id=candidate.target_aircraft_id,
        maneuver_type=candidate.maneuver_type.value,
        target_heading_deg=(
            maneuver.target_heading_deg if isinstance(maneuver, HeadingManeuver) else None
        ),
        target_altitude_ft=(
            maneuver.target_altitude_ft if isinstance(maneuver, AltitudeManeuver) else None
        ),
        target_ground_speed_kt=(
            maneuver.target_ground_speed_kt if isinstance(maneuver, SpeedManeuver) else None
        ),
        delay_seconds=(
            maneuver.delay_seconds if isinstance(maneuver, EntryDelayManeuver) else None
        ),
        target_sequence_position=(
            maneuver.target_sequence_position
            if isinstance(maneuver, SequenceChangeManeuver)
            else None
        ),
        operational_cost_score=candidate.cost.operational_cost_score,
        verdict=validation.verdict.value,
        primary_conflict_status=validation.primary_conflict.status.value,
        primary_horizontal_separation_nm=(
            validation.primary_conflict.minimum_separation.horizontal_nm
        ),
        primary_vertical_separation_ft=(
            validation.primary_conflict.minimum_separation.vertical_ft
        ),
        secondary_conflict_aircraft_ids=tuple(
            item.pair.aircraft_ids for item in validation.secondary_conflicts
        ),
        performance_feasible=validation.performance_feasible,
        rule_violation_ids=tuple(item.rule_id for item in validation.rule_violations),
        reason_codes=tuple(item.value for item in validation.reason_codes),
        validation_profile_id=validation.validation_profile_id,
        recommended=recommended,
    )


def _map_modified_revalidation(result) -> GoldenDemoModifiedRevalidationReadModel:
    validation = result.validation_result
    primary = validation.primary_conflict
    return GoldenDemoModifiedRevalidationReadModel(
        revalidation_step_id=result.revalidation_step_id,
        source_decision_step_id=result.source_decision_step_id,
        candidate_id=result.modified_candidate.candidate_id,
        evaluated_at_utc=_utc_text(validation.evaluated_at_utc),
        validation_run_id=result.validation_run.validation_run_id,
        verdict=validation.verdict.value,
        primary_conflict_status=primary.status.value,
        primary_horizontal_separation_nm=primary.minimum_separation.horizontal_nm,
        primary_vertical_separation_ft=primary.minimum_separation.vertical_ft,
        tcpa_seconds=primary.tcpa_seconds,
        secondary_conflict_aircraft_ids=tuple(
            item.pair.aircraft_ids for item in validation.secondary_conflicts
        ),
        performance_feasible=validation.performance_feasible,
        rule_violation_ids=tuple(item.rule_id for item in validation.rule_violations),
        reason_codes=tuple(item.value for item in validation.reason_codes),
        validation_profile_id=validation.validation_profile_id,
        safe_to_apply=validation.is_safe,
    )


def _map_primary_conflict(
    *,
    step_result,
    resolution_result,
) -> GoldenDemoConflictEvidenceReadModel | None:
    """Keep the pre-maneuver conflict evidence stable through the decision chain."""

    risk = (
        resolution_result.source_exception.assessment
        if resolution_result is not None
        else _highest_actionable_risk(step_result)
    )
    if risk is None:
        return None

    event = _matching_conflict_event(step_result, risk)
    # 사건을 실제로 분류한 기준과 같아야 한다. 여기서만 다른 값을 쓰면
    # 위험평가기의 프로파일 일치 검사에 걸린다.
    rule = active_separation_profile()
    minimum_horizontal_nm = (
        event.minimum_separation.horizontal_nm
        if event is not None
        else risk.horizontal_separation_ratio * rule.horizontal_threshold_nm
    )
    minimum_vertical_ft = (
        event.minimum_separation.vertical_ft
        if event is not None
        else risk.vertical_separation_ratio * rule.vertical_threshold_ft
    )
    closest_approach_time = (
        event.closest_approach_time_utc
        if event is not None
        else risk.evaluated_at_utc + timedelta(seconds=risk.tcpa_seconds)
    )
    status = (
        event.status
        if event is not None
        else rule.classify(
            SeparationMinimum(minimum_horizontal_nm, minimum_vertical_ft)
        )
    )
    return GoldenDemoConflictEvidenceReadModel(
        conflict_id=risk.conflict_id,
        aircraft_ids=risk.pair.aircraft_ids,
        status=status.value,
        evaluated_at_utc=_utc_text(risk.evaluated_at_utc),
        closest_approach_time_utc=_utc_text(closest_approach_time),
        tcpa_seconds=risk.tcpa_seconds,
        horizontal_separation_nm=minimum_horizontal_nm,
        vertical_separation_ft=minimum_vertical_ft,
        horizontal_threshold_nm=rule.horizontal_threshold_nm,
        vertical_threshold_ft=rule.vertical_threshold_ft,
        horizontal_separation_ratio=risk.horizontal_separation_ratio,
        vertical_separation_ratio=risk.vertical_separation_ratio,
        risk_score=risk.risk_score,
        risk_level=risk.risk_level.value,
        risk_reason_codes=tuple(item.value for item in risk.reason_codes),
        rule_profile_id=rule.profile_id,
        risk_policy_profile_id=risk.policy_profile_id,
    )


def _highest_actionable_risk(step_result) -> ConflictRiskAssessment | None:
    if step_result is None:
        return None
    actionable = tuple(
        item
        for item in step_result.risk_assessments
        if item.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL)
    )
    if not actionable:
        return None
    return sorted(
        actionable,
        key=lambda item: (-item.risk_score, item.tcpa_seconds, item.conflict_id),
    )[0]


def _matching_conflict_event(
    step_result,
    risk: ConflictRiskAssessment,
) -> ConflictEvent | None:
    if step_result is None or step_result.conflict_run is None:
        return None
    return next(
        (
            item
            for item in step_result.conflict_run.assessments
            if item.conflict_id == risk.conflict_id
        ),
        None,
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
    modified_revalidation = getattr(application_result, "modified_revalidation", None)
    if modified_revalidation is None:
        candidate = application_result.decision_entry.approved_candidate
        application_source = "ACCEPTED_RECOMMENDATION"
        source_modified_revalidation_step_id = None
        authorization_id = None
        authorized_at_utc = None
    else:
        candidate = modified_revalidation.modified_candidate
        application_source = "REVALIDATED_MODIFICATION"
        source_modified_revalidation_step_id = (
            application_result.source_revalidation_step_id
        )
        authorization_id = application_result.authorization_id
        authorized_at_utc = _utc_text(application_result.authorized_at_utc)
    return GoldenDemoRevalidationReadModel(
        application_step_id=application_result.application_step_id,
        source_decision_step_id=application_result.source_decision_step_id,
        application_source=application_source,
        source_modified_revalidation_step_id=source_modified_revalidation_step_id,
        authorization_id=authorization_id,
        authorized_at_utc=authorized_at_utc,
        applied_maneuver_type=candidate.maneuver.maneuver_type.value,
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
