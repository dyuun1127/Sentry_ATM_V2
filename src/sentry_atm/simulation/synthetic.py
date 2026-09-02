"""Deterministic piecewise constant-motion runtime for synthetic aircraft."""

from collections.abc import Iterable
from math import cos, radians, sin

from sentry_atm.domain.aircraft import AircraftState
from sentry_atm.domain.enums import DataSource
from sentry_atm.domain.units import fpm_to_ft_per_second, knots_to_nm_per_second
from sentry_atm.simulation.clock import SimulationClock


class SyntheticAircraftRuntime:
    """Calculate a synthetic aircraft state from deterministic motion anchors."""

    __slots__ = ("_clock", "_initial_state", "_scheduled_states")

    def __init__(
        self,
        *,
        clock: SimulationClock,
        initial_state: AircraftState,
        scheduled_states: Iterable[AircraftState] = (),
    ) -> None:
        if not isinstance(clock, SimulationClock):
            raise TypeError("clock must be a SimulationClock")
        if not isinstance(initial_state, AircraftState):
            raise TypeError("initial_state must be an AircraftState")
        if initial_state.source is not DataSource.SYNTHETIC:
            raise ValueError("initial_state must use the SYNTHETIC source")

        if isinstance(scheduled_states, (str, bytes)):
            raise TypeError("scheduled_states must be an iterable of AircraftState instances")
        try:
            materialized_states = tuple(scheduled_states)
        except TypeError:
            raise TypeError(
                "scheduled_states must be an iterable of AircraftState instances"
            ) from None
        if not all(isinstance(state, AircraftState) for state in materialized_states):
            raise TypeError("scheduled_states must contain only AircraftState instances")
        if any(state.aircraft_id != initial_state.aircraft_id for state in materialized_states):
            raise ValueError("scheduled_states must use the initial_state aircraft ID")
        if any(state.source is not DataSource.SYNTHETIC for state in materialized_states):
            raise ValueError("scheduled_states must use the SYNTHETIC source")

        motion_anchors = (initial_state, *materialized_states)
        if any(
            current.timestamp_utc <= previous.timestamp_utc
            for previous, current in zip(motion_anchors, motion_anchors[1:], strict=False)
        ):
            raise ValueError("scheduled_states must be strictly ordered after initial_state")

        self._clock = clock
        self._initial_state = initial_state
        self._scheduled_states = materialized_states

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
    def scheduled_states(self) -> tuple[AircraftState, ...]:
        """Return future deterministic motion anchors in activation order."""

        return self._scheduled_states

    @property
    def current_state(self) -> AircraftState | None:
        """Return piecewise constant-motion state at current simulation time."""

        current_time_utc = self._clock.current_time_utc
        motion_anchor = self._initial_state
        if current_time_utc < motion_anchor.timestamp_utc:
            return None
        for scheduled_state in self._scheduled_states:
            if scheduled_state.timestamp_utc > current_time_utc:
                break
            motion_anchor = scheduled_state

        elapsed_seconds = (current_time_utc - motion_anchor.timestamp_utc).total_seconds()
        if elapsed_seconds == 0.0:
            return motion_anchor

        heading_rad = radians(motion_anchor.heading_deg)
        distance_nm = knots_to_nm_per_second(motion_anchor.ground_speed_kt) * elapsed_seconds
        altitude_change_ft = (
            fpm_to_ft_per_second(motion_anchor.vertical_speed_fpm) * elapsed_seconds
        )

        return AircraftState(
            aircraft_id=motion_anchor.aircraft_id,
            timestamp_utc=current_time_utc,
            x_nm=motion_anchor.x_nm + distance_nm * sin(heading_rad),
            y_nm=motion_anchor.y_nm + distance_nm * cos(heading_rad),
            altitude_ft=motion_anchor.altitude_ft + altitude_change_ft,
            ground_speed_kt=motion_anchor.ground_speed_kt,
            heading_deg=motion_anchor.heading_deg,
            vertical_speed_fpm=motion_anchor.vertical_speed_fpm,
            source=motion_anchor.source,
            flight_phase=motion_anchor.flight_phase,
            emergency_status=motion_anchor.emergency_status,
            emergency_type=motion_anchor.emergency_type,
        )
