"""Golden Demo definition and Synthetic simulation construction."""

from dataclasses import dataclass
from datetime import UTC, datetime

from sentry_atm.domain import (
    AircraftCategory,
    AircraftMetadata,
    AircraftState,
    DataSource,
    FlightPhase,
)
from sentry_atm.scenario.model import ScenarioAircraft, ScenarioDefinition
from sentry_atm.simulation import (
    SimulationClock,
    SyntheticAircraftRuntime,
    TrafficSimulationEngine,
)

GOLDEN_DEMO_SCENARIO_ID = "RKTU_GOLDEN_DEMO_V1"
GOLDEN_DEMO_START_UTC = datetime(2026, 9, 1, 3, 0, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class ScenarioSimulation:
    """Runtime objects built from one immutable scenario definition."""

    definition: ScenarioDefinition
    clock: SimulationClock
    engine: TrafficSimulationEngine


def _scenario_aircraft(
    *,
    aircraft_id: str,
    aircraft_type: str,
    category: AircraftCategory,
    performance_profile_id: str,
    x_nm: float,
    y_nm: float,
    altitude_ft: float,
    ground_speed_kt: float,
    heading_deg: float,
    vertical_speed_fpm: float,
    flight_phase: FlightPhase,
) -> ScenarioAircraft:
    return ScenarioAircraft(
        metadata=AircraftMetadata(
            aircraft_id=aircraft_id,
            aircraft_type=aircraft_type,
            category=category,
            performance_class=performance_profile_id,
        ),
        initial_state=AircraftState(
            aircraft_id=aircraft_id,
            timestamp_utc=GOLDEN_DEMO_START_UTC,
            x_nm=x_nm,
            y_nm=y_nm,
            altitude_ft=altitude_ft,
            ground_speed_kt=ground_speed_kt,
            heading_deg=heading_deg,
            vertical_speed_fpm=vertical_speed_fpm,
            source=DataSource.SYNTHETIC,
            flight_phase=flight_phase,
        ),
    )


def build_golden_demo_scenario() -> ScenarioDefinition:
    """Return the Phase 5-A eight-aircraft Golden Demo foundation."""

    return ScenarioDefinition(
        scenario_id=GOLDEN_DEMO_SCENARIO_ID,
        start_time_utc=GOLDEN_DEMO_START_UTC,
        aircraft=(
            _scenario_aircraft(
                aircraft_id="CIV-A01",
                aircraft_type="SYN-AIRLINER",
                category=AircraftCategory.AIRLINER,
                performance_profile_id="AIRLINER-POC-V1",
                x_nm=-3.0,
                y_nm=-4.0,
                altitude_ft=3_000.0,
                ground_speed_kt=170.0,
                heading_deg=0.0,
                vertical_speed_fpm=0.0,
                flight_phase=FlightPhase.APPROACH,
            ),
            _scenario_aircraft(
                aircraft_id="CIV-A02",
                aircraft_type="SYN-AIRLINER",
                category=AircraftCategory.AIRLINER,
                performance_profile_id="AIRLINER-POC-V1",
                x_nm=10.0,
                y_nm=14.0,
                altitude_ft=9_000.0,
                ground_speed_kt=250.0,
                heading_deg=220.0,
                vertical_speed_fpm=-700.0,
                flight_phase=FlightPhase.DESCENT,
            ),
            _scenario_aircraft(
                aircraft_id="CIV-A03",
                aircraft_type="SYN-AIRLINER",
                category=AircraftCategory.AIRLINER,
                performance_profile_id="AIRLINER-POC-V1",
                x_nm=-14.0,
                y_nm=12.0,
                altitude_ft=11_000.0,
                ground_speed_kt=240.0,
                heading_deg=140.0,
                vertical_speed_fpm=-500.0,
                flight_phase=FlightPhase.DESCENT,
            ),
            _scenario_aircraft(
                aircraft_id="CIV-D01",
                aircraft_type="SYN-AIRLINER",
                category=AircraftCategory.AIRLINER,
                performance_profile_id="AIRLINER-POC-V1",
                x_nm=-16.0,
                y_nm=-14.0,
                altitude_ft=5_000.0,
                ground_speed_kt=220.0,
                heading_deg=60.0,
                vertical_speed_fpm=1_000.0,
                flight_phase=FlightPhase.CLIMB,
            ),
            _scenario_aircraft(
                aircraft_id="MIL-F01",
                aircraft_type="SYN-FAST-JET",
                category=AircraftCategory.FAST_JET,
                performance_profile_id="FAST-JET-POC-V1",
                x_nm=18.0,
                y_nm=18.0,
                altitude_ft=9_000.0,
                ground_speed_kt=320.0,
                heading_deg=210.0,
                vertical_speed_fpm=0.0,
                flight_phase=FlightPhase.LEVEL,
            ),
            _scenario_aircraft(
                aircraft_id="MIL-F02",
                aircraft_type="SYN-FAST-JET",
                category=AircraftCategory.FAST_JET,
                performance_profile_id="FAST-JET-POC-V1",
                x_nm=-20.0,
                y_nm=18.0,
                altitude_ft=12_000.0,
                ground_speed_kt=300.0,
                heading_deg=135.0,
                vertical_speed_fpm=-500.0,
                flight_phase=FlightPhase.DESCENT,
            ),
            _scenario_aircraft(
                aircraft_id="MIL-T01",
                aircraft_type="SYN-TRANSPORT",
                category=AircraftCategory.TRANSPORT,
                performance_profile_id="TRANSPORT-POC-V1",
                x_nm=18.0,
                y_nm=-12.0,
                altitude_ft=7_000.0,
                ground_speed_kt=210.0,
                heading_deg=300.0,
                vertical_speed_fpm=0.0,
                flight_phase=FlightPhase.LEVEL,
            ),
            _scenario_aircraft(
                aircraft_id="MIL-T02",
                aircraft_type="SYN-TRANSPORT",
                category=AircraftCategory.TRANSPORT,
                performance_profile_id="TRANSPORT-POC-V1",
                x_nm=2.0,
                y_nm=20.0,
                altitude_ft=10_000.0,
                ground_speed_kt=200.0,
                heading_deg=100.0,
                vertical_speed_fpm=0.0,
                flight_phase=FlightPhase.LEVEL,
            ),
        ),
    )


def build_scenario_simulation(definition: ScenarioDefinition) -> ScenarioSimulation:
    """Build a shared Clock and ordered Synthetic runtimes for a scenario."""

    if not isinstance(definition, ScenarioDefinition):
        raise TypeError("definition must be a ScenarioDefinition")
    clock = SimulationClock(start_time_utc=definition.start_time_utc)
    runtimes = tuple(
        SyntheticAircraftRuntime(clock=clock, initial_state=item.initial_state)
        for item in definition.aircraft
    )
    engine = TrafficSimulationEngine(clock=clock, runtimes=runtimes)
    return ScenarioSimulation(definition=definition, clock=clock, engine=engine)
