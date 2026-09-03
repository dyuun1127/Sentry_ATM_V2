from datetime import UTC, datetime, timedelta

import pytest

from sentry_atm.conflict import (
    ConstantVelocityClosestApproachCalculator,
    PairwiseConflictDetector,
)
from sentry_atm.domain import (
    AircraftCategory,
    AircraftPerformanceProfile,
    AircraftState,
    AltitudeManeuver,
    CandidateCostEstimate,
    ConflictExceptionItem,
    ConflictPair,
    DataSource,
    EntryDelayManeuver,
    HeadingManeuver,
    NoActionManeuver,
    PerformanceDataSource,
    ResolutionCandidate,
    ResolutionCandidateBatch,
    ResolutionObjective,
    ResolutionValidationReasonCode,
    ResolutionValidationVerdict,
    SequenceChangeManeuver,
    SpeedManeuver,
)
from sentry_atm.resolution import (
    POC_SAFETY_V1_VALIDATION_PROFILE,
    DeterministicResolutionCandidateGenerator,
    IsolatedResolutionSafetyValidator,
    ResolutionSafetyValidationProfile,
)
from sentry_atm.risk import ConflictRiskEvaluator
from sentry_atm.scenario import build_golden_demo_scenario, build_scenario_simulation

EVALUATED_AT = datetime(2026, 9, 1, 3, 1, 15, tzinfo=UTC)
_DEFAULT_CANDIDATES = object()


def _performance(
    profile_id: str,
    category: AircraftCategory,
    *,
    min_speed_kt: float,
    max_speed_kt: float = 500.0,
    max_climb_rate_fpm: float = 6_000.0,
    max_descent_rate_fpm: float = 6_000.0,
    max_turn_rate: float = 6.0,
    ceiling_ft: float,
) -> AircraftPerformanceProfile:
    return AircraftPerformanceProfile(
        profile_id=profile_id,
        category=category,
        source=PerformanceDataSource.SIMULATION_ASSUMPTION,
        source_reference="TEST PROFILE",
        min_speed_kt=min_speed_kt,
        max_speed_kt=max_speed_kt,
        max_climb_rate_fpm=max_climb_rate_fpm,
        max_descent_rate_fpm=max_descent_rate_fpm,
        max_turn_rate_deg_per_second=max_turn_rate,
        ceiling_ft=ceiling_ft,
    )


def _profiles(**fast_overrides):
    fast_values = {
        "profile_id": "FAST-JET-POC-V1",
        "category": AircraftCategory.FAST_JET,
        "min_speed_kt": 160.0,
        "ceiling_ft": 50_000.0,
    }
    fast_values.update(fast_overrides)
    return {
        "CIV-A02": _performance(
            "AIRLINER-POC-V1",
            AircraftCategory.AIRLINER,
            min_speed_kt=130.0,
            max_speed_kt=350.0,
            max_climb_rate_fpm=2_500.0,
            max_descent_rate_fpm=3_000.0,
            max_turn_rate=3.0,
            ceiling_ft=39_000.0,
        ),
        "MIL-F01": _performance(**fast_values),
    }


def _state(
    aircraft_id: str,
    *,
    x_nm: float,
    y_nm: float,
    altitude_ft: float,
    speed_kt: float,
    heading_deg: float,
    vertical_speed_fpm: float = 0.0,
    timestamp=EVALUATED_AT,
) -> AircraftState:
    return AircraftState(
        aircraft_id=aircraft_id,
        timestamp_utc=timestamp,
        x_nm=x_nm,
        y_nm=y_nm,
        altitude_ft=altitude_ft,
        ground_speed_kt=speed_kt,
        heading_deg=heading_deg,
        vertical_speed_fpm=vertical_speed_fpm,
        source=DataSource.SYNTHETIC,
    )


def _candidate(
    candidate_id: str,
    *,
    target_aircraft_id: str | None,
    maneuver,
    objective: ResolutionObjective,
    effective_at=EVALUATED_AT,
) -> ResolutionCandidate:
    return ResolutionCandidate(
        candidate_id=candidate_id,
        target_aircraft_id=target_aircraft_id,
        maneuver=maneuver,
        objective=objective,
        effective_from_utc=effective_at,
        cost=CandidateCostEstimate(),
    )


