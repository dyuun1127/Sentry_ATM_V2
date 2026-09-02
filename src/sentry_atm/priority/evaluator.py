"""Deterministic operational Priority evaluation from active Scenario events."""

from collections.abc import Iterable

from sentry_atm.domain import (
    POC_OPERATIONAL_PRIORITY_V1_POLICY_PROFILE,
    AircraftState,
    EmergencyStatus,
    OperationalPriorityAssessment,
    OperationalPriorityPolicyProfile,
    PriorityReasonCode,
)
from sentry_atm.scenario import (
    EmergencyDeclaredPayload,
    EmergencyReasonCategory,
    ScenarioEvent,
    ScenarioEventType,
)


class OperationalPriorityEvaluator:
    """Evaluate one Aircraft independently from Conflict Risk."""

    __slots__ = ("_policy",)

    def __init__(
        self,
        policy: OperationalPriorityPolicyProfile = (POC_OPERATIONAL_PRIORITY_V1_POLICY_PROFILE),
    ) -> None:
        if not isinstance(policy, OperationalPriorityPolicyProfile):
            raise TypeError("policy must be an OperationalPriorityPolicyProfile")
        self._policy = policy

    @property
    def policy(self) -> OperationalPriorityPolicyProfile:
        return self._policy

    def evaluate(
        self,
        state: AircraftState,
        events: Iterable[ScenarioEvent] = (),
    ) -> OperationalPriorityAssessment:
        """Use only events due for the Aircraft at the State timestamp."""

        if not isinstance(state, AircraftState):
            raise TypeError("state must be an AircraftState")
        materialized_events = self._materialize_events(events)
        active_events = tuple(
            event
            for event in sorted(
                materialized_events,
                key=lambda item: (item.scheduled_time_utc, item.event_id),
            )
            if event.target_aircraft_id == state.aircraft_id
            and event.scheduled_time_utc <= state.timestamp_utc
        )

        emergency_events = tuple(
            event
            for event in active_events
            if event.event_type is ScenarioEventType.EMERGENCY_DECLARED
        )
        entry_events = tuple(
            event
            for event in active_events
            if event.event_type is ScenarioEventType.ENTRY_CONFORMANCE_DEVIATION
        )

        if state.emergency_status is EmergencyStatus.DECLARED or emergency_events:
            score = self._policy.emergency_declared_score
            level = self._policy.emergency_declared_level
            reasons = [PriorityReasonCode.EMERGENCY_DECLARED]
            if any(self._is_aircraft_condition(event) for event in emergency_events):
                reasons.append(PriorityReasonCode.AIRCRAFT_CONDITION)
            if entry_events:
                reasons.append(PriorityReasonCode.ENTRY_CONFORMANCE_DEVIATION)
        elif entry_events:
            score = self._policy.entry_deviation_score
            level = self._policy.entry_deviation_level
            reasons = [PriorityReasonCode.ENTRY_CONFORMANCE_DEVIATION]
        else:
            score = self._policy.routine_score
            level = self._policy.routine_level
            reasons = [PriorityReasonCode.ROUTINE_OPERATION]

        timestamp_token = state.timestamp_utc.strftime("%Y%m%dT%H%M%S%fZ")
        return OperationalPriorityAssessment(
            priority_assessment_id=(
                f"PRIORITY-{self._policy.profile_id}-{timestamp_token}-{state.aircraft_id}"
            ),
            aircraft_id=state.aircraft_id,
            evaluated_at_utc=state.timestamp_utc,
            priority_score=score,
            priority_level=level,
            reason_codes=tuple(reasons),
            policy_profile_id=self._policy.profile_id,
            source_event_ids=tuple(event.event_id for event in active_events),
        )

    @staticmethod
    def _materialize_events(
        events: Iterable[ScenarioEvent],
    ) -> tuple[ScenarioEvent, ...]:
        if isinstance(events, (str, bytes)):
            raise TypeError("events must be an iterable of ScenarioEvent instances")
        try:
            materialized = tuple(events)
        except TypeError:
            raise TypeError("events must be an iterable of ScenarioEvent instances") from None
        if not all(isinstance(event, ScenarioEvent) for event in materialized):
            raise TypeError("events must contain only ScenarioEvent instances")
        event_ids = tuple(event.event_id for event in materialized)
        if len(set(event_ids)) != len(event_ids):
            raise ValueError("events must have unique event IDs")
        return materialized

    @staticmethod
    def _is_aircraft_condition(event: ScenarioEvent) -> bool:
        payload = event.payload
        return (
            isinstance(payload, EmergencyDeclaredPayload)
            and payload.reason_category is EmergencyReasonCategory.AIRCRAFT_CONDITION
        )
