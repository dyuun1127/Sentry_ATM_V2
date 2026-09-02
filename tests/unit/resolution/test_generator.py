from datetime import UTC, datetime, timedelta

import pytest

from sentry_atm.conflict import PairwiseConflictDetector
from sentry_atm.domain import (
    AircraftCategory,
    AircraftPerformanceProfile,
    AircraftState,
    AltitudeManeuver,
    CandidateCostEstimate,
    ConflictExceptionItem,
    ConflictPair,
    ConflictRiskAssessment,
    DataSource,
    EntryDelayManeuver,
    ExceptionStatus,
    HeadingManeuver,
    NoActionManeuver,
    PerformanceDataSource,
    ResolutionManeuverType,
    RiskLevel,
    RiskReasonCode,
    SequenceChangeManeuver,
    SpeedManeuver,
)
from sentry_atm.resolution import (
    POC_RESOLUTION_V1_GENERATION_PROFILE,
    CandidateTargetRole,
    DeterministicResolutionCandidateGenerator,
    ResolutionCandidateGenerationProfile,
    ResolutionCandidateTemplate,
)
from sentry_atm.risk import ConflictRiskEvaluator
from sentry_atm.scenario import build_golden_demo_scenario, build_scenario_simulation

ASSESSMENT_TIME = datetime(2026, 9, 1, 3, 1, 10, tzinfo=UTC)
STATE_TIME = ASSESSMENT_TIME + timedelta(seconds=5)
_DEFAULT_TEMPLATES = object()
_ZERO_COST = CandidateCostEstimate()


def _state(
    aircraft_id: str,
    *,
    timestamp=STATE_TIME,
    altitude_ft: float,
    speed_kt: float,
    heading_deg: float,
) -> AircraftState:
    return AircraftState(
        aircraft_id=aircraft_id,
        timestamp_utc=timestamp,
        x_nm=0.0,
        y_nm=0.0,
        altitude_ft=altitude_ft,
        ground_speed_kt=speed_kt,
        heading_deg=heading_deg,
        vertical_speed_fpm=0.0,
        source=DataSource.SYNTHETIC,
    )


def _assessment(
    *,
    level: RiskLevel = RiskLevel.HIGH,
    evaluated_at=ASSESSMENT_TIME,
) -> ConflictRiskAssessment:
    return ConflictRiskAssessment(
        risk_assessment_id="RISK-001",
        conflict_id="CONFLICT-001",
        pair=ConflictPair("CIV-A02", "MIL-F01"),
        evaluated_at_utc=evaluated_at,
        risk_score=0.0 if level is RiskLevel.LOW else 75.0,
        risk_level=level,
        tcpa_seconds=90.0,
        horizontal_separation_ratio=0.46,
        vertical_separation_ratio=0.5,
        reason_codes=(
            RiskReasonCode.NO_PREDICTED_CONFLICT
            if level is RiskLevel.LOW
            else RiskReasonCode.PREDICTED_SEPARATION_LOSS,
        ),
        policy_profile_id="POC_RISK_V1",
    )


def _exception(
    *,
    level: RiskLevel = RiskLevel.HIGH,
    status: ExceptionStatus = ExceptionStatus.OPEN,
    evaluated_at=ASSESSMENT_TIME,
) -> ConflictExceptionItem:
    assessment = _assessment(level=level, evaluated_at=evaluated_at)
    return ConflictExceptionItem(
        exception_id="EXCEPTION-CONFLICT-7-CIV-A02-7-MIL-F01",
        assessment=assessment,
        opened_at_utc=assessment.evaluated_at_utc,
        updated_at_utc=assessment.evaluated_at_utc,
        status=status,
    )


def _performance(
    profile_id: str,
    category: AircraftCategory,
    *,
    min_speed_kt: float,
    ceiling_ft: float,
) -> AircraftPerformanceProfile:
    return AircraftPerformanceProfile(
        profile_id=profile_id,
        category=category,
        source=PerformanceDataSource.SIMULATION_ASSUMPTION,
        source_reference="TEST PROFILE",
        min_speed_kt=min_speed_kt,
        max_speed_kt=500.0,
        max_climb_rate_fpm=6_000.0,
        max_descent_rate_fpm=6_000.0,
        max_turn_rate_deg_per_second=6.0,
        ceiling_ft=ceiling_ft,
    )


def _states(*, timestamp=STATE_TIME):
    return (
        _state(
            "CIV-A02",
            timestamp=timestamp,
            altitude_ft=8_125.0,
            speed_kt=250.0,
            heading_deg=220.0,
        ),
        _state(
            "MIL-F01",
            timestamp=timestamp,
            altitude_ft=7_285.0,
            speed_kt=320.0,
            heading_deg=180.0,
        ),
    )