def _baseline(effective_at=EVALUATED_AT) -> ResolutionCandidate:
    return _candidate(
        "CAND-E",
        target_aircraft_id=None,
        maneuver=NoActionManeuver(),
        objective=ResolutionObjective.BASELINE_COMPARISON,
        effective_at=effective_at,
    )


def _batch(candidates=_DEFAULT_CANDIDATES, **overrides) -> ResolutionCandidateBatch:
    values = {
        "candidate_batch_id": "BATCH-001",
        "source_exception_id": "EXCEPTION-001",
        "source_conflict_id": "CONFLICT-001",
        "conflict_pair": ConflictPair("CIV-A02", "MIL-F01"),
        "generated_at_utc": EVALUATED_AT,
        "generator_profile_id": "TEST-GENERATOR",
        "candidates": ((_baseline(),) if candidates is _DEFAULT_CANDIDATES else candidates),
    }
    values.update(overrides)
    return ResolutionCandidateBatch(**values)


def _profile(**overrides) -> ResolutionSafetyValidationProfile:
    values = {
        "profile_id": "TEST-SAFETY-V1",
        "horizon_seconds": 120.0,
        "command_execution_seconds": 60.0,
        "minimum_candidate_altitude_ft": 7_500.0,
        "max_speed_change_kt": 50.0,
        "minimum_altitude_rule_id": "TEST-MINIMUM-ALTITUDE",
        "source_reference": "TEST SAFETY PROFILE",
    }
    values.update(overrides)
    return ResolutionSafetyValidationProfile(**values)


def _golden_pipeline_inputs():
    simulation = build_scenario_simulation(build_golden_demo_scenario())
    simulation.clock.play()
    at_70 = simulation.engine.tick(steps=70)
    conflict = next(
        event
        for event in PairwiseConflictDetector().detect(at_70.states)
        if event.pair.aircraft_ids == ("CIV-A02", "MIL-F01")
    )
    risk = ConflictRiskEvaluator().evaluate(conflict)
    exception = ConflictExceptionItem(
        exception_id="EXCEPTION-CONFLICT-7-CIV-A02-7-MIL-F01",
        assessment=risk,
        opened_at_utc=risk.evaluated_at_utc,
        updated_at_utc=risk.evaluated_at_utc,
    )
    at_75 = simulation.engine.tick(steps=5)
    pair_profiles = _profiles()
    batch = DeterministicResolutionCandidateGenerator().generate(
        exception,
        tuple(
            state
            for state in at_75.states
            if state.aircraft_id in exception.assessment.pair.aircraft_ids
        ),
        pair_profiles,
        preferred_target_aircraft_id="MIL-F01",
        preferred_altitude_ft=9_000.0,
    )
    return batch, at_75.states, pair_profiles


def test_default_safety_profile_has_explicit_poc_inputs() -> None:
    profile = POC_SAFETY_V1_VALIDATION_PROFILE

    assert profile.profile_id == "POC_SAFETY_V1"
    assert profile.horizon_seconds == 120.0
    assert profile.command_execution_seconds == 60.0
    assert profile.minimum_candidate_altitude_ft == 7_500.0
    assert profile.max_speed_change_kt == 50.0


def test_safety_profile_normalizes_metadata_and_validates_ranges() -> None:
    profile = _profile(
        profile_id=" TEST-SAFETY-V1 ",
        minimum_altitude_rule_id=" TEST-RULE ",
        source_reference=" TEST SOURCE ",
    )
    assert profile.profile_id == "TEST-SAFETY-V1"
    assert profile.minimum_altitude_rule_id == "TEST-RULE"
    assert profile.source_reference == "TEST SOURCE"

    for field_name in (
        "horizon_seconds",
        "command_execution_seconds",
        "max_speed_change_kt",
    ):
        with pytest.raises(ValueError, match="greater than zero"):
            _profile(**{field_name: 0})
    with pytest.raises(ValueError, match="non-negative"):
        _profile(minimum_candidate_altitude_ft=-1)


