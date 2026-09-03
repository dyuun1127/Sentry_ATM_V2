"""Continuous horizontal CPA/TCPA under constant aircraft velocity."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from math import cos, hypot, radians, sin
from numbers import Real

from sentry_atm.domain import AircraftState, ConflictPair, SeparationMinimum
from sentry_atm.domain.time_policy import to_utc
from sentry_atm.domain.units import (
    as_non_negative_float,
    fpm_to_ft_per_second,
    knots_to_nm_per_second,
)

DEFAULT_CPA_HORIZON_SECONDS = 120.0


def _as_positive_float(value: Real, *, field_name: str) -> float:
    normalized = as_non_negative_float(value, field_name=field_name)
    if normalized == 0.0:
        raise ValueError(f"{field_name} must be greater than zero")
    return normalized


@dataclass(frozen=True, slots=True)
class ClosestApproachResult:
    """One pair's closest horizontal approach inside a finite look-ahead."""

    pair: ConflictPair
    evaluated_at_utc: datetime
    closest_approach_time_utc: datetime
    minimum_separation: SeparationMinimum
    horizon_seconds: float

    def __post_init__(self) -> None:
        if not isinstance(self.pair, ConflictPair):
            raise TypeError("pair must be a ConflictPair")
        object.__setattr__(
            self,
            "evaluated_at_utc",
            to_utc(self.evaluated_at_utc, field_name="evaluated_at_utc"),
        )
        object.__setattr__(
            self,
            "closest_approach_time_utc",
            to_utc(
                self.closest_approach_time_utc,
                field_name="closest_approach_time_utc",
            ),
        )
        if self.closest_approach_time_utc < self.evaluated_at_utc:
            raise ValueError("closest_approach_time_utc must not precede evaluated_at_utc")
        if not isinstance(self.minimum_separation, SeparationMinimum):
            raise TypeError("minimum_separation must be a SeparationMinimum")
        object.__setattr__(
            self,
            "horizon_seconds",
            _as_positive_float(self.horizon_seconds, field_name="horizon_seconds"),
        )
        if self.tcpa_seconds > self.horizon_seconds:
            raise ValueError("closest approach must not exceed horizon_seconds")

    @property
    def tcpa_seconds(self) -> float:
        """Return seconds from evaluation to closest horizontal approach."""

        return (self.closest_approach_time_utc - self.evaluated_at_utc).total_seconds()


class ConstantVelocityClosestApproachCalculator:
    """Calculate continuous horizontal CPA and separation at TCPA."""

    __slots__ = ("_horizon_seconds",)

    def __init__(self, *, horizon_seconds: Real = DEFAULT_CPA_HORIZON_SECONDS) -> None:
        self._horizon_seconds = _as_positive_float(
            horizon_seconds,
            field_name="horizon_seconds",
        )

    @property
    def horizon_seconds(self) -> float:
        """Return the finite look-ahead used to clamp TCPA."""

        return self._horizon_seconds

    def calculate(
        self,
        first: AircraftState,
        second: AircraftState,
    ) -> ClosestApproachResult:
        """Return horizontal CPA/TCPA for two same-time constant-velocity states."""

        if not isinstance(first, AircraftState) or not isinstance(second, AircraftState):
            raise TypeError("first and second must be AircraftState instances")
        if first.timestamp_utc != second.timestamp_utc:
            raise ValueError("aircraft states must share the same timestamp")

        pair = ConflictPair(first.aircraft_id, second.aircraft_id)
        first_velocity = self._velocity(first)
        second_velocity = self._velocity(second)
        relative_x_nm = second.x_nm - first.x_nm
        relative_y_nm = second.y_nm - first.y_nm
        relative_vx_nm_per_second = second_velocity[0] - first_velocity[0]
        relative_vy_nm_per_second = second_velocity[1] - first_velocity[1]
        relative_speed_squared = relative_vx_nm_per_second**2 + relative_vy_nm_per_second**2

        if relative_speed_squared == 0.0:
            tcpa_seconds = 0.0
        else:
            unbounded_tcpa_seconds = (
                -(
                    relative_x_nm * relative_vx_nm_per_second
                    + relative_y_nm * relative_vy_nm_per_second
                )
                / relative_speed_squared
            )
            tcpa_seconds = min(
                self._horizon_seconds,
                max(0.0, unbounded_tcpa_seconds),
            )

        closest_approach_time_utc = first.timestamp_utc + timedelta(seconds=tcpa_seconds)
        tcpa_seconds = (closest_approach_time_utc - first.timestamp_utc).total_seconds()

        cpa_relative_x_nm = relative_x_nm + relative_vx_nm_per_second * tcpa_seconds
        cpa_relative_y_nm = relative_y_nm + relative_vy_nm_per_second * tcpa_seconds
        relative_altitude_ft = second.altitude_ft - first.altitude_ft
        relative_vertical_speed_ft_per_second = second_velocity[2] - first_velocity[2]
        cpa_vertical_separation_ft = abs(
            relative_altitude_ft + relative_vertical_speed_ft_per_second * tcpa_seconds
        )

        return ClosestApproachResult(
            pair=pair,
            evaluated_at_utc=first.timestamp_utc,
            closest_approach_time_utc=closest_approach_time_utc,
            minimum_separation=SeparationMinimum(
                horizontal_nm=hypot(cpa_relative_x_nm, cpa_relative_y_nm),
                vertical_ft=cpa_vertical_separation_ft,
            ),
            horizon_seconds=self._horizon_seconds,
        )

    @staticmethod
    def _velocity(state: AircraftState) -> tuple[float, float, float]:
        heading_rad = radians(state.heading_deg)
        horizontal_speed_nm_per_second = knots_to_nm_per_second(state.ground_speed_kt)
        return (
            horizontal_speed_nm_per_second * sin(heading_rad),
            horizontal_speed_nm_per_second * cos(heading_rad),
            fpm_to_ft_per_second(state.vertical_speed_fpm),
        )
