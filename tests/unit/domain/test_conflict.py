from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone

import pytest

from sentry_atm.domain import (
    POC_TERMINAL_V1_RULE_PROFILE,
    ConflictAssessmentRun,
    ConflictEvent,
    ConflictPair,
    ConflictStatus,
    SeparationMinimum,
    SeparationRuleProfile,
)

EVALUATED_AT_UTC = datetime(2026, 9, 2, 3, 0, tzinfo=UTC)


def _event(
    *,
    conflict_id: str = "CONFLICT-001",
    first_aircraft_id: str = "CIV-A01",
    second_aircraft_id: str = "CIV-A02",
    status: ConflictStatus = ConflictStatus.PREDICTED,
    evaluated_at_utc: datetime = EVALUATED_AT_UTC,
    rule_profile_id: str = "POC_TERMINAL_V1",
) -> ConflictEvent:
    return ConflictEvent(
        conflict_id=conflict_id,
        pair=ConflictPair(first_aircraft_id, second_aircraft_id),
        status=status,
        evaluated_at_utc=evaluated_at_utc,
        closest_approach_time_utc=evaluated_at_utc + timedelta(seconds=90),
        minimum_separation=SeparationMinimum(2.3, 500.0),
        rule_profile_id=rule_profile_id,
    )


def test_conflict_pair_normalizes_order_and_exposes_stable_key() -> None:
    pair = ConflictPair(
        first_aircraft_id=" MIL-F01 ",
        second_aircraft_id=" CIV-A02 ",
    )

    assert pair.first_aircraft_id == "CIV-A02"
    assert pair.second_aircraft_id == "MIL-F01"
    assert pair.aircraft_ids == ("CIV-A02", "MIL-F01")
    assert pair == ConflictPair("CIV-A02", "MIL-F01")

    with pytest.raises(FrozenInstanceError):
        pair.first_aircraft_id = "CHANGED"  # type: ignore[misc]


def test_conflict_pair_requires_distinct_non_blank_string_ids() -> None:
    with pytest.raises(ValueError, match="distinct"):
        ConflictPair("CIV-A01", " CIV-A01 ")
    with pytest.raises(ValueError, match="must not be blank"):
        ConflictPair("", "MIL-F01")
    with pytest.raises(TypeError, match="must be a string"):
        ConflictPair(1, "MIL-F01")  # type: ignore[arg-type]


def test_separation_minimum_normalizes_non_negative_canonical_units() -> None:
    minimum = SeparationMinimum(horizontal_nm=2, vertical_ft=500)

    assert minimum.horizontal_nm == 2.0
    assert minimum.vertical_ft == 500.0


@pytest.mark.parametrize(
    ("field_name", "value", "error_type"),
    [
        ("horizontal_nm", -0.1, ValueError),
        ("vertical_ft", float("inf"), ValueError),
        ("horizontal_nm", True, TypeError),
    ],
)
def test_separation_minimum_rejects_invalid_values(
    field_name: str,
    value: object,
    error_type: type[Exception],
) -> None:
    values = {"horizontal_nm": 2.0, "vertical_ft": 500.0}
    values[field_name] = value

    with pytest.raises(error_type, match=field_name):
        SeparationMinimum(**values)


def test_rule_profile_classifies_only_concurrent_threshold_breach() -> None:
    profile = POC_TERMINAL_V1_RULE_PROFILE

    assert profile.profile_id == "POC_TERMINAL_V1"
    assert profile.classify(SeparationMinimum(4.9, 999.0)) is ConflictStatus.PREDICTED
    assert profile.classify(SeparationMinimum(5.0, 999.0)) is ConflictStatus.SAFE
    assert profile.classify(SeparationMinimum(4.9, 1_000.0)) is ConflictStatus.SAFE
    assert profile.classify(SeparationMinimum(2.0, 2_000.0)) is ConflictStatus.SAFE


def test_rule_profile_is_injectable_and_validates_contract() -> None:
    profile = SeparationRuleProfile(
        profile_id=" CUSTOM-RULE ",
        horizontal_threshold_nm=3,
        vertical_threshold_ft=700,
        source_reference=" Test-only configurable rule ",
    )

    assert profile.profile_id == "CUSTOM-RULE"
    assert profile.horizontal_threshold_nm == 3.0
    assert profile.vertical_threshold_ft == 700.0
    assert profile.source_reference == "Test-only configurable rule"
    assert profile.classify(SeparationMinimum(2.9, 699.0)) is ConflictStatus.PREDICTED

    with pytest.raises(ValueError, match="greater than zero"):
        SeparationRuleProfile("ZERO", 0.0, 1_000.0, "test")
    with pytest.raises(ValueError, match="greater than zero"):
        SeparationRuleProfile("ZERO", 5.0, 0.0, "test")
    with pytest.raises(TypeError, match="SeparationMinimum"):
        profile.classify("minimum")  # type: ignore[arg-type]


