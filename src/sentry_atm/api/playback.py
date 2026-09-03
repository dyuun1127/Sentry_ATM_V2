"""Transport-neutral contract for the animated Golden Demo timeline."""

from dataclasses import dataclass
from enum import StrEnum
from math import isfinite

from sentry_atm.domain.validation import require_identifier
from sentry_atm.scenario import GOLDEN_DEMO_SCENARIO_ID


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


def _positive_number(value: float, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be a finite positive number")
    result = float(value)
    if not isfinite(result) or result <= 0.0:
        raise ValueError(f"{field_name} must be a finite positive number")
    return result
