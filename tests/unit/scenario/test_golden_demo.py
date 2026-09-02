from itertools import combinations
from math import hypot

import pytest

from sentry_atm.domain import AircraftCategory, DataSource
from sentry_atm.infrastructure.persistence.seed import (
    POC_AIRCRAFT_TYPES,
    POC_PERFORMANCE_PROFILES,
)
from sentry_atm.scenario import (
    GOLDEN_DEMO_SCENARIO_ID,
    GOLDEN_DEMO_START_UTC,
    build_golden_demo_scenario,
    build_scenario_simulation,
)
from sentry_atm.simulation import ClockState, SyntheticAircraftRuntime

EXPECTED_AIRCRAFT_IDS = (
    "CIV-A01",
    "CIV-A02",
    "CIV-A03",
    "CIV-D01",
    "MIL-F01",
    "MIL-F02",
    "MIL-T01",
    "MIL-T02",
)


def test_golden_demo_definition_contains_ordered_eight_aircraft() -> None:
    definition = build_golden_demo_scenario()

    assert definition.scenario_id == GOLDEN_DEMO_SCENARIO_ID
    assert definition.start_time_utc == GOLDEN_DEMO_START_UTC
    assert definition.aircraft_ids == EXPECTED_AIRCRAFT_IDS
    assert len(definition.aircraft) == 8
    assert (
        tuple(item.metadata.category for item in definition.aircraft).count(
            AircraftCategory.AIRLINER
        )
        == 4
    )
    assert (
        tuple(item.metadata.category for item in definition.aircraft).count(
            AircraftCategory.FAST_JET
        )
        == 2
    )
    assert (
        tuple(item.metadata.category for item in definition.aircraft).count(
            AircraftCategory.TRANSPORT
        )
        == 2
    )


def test_initial_states_use_synthetic_source_and_provisional_area_envelope() -> None:
    definition = build_golden_demo_scenario()

    for item in definition.aircraft:
        state = item.initial_state
        assert state.source is DataSource.SYNTHETIC
        assert state.timestamp_utc == GOLDEN_DEMO_START_UTC
        assert hypot(state.x_nm, state.y_nm) <= 30.0
        assert 0.0 <= state.altitude_ft <= 20_000.0


def test_metadata_links_seeded_type_and_performance_profile() -> None:
    definition = build_golden_demo_scenario()
    aircraft_types = {item.type_code: item for item in POC_AIRCRAFT_TYPES}
    profiles = {item.profile_id: item for item in POC_PERFORMANCE_PROFILES}

    for item in definition.aircraft:
        metadata = item.metadata
        state = item.initial_state
        aircraft_type = aircraft_types[metadata.aircraft_type]
        profile = profiles[metadata.performance_class]

        assert metadata.category is aircraft_type.category is profile.category
        assert profile.aircraft_type_code == metadata.aircraft_type
        assert profile.min_speed_kt <= state.ground_speed_kt <= profile.max_speed_kt
        assert -profile.max_descent_rate_fpm <= state.vertical_speed_fpm
        assert state.vertical_speed_fpm <= profile.max_climb_rate_fpm
        assert state.altitude_ft <= profile.ceiling_ft


def test_initial_snapshot_has_no_current_poc_separation_violation() -> None:
    states = build_golden_demo_scenario().initial_states

    for first, second in combinations(states, 2):
        horizontal_nm = hypot(second.x_nm - first.x_nm, second.y_nm - first.y_nm)
        vertical_ft = abs(second.altitude_ft - first.altitude_ft)
        assert horizontal_nm >= 5.0 or vertical_ft >= 1_000.0


def test_scenario_simulation_builds_shared_ordered_synthetic_runtimes() -> None:
    definition = build_golden_demo_scenario()

    simulation = build_scenario_simulation(definition)

    assert simulation.definition is definition
    assert simulation.clock.state is ClockState.READY
    assert simulation.clock.current_time_utc == GOLDEN_DEMO_START_UTC
    assert simulation.engine.clock is simulation.clock
    assert simulation.engine.aircraft_ids == EXPECTED_AIRCRAFT_IDS
    assert all(
        isinstance(runtime, SyntheticAircraftRuntime) for runtime in simulation.engine.runtimes
    )
    assert simulation.engine.snapshot().states == definition.initial_states


def test_repeated_scenario_builds_produce_identical_snapshots() -> None:
    first = build_scenario_simulation(build_golden_demo_scenario())
    second = build_scenario_simulation(build_golden_demo_scenario())

    assert first.definition == second.definition
    assert first.engine.snapshot() == second.engine.snapshot()

    for simulation in (first, second):
        simulation.clock.play()
        simulation.engine.tick(steps=10)
    assert first.engine.snapshot() == second.engine.snapshot()


def test_scenario_simulation_rejects_wrong_definition_type() -> None:
    with pytest.raises(TypeError, match="ScenarioDefinition"):
        build_scenario_simulation("scenario")  # type: ignore[arg-type]
