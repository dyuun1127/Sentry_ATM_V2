from datetime import UTC, datetime, timedelta

import pytest

from sentry_atm.domain import AircraftState, DataSource, TrajectoryType
from sentry_atm.domain.time_policy import KST
from sentry_atm.prediction import ConstantVelocityPredictor, PredictionRunService
from sentry_atm.simulation import TrafficSnapshot

SNAPSHOT_TIME_UTC = datetime(2026, 9, 1, 3, 0, 10, tzinfo=UTC)
GENERATED_TIME_UTC = SNAPSHOT_TIME_UTC + timedelta(seconds=1)


def _state(
    aircraft_id: str,
    *,
    timestamp_utc: datetime = SNAPSHOT_TIME_UTC,
    x_nm: float = 0.0,
    heading_deg: float = 90.0,
) -> AircraftState:
    return AircraftState(
        aircraft_id=aircraft_id,
        timestamp_utc=timestamp_utc,
        x_nm=x_nm,
        y_nm=0.0,
        altitude_ft=8_000.0,
        ground_speed_kt=360.0,
        heading_deg=heading_deg,
        vertical_speed_fpm=0.0,
        source=DataSource.SYNTHETIC,
    )


def _service() -> PredictionRunService:
    return PredictionRunService(ConstantVelocityPredictor())


def test_service_builds_versioned_run_for_all_snapshot_aircraft() -> None:
    snapshot = TrafficSnapshot(
        timestamp_utc=SNAPSHOT_TIME_UTC,
        states=(
            _state("CIV-A01", x_nm=1.0),
            _state("MIL-F01", x_nm=10.0, heading_deg=270.0),
        ),
    )

    run = _service().run(
        snapshot,
        prediction_run_id="RUN-001",
        generated_at_utc=datetime(2026, 9, 1, 12, 0, 11, tzinfo=KST),
    )

    assert run.prediction_run_id == "RUN-001"
    assert run.input_timestamp_utc == SNAPSHOT_TIME_UTC
    assert run.generated_at_utc == GENERATED_TIME_UTC
    assert run.model_name == "constant-velocity"
    assert run.model_version == "1.0.0"
    assert run.configuration_id == "BASELINE-CV-V1"
    assert run.horizons_seconds == (30, 60, 120)
    assert tuple(item.aircraft_id for item in run.trajectories) == ("CIV-A01", "MIL-F01")
    assert all(item.trajectory_type is TrajectoryType.PREDICTED for item in run.trajectories)


def test_service_anchors_stale_playback_state_to_snapshot_horizons() -> None:
    stale_state = _state(
        "CIV-A01",
        timestamp_utc=SNAPSHOT_TIME_UTC - timedelta(seconds=10),
    )
    snapshot = TrafficSnapshot(timestamp_utc=SNAPSHOT_TIME_UTC, states=(stale_state,))

    trajectory = (
        _service()
        .run(
            snapshot,
            prediction_run_id="RUN-STALE",
            generated_at_utc=GENERATED_TIME_UTC,
        )
        .trajectories[0]
    )

    assert trajectory.points[0].timestamp_utc == SNAPSHOT_TIME_UTC + timedelta(seconds=30)
    assert trajectory.points[0].x_nm == pytest.approx(4.0)
    assert trajectory.points[-1].timestamp_utc == SNAPSHOT_TIME_UTC + timedelta(seconds=120)
    assert trajectory.points[-1].x_nm == pytest.approx(13.0)


def test_empty_snapshot_produces_auditable_empty_run() -> None:
    run = _service().run(
        TrafficSnapshot(timestamp_utc=SNAPSHOT_TIME_UTC, states=()),
        prediction_run_id="RUN-EMPTY",
        generated_at_utc=GENERATED_TIME_UTC,
    )

    assert run.trajectories == ()
    assert run.input_timestamp_utc == SNAPSHOT_TIME_UTC


def test_same_explicit_inputs_produce_identical_prediction_run() -> None:
    snapshot = TrafficSnapshot(
        timestamp_utc=SNAPSHOT_TIME_UTC,
        states=(_state("CIV-A01"),),
    )
    service = _service()

    first = service.run(
        snapshot,
        prediction_run_id="RUN-DETERMINISTIC",
        generated_at_utc=GENERATED_TIME_UTC,
    )
    second = service.run(
        snapshot,
        prediction_run_id="RUN-DETERMINISTIC",
        generated_at_utc=GENERATED_TIME_UTC,
    )

    assert first == second


def test_service_exposes_predictor() -> None:
    predictor = ConstantVelocityPredictor((10, 20))

    assert PredictionRunService(predictor).predictor is predictor


def test_service_rejects_wrong_predictor_or_snapshot_type() -> None:
    with pytest.raises(TypeError, match="ConstantVelocityPredictor"):
        PredictionRunService("predictor")  # type: ignore[arg-type]

    with pytest.raises(TypeError, match="TrafficSnapshot"):
        _service().run(
            "snapshot",  # type: ignore[arg-type]
            prediction_run_id="RUN-001",
            generated_at_utc=GENERATED_TIME_UTC,
        )


def test_service_rejects_future_state_in_snapshot() -> None:
    snapshot = TrafficSnapshot(
        timestamp_utc=SNAPSHOT_TIME_UTC,
        states=(
            _state(
                "CIV-A01",
                timestamp_utc=SNAPSHOT_TIME_UTC + timedelta(seconds=1),
            ),
        ),
    )

    with pytest.raises(ValueError, match="newer than"):
        _service().run(
            snapshot,
            prediction_run_id="RUN-FUTURE-STATE",
            generated_at_utc=GENERATED_TIME_UTC,
        )


def test_service_rejects_generation_time_before_snapshot() -> None:
    snapshot = TrafficSnapshot(timestamp_utc=SNAPSHOT_TIME_UTC, states=())

    with pytest.raises(ValueError, match="generated_at_utc"):
        _service().run(
            snapshot,
            prediction_run_id="RUN-EARLY",
            generated_at_utc=SNAPSHOT_TIME_UTC - timedelta(microseconds=1),
        )
