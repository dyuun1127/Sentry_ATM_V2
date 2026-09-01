"""Deterministic constant-velocity baseline trajectory predictor."""

from collections.abc import Iterable
from datetime import timedelta
from math import cos, radians, sin

from sentry_atm.domain import AircraftState, Trajectory, TrajectoryPoint, TrajectoryType
from sentry_atm.domain.units import fpm_to_ft_per_second, knots_to_nm_per_second

DEFAULT_HORIZONS_SECONDS = (30, 60, 120)


def _validate_horizons(horizons_seconds: Iterable[int]) -> tuple[int, ...]:
    if isinstance(horizons_seconds, (str, bytes)):
        raise TypeError("horizons_seconds must be an iterable of integers")
    try:
        normalized = tuple(horizons_seconds)
    except TypeError:
        raise TypeError("horizons_seconds must be an iterable of integers") from None
    if not normalized:
        raise ValueError("horizons_seconds must not be empty")
    if any(isinstance(value, bool) or not isinstance(value, int) for value in normalized):
        raise TypeError("horizons_seconds must contain only integers")
    if any(value <= 0 for value in normalized):
        raise ValueError("horizons_seconds must contain only positive values")
    if any(
        current <= previous for previous, current in zip(normalized, normalized[1:], strict=False)
    ):
        raise ValueError("horizons_seconds must be strictly increasing")
    return normalized


class ConstantVelocityPredictor:
    """Project one current state with constant speed, heading, and vertical rate."""

    MODEL_NAME = "constant-velocity"
    MODEL_VERSION = "1.0.0"
    CONFIGURATION_ID = "BASELINE-CV-V1"

    __slots__ = ("_horizons_seconds",)

    def __init__(
        self,
        horizons_seconds: Iterable[int] = DEFAULT_HORIZONS_SECONDS,
    ) -> None:
        self._horizons_seconds = _validate_horizons(horizons_seconds)

    @property
    def horizons_seconds(self) -> tuple[int, ...]:
        return self._horizons_seconds

    def predict(self, state: AircraftState) -> Trajectory:
        """Return PREDICTED 4DT points at each configured future horizon."""

        if not isinstance(state, AircraftState):
            raise TypeError("state must be an AircraftState")

        heading_rad = radians(state.heading_deg)
        horizontal_speed_nm_per_second = knots_to_nm_per_second(state.ground_speed_kt)
        vertical_speed_ft_per_second = fpm_to_ft_per_second(state.vertical_speed_fpm)

        return Trajectory(
            aircraft_id=state.aircraft_id,
            trajectory_type=TrajectoryType.PREDICTED,
            points=tuple(
                TrajectoryPoint(
                    timestamp_utc=state.timestamp_utc + timedelta(seconds=horizon_seconds),
                    x_nm=(
                        state.x_nm
                        + horizontal_speed_nm_per_second * horizon_seconds * sin(heading_rad)
                    ),
                    y_nm=(
                        state.y_nm
                        + horizontal_speed_nm_per_second * horizon_seconds * cos(heading_rad)
                    ),
                    altitude_ft=(
                        state.altitude_ft + vertical_speed_ft_per_second * horizon_seconds
                    ),
                )
                for horizon_seconds in self._horizons_seconds
            ),
        )