def _profiles(*, civil_min_speed=130.0, fast_ceiling=50_000.0):
    return {
        "CIV-A02": _performance(
            "AIRLINER-POC-V1",
            AircraftCategory.AIRLINER,
            min_speed_kt=civil_min_speed,
            ceiling_ft=39_000.0,
        ),
        "MIL-F01": _performance(
            "FAST-JET-POC-V1",
            AircraftCategory.FAST_JET,
            min_speed_kt=160.0,
            ceiling_ft=fast_ceiling,
        ),
    }


def _template(
    candidate_id="CAND-A",
    *,
    role=CandidateTargetRole.PREFERRED,
    maneuver_type=ResolutionManeuverType.ALTITUDE,
    cost=_ZERO_COST,
):
    return ResolutionCandidateTemplate(
        candidate_id=candidate_id,
        target_role=role,
        maneuver_type=maneuver_type,
        cost=cost,
    )


def _profile(templates=_DEFAULT_TEMPLATES, **overrides):
    values = {
        "profile_id": "TEST-RESOLUTION-V1",
        "heading_change_deg": 20.0,
        "altitude_change_ft": 1_000.0,
        "speed_change_kt": 30.0,
        "entry_delay_seconds": 30.0,
        "target_sequence_position": 1,
        "templates": ((_template(),) if templates is _DEFAULT_TEMPLATES else templates),
        "baseline_candidate_id": "CAND-E",
        "source_reference": "TEST PROFILE",
    }
    values.update(overrides)
    return ResolutionCandidateGenerationProfile(**values)


def test_default_profile_has_documented_golden_templates() -> None:
    profile = POC_RESOLUTION_V1_GENERATION_PROFILE

    assert profile.profile_id == "POC_RESOLUTION_V1"
    assert profile.heading_change_deg == 20.0
    assert profile.altitude_change_ft == 1_000.0
    assert profile.speed_change_kt == 30.0
    assert profile.baseline_candidate_id == "CAND-E"
    assert tuple(template.candidate_id for template in profile.templates) == (
        "CAND-A",
        "CAND-B",
        "CAND-C",
        "CAND-D",
    )


def test_template_normalizes_values_and_validates_action_only() -> None:
    template = _template(
        " CAND-A ",
        role="PREFERRED",  # type: ignore[arg-type]
        maneuver_type="ALTITUDE",  # type: ignore[arg-type]
    )

    assert template.candidate_id == "CAND-A"
    assert template.target_role is CandidateTargetRole.PREFERRED
    assert template.maneuver_type is ResolutionManeuverType.ALTITUDE

    with pytest.raises(ValueError, match="NO_ACTION"):
        _template(maneuver_type=ResolutionManeuverType.NO_ACTION)
    with pytest.raises(TypeError, match="CandidateCostEstimate"):
        _template(cost="cost")  # type: ignore[arg-type]


def test_profile_normalizes_metadata_materializes_templates_and_validates_ranges() -> None:
    templates = [_template()]
    profile = _profile(
        templates,
        profile_id=" TEST-RESOLUTION-V1 ",
        baseline_candidate_id=" CAND-E ",
        source_reference=" TEST PROFILE ",
    )
    templates.clear()

    assert profile.profile_id == "TEST-RESOLUTION-V1"
    assert profile.templates[0].candidate_id == "CAND-A"
    assert profile.source_reference == "TEST PROFILE"

    for field_name in (
        "heading_change_deg",
        "altitude_change_ft",
        "speed_change_kt",
        "entry_delay_seconds",
    ):
        with pytest.raises(ValueError, match="greater than zero"):
            _profile(**{field_name: 0})
    with pytest.raises(ValueError, match="less than 180"):
        _profile(heading_change_deg=180)
    with pytest.raises(TypeError, match="integer"):
        _profile(target_sequence_position=True)
    with pytest.raises(ValueError, match="at least 1"):
        _profile(target_sequence_position=0)


def test_profile_rejects_invalid_template_collections_and_duplicate_slots() -> None:
    with pytest.raises(TypeError, match="iterable"):
        _profile("templates")
    with pytest.raises(TypeError, match="iterable"):
        _profile(None)
    with pytest.raises(TypeError, match="contain"):
        _profile(("template",))
    with pytest.raises(ValueError, match="must not be empty"):
        _profile(())

    first = _template()
    with pytest.raises(ValueError, match="candidate IDs"):
        _profile((first, _template(role=CandidateTargetRole.OTHER)))
    with pytest.raises(ValueError, match="baseline"):
        _profile((first,), baseline_candidate_id="CAND-A")
    with pytest.raises(ValueError, match="role and maneuver"):
        _profile((first, _template("CAND-B")))


