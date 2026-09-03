from datetime import UTC, datetime, timedelta

import pytest

from sentry_atm.conflict import (
    ConstantVelocityClosestApproachCalculator,
    PairwiseConflictDetector,
)
from sentry_atm.domain import (
    POC_TERMINAL_V1_RULE_PROFILE,
    AircraftState,
    ConflictStatus,
    DataSource,
    SeparationRuleProfile,
)
from sentry_atm.regulation.policy import active_separation_profile
from sentry_atm.scenario import build_golden_demo_scenario

NOW_UTC = datetime(2026, 9, 2, 3, 0, tzinfo=UTC)


def _state(
    aircraft_id: str,
    *,
    x_nm: float,
    y_nm: float,
    altitude_ft: float = 10_000.0,
    ground_speed_kt: float = 360.0,
    heading_deg: float,
    timestamp_utc: datetime = NOW_UTC,
) -> AircraftState:
    return AircraftState(
        aircraft_id=aircraft_id,
        timestamp_utc=timestamp_utc,
        x_nm=x_nm,
        y_nm=y_nm,
        altitude_ft=altitude_ft,
        ground_speed_kt=ground_speed_kt,
        heading_deg=heading_deg,
        vertical_speed_fpm=0.0,
        source=DataSource.SYNTHETIC,
    )


def _three_states() -> tuple[AircraftState, ...]:
    return (
        _state("CIV-A01", x_nm=-10.0, y_nm=0.0, heading_deg=90.0),
        _state("MIL-F01", x_nm=10.0, y_nm=0.0, heading_deg=270.0),
        _state(
            "CIV-A02",
            x_nm=0.0,
            y_nm=30.0,
            altitude_ft=15_000.0,
            heading_deg=0.0,
        ),
    )


def test_assess_returns_every_pair_in_stable_identifier_order() -> None:
    detector = PairwiseConflictDetector()

    assessments = detector.assess(reversed(_three_states()))

    assert tuple(event.pair.aircraft_ids for event in assessments) == (
        ("CIV-A01", "CIV-A02"),
        ("CIV-A01", "MIL-F01"),
        ("CIV-A02", "MIL-F01"),
    )
    assert tuple(event.status for event in assessments) == (
        ConflictStatus.SAFE,
        ConflictStatus.PREDICTED,
        ConflictStatus.SAFE,
    )
    assert assessments[1].tcpa_seconds == pytest.approx(100.0)
    assert assessments[1].minimum_separation.horizontal_nm == pytest.approx(
        0.0,
        abs=1e-12,
    )


def test_detect_returns_only_predicted_events() -> None:
    detector = PairwiseConflictDetector()

    detected = detector.detect(_three_states())

    assert len(detected) == 1
    assert detected[0].pair.aircraft_ids == ("CIV-A01", "MIL-F01")
    assert detected[0].status is ConflictStatus.PREDICTED
    assert detected[0].rule_profile_id == active_separation_profile().profile_id


def test_assessment_ids_are_deterministic_and_include_pair_and_snapshot() -> None:
    detector = PairwiseConflictDetector()

    first = detector.assess(_three_states())
    second = detector.assess(tuple(reversed(_three_states())))

    assert first == second
    assert first[0].conflict_id == "CONFLICT-20260902T030000000000Z-CIV-A01-CIV-A02"
    assert len({event.conflict_id for event in first}) == 3


