"""Explicit Domain↔SQLite row mapping functions."""

from sentry_atm.domain import (
    AircraftMetadata,
    AircraftPerformanceProfile,
    AircraftState,
    AircraftType,
)
from sentry_atm.geo import rktu_local_to_geodetic
from sentry_atm.infrastructure.persistence.models import (
    AircraftPerformanceProfileRow,
    AircraftRow,
    AircraftStateRow,
    AircraftTypeRow,
)


def aircraft_type_to_row(aircraft_type: AircraftType) -> AircraftTypeRow:
    if not isinstance(aircraft_type, AircraftType):
        raise TypeError("aircraft_type must be AircraftType")
    return AircraftTypeRow(
        type_code=aircraft_type.type_code,
        category=aircraft_type.category.value,
        manufacturer=aircraft_type.manufacturer,
        model=aircraft_type.model,
    )


def aircraft_type_from_row(row: AircraftTypeRow) -> AircraftType:
    if not isinstance(row, AircraftTypeRow):
        raise TypeError("row must be AircraftTypeRow")
    return AircraftType(
        type_code=row.type_code,
        category=row.category,
        manufacturer=row.manufacturer,
        model=row.model,
    )


def performance_profile_to_row(
    profile: AircraftPerformanceProfile,
) -> AircraftPerformanceProfileRow:
    if not isinstance(profile, AircraftPerformanceProfile):
        raise TypeError("profile must be AircraftPerformanceProfile")
    return AircraftPerformanceProfileRow(
        profile_id=profile.profile_id,
        category=profile.category.value,
        source=profile.source.value,
        source_reference=profile.source_reference,
        min_speed_kt=profile.min_speed_kt,
        max_speed_kt=profile.max_speed_kt,
        max_climb_rate_fpm=profile.max_climb_rate_fpm,
        max_descent_rate_fpm=profile.max_descent_rate_fpm,
        max_turn_rate_deg_per_second=profile.max_turn_rate_deg_per_second,
        ceiling_ft=profile.ceiling_ft,
        aircraft_type_code=profile.aircraft_type_code,
    )


def performance_profile_from_row(
    row: AircraftPerformanceProfileRow,
) -> AircraftPerformanceProfile:
    if not isinstance(row, AircraftPerformanceProfileRow):
        raise TypeError("row must be AircraftPerformanceProfileRow")
    return AircraftPerformanceProfile(
        profile_id=row.profile_id,
        category=row.category,
        source=row.source,
        source_reference=row.source_reference,
        min_speed_kt=row.min_speed_kt,
        max_speed_kt=row.max_speed_kt,
        max_climb_rate_fpm=row.max_climb_rate_fpm,
        max_descent_rate_fpm=row.max_descent_rate_fpm,
        max_turn_rate_deg_per_second=row.max_turn_rate_deg_per_second,
        ceiling_ft=row.ceiling_ft,
        aircraft_type_code=row.aircraft_type_code,
    )


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
