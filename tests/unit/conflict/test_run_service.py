from datetime import UTC, datetime, timedelta

import pytest

from sentry_atm.conflict import (
    ConflictAssessmentService,
    PairwiseConflictDetector,
)
from sentry_atm.domain import AircraftState, ConflictStatus, DataSource
from sentry_atm.simulation import TrafficSnapshot

NOW_UTC = datetime(2026, 9, 2, 3, 0, tzinfo=UTC)


def _state(
    aircraft_id: str,
    *,
    x_nm: float,
    heading_deg: float,
    timestamp_utc: datetime = NOW_UTC,
) -> AircraftState:
    return AircraftState(
        aircraft_id=aircraft_id,
        timestamp_utc=timestamp_utc,
        x_nm=x_nm,
        y_nm=0.0,
        altitude_ft=10_000.0,
        ground_speed_kt=360.0,
        heading_deg=heading_deg,
        vertical_speed_fpm=0.0,
        source=DataSource.OPENSKY,
    )


def _service() -> ConflictAssessmentService:
    return ConflictAssessmentService(PairwiseConflictDetector())


def test_service_builds_assessment_run_from_current_snapshot() -> None:
    snapshot = TrafficSnapshot(
        timestamp_utc=NOW_UTC,
        states=(
            _state("CIV-A01", x_nm=-10.0, heading_deg=90.0),
            _state("MIL-F01", x_nm=10.0, heading_deg=270.0),
        ),
    )

    run = _service().run(snapshot, assessment_run_id="CONFLICT-0001")

    assert run.assessment_run_id == "CONFLICT-0001"
    assert run.input_timestamp_utc == NOW_UTC
    assert run.rule_profile_id == "POC_TERMINAL_V1"
    assert run.horizon_seconds == 120.0
    assert len(run.assessments) == 1
    assert run.assessments[0].status is ConflictStatus.PREDICTED
    assert run.assessments[0].tcpa_seconds == pytest.approx(100.0)
    assert run.predicted_events == run.assessments


def test_service_advances_stale_playback_states_to_snapshot_time() -> None:
    snapshot_time = NOW_UTC + timedelta(seconds=10)
    snapshot = TrafficSnapshot(
        timestamp_utc=snapshot_time,
        states=(
            _state("CIV-A01", x_nm=-10.0, heading_deg=90.0),
            _state("MIL-F01", x_nm=10.0, heading_deg=270.0),
        ),
    )

    run = _service().run(snapshot, assessment_run_id="CONFLICT-0010")

    assert run.input_timestamp_utc == snapshot_time
    assert run.assessments[0].evaluated_at_utc == snapshot_time
    assert run.assessments[0].tcpa_seconds == pytest.approx(90.0)
    assert run.assessments[0].minimum_separation.horizontal_nm == pytest.approx(
        0.0,
        abs=1e-12,
    )


def test_service_accepts_snapshot_with_fewer_than_two_states() -> None:
    empty = TrafficSnapshot(timestamp_utc=NOW_UTC, states=())

    run = _service().run(empty, assessment_run_id="EMPTY")

    assert run.assessments == ()
    assert run.predicted_events == ()


def test_service_rejects_future_state_or_wrong_dependencies() -> None:
    future_snapshot = TrafficSnapshot(
        timestamp_utc=NOW_UTC,
        states=(
            _state(
                "CIV-A01",
                x_nm=0.0,
                heading_deg=90.0,
                timestamp_utc=NOW_UTC + timedelta(seconds=1),
            ),
        ),
    )
    service = _service()

    with pytest.raises(ValueError, match="must not be newer"):
        service.run(future_snapshot, assessment_run_id="FUTURE")
    with pytest.raises(TypeError, match="TrafficSnapshot"):
        service.run("snapshot", assessment_run_id="WRONG")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="PairwiseConflictDetector"):
        ConflictAssessmentService("detector")  # type: ignore[arg-type]


def test_service_exposes_injected_detector() -> None:
    detector = PairwiseConflictDetector()

    service = ConflictAssessmentService(detector)

    assert service.detector is detector
