import pytest

from sentry_atm.domain import (
    AircraftCategory,
    AircraftPerformanceProfile,
    AircraftType,
    PerformanceDataSource,
)


def _profile(**overrides: object) -> AircraftPerformanceProfile:
    values: dict[str, object] = {
        "profile_id": "AIRLINER-POC-V1",
        "category": AircraftCategory.AIRLINER,
        "source": PerformanceDataSource.SIMULATION_ASSUMPTION,
        "source_reference": "ASM-013",
        "min_speed_kt": 120.0,
        "max_speed_kt": 480.0,
        "max_climb_rate_fpm": 3_000.0,
        "max_descent_rate_fpm": 3_000.0,
        "max_turn_rate_deg_per_second": 3.0,
        "ceiling_ft": 41_000.0,
        "aircraft_type_code": "a320",
    }
    values.update(overrides)
    return AircraftPerformanceProfile(**values)  # type: ignore[arg-type]


def test_aircraft_type_normalizes_type_code_and_optional_text() -> None:
    aircraft_type = AircraftType(
        type_code=" a320 ",
        category="AIRLINER",
        manufacturer=" Airbus ",
        model=" A320 family ",
    )

    assert aircraft_type.type_code == "A320"
    assert aircraft_type.category is AircraftCategory.AIRLINER
    assert aircraft_type.manufacturer == "Airbus"
    assert aircraft_type.model == "A320 family"


def test_performance_profile_normalizes_values_and_requires_provenance() -> None:
    profile = _profile(min_speed_kt=120, aircraft_type_code=" a320 ")

    assert profile.min_speed_kt == 120.0
    assert profile.aircraft_type_code == "A320"
    assert profile.source is PerformanceDataSource.SIMULATION_ASSUMPTION
    assert profile.source_reference == "ASM-013"


def test_performance_profile_rejects_inverted_speed_envelope() -> None:
    with pytest.raises(ValueError, match="must not exceed"):
        _profile(min_speed_kt=500.0, max_speed_kt=480.0)


@pytest.mark.parametrize(
    "field_name",
    [
        "max_speed_kt",
        "max_climb_rate_fpm",
        "max_descent_rate_fpm",
        "max_turn_rate_deg_per_second",
        "ceiling_ft",
    ],
)
def test_performance_profile_requires_positive_envelope_limits(field_name: str) -> None:
    with pytest.raises(ValueError, match="greater than zero"):
        _profile(**{field_name: 0.0})


def test_performance_profile_rejects_missing_source_reference() -> None:
    with pytest.raises(ValueError, match="source_reference must not be blank"):
        _profile(source_reference="  ")