def test_custom_rule_profile_changes_assessment_without_detector_changes() -> None:
    states = (
        _state("CIV-A01", x_nm=0.0, y_nm=0.0, heading_deg=0.0),
        _state("CIV-A02", x_nm=4.0, y_nm=0.0, heading_deg=0.0),
    )
    # 기본값이 고시 3NM 이므로, 대비를 보이려면 더 넓은 프로파일을 주입한다.
    # 4NM 이격은 고시 기준으로 분리가 확보된 상태이고, 5NM 을 요구하는 프로파일
    # 아래에서는 아니다.
    custom_rule = SeparationRuleProfile(
        profile_id="CUSTOM-5NM",
        horizontal_threshold_nm=5.0,
        vertical_threshold_ft=1_000.0,
        source_reference="test-only",
    )

    default_event = PairwiseConflictDetector().assess(states)[0]
    custom_event = PairwiseConflictDetector(rule_profile=custom_rule).assess(states)[0]

    assert default_event.status is ConflictStatus.SAFE
    assert custom_event.status is ConflictStatus.PREDICTED
    assert custom_event.rule_profile_id == "CUSTOM-5NM"


def test_exact_rule_boundaries_are_safe() -> None:
    detector = PairwiseConflictDetector()
    horizontal_boundary = (
        _state("CIV-A01", x_nm=0.0, y_nm=0.0, heading_deg=0.0),
        _state("CIV-A02", x_nm=5.0, y_nm=0.0, heading_deg=0.0),
    )
    vertical_boundary = (
        _state("CIV-A01", x_nm=-1.0, y_nm=0.0, heading_deg=90.0),
        _state(
            "CIV-A02",
            x_nm=1.0,
            y_nm=0.0,
            altitude_ft=11_000.0,
            heading_deg=270.0,
        ),
    )

    assert detector.assess(horizontal_boundary)[0].status is ConflictStatus.SAFE
    assert detector.assess(vertical_boundary)[0].status is ConflictStatus.SAFE


def test_empty_or_single_aircraft_input_has_no_pairs() -> None:
    detector = PairwiseConflictDetector()
    state = _state("CIV-A01", x_nm=0.0, y_nm=0.0, heading_deg=0.0)

    assert detector.assess(()) == ()
    assert detector.detect((state,)) == ()


def test_detector_materializes_generator_input_once() -> None:
    detector = PairwiseConflictDetector()
    states = _three_states()

    assessments = detector.assess(state for state in states)

    assert len(assessments) == 3


def test_golden_demo_eight_aircraft_produce_twenty_eight_assessments() -> None:
    states = build_golden_demo_scenario().initial_states
    detector = PairwiseConflictDetector()

    assessments = detector.assess(states)

    assert len(assessments) == 28
    assert assessments[0].pair.aircraft_ids == ("CIV-A01", "CIV-A02")
    assert assessments[-1].pair.aircraft_ids == ("MIL-T01", "MIL-T02")
    assert detector.detect(states) == ()


def test_detector_rejects_invalid_state_collections() -> None:
    detector = PairwiseConflictDetector()
    first = _state("CIV-A01", x_nm=0.0, y_nm=0.0, heading_deg=0.0)
    duplicate = _state("CIV-A01", x_nm=1.0, y_nm=0.0, heading_deg=0.0)
    later = _state(
        "CIV-A02",
        x_nm=1.0,
        y_nm=0.0,
        heading_deg=0.0,
        timestamp_utc=NOW_UTC + timedelta(seconds=1),
    )

    with pytest.raises(TypeError, match="iterable"):
        detector.assess(None)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="iterable"):
        detector.assess("states")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="only AircraftState"):
        detector.assess((first, "state"))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="unique aircraft IDs"):
        detector.assess((first, duplicate))
    with pytest.raises(ValueError, match="same timestamp"):
        detector.assess((first, later))


def test_detector_validates_and_exposes_injected_dependencies() -> None:
    calculator = ConstantVelocityClosestApproachCalculator(horizon_seconds=60)
    detector = PairwiseConflictDetector(
        calculator=calculator,
        rule_profile=POC_TERMINAL_V1_RULE_PROFILE,
    )

    assert detector.calculator is calculator
    assert detector.rule_profile is POC_TERMINAL_V1_RULE_PROFILE

    with pytest.raises(TypeError, match="calculator"):
        PairwiseConflictDetector(calculator="calculator")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="rule_profile"):
        PairwiseConflictDetector(rule_profile="rule")  # type: ignore[arg-type]
