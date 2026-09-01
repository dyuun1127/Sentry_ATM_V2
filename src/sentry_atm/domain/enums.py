"""Shared domain enumerations with stable serialization values."""

from enum import StrEnum


class DataSource(StrEnum):
    """Origin of an aircraft state or trajectory observation."""

    OPENSKY = "OPENSKY"
    SYNTHETIC = "SYNTHETIC"


class AircraftCategory(StrEnum):
    """Non-sensitive performance-oriented aircraft grouping."""

    AIRLINER = "AIRLINER"
    FAST_JET = "FAST_JET"
    TRANSPORT = "TRANSPORT"
    UNKNOWN = "UNKNOWN"


class FlightPhase(StrEnum):
    """Coarse flight phase used by the PoC domain."""

    UNKNOWN = "UNKNOWN"
    CLIMB = "CLIMB"
    LEVEL = "LEVEL"
    DESCENT = "DESCENT"
    APPROACH = "APPROACH"
    FINAL = "FINAL"


class EmergencyStatus(StrEnum):
    """Whether an aircraft has an active declared emergency."""

    NONE = "NONE"
    DECLARED = "DECLARED"


class EmergencyType(StrEnum):
    """Deliberately abstract emergency categories for simulation."""

    PRIORITY_RETURN = "PRIORITY_RETURN"
    AIRCRAFT_CONDITION = "AIRCRAFT_CONDITION"


class TrajectoryType(StrEnum):
    """Meaning of a trajectory in the 4DT lifecycle."""

    PLANNED = "PLANNED"
    ACTUAL = "ACTUAL"
    PREDICTED = "PREDICTED"


class PerformanceDataSource(StrEnum):
    """Provenance category for non-sensitive performance profiles."""

    SIMULATION_ASSUMPTION = "SIMULATION_ASSUMPTION"
    PUBLIC_REFERENCE = "PUBLIC_REFERENCE"
    OPENAP = "OPENAP"
    LICENSED_REFERENCE = "LICENSED_REFERENCE"


class FlightStatus(StrEnum):
    """Lifecycle state of a flight record."""

    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