def test_golden_candidates_are_calculated_without_mutating_runtime_states() -> None:
    batch, states, profiles = _golden_pipeline_inputs()
    original_states = states
    validator = IsolatedResolutionSafetyValidator()

    run = validator.validate(batch, states, profiles)
    result_by_id = {result.candidate_id: result for result in run.results}

    assert states == original_states
    assert validator.profile is POC_SAFETY_V1_VALIDATION_PROFILE
    assert validator.detector.calculator.horizon_seconds == 120.0
    assert run.source_candidate_batch_id == batch.candidate_batch_id
    assert run.horizon_seconds == 120.0
    assert result_by_id["CAND-A"].verdict is ResolutionValidationVerdict.SAFE
    assert result_by_id["CAND-A"].primary_resolved
    candidate_b = result_by_id["CAND-B"]
    assert candidate_b.verdict is ResolutionValidationVerdict.UNSAFE
    assert candidate_b.primary_resolved
    assert candidate_b.primary_conflict.minimum_separation.vertical_ft == pytest.approx(1_016.25)
    assert tuple(conflict.pair.aircraft_ids for conflict in candidate_b.secondary_conflicts) == (
        ("MIL-F01", "MIL-F02"),
    )
    secondary = candidate_b.secondary_conflicts[0]
    assert secondary.minimum_separation.horizontal_nm == pytest.approx(2.394, abs=0.001)
    assert secondary.minimum_separation.vertical_ft == pytest.approx(406.49, abs=0.01)
    assert ResolutionValidationReasonCode.SECONDARY_CONFLICT_DETECTED in candidate_b.reason_codes
    assert result_by_id["CAND-C"].verdict is ResolutionValidationVerdict.INEFFECTIVE
    assert result_by_id["CAND-D"].verdict is ResolutionValidationVerdict.UNSAFE
    assert result_by_id["CAND-D"].rule_violations[0].rule_id == (
        "POC-MINIMUM-CANDIDATE-ALTITUDE-V1"
    )
    assert ResolutionValidationReasonCode.RULE_VIOLATION in result_by_id["CAND-D"].reason_codes
    assert result_by_id["CAND-E"].verdict is ResolutionValidationVerdict.UNSAFE
    assert ResolutionValidationReasonCode.NO_ACTION_BASELINE in result_by_id["CAND-E"].reason_codes
    assert validator.validate(batch, reversed(states), profiles) == run


def test_validator_detects_secondary_conflicts_across_all_traffic() -> None:
    states = (
        _state(
            "CIV-A02",
            x_nm=-2,
            y_nm=0,
            altitude_ft=10_000,
            speed_kt=120,
            heading_deg=90,
        ),
        _state(
            "MIL-F01",
            x_nm=2,
            y_nm=0,
            altitude_ft=10_000,
            speed_kt=120,
            heading_deg=270,
        ),
        _state(
            "THIRD",
            x_nm=-2,
            y_nm=0.5,
            altitude_ft=10_000,
            speed_kt=120,
            heading_deg=90,
        ),
    )

    result = (
        IsolatedResolutionSafetyValidator()
        .validate(
            _batch(),
            states,
            _profiles(),
        )
        .results[0]
    )

    assert result.verdict is ResolutionValidationVerdict.UNSAFE
    assert result.secondary_conflicts
    assert all(
        conflict.pair != ConflictPair("CIV-A02", "MIL-F01")
        for conflict in result.secondary_conflicts
    )
    assert ResolutionValidationReasonCode.SECONDARY_CONFLICT_DETECTED in result.reason_codes


def test_entry_delay_and_sequence_change_are_applied_to_isolated_states() -> None:
    candidates = (
        _candidate(
            "CAND-F",
            target_aircraft_id="CIV-A02",
            maneuver=EntryDelayManeuver(30),
            objective=ResolutionObjective.TIME_SEPARATION,
        ),
        _candidate(
            "CAND-G",
            target_aircraft_id="MIL-F01",
            maneuver=SequenceChangeManeuver(1),
            objective=ResolutionObjective.SEQUENCE_MANAGEMENT,
        ),
        _baseline(),
    )
    states = (
        _state(
            "CIV-A02",
            x_nm=-5,
            y_nm=0,
            altitude_ft=10_000,
            speed_kt=200,
            heading_deg=90,
            vertical_speed_fpm=-600,
        ),
        _state(
            "MIL-F01",
            x_nm=5,
            y_nm=0,
            altitude_ft=10_000,
            speed_kt=200,
            heading_deg=270,
        ),
    )
    original_states = states

    run = IsolatedResolutionSafetyValidator().validate(
        _batch(candidates),
        states,
        _profiles(),
    )

    assert states == original_states
    assert {result.candidate_id for result in run.results} == {
        "CAND-E",
        "CAND-F",
        "CAND-G",
    }