def test_generator_builds_golden_a_to_e_from_actual_t_plus_75_state() -> None:
    scenario = build_golden_demo_scenario()
    simulation = build_scenario_simulation(scenario)
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
    pair_states = tuple(
        state
        for state in at_75.states
        if state.aircraft_id in exception.assessment.pair.aircraft_ids
    )
    original_states = pair_states

    batch = DeterministicResolutionCandidateGenerator().generate(
        exception,
        pair_states,
        _profiles(),
        preferred_target_aircraft_id="MIL-F01",
        preferred_altitude_ft=9_000.0,
    )

    assert pair_states == original_states
    assert batch.generated_at_utc == STATE_TIME
    assert batch.source_exception_id == exception.exception_id
    assert batch.generator_profile_id == "POC_RESOLUTION_V1"
    assert tuple(candidate.candidate_id for candidate in batch.candidates) == (
        "CAND-A",
        "CAND-B",
        "CAND-C",
        "CAND-D",
        "CAND-E",
    )
    candidate_a, candidate_b, candidate_c, candidate_d, candidate_e = batch.candidates
    assert candidate_a.target_aircraft_id == "MIL-F01"
    assert isinstance(candidate_a.maneuver, AltitudeManeuver)
    assert candidate_a.maneuver.target_altitude_ft == 9_000.0
    assert isinstance(candidate_b.maneuver, HeadingManeuver)
    assert candidate_b.maneuver.target_heading_deg == 200.0
    assert candidate_c.target_aircraft_id == "CIV-A02"
    assert isinstance(candidate_c.maneuver, SpeedManeuver)
    assert candidate_c.maneuver.target_ground_speed_kt == 220.0
    assert isinstance(candidate_d.maneuver, AltitudeManeuver)
    assert candidate_d.maneuver.target_altitude_ft == 7_200.0
    assert isinstance(candidate_e.maneuver, NoActionManeuver)


def test_custom_profile_generates_entry_delay_sequence_and_wraps_heading() -> None:
    profile = _profile(
        (
            _template(
                "CAND-H",
                maneuver_type=ResolutionManeuverType.HEADING,
            ),
            _template(
                "CAND-I",
                maneuver_type=ResolutionManeuverType.ENTRY_DELAY,
            ),
            _template(
                "CAND-J",
                role=CandidateTargetRole.OTHER,
                maneuver_type=ResolutionManeuverType.SEQUENCE_CHANGE,
            ),
        )
    )
    states = (
        _state("CIV-A02", altitude_ft=8_125, speed_kt=250, heading_deg=220),
        _state("MIL-F01", altitude_ft=7_285, speed_kt=320, heading_deg=350),
    )

    batch = DeterministicResolutionCandidateGenerator(profile).generate(
        _exception(),
        states,
        _profiles(),
        preferred_target_aircraft_id="MIL-F01",
    )

    candidate_by_id = {candidate.candidate_id: candidate for candidate in batch.candidates}
    heading = candidate_by_id["CAND-H"]
    delay = candidate_by_id["CAND-I"]
    sequence = candidate_by_id["CAND-J"]
    assert isinstance(heading.maneuver, HeadingManeuver)
    assert heading.maneuver.target_heading_deg == 10.0
    assert isinstance(delay.maneuver, EntryDelayManeuver)
    assert delay.maneuver.delay_seconds == 30.0
    assert isinstance(sequence.maneuver, SequenceChangeManeuver)
    assert sequence.maneuver.target_sequence_position == 1


def test_generator_clips_default_altitude_and_speed_to_profile_envelopes() -> None:
    states = (
        _state("CIV-A02", altitude_ft=8_125, speed_kt=250, heading_deg=220),
        _state("MIL-F01", altitude_ft=9_000, speed_kt=320, heading_deg=180),
    )

    batch = DeterministicResolutionCandidateGenerator().generate(
        _exception(),
        states,
        _profiles(civil_min_speed=240, fast_ceiling=9_500),
        preferred_target_aircraft_id="MIL-F01",
    )

    assert batch.candidates[0].maneuver.target_altitude_ft == 9_500.0  # type: ignore[union-attr]
    assert batch.candidates[2].maneuver.target_ground_speed_kt == 240.0  # type: ignore[union-attr]


