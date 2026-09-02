from datetime import UTC, datetime, timedelta
from typing import cast
from unittest.mock import MagicMock, create_autospec

import pytest
from sqlalchemy.orm import Session

from sentry_atm.domain import PredictionRun
from sentry_atm.infrastructure.persistence.models import PredictionRunRow
from sentry_atm.infrastructure.persistence.repositories import (
    SqlAlchemyPredictionRunRepository,
)

INPUT_UTC = datetime(2026, 9, 2, 3, 0, tzinfo=UTC)


def _session() -> tuple[Session, MagicMock]:
    session_mock = create_autospec(Session, instance=True)
    return cast(Session, session_mock), cast(MagicMock, session_mock)


def _prediction_run() -> PredictionRun:
    return PredictionRun(
        prediction_run_id="RUN-001",
        input_timestamp_utc=INPUT_UTC,
        generated_at_utc=INPUT_UTC,
        model_name="constant-velocity",
        model_version="1.0.0",
        horizons_seconds=(30, 60, 120),
        configuration_id="BASELINE-CV-V1",
    )


def test_prediction_repository_returns_none_when_missing() -> None:
    session, session_mock = _session()
    session_mock.get.return_value = None

    assert SqlAlchemyPredictionRunRepository(session).get("RUN-001") is None


def test_prediction_repository_rejects_duplicate_run_without_mutation() -> None:
    session, session_mock = _session()
    session_mock.get.return_value = PredictionRunRow(
        prediction_run_id="RUN-001",
        input_timestamp_utc=INPUT_UTC,
        generated_at_utc=INPUT_UTC,
        model_name="constant-velocity",
        model_version="1.0.0",
        horizons_seconds_json="[30,60,120]",
    )

    with pytest.raises(ValueError, match="already exists"):
        SqlAlchemyPredictionRunRepository(session).save(_prediction_run())

    session_mock.add.assert_not_called()
    session_mock.flush.assert_not_called()


def test_prediction_repository_rejects_reversed_range() -> None:
    session, session_mock = _session()

    with pytest.raises(ValueError, match="must not be earlier"):
        SqlAlchemyPredictionRunRepository(session).list_between(
            INPUT_UTC + timedelta(seconds=1),
            INPUT_UTC,
        )

    session_mock.scalars.assert_not_called()


def test_prediction_repository_requires_real_sqlalchemy_session() -> None:
    with pytest.raises(TypeError, match="SQLAlchemy Session"):
        SqlAlchemyPredictionRunRepository(cast(Session, "not-session"))
