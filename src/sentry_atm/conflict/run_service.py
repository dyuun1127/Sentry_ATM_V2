"""Build one conflict assessment run from a traffic snapshot."""

from math import cos, radians, sin

from sentry_atm.conflict.detector import PairwiseConflictDetector
from sentry_atm.domain import AircraftState, ConflictAssessmentRun
from sentry_atm.domain.units import fpm_to_ft_per_second, knots_to_nm_per_second
from sentry_atm.simulation import TrafficSnapshot


class ConflictAssessmentService:
    """Align active states to Snapshot time and assess every unique pair."""

    __slots__ = ("_detector",)

    def __init__(self, detector: PairwiseConflictDetector) -> None:
        if not isinstance(detector, PairwiseConflictDetector):
            raise TypeError("detector must be a PairwiseConflictDetector")
        self._detector = detector

    @property
    def detector(self) -> PairwiseConflictDetector:
        """Return the injected Pairwise Detector."""

        return self._detector

    def run(
        self,
        snapshot: TrafficSnapshot,
        *,
        assessment_run_id: str,
    ) -> ConflictAssessmentRun:
        """Return an immutable assessment run anchored to Snapshot UTC."""

        if not isinstance(snapshot, TrafficSnapshot):
            raise TypeError("snapshot must be a TrafficSnapshot")
        aligned_states = tuple(
            self._align_state_to_snapshot(state, snapshot) for state in snapshot.states
        )
        return ConflictAssessmentRun(
            assessment_run_id=assessment_run_id,
            input_timestamp_utc=snapshot.timestamp_utc,
            rule_profile_id=self._detector.rule_profile.profile_id,
            horizon_seconds=self._detector.calculator.horizon_seconds,
            assessments=self._detector.assess(aligned_states),
        )

    @staticmethod
    def _align_state_to_snapshot(
        state: AircraftState,
        snapshot: TrafficSnapshot,
    ) -> AircraftState:
        elapsed_seconds = (snapshot.timestamp_utc - state.timestamp_utc).total_seconds()
        if elapsed_seconds < 0.0:
            raise ValueError("snapshot states must not be newer than the snapshot timestamp")
        if elapsed_seconds == 0.0:
            return state

        heading_rad = radians(state.heading_deg)
        distance_nm = knots_to_nm_per_second(state.ground_speed_kt) * elapsed_seconds
        altitude_change_ft = fpm_to_ft_per_second(state.vertical_speed_fpm) * elapsed_seconds
        return AircraftState(
            aircraft_id=state.aircraft_id,
            timestamp_utc=snapshot.timestamp_utc,
            x_nm=state.x_nm + distance_nm * sin(heading_rad),
            y_nm=state.y_nm + distance_nm * cos(heading_rad),
            altitude_ft=state.altitude_ft + altitude_change_ft,
            ground_speed_kt=state.ground_speed_kt,
            heading_deg=state.heading_deg,
            vertical_speed_fpm=state.vertical_speed_fpm,
            source=state.source,
            flight_phase=state.flight_phase,
            emergency_status=state.emergency_status,
            emergency_type=state.emergency_type,
        )
