"""Composition root for deterministic Golden Demo components."""

from dataclasses import dataclass

from sentry_atm.api import (
    InProcessControllerDecisionApi,
    InProcessExceptionQueueApi,
    InProcessRecommendationApi,
)
from sentry_atm.conflict import (
    ConflictAssessmentService,
    PairwiseConflictDetector,
    RollingConflictScheduler,
)
from sentry_atm.controller_decision import DeterministicControllerDecisionService
from sentry_atm.domain import AircraftPerformanceProfile, ResolutionRecommendationSet
from sentry_atm.domain.validation import require_identifier
from sentry_atm.exception_queue import ExceptionQueueService
from sentry_atm.infrastructure.http import (
    ControllerDecisionWsgiApp,
    ExceptionQueueWsgiApp,
    RecommendationWsgiApp,
)
from sentry_atm.prediction import (
    ConstantVelocityPredictor,
    PredictionRunService,
    RollingPredictionScheduler,
)
from sentry_atm.priority import OperationalPriorityEvaluator
from sentry_atm.recommendation import DeterministicRecommendationRankingService
from sentry_atm.reference_data import POC_PERFORMANCE_PROFILES
from sentry_atm.resolution import (
    DeterministicResolutionCandidateGenerator,
    IsolatedResolutionSafetyValidator,
)
from sentry_atm.risk import ConflictRiskEvaluator
from sentry_atm.scenario import (
    GOLDEN_DEMO_SCENARIO_ID,
    ScenarioDefinition,
    ScenarioSimulation,
    build_golden_demo_scenario,
    build_scenario_simulation,
)


class InMemoryRecommendationCatalog:
    """Process-local source and lookup for immutable Recommendation Sets."""

    __slots__ = ("_current_id", "_sets_by_id")

    def __init__(self) -> None:
        self._sets_by_id: dict[str, ResolutionRecommendationSet] = {}
        self._current_id: str | None = None

    @property
    def recommendation_sets(self) -> tuple[ResolutionRecommendationSet, ...]:
        return tuple(
            sorted(
                self._sets_by_id.values(),
                key=lambda item: (item.generated_at_utc, item.recommendation_set_id),
            )
        )

    def get_current_recommendation(self) -> ResolutionRecommendationSet | None:
        if self._current_id is None:
            return None
        return self._sets_by_id[self._current_id]

    def get_recommendation_set(
        self,
        recommendation_set_id: str,
    ) -> ResolutionRecommendationSet | None:
        normalized_id = require_identifier(
            recommendation_set_id,
            field_name="recommendation_set_id",
        )
        return self._sets_by_id.get(normalized_id)

    def publish(self, recommendation_set: ResolutionRecommendationSet) -> None:
        """Append one immutable Set and make it current after all checks pass."""

        if not isinstance(recommendation_set, ResolutionRecommendationSet):
            raise TypeError("recommendation_set must be a ResolutionRecommendationSet")
        set_id = recommendation_set.recommendation_set_id
        if set_id in self._sets_by_id:
            raise ValueError("recommendation_set_id already exists")
        current = self.get_current_recommendation()
        if current is not None and recommendation_set.generated_at_utc < current.generated_at_utc:
            raise ValueError("Recommendation Set cannot precede the current Set")
        self._sets_by_id = {**self._sets_by_id, set_id: recommendation_set}
        self._current_id = set_id

    def reset(self) -> None:
        self._sets_by_id.clear()
        self._current_id = None


@dataclass(frozen=True, slots=True)
class GoldenDemoRuntime:
    """Wired components for one unstarted, process-local Golden Demo run."""

    simulation: ScenarioSimulation
    performance_profiles: tuple[AircraftPerformanceProfile, ...]
    prediction_scheduler: RollingPredictionScheduler
    conflict_scheduler: RollingConflictScheduler
    risk_evaluator: ConflictRiskEvaluator
    priority_evaluator: OperationalPriorityEvaluator
    exception_queue_service: ExceptionQueueService
    candidate_generator: DeterministicResolutionCandidateGenerator
    safety_validator: IsolatedResolutionSafetyValidator
    recommendation_service: DeterministicRecommendationRankingService
    recommendation_catalog: InMemoryRecommendationCatalog
    controller_decision_service: DeterministicControllerDecisionService
    exception_queue_api: InProcessExceptionQueueApi
    recommendation_api: InProcessRecommendationApi
    controller_decision_api: InProcessControllerDecisionApi
    exception_queue_http_app: ExceptionQueueWsgiApp
    recommendation_http_app: RecommendationWsgiApp
    controller_decision_http_app: ControllerDecisionWsgiApp

    @property
    def definition(self) -> ScenarioDefinition:
        return self.simulation.definition


def build_golden_demo_runtime() -> GoldenDemoRuntime:
    """Wire deterministic components without starting Clock or calculating outputs."""

    definition = build_golden_demo_scenario()
    if definition.scenario_id != GOLDEN_DEMO_SCENARIO_ID:  # pragma: no cover - builder invariant
        raise ValueError("Golden Demo builder returned an unexpected scenario")
    simulation = build_scenario_simulation(definition)

    prediction_service = PredictionRunService(ConstantVelocityPredictor())
    prediction_scheduler = RollingPredictionScheduler(
        clock=simulation.clock,
        service=prediction_service,
    )
    conflict_service = ConflictAssessmentService(PairwiseConflictDetector())
    conflict_scheduler = RollingConflictScheduler(
        clock=simulation.clock,
        service=conflict_service,
    )

    exception_queue_service = ExceptionQueueService()
    recommendation_catalog = InMemoryRecommendationCatalog()
    controller_decision_service = DeterministicControllerDecisionService()

    exception_queue_api = InProcessExceptionQueueApi(exception_queue_service)
    recommendation_api = InProcessRecommendationApi(recommendation_catalog)
    controller_decision_api = InProcessControllerDecisionApi(
        controller_decision_service,
        recommendation_catalog,
    )

    return GoldenDemoRuntime(
        simulation=simulation,
        performance_profiles=POC_PERFORMANCE_PROFILES,
        prediction_scheduler=prediction_scheduler,
        conflict_scheduler=conflict_scheduler,
        risk_evaluator=ConflictRiskEvaluator(),
        priority_evaluator=OperationalPriorityEvaluator(),
        exception_queue_service=exception_queue_service,
        candidate_generator=DeterministicResolutionCandidateGenerator(),
        safety_validator=IsolatedResolutionSafetyValidator(),
        recommendation_service=DeterministicRecommendationRankingService(),
        recommendation_catalog=recommendation_catalog,
        controller_decision_service=controller_decision_service,
        exception_queue_api=exception_queue_api,
        recommendation_api=recommendation_api,
        controller_decision_api=controller_decision_api,
        exception_queue_http_app=ExceptionQueueWsgiApp(exception_queue_api),
        recommendation_http_app=RecommendationWsgiApp(recommendation_api),
        controller_decision_http_app=ControllerDecisionWsgiApp(controller_decision_api),
    )
