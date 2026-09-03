import pytest

from sentry_atm.api import (
    GoldenDemoPlaybackContract,
    GoldenDemoPlaybackCue,
    GoldenDemoPlaybackCueType,
    build_golden_demo_playback_contract,
)


def _cue(**overrides) -> GoldenDemoPlaybackCue:
    values = {
        "cue_id": "CUE-TEST",
        "cue_type": GoldenDemoPlaybackCueType.PLAYBACK_STARTED,
        "offset_seconds": 0.0,
        "label": "Test cue",
    }
    values.update(overrides)
    return GoldenDemoPlaybackCue(**values)


def _contract(**overrides) -> GoldenDemoPlaybackContract:
    values = {
        "scenario_id": "SCENARIO-TEST",
        "duration_seconds": 300.0,
        "frame_interval_seconds": 1.0,
        "render_fps": 60,
        "default_rate": 1.0,
        "supported_rates": (1.0, 2.0, 4.0),
        "cues": (_cue(),),
    }
    values.update(overrides)
    return GoldenDemoPlaybackContract(**values)


def test_canonical_contract_defines_continuous_timeline_and_pause_policy() -> None:
    contract = build_golden_demo_playback_contract()

    assert contract.duration_seconds == 300.0
    assert contract.frame_interval_seconds == 1.0
    assert contract.render_fps == 60
    assert contract.supported_rates == (1.0, 2.0, 4.0)
    assert tuple(cue.offset_seconds for cue in contract.cues) == (
        0.0,
        60.0,
        70.0,
        75.0,
        90.0,
        240.0,
        260.0,
    )
    assert contract.auto_pause_offsets == (70.0, 75.0, 90.0, 240.0, 260.0)


def test_only_operator_boundaries_require_action() -> None:
    contract = build_golden_demo_playback_contract()
    action_cues = tuple(cue for cue in contract.cues if cue.requires_operator_action)

    assert tuple(cue.cue_type for cue in action_cues) == (
        GoldenDemoPlaybackCueType.RECOMMENDATION_AVAILABLE,
        GoldenDemoPlaybackCueType.EMERGENCY_DECLARED,
    )
    assert all(cue.auto_pause for cue in action_cues)


def test_contract_is_json_ready_and_deterministic() -> None:
    first = build_golden_demo_playback_contract().to_dict()
    second = build_golden_demo_playback_contract().to_dict()

    assert first == second
    assert first["default_rate"] == 1.0
    assert first["supported_rates"] == [1.0, 2.0, 4.0]
    assert first["cues"][2] == {
        "cue_id": "CUE-T070-CONFLICT",
        "cue_type": "CONFLICT_DETECTED",
        "offset_seconds": 70.0,
        "label": "CIV-A02 / MIL-F01 미래 충돌",
        "auto_pause": True,
        "requires_operator_action": False,
    }


def test_operator_action_cue_must_pause() -> None:
    with pytest.raises(ValueError, match="must auto-pause"):
        _cue(requires_operator_action=True)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"supported_rates": (2.0, 1.0)}, "unique and ascending"),
        ({"default_rate": 3.0}, "one of supported_rates"),
        ({"render_fps": 0}, "1 through 120"),
        ({"frame_interval_seconds": 301.0}, "must not exceed"),
        ({"cues": (_cue(offset_seconds=1.0),)}, r"start at T\+0"),
        (
            {"cues": (_cue(), _cue(cue_id="CUE-LATE", offset_seconds=301.0))},
            "must not exceed",
        ),
    ],
)
def test_contract_rejects_invalid_playback_policy(overrides, message) -> None:
    with pytest.raises((TypeError, ValueError), match=message):
        _contract(**overrides)