def test_generator_is_input_order_independent_and_uses_preferred_role() -> None:
    generator = DeterministicResolutionCandidateGenerator()

    first = generator.generate(
        _exception(),
        _states(),
        _profiles(),
        preferred_target_aircraft_id=" CIV-A02 ",
        preferred_altitude_ft=10_000,
    )
    second = generator.generate(
        _exception(),
        reversed(_states()),
        dict(reversed(tuple(_profiles().items()))),
        preferred_target_aircraft_id="CIV-A02",
        preferred_altitude_ft=10_000,
    )

    assert first == second
    assert first.candidates[0].target_aircraft_id == "CIV-A02"
    assert first.candidates[2].target_aircraft_id == "MIL-F01"


def test_generator_rejects_wrong_profile_exception_or_inactive_risk() -> None:
    with pytest.raises(TypeError, match="GenerationProfile"):
        DeterministicResolutionCandidateGenerator("profile")  # type: ignore[arg-type]
    generator = DeterministicResolutionCandidateGenerator()
    assert generator.profile is POC_RESOLUTION_V1_GENERATION_PROFILE
    with pytest.raises(TypeError, match="ConflictExceptionItem"):
        generator.generate(  # type: ignore[arg-type]
            "exception",
            _states(),
            _profiles(),
            preferred_target_aircraft_id="MIL-F01",
        )
    with pytest.raises(ValueError, match="resolved"):
        generator.generate(
            _exception(status=ExceptionStatus.RESOLVED),
            _states(),
            _profiles(),
            preferred_target_aircraft_id="MIL-F01",
        )
    with pytest.raises(ValueError, match="LOW"):
        generator.generate(
            _exception(level=RiskLevel.LOW),
            _states(),
            _profiles(),
            preferred_target_aircraft_id="MIL-F01",
        )


@pytest.mark.parametrize("invalid", ["states", None, ("state",)])
def test_generator_rejects_invalid_state_iterables(invalid) -> None:
    with pytest.raises(TypeError, match="states"):
        DeterministicResolutionCandidateGenerator().generate(
            _exception(),
            invalid,
            _profiles(),
            preferred_target_aircraft_id="MIL-F01",
        )


def test_generator_requires_exact_unique_synchronized_pair_states() -> None:
    generator = DeterministicResolutionCandidateGenerator()
    first, second = _states()
    cases = (
        (first, first),
        (first,),
        (
            first,
            _state(
                "MIL-F01",
                timestamp=STATE_TIME + timedelta(seconds=1),
                altitude_ft=7_285,
                speed_kt=320,
                heading_deg=180,
            ),
        ),
    )
    messages = ("unique", "exactly", "share one timestamp")
    for states, message in zip(cases, messages, strict=True):
        with pytest.raises(ValueError, match=message):
            generator.generate(
                _exception(),
                states,
                _profiles(),
                preferred_target_aircraft_id="MIL-F01",
            )


def test_generator_validates_profile_mapping_preferred_target_and_altitude() -> None:
    generator = DeterministicResolutionCandidateGenerator()
    with pytest.raises(TypeError, match="mapping"):
        generator.generate(
            _exception(),
            _states(),
            [],  # type: ignore[arg-type]
            preferred_target_aircraft_id="MIL-F01",
        )
    with pytest.raises(ValueError, match="exactly"):
        generator.generate(
            _exception(),
            _states(),
            {"MIL-F01": _profiles()["MIL-F01"]},
            preferred_target_aircraft_id="MIL-F01",
        )
    invalid_profiles = dict(_profiles())
    invalid_profiles["CIV-A02"] = "profile"  # type: ignore[assignment]
    with pytest.raises(TypeError, match="AircraftPerformanceProfile"):
        generator.generate(
            _exception(),
            _states(),
            invalid_profiles,
            preferred_target_aircraft_id="MIL-F01",
        )
    with pytest.raises(ValueError, match="belong"):
        generator.generate(
            _exception(),
            _states(),
            _profiles(),
            preferred_target_aircraft_id="OTHER",
        )
    with pytest.raises(ValueError, match="non-negative"):
        generator.generate(
            _exception(),
            _states(),
            _profiles(),
            preferred_target_aircraft_id="MIL-F01",
            preferred_altitude_ft=-1,
        )
    with pytest.raises(ValueError, match="ceiling"):
        generator.generate(
            _exception(),
            _states(),
            _profiles(),
            preferred_target_aircraft_id="MIL-F01",
            preferred_altitude_ft=60_000,
        )


def test_generator_rejects_conflict_assessment_newer_than_states() -> None:
    with pytest.raises(ValueError, match="newer"):
        DeterministicResolutionCandidateGenerator().generate(
            _exception(evaluated_at=STATE_TIME + timedelta(seconds=1)),
            _states(),
            _profiles(),
            preferred_target_aircraft_id="MIL-F01",
        )
