"""Reproducible prediction-run aggregate metadata."""

from dataclasses import dataclass
from datetime import datetime

from sentry_atm.domain.enums import TrajectoryType
from sentry_atm.domain.time_policy import to_utc
from sentry_atm.domain.trajectory import Trajectory
from sentry_atm.domain.validation import normalize_optional_text, require_identifier


@dataclass(frozen=True, slots=True)
class PredictionRun:
    """A versioned predictor execution and its predicted trajectories."""

    prediction_run_id: str
    input_timestamp_utc: datetime
    generated_at_utc: datetime
    model_name: str
    model_version: str
    horizons_seconds: tuple[int, ...]
    trajectories: tuple[Trajectory, ...] = ()
    configuration_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "prediction_run_id",
            require_identifier(
                self.prediction_run_id,
                field_name="prediction_run_id",
            ),
        )
        object.__setattr__(
            self,
            "input_timestamp_utc",
            to_utc(self.input_timestamp_utc, field_name="input_timestamp_utc"),
        )
        object.__setattr__(
            self,
            "generated_at_utc",
            to_utc(self.generated_at_utc, field_name="generated_at_utc"),
        )
        object.__setattr__(
            self,
            "model_name",
            require_identifier(self.model_name, field_name="model_name"),
        )
        object.__setattr__(
            self,
            "model_version",
            require_identifier(self.model_version, field_name="model_version"),
        )
        object.__setattr__(self, "horizons_seconds", tuple(self.horizons_seconds))
        object.__setattr__(self, "trajectories", tuple(self.trajectories))
        object.__setattr__(
            self,
            "configuration_id",
            normalize_optional_text(
                self.configuration_id,
                field_name="configuration_id",
            ),
        )
        self._validate_horizons()
        self._validate_trajectories()

    def _validate_horizons(self) -> None:
        if not self.horizons_seconds:
            raise ValueError("horizons_seconds must not be empty")
        if any(
            isinstance(value, bool) or not isinstance(value, int) for value in self.horizons_seconds
        ):
            raise TypeError("horizons_seconds must contain only integers")
        if any(value <= 0 for value in self.horizons_seconds):
            raise ValueError("horizons_seconds must contain only positive values")
        if any(
            current <= previous
            for previous, current in zip(
                self.horizons_seconds,
                self.horizons_seconds[1:],
                strict=False,
            )
        ):
            raise ValueError("horizons_seconds must be strictly increasing")

    def _validate_trajectories(self) -> None:
        if not all(isinstance(item, Trajectory) for item in self.trajectories):
            raise TypeError("trajectories must contain only Trajectory instances")
        if any(item.trajectory_type is not TrajectoryType.PREDICTED for item in self.trajectories):
            raise ValueError("prediction run trajectories must be PREDICTED")
        aircraft_ids = tuple(item.aircraft_id for item in self.trajectories)
        if len(set(aircraft_ids)) != len(aircraft_ids):
            raise ValueError("prediction run must contain at most one trajectory per aircraft")