@pytest.mark.parametrize(
    "candidate",
    [
        _candidate(
            "CAND-H",
            target_aircraft_id="MIL-F01",
            maneuver=HeadingManeuver(180),
            objective=ResolutionObjective.LATERAL_SEPARATION,
        ),
        _candidate(
            "CAND-I",
            target_aircraft_id="MIL-F01",
            maneuver=AltitudeManeuver(60_000),
            objective=ResolutionObjective.VERTICAL_SEPARATION,
        ),
        _candidate(
            "CAND-J",
            target_aircraft_id="MIL-F01",
            maneuver=SpeedManeuver(100),
            objective=ResolutionObjective.TIME_SEPARATION,
        ),
    ],
)
def test_performance_envelope_failures_make_candidate_unsafe(candidate) -> None:
    states = (
        _state(
            "CIV-A02",
            x_nm=-2,
            y_nm=0,
            altitude_ft=10_000,
            speed_kt=200,
            heading_deg=90,
        ),
        _state(
            "MIL-F01",
            x_nm=2,
            y_nm=0,
            altitude_ft=10_000,
            speed_kt=200,
            heading_deg=0,
        ),
    )
    profiles = _profiles(max_turn_rate=1.0)

    run = IsolatedResolutionSafetyValidator().validate(
        _batch((candidate, _baseline())),
        states,
        profiles,
    )
    result = next(item for item in run.results if item.candidate_id == candidate.candidate_id)

    assert result.candidate_id == candidate.candidate_id
    assert not result.performance_feasible
    assert result.verdict is ResolutionValidationVerdict.UNSAFE
    assert ResolutionValidationReasonCode.PERFORMANCE_ENVELOPE_EXCEEDED in result.reason_codes


def test_altitude_rate_and_speed_change_limits_are_checked() -> None:
    states = (
        _state(
            "CIV-A02",
            x_nm=-2,
            y_nm=0,
            altitude_ft=10_000,
            speed_kt=200,
            heading_deg=90,
        ),
        _state(
            "MIL-F01",
            x_nm=2,
            y_nm=0,
            altitude_ft=10_000,
            speed_kt=200,
            heading_deg=270,
        ),
    )
    candidates = (
        _candidate(
            "CAND-K",
            target_aircraft_id="MIL-F01",
            maneuver=AltitudeManeuver(15_000),
            objective=ResolutionObjective.VERTICAL_SEPARATION,
        ),
        _candidate(
            "CAND-L",
            target_aircraft_id="MIL-F01",
            maneuver=AltitudeManeuver(5_000),
            objective=ResolutionObjective.VERTICAL_SEPARATION,
        ),
        _candidate(
            "CAND-M",
            target_aircraft_id="MIL-F01",
            maneuver=SpeedManeuver(300),
            objective=ResolutionObjective.TIME_SEPARATION,
        ),
        _baseline(),
    )
    profiles = _profiles(max_climb_rate_fpm=1_000, max_descent_rate_fpm=1_000)

    results = (
        IsolatedResolutionSafetyValidator()
        .validate(
            _batch(candidates),
            states,
            profiles,
        )
        .results
    )
    result_by_id = {result.candidate_id: result for result in results}

    assert not result_by_id["CAND-K"].performance_feasible
    assert not result_by_id["CAND-L"].performance_feasible
    assert not result_by_id["CAND-M"].performance_feasible


def test_heading_shortest_turn_across_north_can_be_feasible() -> None:
    states = (
        _state(
            "CIV-A02",
            x_nm=-2,
            y_nm=0,
            altitude_ft=10_000,
            speed_kt=200,
            heading_deg=90,
        ),
        _state(
            "MIL-F01",
            x_nm=2,
            y_nm=0,
            altitude_ft=10_000,
            speed_kt=200,
            heading_deg=350,
        ),
    )
    candidate = _candidate(
        "CAND-N",
        target_aircraft_id="MIL-F01",
        maneuver=HeadingManeuver(10),
        objective=ResolutionObjective.LATERAL_SEPARATION,
    )

    run = IsolatedResolutionSafetyValidator().validate(
        _batch((candidate, _baseline())),
        states,
        _profiles(max_turn_rate=1.0),
    )
    result = next(item for item in run.results if item.candidate_id == "CAND-N")

    assert result.performance_feasible


