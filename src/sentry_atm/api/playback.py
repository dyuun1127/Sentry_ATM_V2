"""Transport-neutral contract for the animated Golden Demo timeline."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from math import isfinite
from typing import Protocol, runtime_checkable

from sentry_atm.domain import AircraftState
from sentry_atm.domain.time_policy import to_utc
from sentry_atm.domain.validation import require_identifier
from sentry_atm.scenario import (
    GOLDEN_DEMO_SCENARIO_ID,
    ScenarioDefinition,
    build_golden_demo_scenario,
    build_scenario_simulation,
)


class GoldenDemoPlaybackCueType(StrEnum):
    """A presentation event anchored to deterministic simulation time."""

    PLAYBACK_STARTED = "PLAYBACK_STARTED"
    ENTRY_DEVIATION = "ENTRY_DEVIATION"
    CONFLICT_DETECTED = "CONFLICT_DETECTED"
    RECOMMENDATION_AVAILABLE = "RECOMMENDATION_AVAILABLE"
    POST_ACTION_REVALIDATION = "POST_ACTION_REVALIDATION"
    EMERGENCY_DECLARED = "EMERGENCY_DECLARED"
    RECOVERY_COMPLETE = "RECOVERY_COMPLETE"


@dataclass(frozen=True, slots=True)
class GoldenDemoPlaybackCue:
    """One ordered UI cue with an explicit pause and operator policy."""

    cue_id: str
    cue_type: GoldenDemoPlaybackCueType
    offset_seconds: float
    label: str
    auto_pause: bool = False
    requires_operator_action: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "cue_id",
            require_identifier(self.cue_id, field_name="cue_id"),
        )
        object.__setattr__(self, "cue_type", GoldenDemoPlaybackCueType(self.cue_type))
        if isinstance(self.offset_seconds, bool) or not isinstance(
            self.offset_seconds, (int, float)
        ):
            raise TypeError("offset_seconds must be a finite non-negative number")
        offset_seconds = float(self.offset_seconds)
        if not isfinite(offset_seconds) or offset_seconds < 0.0:
            raise ValueError("offset_seconds must be a finite non-negative number")
        object.__setattr__(self, "offset_seconds", offset_seconds)
        if not isinstance(self.label, str) or not self.label.strip():
            raise ValueError("label must be a non-empty string")
        object.__setattr__(self, "label", self.label.strip())
        if type(self.auto_pause) is not bool:
            raise TypeError("auto_pause must be bool")
        if type(self.requires_operator_action) is not bool:
            raise TypeError("requires_operator_action must be bool")
        if self.requires_operator_action and not self.auto_pause:
            raise ValueError("operator action cues must auto-pause")

    def to_dict(self) -> dict[str, object]:
        return {
            "cue_id": self.cue_id,
            "cue_type": self.cue_type.value,
            "offset_seconds": self.offset_seconds,
            "label": self.label,
            "auto_pause": self.auto_pause,
            "requires_operator_action": self.requires_operator_action,
        }


@dataclass(frozen=True, slots=True)
class GoldenDemoPlaybackContract:
    """Stable playback policy consumed by the future Frame API and browser."""

    scenario_id: str
    duration_seconds: float
    frame_interval_seconds: float
    render_fps: int
    default_rate: float
    supported_rates: tuple[float, ...]
    cues: tuple[GoldenDemoPlaybackCue, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "scenario_id",
            require_identifier(self.scenario_id, field_name="scenario_id"),
        )
        duration = _positive_number(self.duration_seconds, field_name="duration_seconds")
        interval = _positive_number(
            self.frame_interval_seconds,
            field_name="frame_interval_seconds",
        )
        if interval > duration:
            raise ValueError("frame_interval_seconds must not exceed duration_seconds")
        object.__setattr__(self, "duration_seconds", duration)
        object.__setattr__(self, "frame_interval_seconds", interval)
        if type(self.render_fps) is not int or not 1 <= self.render_fps <= 120:
            raise ValueError("render_fps must be an integer from 1 through 120")

        rates = tuple(
            _positive_number(rate, field_name="supported_rates") for rate in self.supported_rates
        )
        if not rates:
            raise ValueError("supported_rates must not be empty")
        if rates != tuple(sorted(set(rates))):
            raise ValueError("supported_rates must be unique and ascending")
        default_rate = _positive_number(self.default_rate, field_name="default_rate")
        if default_rate not in rates:
            raise ValueError("default_rate must be one of supported_rates")
        object.__setattr__(self, "supported_rates", rates)
        object.__setattr__(self, "default_rate", default_rate)

        cues = tuple(self.cues)
        if not cues or not all(isinstance(cue, GoldenDemoPlaybackCue) for cue in cues):
            raise TypeError("cues must contain GoldenDemoPlaybackCue instances")
        cue_ids = tuple(cue.cue_id for cue in cues)
        if len(set(cue_ids)) != len(cue_ids):
            raise ValueError("cue IDs must be unique")
        offsets = tuple(cue.offset_seconds for cue in cues)
        if offsets != tuple(sorted(offsets)):
            raise ValueError("cues must be ordered by offset_seconds")
        if offsets[0] != 0.0:
            raise ValueError("the first playback cue must start at T+0")
        if offsets[-1] > duration:
            raise ValueError("playback cues must not exceed duration_seconds")
        object.__setattr__(self, "cues", cues)

    @property
    def auto_pause_offsets(self) -> tuple[float, ...]:
        return tuple(cue.offset_seconds for cue in self.cues if cue.auto_pause)

    def to_dict(self) -> dict[str, object]:
        return {
            "scenario_id": self.scenario_id,
            "duration_seconds": self.duration_seconds,
            "frame_interval_seconds": self.frame_interval_seconds,
            "render_fps": self.render_fps,
            "default_rate": self.default_rate,
            "supported_rates": list(self.supported_rates),
            "cues": [cue.to_dict() for cue in self.cues],
        }


def build_golden_demo_playback_contract() -> GoldenDemoPlaybackContract:
    """Return the canonical T+0 through T+300 animated presentation contract."""

    return GoldenDemoPlaybackContract(
        scenario_id=GOLDEN_DEMO_SCENARIO_ID,
        duration_seconds=300.0,
        frame_interval_seconds=1.0,
        render_fps=60,
        default_rate=1.0,
        supported_rates=(1.0, 2.0, 4.0),
        cues=(
            GoldenDemoPlaybackCue(
                cue_id="CUE-T000-START",
                cue_type=GoldenDemoPlaybackCueType.PLAYBACK_STARTED,
                offset_seconds=0.0,
                label="8대 Traffic 감시 시작",
            ),
            GoldenDemoPlaybackCue(
                cue_id="CUE-T060-DEVIATION",
                cue_type=GoldenDemoPlaybackCueType.ENTRY_DEVIATION,
                offset_seconds=60.0,
                label="MIL-F01 진입 편차",
            ),
            GoldenDemoPlaybackCue(
                cue_id="CUE-T070-CONFLICT",
                cue_type=GoldenDemoPlaybackCueType.CONFLICT_DETECTED,
                offset_seconds=70.0,
                label="CIV-A02 / MIL-F01 미래 충돌",
                auto_pause=True,
            ),
            GoldenDemoPlaybackCue(
                cue_id="CUE-T075-RECOMMENDATION",
                cue_type=GoldenDemoPlaybackCueType.RECOMMENDATION_AVAILABLE,
                offset_seconds=75.0,
                label="CAND-A~E 검증 및 관제사 결정",
                auto_pause=True,
                requires_operator_action=True,
            ),
            GoldenDemoPlaybackCue(
                cue_id="CUE-T090-REVALIDATION",
                cue_type=GoldenDemoPlaybackCueType.POST_ACTION_REVALIDATION,
                offset_seconds=90.0,
                label="승인 기동 적용 후 재검증",
                auto_pause=True,
            ),
            GoldenDemoPlaybackCue(
                cue_id="CUE-T240-EMERGENCY",
                cue_type=GoldenDemoPlaybackCueType.EMERGENCY_DECLARED,
                offset_seconds=240.0,
                label="MIL-T01 비상 우선 복귀",
                auto_pause=True,
                requires_operator_action=True,
            ),
            GoldenDemoPlaybackCue(
                cue_id="CUE-T260-RECOVERY",
                cue_type=GoldenDemoPlaybackCueType.RECOVERY_COMPLETE,
                offset_seconds=260.0,
                label="안전 복귀 및 정상 흐름 회복",
                auto_pause=True,
            ),
        ),
    )


@dataclass(frozen=True, slots=True)
class GoldenDemoPlaybackAircraftFrame:
    """One browser-ready Aircraft state at an authoritative simulation second."""

    aircraft_id: str
    category: str
    x_nm: float
    y_nm: float
    altitude_ft: float
    ground_speed_kt: float
    heading_deg: float
    vertical_speed_fpm: float
    flight_phase: str
    emergency_status: str
    emergency_type: str | None

    @classmethod
    def from_state(cls, state: AircraftState, *, category: str):
        if not isinstance(state, AircraftState):
            raise TypeError("state must be an AircraftState")
        if not isinstance(category, str) or not category.strip():
            raise ValueError("category must be a non-empty string")
        return cls(
            aircraft_id=state.aircraft_id,
            category=category.strip(),
            x_nm=state.x_nm,
            y_nm=state.y_nm,
            altitude_ft=state.altitude_ft,
            ground_speed_kt=state.ground_speed_kt,
            heading_deg=state.heading_deg,
            vertical_speed_fpm=state.vertical_speed_fpm,
            flight_phase=state.flight_phase.value,
            emergency_status=state.emergency_status.value,
            emergency_type=state.emergency_type.value if state.emergency_type is not None else None,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "aircraft_id": self.aircraft_id,
            "category": self.category,
            "x_nm": self.x_nm,
            "y_nm": self.y_nm,
            "altitude_ft": self.altitude_ft,
            "ground_speed_kt": self.ground_speed_kt,
            "heading_deg": self.heading_deg,
            "vertical_speed_fpm": self.vertical_speed_fpm,
            "flight_phase": self.flight_phase,
            "emergency_status": self.emergency_status,
            "emergency_type": self.emergency_type,
        }


@dataclass(frozen=True, slots=True)
class GoldenDemoPlaybackFrame:
    """All ordered Aircraft states rendered at one simulation offset."""

    sequence_index: int
    offset_seconds: float
    timestamp_utc: datetime
    aircraft: tuple[GoldenDemoPlaybackAircraftFrame, ...]
    cue_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if type(self.sequence_index) is not int or self.sequence_index < 0:
            raise ValueError("sequence_index must be a non-negative integer")
        offset = _non_negative_number(self.offset_seconds, field_name="offset_seconds")
        object.__setattr__(self, "offset_seconds", offset)
        object.__setattr__(
            self,
            "timestamp_utc",
            to_utc(self.timestamp_utc, field_name="timestamp_utc"),
        )
        aircraft = tuple(self.aircraft)
        if not aircraft or not all(
            isinstance(item, GoldenDemoPlaybackAircraftFrame) for item in aircraft
        ):
            raise TypeError("aircraft must contain playback Aircraft frames")
        aircraft_ids = tuple(item.aircraft_id for item in aircraft)
        if len(set(aircraft_ids)) != len(aircraft_ids):
            raise ValueError("playback frame Aircraft IDs must be unique")
        object.__setattr__(self, "aircraft", aircraft)
        cue_ids = tuple(
            require_identifier(cue_id, field_name="cue_id") for cue_id in self.cue_ids
        )
        if len(set(cue_ids)) != len(cue_ids):
            raise ValueError("playback frame cue IDs must be unique")
        object.__setattr__(self, "cue_ids", cue_ids)

    def to_dict(self) -> dict[str, object]:
        return {
            "sequence_index": self.sequence_index,
            "offset_seconds": self.offset_seconds,
            "timestamp_utc": _utc_text(self.timestamp_utc),
            "aircraft": [item.to_dict() for item in self.aircraft],
            "cue_ids": list(self.cue_ids),
        }


@dataclass(frozen=True, slots=True)
class GoldenDemoPlaybackReadModel:
    """Self-contained immutable manifest fetched once by the animated UI."""

    contract: GoldenDemoPlaybackContract
    frames: tuple[GoldenDemoPlaybackFrame, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.contract, GoldenDemoPlaybackContract):
            raise TypeError("contract must be a GoldenDemoPlaybackContract")
        frames = tuple(self.frames)
        if not frames or not all(isinstance(frame, GoldenDemoPlaybackFrame) for frame in frames):
            raise TypeError("frames must contain GoldenDemoPlaybackFrame instances")
        expected_indices = tuple(range(len(frames)))
        if tuple(frame.sequence_index for frame in frames) != expected_indices:
            raise ValueError("playback frame sequence indices must be contiguous from zero")
        expected_offsets = tuple(
            index * self.contract.frame_interval_seconds for index in expected_indices
        )
        if tuple(frame.offset_seconds for frame in frames) != expected_offsets:
            raise ValueError("playback frame offsets must match the configured interval")
        if frames[-1].offset_seconds != self.contract.duration_seconds:
            raise ValueError("playback frames must include the configured duration endpoint")
        object.__setattr__(self, "frames", frames)

    @property
    def frame_count(self) -> int:
        return len(self.frames)

    @property
    def aircraft_count(self) -> int:
        return len(self.frames[0].aircraft)

    def to_dict(self) -> dict[str, object]:
        return {
            "contract": self.contract.to_dict(),
            "frame_count": self.frame_count,
            "aircraft_count": self.aircraft_count,
            "frames": [frame.to_dict() for frame in self.frames],
        }


@runtime_checkable
class GoldenDemoPlaybackApiContract(Protocol):
    """Synchronous read-only animated playback boundary."""

    def get_playback(self) -> GoldenDemoPlaybackReadModel: ...


class InProcessGoldenDemoPlaybackApi:
    """Generate playback on an isolated Simulation and return one cached manifest."""

    __slots__ = ("_read_model",)

    def __init__(
        self,
        definition: ScenarioDefinition | None = None,
        contract: GoldenDemoPlaybackContract | None = None,
    ) -> None:
        resolved_definition = definition or build_golden_demo_scenario()
        resolved_contract = contract or build_golden_demo_playback_contract()
        if not isinstance(resolved_definition, ScenarioDefinition):
            raise TypeError("definition must be a ScenarioDefinition")
        if not isinstance(resolved_contract, GoldenDemoPlaybackContract):
            raise TypeError("contract must be a GoldenDemoPlaybackContract")
        if resolved_definition.scenario_id != resolved_contract.scenario_id:
            raise ValueError("definition and playback contract scenario IDs must match")
        if resolved_contract.frame_interval_seconds != 1.0:
            raise ValueError("Phase 17-B supports exactly one-second Simulation frames")
        self._read_model = _generate_playback(resolved_definition, resolved_contract)

    def get_playback(self) -> GoldenDemoPlaybackReadModel:
        return self._read_model


def _generate_playback(
    definition: ScenarioDefinition,
    contract: GoldenDemoPlaybackContract,
) -> GoldenDemoPlaybackReadModel:
    simulation = build_scenario_simulation(definition)
    categories = {item.aircraft_id: item.metadata.category.value for item in definition.aircraft}
    cues_by_offset: dict[float, list[str]] = {}
    for cue in contract.cues:
        cues_by_offset.setdefault(cue.offset_seconds, []).append(cue.cue_id)

    total_steps = int(contract.duration_seconds / contract.frame_interval_seconds)
    frames: list[GoldenDemoPlaybackFrame] = []
    for sequence_index in range(total_steps + 1):
        if sequence_index == 0:
            snapshot = simulation.engine.snapshot()
            simulation.clock.play()
        else:
            snapshot = simulation.engine.tick()
        offset_seconds = sequence_index * contract.frame_interval_seconds
        frames.append(
            GoldenDemoPlaybackFrame(
                sequence_index=sequence_index,
                offset_seconds=offset_seconds,
                timestamp_utc=snapshot.timestamp_utc,
                aircraft=tuple(
                    GoldenDemoPlaybackAircraftFrame.from_state(
                        state,
                        category=categories[state.aircraft_id],
                    )
                    for state in snapshot.states
                ),
                cue_ids=tuple(cues_by_offset.get(offset_seconds, ())),
            )
        )
    return GoldenDemoPlaybackReadModel(contract=contract, frames=tuple(frames))


def _positive_number(value: float, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be a finite positive number")
    result = float(value)
    if not isfinite(result) or result <= 0.0:
        raise ValueError(f"{field_name} must be a finite positive number")
    return result


def _non_negative_number(value: float, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be a finite non-negative number")
    result = float(value)
    if not isfinite(result) or result < 0.0:
        raise ValueError(f"{field_name} must be a finite non-negative number")
    return result


def _utc_text(value: datetime) -> str:
    return to_utc(value).isoformat(timespec="microseconds").replace("+00:00", "Z")
