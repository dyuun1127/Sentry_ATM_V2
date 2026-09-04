"""예외 하나를 회피안 목록으로 — 어느 시나리오에서든.

이 계층은 골든 데모의 보정된 순간(T+75, CIV-A02/MIL-F01, 9,000 ft)에 못박혀
있었다. 그 값들은 시연 대본을 재현하기 위한 것이고, 다른 시나리오에서는 상신
자체가 성립하지 않게 만들었다 — 75분짜리 소티에서 T+75 는 아무 일도 없는 시각이다.

보정을 걷어내되 지켜야 할 것은 남긴다. 증거가 현재 시각의 것이어야 하고, 한 틱에
한 번만 상신하며, 위험도가 충분히 높아야 한다. 이것들은 시나리오와 무관하게
성립하는 조건이다.

보정된 값이 있던 자리에는 파생 규칙이 들어간다. 대상 예외는 가장 심각한 것,
기동시킬 항공기는 우선권과 안정 여부와 성능으로 정한다. 고도는 후보 생성기가
배정 가능한 값으로 낸다.
"""

from dataclasses import dataclass
from datetime import datetime

from sentry_atm.domain import (
    AircraftPerformanceProfile,
    AircraftState,
    ConflictExceptionItem,
    EmergencyStatus,
    ExceptionStatus,
    ResolutionCandidateBatch,
    ResolutionRecommendationSet,
    ResolutionSafetyValidationRun,
    RiskLevel,
)
from sentry_atm.domain.approach_sequence import STABILISED_PHASES
from sentry_atm.runtime.orchestrator import GoldenDemoStepOrchestrator
from sentry_atm.scenario import ScenarioAircraft

# 상신 대상이 되는 위험 등급. 이보다 낮은 것을 올리면 큐가 배경 소음으로 차고,
# 관제사가 큐 자체를 보지 않게 된다.
_RESOLVABLE_RISK = (RiskLevel.HIGH, RiskLevel.CRITICAL)


@dataclass(frozen=True, slots=True)
class GoldenDemoResolutionResult:
    """Immutable evidence produced from one Golden Demo Conflict Exception."""

    resolution_step_id: str
    source_step_id: str
    timestamp_utc: datetime
    source_exception: ConflictExceptionItem
    candidate_batch: ResolutionCandidateBatch
    validation_run: ResolutionSafetyValidationRun
    recommendation_set: ResolutionRecommendationSet


class GoldenDemoResolutionOrchestrator:
    """Generate, validate, rank and publish the calibrated T+75 Resolution."""

    __slots__ = (
        "_last_result",
        "_last_tick_count",
        "_observed_reset_count",
        "_step_orchestrator",
    )

    def __init__(self, step_orchestrator: GoldenDemoStepOrchestrator) -> None:
        if not isinstance(step_orchestrator, GoldenDemoStepOrchestrator):
            raise TypeError("step_orchestrator must be a GoldenDemoStepOrchestrator")
        self._step_orchestrator = step_orchestrator
        self._observed_reset_count = step_orchestrator.runtime.simulation.clock.reset_count
        self._last_tick_count: int | None = None
        self._last_result: GoldenDemoResolutionResult | None = None

    @property
    def step_orchestrator(self) -> GoldenDemoStepOrchestrator:
        return self._step_orchestrator

    @property
    def last_result(self) -> GoldenDemoResolutionResult | None:
        _ = self._step_orchestrator.last_result
        self._synchronize_reset()
        return self._last_result

    def resolve(self) -> GoldenDemoResolutionResult:
        """현재 단계의 가장 심각한 예외 하나를 회피안 목록으로 낸다."""

        step_result = self._step_orchestrator.last_result
        self._synchronize_reset()
        if step_result is None:
            raise ValueError("a Golden Demo Step is required before Resolution")

        runtime = self._step_orchestrator.runtime
        clock = runtime.simulation.clock
        # 증거가 현재 시각의 것이어야 한다. 지난 단계로 회피안을 만들면 이미
        # 움직인 항공기에 대해 판단하게 된다.
        if step_result.timestamp_utc != clock.current_time_utc:
            raise ValueError("the latest Golden Demo Step must match the current Clock")
        if self._last_tick_count == clock.tick_count:
            raise ValueError("a Golden Demo Resolution already exists for the current Tick")

        source_exception = _select_source_exception(
            step_result.exception_queue_snapshot.active_items
        )
        pair_states = tuple(
            state
            for state in step_result.traffic_snapshot.states
            if state.aircraft_id in source_exception.subject_aircraft_ids
        )
        performance_profiles = _performance_profiles_for_pair(
            runtime.performance_profiles,
            runtime.definition.aircraft,
            source_exception.subject_aircraft_ids,
        )
        candidate_batch = runtime.candidate_generator.generate(
            source_exception,
            pair_states,
            performance_profiles,
            preferred_target_aircraft_id=_preferred_target_aircraft_id(
                pair_states, performance_profiles
            ),
            # 고도는 지정하지 않는다. 생성기가 현재고도와 성능에서 배정 가능한
            # 값을 낸다 — 여기서 숫자를 고르면 그 숫자가 어디서 왔는지 설명할
            # 근거가 없다.
            preferred_altitude_ft=None,
        )
        validation_run = runtime.safety_validator.validate(
            candidate_batch,
            step_result.traffic_snapshot.states,
            performance_profiles,
        )
        recommendation_set = runtime.recommendation_service.recommend(
            candidate_batch,
            validation_run,
            generated_at_utc=step_result.timestamp_utc,
        )
        runtime.recommendation_catalog.publish(recommendation_set)

        result = GoldenDemoResolutionResult(
            resolution_step_id=f"GOLDEN-RESOLUTION-{clock.tick_count:012d}",
            source_step_id=step_result.step_id,
            timestamp_utc=step_result.timestamp_utc,
            source_exception=source_exception,
            candidate_batch=candidate_batch,
            validation_run=validation_run,
            recommendation_set=recommendation_set,
        )
        self._last_tick_count = clock.tick_count
        self._last_result = result
        return result

    def _synchronize_reset(self) -> None:
        reset_count = self._step_orchestrator.runtime.simulation.clock.reset_count
        if reset_count == self._observed_reset_count:
            return
        self._last_tick_count = None
        self._last_result = None
        self._observed_reset_count = reset_count