def test_constructor_validates_profile_detector_and_horizon() -> None:
    with pytest.raises(TypeError, match="SafetyValidationProfile"):
        IsolatedResolutionSafetyValidator("profile")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="PairwiseConflictDetector"):
        IsolatedResolutionSafetyValidator(detector="detector")  # type: ignore[arg-type]
    wrong_horizon = PairwiseConflictDetector(
        calculator=ConstantVelocityClosestApproachCalculator(horizon_seconds=60)
    )
    with pytest.raises(ValueError, match="horizon"):
        IsolatedResolutionSafetyValidator(detector=wrong_horizon)


@pytest.mark.parametrize("invalid", ["states", None, ("state",)])
def test_validator_rejects_invalid_traffic_state_iterables(invalid) -> None:
    with pytest.raises(TypeError, match="traffic_states"):
        IsolatedResolutionSafetyValidator().validate(
            _batch(),
            invalid,
            _profiles(),
        )


def test_validator_requires_unique_synchronized_states_with_conflict_pair() -> None:
    first = _state(
        "CIV-A02",
        x_nm=-2,
        y_nm=0,
        altitude_ft=10_000,
        speed_kt=200,
        heading_deg=90,
    )
    second = _state(
        "MIL-F01",
        x_nm=2,
        y_nm=0,
        altitude_ft=10_000,
        speed_kt=200,
        heading_deg=270,
    )
    other = _state(
        "OTHER",
        x_nm=2,
        y_nm=0,
        altitude_ft=10_000,
        speed_kt=200,
        heading_deg=270,
    )
    later = replace_state_timestamp(second, EVALUATED_AT + timedelta(seconds=1))
    cases = (
        ((first,), "at least two"),
        ((first, first), "unique"),
        ((first, other), "Conflict Pair"),
        ((first, later), "share one timestamp"),
    )
    for states, message in cases:
        with pytest.raises(ValueError, match=message):
            IsolatedResolutionSafetyValidator().validate(_batch(), states, _profiles())


def replace_state_timestamp(state: AircraftState, timestamp) -> AircraftState:
    return AircraftState(
        aircraft_id=state.aircraft_id,
        timestamp_utc=timestamp,
        x_nm=state.x_nm,
        y_nm=state.y_nm,
        altitude_ft=state.altitude_ft,
        ground_speed_kt=state.ground_speed_kt,
        heading_deg=state.heading_deg,
        vertical_speed_fpm=state.vertical_speed_fpm,
        source=state.source,
    )


def test_validator_requires_batch_and_candidate_timestamps_to_match_states() -> None:
    states = (
        _state(
            "CIV-A02",
            x_nm=-2,
            y_nm=0,
            altitude_ft=10_000,
            speed_kt=200,
            heading_deg=90,
        ),
        _state(
            "MIL-F01",
            x_nm=2,
            y_nm=0,
            altitude_ft=10_000,
            speed_kt=200,
            heading_deg=270,
        ),
    )
    with pytest.raises(TypeError, match="ResolutionCandidateBatch"):
        IsolatedResolutionSafetyValidator().validate(  # type: ignore[arg-type]
            "batch",
            states,
            _profiles(),
        )
    with pytest.raises(ValueError, match="Batch"):
        IsolatedResolutionSafetyValidator().validate(
            _batch(generated_at_utc=EVALUATED_AT - timedelta(seconds=1)),
            states,
            _profiles(),
        )
    future = EVALUATED_AT + timedelta(seconds=1)
    with pytest.raises(ValueError, match="effective"):
        IsolatedResolutionSafetyValidator().validate(
            _batch((_baseline(effective_at=future),)),
            states,
            _profiles(),
        )


def test_validator_validates_performance_profile_mapping() -> None:
    states = (
        _state(
            "CIV-A02",
            x_nm=-2,
            y_nm=0,
            altitude_ft=10_000,
            speed_kt=200,
            heading_deg=90,
        ),
        _state(
            "MIL-F01",
            x_nm=2,
            y_nm=0,
            altitude_ft=10_000,
            speed_kt=200,
            heading_deg=270,
        ),
    )
    validator = IsolatedResolutionSafetyValidator()
    with pytest.raises(TypeError, match="mapping"):
        validator.validate(_batch(), states, [])  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="Conflict Pair"):
        validator.validate(
            _batch(),
            states,
            {"MIL-F01": _profiles()["MIL-F01"]},
        )
    invalid = dict(_profiles())
    invalid["MIL-F01"] = "profile"  # type: ignore[assignment]
    with pytest.raises(TypeError, match="AircraftPerformanceProfile"):
        validator.validate(_batch(), states, invalid)
