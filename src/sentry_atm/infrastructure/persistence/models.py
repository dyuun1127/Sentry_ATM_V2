"""SQLAlchemy table mappings for the initial SQLite schema."""

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    UniqueConstraint,
)
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from sentry_atm.domain.time_policy import to_utc

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class UTCDateTime(TypeDecorator[datetime]):
    """Store aware UTC datetimes as fixed-width ISO-8601 text in SQLite."""

    impl = String(27)
    cache_ok = True

    def process_bind_param(
        self,
        value: datetime | None,
        dialect: Dialect,
    ) -> str | None:
        del dialect
        if value is None:
            return None
        return to_utc(value).isoformat(timespec="microseconds").replace("+00:00", "Z")

    def process_result_value(
        self,
        value: str | None,
        dialect: Dialect,
    ) -> datetime | None:
        del dialect
        if value is None:
            return None
        return to_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class AircraftTypeRow(Base):
    __tablename__ = "aircraft_type"
    __table_args__ = (
        CheckConstraint(
            "category IN ('AIRLINER', 'FAST_JET', 'TRANSPORT', 'UNKNOWN')",
            name="category_value",
        ),
    )

    type_code: Mapped[str] = mapped_column(String(32), primary_key=True)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    manufacturer: Mapped[str | None] = mapped_column(String(128))
    model: Mapped[str | None] = mapped_column(String(128))


class AircraftPerformanceProfileRow(Base):
    __tablename__ = "aircraft_performance_profile"
    __table_args__ = (
        CheckConstraint(
            "category IN ('AIRLINER', 'FAST_JET', 'TRANSPORT', 'UNKNOWN')",
            name="category_value",
        ),
        CheckConstraint(
            "source IN ('SIMULATION_ASSUMPTION', 'PUBLIC_REFERENCE', "
            "'OPENAP', 'LICENSED_REFERENCE')",
            name="source_value",
        ),
        CheckConstraint("min_speed_kt >= 0", name="min_speed_non_negative"),
        CheckConstraint("max_speed_kt > 0", name="max_speed_positive"),
        CheckConstraint("min_speed_kt <= max_speed_kt", name="speed_envelope"),
        CheckConstraint("max_climb_rate_fpm > 0", name="climb_rate_positive"),
        CheckConstraint("max_descent_rate_fpm > 0", name="descent_rate_positive"),
        CheckConstraint("max_turn_rate_deg_per_second > 0", name="turn_rate_positive"),
        CheckConstraint("ceiling_ft > 0", name="ceiling_positive"),
    )

    profile_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    source_reference: Mapped[str] = mapped_column(String(256), nullable=False)
    min_speed_kt: Mapped[float] = mapped_column(Float, nullable=False)
    max_speed_kt: Mapped[float] = mapped_column(Float, nullable=False)
    max_climb_rate_fpm: Mapped[float] = mapped_column(Float, nullable=False)
    max_descent_rate_fpm: Mapped[float] = mapped_column(Float, nullable=False)
    max_turn_rate_deg_per_second: Mapped[float] = mapped_column(Float, nullable=False)
    ceiling_ft: Mapped[float] = mapped_column(Float, nullable=False)
    aircraft_type_code: Mapped[str | None] = mapped_column(
        ForeignKey("aircraft_type.type_code"),
    )


class AircraftRow(Base):
    __tablename__ = "aircraft"
    __table_args__ = (
        CheckConstraint(
            "category IN ('AIRLINER', 'FAST_JET', 'TRANSPORT', 'UNKNOWN')",
            name="category_value",
        ),
    )

    aircraft_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    aircraft_type: Mapped[str] = mapped_column(
        ForeignKey("aircraft_type.type_code"),
        nullable=False,
    )
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    callsign: Mapped[str | None] = mapped_column(String(32))
    icao24: Mapped[str | None] = mapped_column(String(6), unique=True)
    performance_profile_id: Mapped[str | None] = mapped_column(
        ForeignKey("aircraft_performance_profile.profile_id"),
    )


