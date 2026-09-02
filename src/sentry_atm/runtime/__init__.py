"""Golden Demo application composition."""

from sentry_atm.runtime.composition import (
    GoldenDemoRuntime,
    InMemoryRecommendationCatalog,
    build_golden_demo_runtime,
)

__all__ = [
    "GoldenDemoRuntime",
    "InMemoryRecommendationCatalog",
    "build_golden_demo_runtime",
]
