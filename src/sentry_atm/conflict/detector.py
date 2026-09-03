"""Deterministic all-pairs predictive conflict assessment."""

from collections.abc import Iterable
from itertools import combinations

from sentry_atm.conflict.closest_approach import (
    ConstantVelocityClosestApproachCalculator,
)
from sentry_atm.domain import (
    POC_TERMINAL_V1_RULE_PROFILE,
    AircraftState,
    ConflictEvent,
    ConflictStatus,
    SeparationRuleProfile,
)


class PairwiseConflictDetector:
    """Assess every unique Aircraft pair in stable identifier order."""

    __slots__ = ("_calculator", "_rule_profile")

    def __init__(
        self,
        *,
        calculator: ConstantVelocityClosestApproachCalculator | None = None,
        rule_profile: SeparationRuleProfile = POC_TERMINAL_V1_RULE_PROFILE,
    ) -> None:
        selected_calculator = (
            ConstantVelocityClosestApproachCalculator() if calculator is None else calculator
        )
        if not isinstance(
            selected_calculator,
            ConstantVelocityClosestApproachCalculator,
        ):
            raise TypeError("calculator must be a ConstantVelocityClosestApproachCalculator")
        if not isinstance(rule_profile, SeparationRuleProfile):
            raise TypeError("rule_profile must be a SeparationRuleProfile")
        self._calculator = selected_calculator
        self._rule_profile = rule_profile

    @property
    def calculator(self) -> ConstantVelocityClosestApproachCalculator:
        """Return the injected closest-approach calculator."""

        return self._calculator

    @property
    def rule_profile(self) -> SeparationRuleProfile:
        """Return the injected separation rule profile."""

        return self._rule_profile

    def assess(
        self,
        states: Iterable[AircraftState],
    ) -> tuple[ConflictEvent, ...]:
        """Return SAFE and PREDICTED assessments for every unique pair."""

        ordered_states = self._validate_and_order_states(states)
        return tuple(
            self._assess_pair(first, second) for first, second in combinations(ordered_states, 2)
        )

    def detect(
        self,
        states: Iterable[AircraftState],
    ) -> tuple[ConflictEvent, ...]:
        """Return only PREDICTED assessments in deterministic pair order."""

        return tuple(
            event for event in self.assess(states) if event.status is ConflictStatus.PREDICTED
        )

    def _assess_pair(
        self,
        first: AircraftState,
        second: AircraftState,
    ) -> ConflictEvent:
        closest_approach = self._calculator.calculate(first, second)
        # 분리 최저치가 쌍에 따라 달라질 수 있으므로 두 항적을 함께 넘긴다
        # (고시 5-5-4 차의 중량등급 조건, 5-5-8 편대 추가분리 등).
        status = self._rule_profile.classify(
            closest_approach.minimum_separation, first, second
        )
        pair = closest_approach.pair
        timestamp_token = closest_approach.evaluated_at_utc.strftime("%Y%m%dT%H%M%S%fZ")
        return ConflictEvent(
            conflict_id=(
                f"CONFLICT-{timestamp_token}-{pair.first_aircraft_id}-{pair.second_aircraft_id}"
            ),
            pair=pair,
            status=status,
            evaluated_at_utc=closest_approach.evaluated_at_utc,
            closest_approach_time_utc=closest_approach.closest_approach_time_utc,
            minimum_separation=closest_approach.minimum_separation,
            rule_profile_id=self._rule_profile.profile_id,
        )

    @staticmethod
    def _validate_and_order_states(
        states: Iterable[AircraftState],
    ) -> tuple[AircraftState, ...]:
        if isinstance(states, (str, bytes)):
            raise TypeError("states must be an iterable of AircraftState instances")
        try:
            materialized_states = tuple(states)
        except TypeError:
            raise TypeError("states must be an iterable of AircraftState instances") from None
        if not all(isinstance(state, AircraftState) for state in materialized_states):
            raise TypeError("states must contain only AircraftState instances")

        aircraft_ids = tuple(state.aircraft_id for state in materialized_states)
        if len(set(aircraft_ids)) != len(aircraft_ids):
            raise ValueError("states must have unique aircraft IDs")
        timestamps = {state.timestamp_utc for state in materialized_states}
        if len(timestamps) > 1:
            raise ValueError("states must share the same timestamp")
        return tuple(sorted(materialized_states, key=lambda state: state.aircraft_id))