class AircraftStateRow(Base):
    __tablename__ = "aircraft_state"
    __table_args__ = (
        UniqueConstraint(
            "aircraft_id",
            "timestamp_utc",
            "source",
            name="uq_aircraft_state_observation",
        ),
        CheckConstraint("ground_speed_kt >= 0", name="ground_speed_non_negative"),
        CheckConstraint("heading_deg >= 0 AND heading_deg < 360", name="heading_range"),
        CheckConstraint("source IN ('OPENSKY', 'SYNTHETIC')", name="source_value"),
        CheckConstraint(
            "flight_phase IN ('UNKNOWN', 'CLIMB', 'LEVEL', 'DESCENT', 'APPROACH', 'FINAL')",
            name="flight_phase_value",
        ),
        CheckConstraint(
            "emergency_status IN ('NONE', 'DECLARED')",
            name="emergency_status_value",
        ),
        CheckConstraint(
            "emergency_type IS NULL OR emergency_type IN ('PRIORITY_RETURN', 'AIRCRAFT_CONDITION')",
            name="emergency_type_value",
        ),
        CheckConstraint(
            "(emergency_status = 'NONE' AND emergency_type IS NULL) OR "
            "(emergency_status = 'DECLARED' AND emergency_type IS NOT NULL)",
            name="emergency_consistency",
        ),
        CheckConstraint(
            "latitude_deg >= -90 AND latitude_deg <= 90",
            name="latitude_range",
        ),
        CheckConstraint(
            "longitude_deg >= -180 AND longitude_deg <= 180",
            name="longitude_range",
        ),
        Index(
            "ix_aircraft_state_aircraft_time",
            "aircraft_id",
            "timestamp_utc",
        ),
    )

    state_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    aircraft_id: Mapped[str] = mapped_column(
        ForeignKey("aircraft.aircraft_id"),
        nullable=False,
    )
    timestamp_utc: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    x_nm: Mapped[float] = mapped_column(Float, nullable=False)
    y_nm: Mapped[float] = mapped_column(Float, nullable=False)
    latitude_deg: Mapped[float] = mapped_column(Float, nullable=False)
    longitude_deg: Mapped[float] = mapped_column(Float, nullable=False)
    altitude_ft: Mapped[float] = mapped_column(Float, nullable=False)
    ground_speed_kt: Mapped[float] = mapped_column(Float, nullable=False)
    heading_deg: Mapped[float] = mapped_column(Float, nullable=False)
    vertical_speed_fpm: Mapped[float] = mapped_column(Float, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    flight_phase: Mapped[str] = mapped_column(String(32), nullable=False)
    emergency_status: Mapped[str] = mapped_column(String(32), nullable=False)
    emergency_type: Mapped[str | None] = mapped_column(String(32))


class PredictionRunRow(Base):
    __tablename__ = "prediction_run"

    prediction_run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    input_timestamp_utc: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    generated_at_utc: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    model_name: Mapped[str] = mapped_column(String(64), nullable=False)
    model_version: Mapped[str] = mapped_column(String(32), nullable=False)
    horizons_seconds_json: Mapped[str] = mapped_column(String(256), nullable=False)
    configuration_id: Mapped[str | None] = mapped_column(String(64))


class TrajectoryRow(Base):
    __tablename__ = "trajectory"
    __table_args__ = (
        UniqueConstraint(
            "prediction_run_id",
            "aircraft_id",
            name="uq_trajectory_run_aircraft",
        ),
        UniqueConstraint(
            "prediction_run_id",
            "sequence_index",
            name="uq_trajectory_run_sequence",
        ),
        CheckConstraint("sequence_index >= 0", name="sequence_non_negative"),
        CheckConstraint("trajectory_type = 'PREDICTED'", name="predicted_type"),
        Index(
            "ix_trajectory_prediction_run_sequence",
            "prediction_run_id",
            "sequence_index",
        ),
    )

    trajectory_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    prediction_run_id: Mapped[str] = mapped_column(
        ForeignKey("prediction_run.prediction_run_id", ondelete="CASCADE"),
        nullable=False,
    )
    aircraft_id: Mapped[str] = mapped_column(
        ForeignKey("aircraft.aircraft_id"),
        nullable=False,
    )
    sequence_index: Mapped[int] = mapped_column(Integer, nullable=False)
    trajectory_type: Mapped[str] = mapped_column(String(32), nullable=False)


class TrajectoryPointRow(Base):
    __tablename__ = "trajectory_point"
    __table_args__ = (
        UniqueConstraint(
            "trajectory_id",
            "sequence_index",
            name="uq_trajectory_point_sequence",
        ),
        CheckConstraint("sequence_index >= 0", name="sequence_non_negative"),
        Index(
            "ix_trajectory_point_trajectory_sequence",
            "trajectory_id",
            "sequence_index",
        ),
    )

    trajectory_point_id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )
    trajectory_id: Mapped[int] = mapped_column(
        ForeignKey("trajectory.trajectory_id", ondelete="CASCADE"),
        nullable=False,
    )
    sequence_index: Mapped[int] = mapped_column(Integer, nullable=False)
    timestamp_utc: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    x_nm: Mapped[float] = mapped_column(Float, nullable=False)
    y_nm: Mapped[float] = mapped_column(Float, nullable=False)
    altitude_ft: Mapped[float] = mapped_column(Float, nullable=False)
