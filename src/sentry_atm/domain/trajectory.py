"""Minimal immutable 4D trajectory models."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from sentry_atm.domain.enums import TrajectoryType
from sentry_atm.domain.time_policy import to_utc
from sentry_atm.domain.units import as_finite_float


def _require_aircraft_id(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("aircraft_id must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError("aircraft_id must not be blank")
    return normalized


@dataclass(frozen=True, slots=True)
class TrajectoryPoint:
    """A single local Cartesian 4DT point in canonical units."""

    timestamp_utc: datetime
    x_nm: float
    y_nm: float
    altitude_ft: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "timestamp_utc",
            to_utc(self.timestamp_utc, field_name="timestamp_utc"),
        )
        object.__setattr__(self, "x_nm", as_finite_float(self.x_nm, field_name="x_nm"))
        object.__setattr__(self, "y_nm", as_finite_float(self.y_nm, field_name="y_nm"))
        object.__setattr__(
            self,
            "altitude_ft",
            as_finite_float(self.altitude_ft, field_name="altitude_ft"),
        )


@dataclass(frozen=True, slots=True)
class Trajectory:
    """A non-empty, strictly time-ordered sequence of 4DT points."""

    aircraft_id: str
    trajectory_type: TrajectoryType
    points: tuple[TrajectoryPoint, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "aircraft_id", _require_aircraft_id(self.aircraft_id))
        object.__setattr__(self, "trajectory_type", TrajectoryType(self.trajectory_type))
        object.__setattr__(self, "points", tuple(self.points))
        if not self.points:
            raise ValueError("trajectory must contain at least one point")
        if not all(isinstance(point, TrajectoryPoint) for point in self.points):
            raise TypeError("trajectory points must all be TrajectoryPoint instances")
        self._validate_strict_time_order()

    @classmethod
    def from_points(
        cls,
        *,
        aircraft_id: str,
        trajectory_type: TrajectoryType,
        points: Iterable[TrajectoryPoint],
    ) -> "Trajectory":
        """Build a trajectory from any finite iterable of points."""

        return cls(
            aircraft_id=aircraft_id,
            trajectory_type=trajectory_type,
            points=tuple(points),
        )

    def _validate_strict_time_order(self) -> None:
        for previous, current in zip(self.points, self.points[1:], strict=False):
            if current.timestamp_utc <= previous.timestamp_utc:
                raise ValueError("trajectory timestamps must be strictly increasing")

    @property
    def start_time_utc(self) -> datetime:
        return self.points[0].timestamp_utc

    @property
    def end_time_utc(self) -> datetime:
        return self.points[-1].timestamp_utc

    @property
    def duration_seconds(self) -> float:
        return (self.end_time_utc - self.start_time_utc).total_seconds()