def test_conflict_event_normalizes_utc_enum_and_derives_tcpa() -> None:
    event = ConflictEvent(
        conflict_id=" CONFLICT-001 ",
        pair=ConflictPair("MIL-F01", "CIV-A02"),
        status="PREDICTED",
        evaluated_at_utc=datetime(
            2026,
            9,
            2,
            12,
            0,
            tzinfo=timezone(timedelta(hours=9)),
        ),
        closest_approach_time_utc=EVALUATED_AT_UTC + timedelta(seconds=90),
        minimum_separation=SeparationMinimum(2.3, 500.0),
        rule_profile_id=" POC_TERMINAL_V1 ",
    )

    assert event.conflict_id == "CONFLICT-001"
    assert event.pair.aircraft_ids == ("CIV-A02", "MIL-F01")
    assert event.status is ConflictStatus.PREDICTED
    assert event.evaluated_at_utc == EVALUATED_AT_UTC
    assert event.closest_approach_time_utc == EVALUATED_AT_UTC + timedelta(seconds=90)
    assert event.tcpa_seconds == 90.0
    assert event.rule_profile_id == "POC_TERMINAL_V1"


def test_conflict_event_accepts_safe_assessment_at_current_time() -> None:
    event = ConflictEvent(
        conflict_id="SAFE-001",
        pair=ConflictPair("CIV-A01", "CIV-A02"),
        status=ConflictStatus.SAFE,
        evaluated_at_utc=EVALUATED_AT_UTC,
        closest_approach_time_utc=EVALUATED_AT_UTC,
        minimum_separation=SeparationMinimum(8.0, 2_000.0),
        rule_profile_id="POC_TERMINAL_V1",
    )

    assert event.status is ConflictStatus.SAFE
    assert event.tcpa_seconds == 0.0


def test_conflict_event_rejects_wrong_components_or_past_approach() -> None:
    valid_values = {
        "conflict_id": "CONFLICT-001",
        "pair": ConflictPair("CIV-A02", "MIL-F01"),
        "status": ConflictStatus.PREDICTED,
        "evaluated_at_utc": EVALUATED_AT_UTC,
        "closest_approach_time_utc": EVALUATED_AT_UTC + timedelta(seconds=90),
        "minimum_separation": SeparationMinimum(2.3, 500.0),
        "rule_profile_id": "POC_TERMINAL_V1",
    }

    with pytest.raises(TypeError, match="ConflictPair"):
        ConflictEvent(**(valid_values | {"pair": "pair"}))
    with pytest.raises(TypeError, match="SeparationMinimum"):
        ConflictEvent(**(valid_values | {"minimum_separation": "minimum"}))
    with pytest.raises(ValueError, match="must not precede"):
        ConflictEvent(
            **(
                valid_values
                | {"closest_approach_time_utc": EVALUATED_AT_UTC - timedelta(seconds=1)}
            )
        )


def test_conflict_assessment_run_materializes_and_filters_events() -> None:
    predicted = _event()
    safe = _event(
        conflict_id="CONFLICT-002",
        second_aircraft_id="CIV-A03",
        status=ConflictStatus.SAFE,
    )
    source = [predicted, safe]

    run = ConflictAssessmentRun(
        assessment_run_id=" RUN-001 ",
        input_timestamp_utc=EVALUATED_AT_UTC,
        rule_profile_id=" POC_TERMINAL_V1 ",
        horizon_seconds=120,
        assessments=source,
    )
    source.clear()

    assert run.assessment_run_id == "RUN-001"
    assert run.rule_profile_id == "POC_TERMINAL_V1"
    assert run.horizon_seconds == 120.0
    assert run.assessments == (predicted, safe)
    assert run.predicted_events == (predicted,)


def test_conflict_assessment_run_allows_empty_assessment_set() -> None:
    run = ConflictAssessmentRun(
        assessment_run_id="EMPTY-RUN",
        input_timestamp_utc=EVALUATED_AT_UTC,
        rule_profile_id="POC_TERMINAL_V1",
        horizon_seconds=120.0,
    )

    assert run.assessments == ()
    assert run.predicted_events == ()


def test_conflict_assessment_run_rejects_inconsistent_events() -> None:
    first = _event()
    second = _event(
        conflict_id="CONFLICT-002",
        second_aircraft_id="CIV-A03",
    )
    valid_values = {
        "assessment_run_id": "RUN-001",
        "input_timestamp_utc": EVALUATED_AT_UTC,
        "rule_profile_id": "POC_TERMINAL_V1",
        "horizon_seconds": 120.0,
        "assessments": (first, second),
    }

    with pytest.raises(TypeError, match="ConflictEvent"):
        ConflictAssessmentRun(**(valid_values | {"assessments": ("event",)}))
    with pytest.raises(ValueError, match="times must match"):
        ConflictAssessmentRun(
            **(
                valid_values
                | {
                    "assessments": (
                        _event(evaluated_at_utc=EVALUATED_AT_UTC + timedelta(seconds=1)),
                    )
                }
            )
        )
    with pytest.raises(ValueError, match="run rule_profile_id"):
        ConflictAssessmentRun(
            **(valid_values | {"assessments": (_event(rule_profile_id="OTHER-RULE"),)})
        )
    with pytest.raises(ValueError, match="TCPA must not exceed"):
        ConflictAssessmentRun(**(valid_values | {"horizon_seconds": 89.0}))
    with pytest.raises(ValueError, match="conflict IDs must be unique"):
        ConflictAssessmentRun(**(valid_values | {"assessments": (first, first)}))
    with pytest.raises(ValueError, match="strictly ordered"):
        ConflictAssessmentRun(**(valid_values | {"assessments": (second, first)}))
    with pytest.raises(ValueError, match="greater than zero"):
        ConflictAssessmentRun(**(valid_values | {"horizon_seconds": 0.0}))
