from datetime import UTC, datetime, timedelta, timezone

import pytest

from sentry_atm.domain import (
    AltitudeManeuver,
    CandidateCostEstimate,
    ConflictPair,
    EntryDelayManeuver,
    HeadingManeuver,
    NoActionManeuver,
    ResolutionCandidate,
    ResolutionCandidateBatch,
    ResolutionManeuverType,
    ResolutionObjective,
    SequenceChangeManeuver,
    SpeedManeuver,
)

GENERATED_AT = datetime(2026, 9, 1, 3, 1, 15, tzinfo=UTC)
_DEFAULT_CANDIDATES = object()


def _candidate(
    candidate_id: str = "CAND-A",
    *,
    target_aircraft_id: str | None = "MIL-F01",
    maneuver=None,
    objective: ResolutionObjective = ResolutionObjective.VERTICAL_SEPARATION,
    effective_from_utc: datetime = GENERATED_AT,
    cost: CandidateCostEstimate | None = None,
) -> ResolutionCandidate:
    return ResolutionCandidate(
        candidate_id=candidate_id,
        target_aircraft_id=target_aircraft_id,
        maneuver=AltitudeManeuver(9_000.0) if maneuver is None else maneuver,
        objective=objective,
        effective_from_utc=effective_from_utc,
        cost=CandidateCostEstimate() if cost is None else cost,
    )


def _baseline(candidate_id: str = "CAND-E") -> ResolutionCandidate:
    return _candidate(
        candidate_id,
        target_aircraft_id=None,
        maneuver=NoActionManeuver(),
        objective=ResolutionObjective.BASELINE_COMPARISON,
    )


def _batch(candidates=_DEFAULT_CANDIDATES, **overrides) -> ResolutionCandidateBatch:
    values = {
        "candidate_batch_id": "BATCH-001",
        "source_exception_id": "EXCEPTION-CONFLICT-7-CIV-A02-7-MIL-F01",
        "source_conflict_id": "CONFLICT-001",
        "conflict_pair": ConflictPair("MIL-F01", "CIV-A02"),
        "generated_at_utc": GENERATED_AT,
        "generator_profile_id": "POC_RESOLUTION_V1",
        "candidates": (
            (_candidate(), _baseline()) if candidates is _DEFAULT_CANDIDATES else candidates
        ),
    }
    values.update(overrides)
    return ResolutionCandidateBatch(**values)


def test_resolution_enums_have_stable_values() -> None:
    assert tuple(item.value for item in ResolutionManeuverType) == (
        "HEADING",
        "ALTITUDE",
        "SPEED",
        "ENTRY_DELAY",
        "SEQUENCE_CHANGE",
        "NO_ACTION",
    )
    assert tuple(item.value for item in ResolutionObjective) == (
        "LATERAL_SEPARATION",
        "VERTICAL_SEPARATION",
        "TIME_SEPARATION",
        "SEQUENCE_MANAGEMENT",
        "BASELINE_COMPARISON",
    )


def test_maneuver_primitives_expose_typed_values() -> None:
    maneuvers = (
        HeadingManeuver(200),
        AltitudeManeuver(9_000),
        SpeedManeuver(220),
        EntryDelayManeuver(30),
        SequenceChangeManeuver(2),
        NoActionManeuver(),
    )

    assert tuple(item.maneuver_type for item in maneuvers) == tuple(ResolutionManeuverType)
    assert maneuvers[0].target_heading_deg == 200.0  # type: ignore[union-attr]
    assert maneuvers[1].target_altitude_ft == 9_000.0  # type: ignore[union-attr]
    assert maneuvers[2].target_ground_speed_kt == 220.0  # type: ignore[union-attr]
    assert maneuvers[3].delay_seconds == 30.0  # type: ignore[union-attr]


@pytest.mark.parametrize(
    "factory",
    [
        lambda: HeadingManeuver(360),
        lambda: AltitudeManeuver(-1),
        lambda: SpeedManeuver(0),
        lambda: EntryDelayManeuver(0),
        lambda: SequenceChangeManeuver(0),
    ],
)
def test_maneuver_primitives_reject_invalid_ranges(factory) -> None:
    with pytest.raises(ValueError):
        factory()


def test_sequence_position_rejects_non_integer_or_boolean() -> None:
    with pytest.raises(TypeError, match="integer"):
        SequenceChangeManeuver(1.5)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="integer"):
        SequenceChangeManeuver(True)


def test_candidate_cost_is_finite_bounded_and_reports_zero() -> None:
    zero = CandidateCostEstimate()
    cost = CandidateCostEstimate(15, 2.5, 35)

    assert zero.is_zero
    assert not cost.is_zero
    assert cost.estimated_delay_seconds == 15.0
    assert cost.estimated_path_extension_nm == 2.5
    assert cost.operational_cost_score == 35.0

    with pytest.raises(ValueError, match="non-negative"):
        CandidateCostEstimate(estimated_delay_seconds=-1)
    with pytest.raises(ValueError, match=r"\[0, 100\]"):
        CandidateCostEstimate(operational_cost_score=101)


