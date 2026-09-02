"""Golden Demo application composition."""

from sentry_atm.runtime.composition import (
    GoldenDemoRuntime,
    InMemoryRecommendationCatalog,
    build_golden_demo_runtime,
)
from sentry_atm.runtime.orchestrator import (
    GoldenDemoStepOrchestrator,
    GoldenDemoStepResult,
)
from sentry_atm.runtime.resolution_orchestrator import (
    GoldenDemoResolutionOrchestrator,
    GoldenDemoResolutionResult,
)

__all__ = [
    "GoldenDemoRuntime",
    "GoldenDemoResolutionOrchestrator",
    "GoldenDemoResolutionResult",
    "GoldenDemoStepOrchestrator",
    "GoldenDemoStepResult",
    "InMemoryRecommendationCatalog",
    "build_golden_demo_runtime",
]
