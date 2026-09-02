"""Golden Demo definition and Synthetic simulation construction."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sentry_atm.domain import (
    AircraftCategory,
    AircraftMetadata,
    AircraftState,
    DataSource,
    EmergencyType,
    FlightPhase,
)
from sentry_atm.scenario.event import (
    EmergencyDeclaredPayload,
    EmergencyReasonCategory,
    EntryConformanceDeviationPayload,
    ScenarioEvent,
    ScenarioEventType,
)
from sentry_atm.scenario.model import ScenarioAircraft, ScenarioDefinition
from sentry_atm.scenario.timeline import ScenarioEventTimeline
from sentry_atm.simulation import (
    SimulationClock,
    SyntheticAircraftRuntime,
    TrafficSimulationEngine,
)

GOLDEN_DEMO_SCENARIO_ID = "RKTU_GOLDEN_DEMO_V1"
GOLDEN_DEMO_START_UTC = datetime(2026, 9, 1, 3, 0, tzinfo=UTC)

# Phase 6-E calibration: at T+70 the ordinary constant-velocity CPA calculation
# yields TCPA 90 s, horizontal separation 2.3 NM, and vertical separation 500 ft.
_MIL_F01_INITIAL_X_NM = 5.928937934153731
_MIL_F01_INITIAL_Y_NM = 22.62140027743578
_MIL_F01_ACTUAL_X_NM = 4.29424619131654
_MIL_F01_ACTUAL_Y_NM = 16.173656419930605

# Phase 9-E calibration: preserve the Phase 6-E primary CPA while making the
# 20-degree CAND-B heading change resolve that pair vertically and create one
# calculated secondary conflict with MIL-F02.
_CIV_A02_INITIAL_ALTITUDE_FT = 9_075.0
_MIL_F01_ACTUAL_VERTICAL_SPEED_FPM = 185.0
_MIL_F02_INITIAL_X_NM = -11.319417382415922
_MIL_F02_INITIAL_Y_NM = 20.31941738241592
_MIL_F02_INITIAL_ALTITUDE_FT = 6_946.25
_MIL_F02_VERTICAL_SPEED_FPM = 400.0


@dataclass(frozen=True, slots=True)
class ScenarioSimulation:
    """Runtime objects built from one immutable scenario definition."""

    definition: ScenarioDefinition
    clock: SimulationClock
    engine: TrafficSimulationEngine
    timeline: ScenarioEventTimeline


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
    scheduled_states: tuple[AircraftState, ...] = (),
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
        scheduled_states=scheduled_states,
    )


def build_golden_demo_scenario() -> ScenarioDefinition:
    """Return the eight-aircraft Golden Demo definition and event schedule."""

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
                altitude_ft=_CIV_A02_INITIAL_ALTITUDE_FT,
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
                x_nm=_MIL_F01_INITIAL_X_NM,
                y_nm=_MIL_F01_INITIAL_Y_NM,
                altitude_ft=13_000.0,
                ground_speed_kt=320.0,
                heading_deg=210.0,
                vertical_speed_fpm=-4_000.0,
                flight_phase=FlightPhase.DESCENT,
                scheduled_states=(
                    AircraftState(
                        aircraft_id="MIL-F01",
                        timestamp_utc=GOLDEN_DEMO_START_UTC + timedelta(seconds=60),
                        x_nm=_MIL_F01_ACTUAL_X_NM,
                        y_nm=_MIL_F01_ACTUAL_Y_NM,
                        altitude_ft=7_400.0,
                        ground_speed_kt=320.0,
                        heading_deg=180.0,
                        vertical_speed_fpm=_MIL_F01_ACTUAL_VERTICAL_SPEED_FPM,
                        source=DataSource.SYNTHETIC,
                        flight_phase=FlightPhase.CLIMB,
                    ),
                ),
            ),
            _scenario_aircraft(
                aircraft_id="MIL-F02",
                aircraft_type="SYN-FAST-JET",
                category=AircraftCategory.FAST_JET,
                performance_profile_id="FAST-JET-POC-V1",
                x_nm=_MIL_F02_INITIAL_X_NM,
                y_nm=_MIL_F02_INITIAL_Y_NM,
                altitude_ft=_MIL_F02_INITIAL_ALTITUDE_FT,
                ground_speed_kt=300.0,
                heading_deg=135.0,
                vertical_speed_fpm=_MIL_F02_VERTICAL_SPEED_FPM,
                flight_phase=FlightPhase.CLIMB,
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
                x_nm=-1.0,
                y_nm=18.0,
                altitude_ft=10_000.0,
                ground_speed_kt=200.0,
                heading_deg=100.0,
                vertical_speed_fpm=0.0,
                flight_phase=FlightPhase.LEVEL,
            ),
        ),
        events=build_golden_demo_events(),
    )


def build_golden_demo_events() -> tuple[ScenarioEvent, ...]:
    """Return the ordered Phase 5-B events for the Golden Demo."""

    return (
        ScenarioEvent(
            event_id="EVT-MIL-F01-ENTRY-DEVIATION",
            event_type=ScenarioEventType.ENTRY_CONFORMANCE_DEVIATION,
            scheduled_time_utc=GOLDEN_DEMO_START_UTC + timedelta(seconds=60),
            target_aircraft_id="MIL-F01",
            payload=EntryConformanceDeviationPayload(
                expected_entry_point="ENTRY-A",
                expected_altitude_ft=9_000.0,
                expected_heading_deg=210.0,
                actual_altitude_ft=7_400.0,
                lateral_deviation_nm=2.1,
                time_deviation_seconds=25.0,
            ),
        ),
        ScenarioEvent(
            event_id="EVT-MIL-T01-EMERGENCY",
            event_type=ScenarioEventType.EMERGENCY_DECLARED,
            scheduled_time_utc=GOLDEN_DEMO_START_UTC + timedelta(seconds=240),
            target_aircraft_id="MIL-T01",
            payload=EmergencyDeclaredPayload(
                emergency_type=EmergencyType.PRIORITY_RETURN,
                reason_category=EmergencyReasonCategory.AIRCRAFT_CONDITION,
            ),
        ),
    )


def build_scenario_simulation(definition: ScenarioDefinition) -> ScenarioSimulation:
    """Build a shared Clock and ordered Synthetic runtimes for a scenario."""

    if not isinstance(definition, ScenarioDefinition):
        raise TypeError("definition must be a ScenarioDefinition")
    clock = SimulationClock(start_time_utc=definition.start_time_utc)
    runtimes = tuple(
        SyntheticAircraftRuntime(
            clock=clock,
            initial_state=item.initial_state,
            scheduled_states=item.scheduled_states,
        )
        for item in definition.aircraft
    )
    engine = TrafficSimulationEngine(clock=clock, runtimes=runtimes)
    timeline = ScenarioEventTimeline(clock=clock, events=definition.events)
    return ScenarioSimulation(
        definition=definition,
        clock=clock,
        engine=engine,
        timeline=timeline,
    )
