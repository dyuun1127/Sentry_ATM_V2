"""Explicit Domain↔SQLite row mapping functions."""

from sentry_atm.domain import AircraftMetadata, AircraftState
from sentry_atm.geo import rktu_local_to_geodetic
from sentry_atm.infrastructure.persistence.models import AircraftRow, AircraftStateRow


def aircraft_to_row(aircraft: AircraftMetadata) -> AircraftRow:
    if not isinstance(aircraft, AircraftMetadata):
        raise TypeError("aircraft must be AircraftMetadata")
    return AircraftRow(
        aircraft_id=aircraft.aircraft_id,
        aircraft_type=aircraft.aircraft_type.upper(),
        category=aircraft.category.value,
        callsign=aircraft.callsign,
        icao24=aircraft.icao24,
        performance_profile_id=aircraft.performance_class,
    )


def aircraft_from_row(row: AircraftRow) -> AircraftMetadata:
    if not isinstance(row, AircraftRow):
        raise TypeError("row must be AircraftRow")
    return AircraftMetadata(
        aircraft_id=row.aircraft_id,
        aircraft_type=row.aircraft_type,
        category=row.category,
        callsign=row.callsign,
        icao24=row.icao24,
        performance_class=row.performance_profile_id,
    )


def aircraft_state_to_row(state: AircraftState) -> AircraftStateRow:
    if not isinstance(state, AircraftState):
        raise TypeError("state must be AircraftState")
    geodetic = rktu_local_to_geodetic(x_nm=state.x_nm, y_nm=state.y_nm)
    return AircraftStateRow(
        aircraft_id=state.aircraft_id,
        timestamp_utc=state.timestamp_utc,
        x_nm=state.x_nm,
        y_nm=state.y_nm,
        latitude_deg=geodetic.latitude_deg,
        longitude_deg=geodetic.longitude_deg,
        altitude_ft=state.altitude_ft,
        ground_speed_kt=state.ground_speed_kt,
        heading_deg=state.heading_deg,
        vertical_speed_fpm=state.vertical_speed_fpm,
        source=state.source.value,
        flight_phase=state.flight_phase.value,
        emergency_status=state.emergency_status.value,
        emergency_type=state.emergency_type.value if state.emergency_type else None,
    )


def aircraft_state_from_row(row: AircraftStateRow) -> AircraftState:
    if not isinstance(row, AircraftStateRow):
        raise TypeError("row must be AircraftStateRow")
    return AircraftState(
        aircraft_id=row.aircraft_id,
        timestamp_utc=row.timestamp_utc,
        x_nm=row.x_nm,
        y_nm=row.y_nm,
        altitude_ft=row.altitude_ft,
        ground_speed_kt=row.ground_speed_kt,
        heading_deg=row.heading_deg,
        vertical_speed_fpm=row.vertical_speed_fpm,
        source=row.source,
        flight_phase=row.flight_phase,
        emergency_status=row.emergency_status,
        emergency_type=row.emergency_type,
    )
