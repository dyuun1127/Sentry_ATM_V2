"""Deterministic trajectory prediction services."""

from sentry_atm.prediction.baseline import (
    DEFAULT_HORIZONS_SECONDS,
    ConstantVelocityPredictor,
)

__all__ = [
    "DEFAULT_HORIZONS_SECONDS",
    "ConstantVelocityPredictor",
]