def _select_source_exception(items: tuple) -> ConflictExceptionItem:
    """상신할 예외 하나를 고른다 — 가장 심각한 것.

    한 번에 하나만 다루는 이유는 회피안이 서로 간섭하기 때문이다. 두 예외에
    동시에 기동을 내면 한쪽을 푼 기동이 다른 쪽을 만들 수 있고, 그때 어느
    회피안이 원인인지 화면에서 가려낼 수 없다.
    """
    matches = tuple(
        item
        for item in items
        if isinstance(item, ConflictExceptionItem)
        and item.status is not ExceptionStatus.RESOLVED
        and item.assessment.risk_level in _RESOLVABLE_RISK
    )
    if not matches:
        raise ValueError(
            "an active Conflict Exception with HIGH or CRITICAL Risk is required"
        )
    # 위험도가 같으면 예외 식별자로 정한다. 순서가 흔들리면 같은 입력에서 다른
    # 회피안이 나오고, 시연에서 무엇을 보여 주는지 설명할 수 없다.
    return min(
        matches,
        key=lambda item: (
            -_RISK_RANK[item.assessment.risk_level],
            item.exception_id,
        ),
    )


_RISK_RANK = {RiskLevel.CRITICAL: 2, RiskLevel.HIGH: 1}


def _preferred_target_aircraft_id(
    pair_states: tuple[AircraftState, ...],
    performance_profiles: dict[str, AircraftPerformanceProfile],
) -> str:
    """둘 중 어느 쪽을 기동시킬 것인가.

    셋을 차례로 본다.

    **비상 선언한 항공기는 움직이지 않는다** (고시 2-1-4 가). 조난 항공기에 우선
    통행권이 있고, 그 항공기를 벡터로 돌리는 것은 우선권을 이름뿐으로 만든다.

    **최종접근에 안정된 항공기도 움직이지 않는다** (`ASM-023`, `ASM-026`). 늦은
    기동의 위험은 순서를 바꾸든 고도를 바꾸든 똑같이 생긴다. 접근 순서 재구성에서
    쓰는 것과 같은 기준이다.

    **남으면 여유가 큰 쪽을 움직인다.** 상승·강하 성능이 좋을수록 같은 시간에 더
    많은 수직 분리를 만들 수 있다. 전투기와 여객기가 얽히면 전투기가 움직이는 것이
    그 때문이며, 소속이 아니라 성능으로 정한다.
    """
    if len(pair_states) != 2:
        raise ValueError("a Conflict Pair must contain exactly two Aircraft states")

    def movable(state: AircraftState) -> bool:
        if state.emergency_status is EmergencyStatus.DECLARED:
            return False
        return state.flight_phase not in STABILISED_PHASES

    movable_states = tuple(state for state in pair_states if movable(state))
    if not movable_states:
        # 둘 다 건드릴 수 없으면 회피안을 만들 수 없다. 조용히 한쪽을 고르면
        # 우선권이나 안정 규칙을 어긴 안이 상신된다.
        raise ValueError(
            "neither Conflict Pair Aircraft may be manoeuvred "
            "(emergency priority or stabilised on final approach)"
        )

    def vertical_margin(state: AircraftState) -> float:
        profile = performance_profiles[state.aircraft_id]
        return max(profile.max_climb_rate_fpm, profile.max_descent_rate_fpm)

    return min(
        movable_states,
        key=lambda state: (-vertical_margin(state), state.aircraft_id),
    ).aircraft_id


def _performance_profiles_for_pair(
    profiles: tuple[AircraftPerformanceProfile, ...],
    scenario_aircraft: tuple[ScenarioAircraft, ...],
    aircraft_ids: tuple[str, str],
) -> dict[str, AircraftPerformanceProfile]:
    profile_by_id = {profile.profile_id: profile for profile in profiles}
    metadata_by_id = {item.aircraft_id: item.metadata for item in scenario_aircraft}
    try:
        return {
            aircraft_id: profile_by_id[metadata_by_id[aircraft_id].performance_class]
            for aircraft_id in aircraft_ids
        }
    except KeyError:
        raise ValueError(
            "Golden Demo Aircraft must reference an available Performance Profile"
        ) from None