def test_candidate_normalizes_metadata_time_and_exposes_maneuver_type() -> None:
    local_time = GENERATED_AT.astimezone(timezone(timedelta(hours=9)))

    candidate = _candidate(
        " CAND-A ",
        target_aircraft_id=" MIL-F01 ",
        objective="VERTICAL_SEPARATION",  # type: ignore[arg-type]
        effective_from_utc=local_time,
    )

    assert candidate.candidate_id == "CAND-A"
    assert candidate.target_aircraft_id == "MIL-F01"
    assert candidate.effective_from_utc == GENERATED_AT
    assert candidate.maneuver_type is ResolutionManeuverType.ALTITUDE
    assert candidate.objective is ResolutionObjective.VERTICAL_SEPARATION


def test_candidate_requires_supported_maneuver_objective_and_cost() -> None:
    with pytest.raises(TypeError, match="supported"):
        _candidate(maneuver="ALTITUDE")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="objective"):
        _candidate(objective=ResolutionObjective.LATERAL_SEPARATION)
    with pytest.raises(TypeError, match="CandidateCostEstimate"):
        _candidate(cost="cost")  # type: ignore[arg-type]


def test_no_action_requires_no_target_and_zero_cost() -> None:
    assert _baseline().target_aircraft_id is None

    with pytest.raises(ValueError, match="must not have"):
        _candidate(
            target_aircraft_id="MIL-F01",
            maneuver=NoActionManeuver(),
            objective=ResolutionObjective.BASELINE_COMPARISON,
        )
    with pytest.raises(ValueError, match="zero"):
        _candidate(
            target_aircraft_id=None,
            maneuver=NoActionManeuver(),
            objective=ResolutionObjective.BASELINE_COMPARISON,
            cost=CandidateCostEstimate(operational_cost_score=1),
        )


def test_action_candidate_requires_target_aircraft() -> None:
    with pytest.raises(TypeError, match="target_aircraft_id"):
        _candidate(target_aircraft_id=None)


def test_batch_normalizes_sorts_materializes_and_exposes_views() -> None:
    source = [_baseline(), _candidate()]
    batch = _batch(
        source,
        candidate_batch_id=" BATCH-001 ",
        source_exception_id=" EXCEPTION-001 ",
        source_conflict_id=" CONFLICT-001 ",
        generator_profile_id=" POC_RESOLUTION_V1 ",
    )
    source.clear()

    assert batch.candidate_batch_id == "BATCH-001"
    assert batch.source_exception_id == "EXCEPTION-001"
    assert batch.generated_at_utc == GENERATED_AT
    assert tuple(item.candidate_id for item in batch.candidates) == ("CAND-A", "CAND-E")
    assert batch.actionable_candidates == (batch.candidates[0],)
    assert batch.baseline_candidate is batch.candidates[1]


def test_batch_rejects_wrong_pair_or_candidate_iterables() -> None:
    with pytest.raises(TypeError, match="ConflictPair"):
        _batch(conflict_pair="pair")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="iterable"):
        _batch("candidates")
    with pytest.raises(TypeError, match="iterable"):
        _batch(None)
    with pytest.raises(TypeError, match="contain"):
        _batch(("candidate",))
    with pytest.raises(ValueError, match="must not be empty"):
        _batch(())


def test_batch_requires_unique_ids_and_exactly_one_baseline() -> None:
    candidate = _candidate()
    with pytest.raises(ValueError, match="IDs"):
        _batch((candidate, candidate, _baseline()))
    with pytest.raises(ValueError, match="exactly one"):
        _batch((candidate,))
    with pytest.raises(ValueError, match="exactly one"):
        _batch((candidate, _baseline("CAND-E"), _baseline("CAND-F")))


def test_batch_restricts_targets_to_pair_and_effective_time_to_future() -> None:
    with pytest.raises(ValueError, match="conflict_pair"):
        _batch((_candidate(target_aircraft_id="OTHER"), _baseline()))
    with pytest.raises(ValueError, match="must not precede"):
        _batch(
            (
                _candidate(effective_from_utc=GENERATED_AT - timedelta(seconds=1)),
                _baseline(),
            )
        )


def test_golden_demo_candidate_contract_contains_documented_a_to_e() -> None:
    candidates = (
        _candidate("CAND-A", maneuver=AltitudeManeuver(9_000)),
        _candidate(
            "CAND-B",
            maneuver=HeadingManeuver(200),
            objective=ResolutionObjective.LATERAL_SEPARATION,
            cost=CandidateCostEstimate(0, 1.5, 25),
        ),
        _candidate(
            "CAND-C",
            target_aircraft_id="CIV-A02",
            maneuver=SpeedManeuver(220),
            objective=ResolutionObjective.TIME_SEPARATION,
            cost=CandidateCostEstimate(30, 0, 20),
        ),
        _candidate(
            "CAND-D",
            target_aircraft_id="CIV-A02",
            maneuver=AltitudeManeuver(8_000),
            cost=CandidateCostEstimate(0, 0, 30),
        ),
        _baseline(),
    )

    batch = _batch(reversed(candidates))

    assert tuple(candidate.candidate_id for candidate in batch.candidates) == (
        "CAND-A",
        "CAND-B",
        "CAND-C",
        "CAND-D",
        "CAND-E",
    )
    assert len(batch.actionable_candidates) == 4
