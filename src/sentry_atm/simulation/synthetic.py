"""Deterministic constant-motion runtime for synthetic aircraft."""

from math import cos, radians, sin

from sentry_atm.domain.aircraft import AircraftState
from sentry_atm.domain.enums import DataSource
from sentry_atm.domain.units import fpm_to_ft_per_second, knots_to_nm_per_second
from sentry_atm.simulation.clock import SimulationClock


class SyntheticAircraftRuntime:
    """Calculate a synthetic aircraft state at the simulation clock time."""

    __slots__ = ("_clock", "_initial_state")

    def __init__(
        self,
        *,
        clock: SimulationClock,
        initial_state: AircraftState,
    ) -> None:
        if not isinstance(clock, SimulationClock):
            raise TypeError("clock must be a SimulationClock")
        if not isinstance(initial_state, AircraftState):
            raise TypeError("initial_state must be an AircraftState")
        if initial_state.source is not DataSource.SYNTHETIC:
            raise ValueError("initial_state must use the SYNTHETIC source")

        self._clock = clock
        self._initial_state = initial_state

    @property
    def aircraft_id(self) -> str:
        """Return the synthetic aircraft identifier."""

        return self._initial_state.aircraft_id

    @property
    def clock(self) -> SimulationClock:
        """Return the shared simulation clock consumed by this runtime."""

        return self._clock

    @property
    def initial_state(self) -> AircraftState:
        """Return the immutable state used as the motion origin."""

        return self._initial_state

    @property
    def current_state(self) -> AircraftState | None:
        """Return constant-motion state at current simulation time."""

        current_time_utc = self._clock.current_time_utc
        elapsed_seconds = (current_time_utc - self._initial_state.timestamp_utc).total_seconds()
        if elapsed_seconds < 0.0:
            return None
        if elapsed_seconds == 0.0:
            return self._initial_state

        heading_rad = radians(self._initial_state.heading_deg)
        distance_nm = knots_to_nm_per_second(self._initial_state.ground_speed_kt) * elapsed_seconds
        altitude_change_ft = (
            fpm_to_ft_per_second(self._initial_state.vertical_speed_fpm) * elapsed_seconds
        )

        return AircraftState(
            aircraft_id=self._initial_state.aircraft_id,
            timestamp_utc=current_time_utc,
            x_nm=self._initial_state.x_nm + distance_nm * sin(heading_rad),
            y_nm=self._initial_state.y_nm + distance_nm * cos(heading_rad),
            altitude_ft=self._initial_state.altitude_ft + altitude_change_ft,
            ground_speed_kt=self._initial_state.ground_speed_kt,
            heading_deg=self._initial_state.heading_deg,
            vertical_speed_fpm=self._initial_state.vertical_speed_fpm,
            source=self._initial_state.source,
            flight_phase=self._initial_state.flight_phase,
            emergency_status=self._initial_state.emergency_status,
            emergency_type=self._initial_state.emergency_type,
        )
