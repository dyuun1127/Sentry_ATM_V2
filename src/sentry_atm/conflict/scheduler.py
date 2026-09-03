"""Simulation-clock-driven rolling conflict assessment scheduler."""

from math import floor
from numbers import Real

from sentry_atm.conflict.run_service import ConflictAssessmentService
from sentry_atm.domain import ConflictAssessmentRun
from sentry_atm.domain.units import as_non_negative_float
from sentry_atm.domain.validation import require_identifier
from sentry_atm.simulation import SimulationClock, TrafficSnapshot

DEFAULT_CONFLICT_INTERVAL_SECONDS = 5.0
DEFAULT_ASSESSMENT_RUN_ID_PREFIX = "CONFLICT"


class RollingConflictScheduler:
    """Create at most one conflict assessment in each simulation-time interval."""

    __slots__ = (
        "_clock",
        "_interval_seconds",
        "_last_run",
        "_last_slot",
        "_observed_reset_count",
        "_run_id_prefix",
        "_service",
    )

    def __init__(
        self,
        *,
        clock: SimulationClock,
        service: ConflictAssessmentService,
        interval_seconds: Real = DEFAULT_CONFLICT_INTERVAL_SECONDS,
        run_id_prefix: str = DEFAULT_ASSESSMENT_RUN_ID_PREFIX,
    ) -> None:
        if not isinstance(clock, SimulationClock):
            raise TypeError("clock must be a SimulationClock")
        if not isinstance(service, ConflictAssessmentService):
            raise TypeError("service must be a ConflictAssessmentService")
        validated_interval = as_non_negative_float(
            interval_seconds,
            field_name="interval_seconds",
        )
        if validated_interval == 0.0:
            raise ValueError("interval_seconds must be greater than zero")

        self._clock = clock
        self._service = service
        self._interval_seconds = validated_interval
        self._run_id_prefix = require_identifier(
            run_id_prefix,
            field_name="run_id_prefix",
        )
        self._observed_reset_count = clock.reset_count
        self._last_slot: int | None = None
        self._last_run: ConflictAssessmentRun | None = None

    @property
    def clock(self) -> SimulationClock:
        return self._clock

    @property
    def service(self) -> ConflictAssessmentService:
        return self._service

    @property
    def interval_seconds(self) -> float:
        return self._interval_seconds

    @property
    def last_run(self) -> ConflictAssessmentRun | None:
        self._synchronize_reset()
        return self._last_run

    def run_if_due(
        self,
        snapshot: TrafficSnapshot,
    ) -> ConflictAssessmentRun | None:
        """Create the current slot's assessment, or return None when not due."""

        if not isinstance(snapshot, TrafficSnapshot):
            raise TypeError("snapshot must be a TrafficSnapshot")
        if snapshot.timestamp_utc != self._clock.current_time_utc:
            raise ValueError("snapshot timestamp must match the scheduler clock")

        self._synchronize_reset()
        if not self._clock.is_running:
            return None

        current_slot = floor(self._clock.elapsed_seconds / self._interval_seconds)
        if self._last_slot is not None and current_slot <= self._last_slot:
            return None

        assessment_run = self._service.run(
            snapshot,
            assessment_run_id=(f"{self._run_id_prefix}-{self._clock.tick_count:012d}"),
        )
        self._last_slot = current_slot
        self._last_run = assessment_run
        return assessment_run

    def _synchronize_reset(self) -> None:
        if self._clock.reset_count == self._observed_reset_count:
            return
        self._observed_reset_count = self._clock.reset_count
        self._last_slot = None
        self._last_run = None
