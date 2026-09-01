"""Build versioned multi-aircraft prediction runs from traffic snapshots."""

from datetime import datetime

from sentry_atm.domain import PredictionRun
from sentry_atm.domain.time_policy import to_utc
from sentry_atm.prediction.baseline import ConstantVelocityPredictor
from sentry_atm.simulation import TrafficSnapshot


class PredictionRunService:
    """Apply one predictor to every active state in a traffic snapshot."""

    __slots__ = ("_predictor",)

    def __init__(self, predictor: ConstantVelocityPredictor) -> None:
        if not isinstance(predictor, ConstantVelocityPredictor):
            raise TypeError("predictor must be a ConstantVelocityPredictor")
        self._predictor = predictor

    @property
    def predictor(self) -> ConstantVelocityPredictor:
        return self._predictor

    def run(
        self,
        snapshot: TrafficSnapshot,
        *,
        prediction_run_id: str,
        generated_at_utc: datetime,
    ) -> PredictionRun:
        """Return one immutable PredictionRun while preserving snapshot order."""

        if not isinstance(snapshot, TrafficSnapshot):
            raise TypeError("snapshot must be a TrafficSnapshot")
        generated_time = to_utc(generated_at_utc, field_name="generated_at_utc")
        if generated_time < snapshot.timestamp_utc:
            raise ValueError("generated_at_utc must not be earlier than snapshot timestamp")
        if any(state.timestamp_utc > snapshot.timestamp_utc for state in snapshot.states):
            raise ValueError("snapshot states must not be newer than the snapshot timestamp")

        trajectories = tuple(
            self._predictor.predict(
                state,
                reference_time_utc=snapshot.timestamp_utc,
            )
            for state in snapshot.states
        )
        return PredictionRun(
            prediction_run_id=prediction_run_id,
            input_timestamp_utc=snapshot.timestamp_utc,
            generated_at_utc=generated_time,
            model_name=self._predictor.MODEL_NAME,
            model_version=self._predictor.MODEL_VERSION,
            horizons_seconds=self._predictor.horizons_seconds,
            trajectories=trajectories,
            configuration_id=self._predictor.CONFIGURATION_ID,
        )
