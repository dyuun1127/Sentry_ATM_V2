"""Framework-independent HTTP adapters."""

from sentry_atm.infrastructure.http.controller_decision import (
    ControllerDecisionWsgiApp,
)
from sentry_atm.infrastructure.http.exception_queue import ExceptionQueueWsgiApp
from sentry_atm.infrastructure.http.recommendation import RecommendationWsgiApp
from sentry_atm.infrastructure.http.session import GoldenDemoSessionWsgiApp

__all__ = [
    "ControllerDecisionWsgiApp",
    "ExceptionQueueWsgiApp",
    "GoldenDemoSessionWsgiApp",
    "RecommendationWsgiApp",
]
