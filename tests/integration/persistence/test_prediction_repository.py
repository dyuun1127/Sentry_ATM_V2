from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from sentry_atm.domain import (
    AircraftMetadata,
    PredictionRun,
    Trajectory,
    TrajectoryPoint,
    TrajectoryType,
)
from sentry_atm.infrastructure.persistence import (
    DatabaseSettings,
    SqlAlchemyAircraftRepository,
    SqlAlchemyPredictionRunRepository,
    create_database_engine,
    create_session_factory,
    initialize_database,
)
from sentry_atm.infrastructure.persistence.models import (
    PredictionRunRow,
    TrajectoryPointRow,
    TrajectoryRow,
)

pytestmark = pytest.mark.integration
INPUT_UTC = datetime(2026, 9, 2, 3, 0, tzinfo=UTC)


def _trajectory(aircraft_id: str, *, input_offset_seconds: int) -> Trajectory:
    input_time = INPUT_UTC + timedelta(seconds=input_offset_seconds)
    return Trajectory(
        aircraft_id=aircraft_id,
        trajectory_type=TrajectoryType.PREDICTED,
        points=tuple(
            TrajectoryPoint(
                timestamp_utc=input_time + timedelta(seconds=horizon),
                x_nm=float(horizon) / 10.0,
                y_nm=float(input_offset_seconds),
                altitude_ft=8_000.0 + horizon,
            )
            for horizon in (30, 60, 120)
        ),
    )


def _prediction_run(run_id: str, *, input_offset_seconds: int) -> PredictionRun:
    input_time = INPUT_UTC + timedelta(seconds=input_offset_seconds)
    return PredictionRun(
        prediction_run_id=run_id,
        input_timestamp_utc=input_time,
        generated_at_utc=input_time,
        model_name="constant-velocity",
        model_version="1.0.0",
        horizons_seconds=(30, 60, 120),
        trajectories=(
            _trajectory("CIV-A01", input_offset_seconds=input_offset_seconds),
            _trajectory("MIL-F01", input_offset_seconds=input_offset_seconds),
        ),
        configuration_id="BASELINE-CV-V1",
    )


def test_prediction_repository_round_trips_aggregate_and_orders_range(
    tmp_path: Path,
) -> None:
    engine = create_database_engine(DatabaseSettings(database_path=tmp_path / "prediction.db"))
    initialize_database(engine)
    session_factory = create_session_factory(engine)
    first = _prediction_run("RUN-005", input_offset_seconds=5)
    second = _prediction_run("RUN-010", input_offset_seconds=10)

    with session_factory.begin() as session:
        aircraft_repository = SqlAlchemyAircraftRepository(session)
        aircraft_repository.upsert(AircraftMetadata(aircraft_id="CIV-A01"))
        aircraft_repository.upsert(AircraftMetadata(aircraft_id="MIL-F01"))
        repository = SqlAlchemyPredictionRunRepository(session)
        repository.save(second)
        repository.save(first)

        assert repository.get(first.prediction_run_id) == first
        assert repository.list_between(
            INPUT_UTC + timedelta(seconds=5),
            INPUT_UTC + timedelta(seconds=10),
        ) == (first, second)
        with pytest.raises(ValueError, match="already exists"):
            repository.save(first)

    with engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(PredictionRunRow)) == 2
        assert connection.scalar(select(func.count()).select_from(TrajectoryRow)) == 4
        assert connection.scalar(select(func.count()).select_from(TrajectoryPointRow)) == 12

    engine.dispose()


def test_prediction_aggregate_rolls_back_when_aircraft_foreign_key_fails(
    tmp_path: Path,
) -> None:
    engine = create_database_engine(DatabaseSettings(database_path=tmp_path / "rollback.db"))
    initialize_database(engine)
    session_factory = create_session_factory(engine)
    prediction_run = PredictionRun(
        prediction_run_id="RUN-MISSING-AIRCRAFT",
        input_timestamp_utc=INPUT_UTC,
        generated_at_utc=INPUT_UTC,
        model_name="constant-velocity",
        model_version="1.0.0",
        horizons_seconds=(30, 60, 120),
        trajectories=(_trajectory("MISSING", input_offset_seconds=0),),
    )

    with pytest.raises(IntegrityError):
        with session_factory.begin() as session:
            SqlAlchemyPredictionRunRepository(session).save(prediction_run)

    with session_factory() as session:
        assert (
            SqlAlchemyPredictionRunRepository(session).get(prediction_run.prediction_run_id) is None
        )

    engine.dispose()
