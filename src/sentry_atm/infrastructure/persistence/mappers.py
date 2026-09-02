"""Explicit Domain↔SQLite row mapping functions."""

from json import dumps, loads

from sentry_atm.domain import (
    AircraftMetadata,
    AircraftPerformanceProfile,
    AircraftState,
    AircraftType,
    PredictionRun,
    Trajectory,
    TrajectoryPoint,
    TrajectoryType,
)
from sentry_atm.geo import rktu_local_to_geodetic
from sentry_atm.infrastructure.persistence.models import (
    AircraftPerformanceProfileRow,
    AircraftRow,
    AircraftStateRow,
    AircraftTypeRow,
    PredictionRunRow,
    TrajectoryPointRow,
    TrajectoryRow,
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


def prediction_run_to_row(prediction_run: PredictionRun) -> PredictionRunRow:
    if not isinstance(prediction_run, PredictionRun):
        raise TypeError("prediction_run must be PredictionRun")
    return PredictionRunRow(
        prediction_run_id=prediction_run.prediction_run_id,
        input_timestamp_utc=prediction_run.input_timestamp_utc,
        generated_at_utc=prediction_run.generated_at_utc,
        model_name=prediction_run.model_name,
        model_version=prediction_run.model_version,
        horizons_seconds_json=dumps(
            prediction_run.horizons_seconds,
            separators=(",", ":"),
        ),
        configuration_id=prediction_run.configuration_id,
    )


def prediction_run_from_row(
    row: PredictionRunRow,
    trajectories: tuple[Trajectory, ...],
) -> PredictionRun:
    if not isinstance(row, PredictionRunRow):
        raise TypeError("row must be PredictionRunRow")
    if not isinstance(trajectories, tuple) or not all(
        isinstance(trajectory, Trajectory) for trajectory in trajectories
    ):
        raise TypeError("trajectories must be a tuple of Trajectory instances")
    return PredictionRun(
        prediction_run_id=row.prediction_run_id,
        input_timestamp_utc=row.input_timestamp_utc,
        generated_at_utc=row.generated_at_utc,
        model_name=row.model_name,
        model_version=row.model_version,
        horizons_seconds=tuple(loads(row.horizons_seconds_json)),
        trajectories=trajectories,
        configuration_id=row.configuration_id,
    )


def trajectory_to_row(
    trajectory: Trajectory,
    *,
    prediction_run_id: str,
    sequence_index: int,
) -> TrajectoryRow:
    if not isinstance(trajectory, Trajectory):
        raise TypeError("trajectory must be Trajectory")
    if trajectory.trajectory_type is not TrajectoryType.PREDICTED:
        raise ValueError("prediction persistence only accepts PREDICTED trajectories")
    return TrajectoryRow(
        prediction_run_id=prediction_run_id,
        aircraft_id=trajectory.aircraft_id,
        sequence_index=sequence_index,
        trajectory_type=trajectory.trajectory_type.value,
    )


def trajectory_from_rows(
    row: TrajectoryRow,
    point_rows: tuple[TrajectoryPointRow, ...],
) -> Trajectory:
    if not isinstance(row, TrajectoryRow):
        raise TypeError("row must be TrajectoryRow")
    if not isinstance(point_rows, tuple) or not all(
        isinstance(point_row, TrajectoryPointRow) for point_row in point_rows
    ):
        raise TypeError("point_rows must be a tuple of TrajectoryPointRow instances")
    return Trajectory(
        aircraft_id=row.aircraft_id,
        trajectory_type=row.trajectory_type,
        points=tuple(trajectory_point_from_row(point_row) for point_row in point_rows),
    )


def trajectory_point_to_row(
    point: TrajectoryPoint,
    *,
    trajectory_id: int,
    sequence_index: int,
) -> TrajectoryPointRow:
    if not isinstance(point, TrajectoryPoint):
        raise TypeError("point must be TrajectoryPoint")
    return TrajectoryPointRow(
        trajectory_id=trajectory_id,
        sequence_index=sequence_index,
        timestamp_utc=point.timestamp_utc,
        x_nm=point.x_nm,
        y_nm=point.y_nm,
        altitude_ft=point.altitude_ft,
    )


def trajectory_point_from_row(row: TrajectoryPointRow) -> TrajectoryPoint:
    if not isinstance(row, TrajectoryPointRow):
        raise TypeError("row must be TrajectoryPointRow")
    return TrajectoryPoint(
        timestamp_utc=row.timestamp_utc,
        x_nm=row.x_nm,
        y_nm=row.y_nm,
        altitude_ft=row.altitude_ft,
    )
