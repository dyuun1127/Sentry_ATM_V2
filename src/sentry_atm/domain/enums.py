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


class ConflictStatus(StrEnum):
    """Outcome of a predictive separation assessment."""

    SAFE = "SAFE"
    PREDICTED = "PREDICTED"


class RiskLevel(StrEnum):
    """Explainable severity band for one conflict risk assessment."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class RiskReasonCode(StrEnum):
    """Stable reason codes supporting a conflict risk decision."""

    NO_PREDICTED_CONFLICT = "NO_PREDICTED_CONFLICT"
    NEAR_SEPARATION_THRESHOLD = "NEAR_SEPARATION_THRESHOLD"
    PREDICTED_SEPARATION_LOSS = "PREDICTED_SEPARATION_LOSS"
    HORIZONTAL_THRESHOLD_BREACH = "HORIZONTAL_THRESHOLD_BREACH"
    VERTICAL_THRESHOLD_BREACH = "VERTICAL_THRESHOLD_BREACH"
    SHORT_TCPA = "SHORT_TCPA"
    IMMEDIATE_SEPARATION_LOSS = "IMMEDIATE_SEPARATION_LOSS"


class OperationalPriorityLevel(StrEnum):
    """Operational handling priority independent from conflict risk."""

    ROUTINE = "ROUTINE"
    ATTENTION = "ATTENTION"
    URGENT = "URGENT"
    EMERGENCY = "EMERGENCY"


class PriorityReasonCode(StrEnum):
    """Stable reason codes supporting an operational priority decision."""

    ROUTINE_OPERATION = "ROUTINE_OPERATION"
    ENTRY_CONFORMANCE_DEVIATION = "ENTRY_CONFORMANCE_DEVIATION"
    EMERGENCY_DECLARED = "EMERGENCY_DECLARED"
    AIRCRAFT_CONDITION = "AIRCRAFT_CONDITION"


class ExceptionKind(StrEnum):
    """Type-safe source category for one Exception Queue item."""

    CONFLICT_RISK = "CONFLICT_RISK"
    OPERATIONAL_PRIORITY = "OPERATIONAL_PRIORITY"


class ExceptionStatus(StrEnum):
    """Human-in-the-loop lifecycle state of an Exception item."""

    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"


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
