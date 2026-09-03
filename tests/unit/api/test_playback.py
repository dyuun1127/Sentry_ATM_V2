import pytest

from sentry_atm.api import (
    GoldenDemoPlaybackApiContract,
    GoldenDemoPlaybackContract,
    GoldenDemoPlaybackCue,
    GoldenDemoPlaybackCueType,
    InProcessGoldenDemoPlaybackApi,
    build_golden_demo_playback_contract,
)
from sentry_atm.scenario import GOLDEN_DEMO_START_UTC


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


def test_playback_api_generates_301_ordered_eight_aircraft_frames() -> None:
    api = InProcessGoldenDemoPlaybackApi()

    playback = api.get_playback()

    assert isinstance(api, GoldenDemoPlaybackApiContract)
    assert playback.frame_count == 301
    assert playback.aircraft_count == 8
    assert playback.frames[0].sequence_index == 0
    assert playback.frames[0].offset_seconds == 0.0
    assert playback.frames[0].timestamp_utc == GOLDEN_DEMO_START_UTC
    assert playback.frames[-1].sequence_index == 300
    assert playback.frames[-1].offset_seconds == 300.0
    assert tuple(item.aircraft_id for item in playback.frames[0].aircraft) == (
        "CIV-A01",
        "CIV-A02",
        "CIV-A03",
        "CIV-D01",
        "MIL-F01",
        "MIL-F02",
        "MIL-T01",
        "MIL-T02",
    )


def test_playback_frames_preserve_scheduled_motion_anchor_and_cues() -> None:
    playback = InProcessGoldenDemoPlaybackApi().get_playback()
    at_59 = playback.frames[59]
    at_60 = playback.frames[60]
    mil_f01_at_59 = next(item for item in at_59.aircraft if item.aircraft_id == "MIL-F01")
    mil_f01_at_60 = next(item for item in at_60.aircraft if item.aircraft_id == "MIL-F01")

    assert mil_f01_at_59.altitude_ft != 7_400.0
    assert mil_f01_at_60.altitude_ft == 7_400.0
    assert mil_f01_at_60.heading_deg == 180.0
    assert playback.frames[60].cue_ids == ("CUE-T060-DEVIATION",)
    assert playback.frames[70].cue_ids == ("CUE-T070-CONFLICT",)
    assert playback.frames[240].cue_ids == ("CUE-T240-EMERGENCY",)
    assert playback.frames[260].cue_ids == ("CUE-T260-RECOVERY",)


def test_playback_read_model_is_cached_and_json_deterministic() -> None:
    first_api = InProcessGoldenDemoPlaybackApi()
    second_api = InProcessGoldenDemoPlaybackApi()

    assert first_api.get_playback() is first_api.get_playback()
    assert first_api.get_playback() == second_api.get_playback()
    payload = first_api.get_playback().to_dict()
    assert payload["frame_count"] == 301
    assert payload["aircraft_count"] == 8
    assert payload["frames"][75]["cue_ids"] == ["CUE-T075-RECOMMENDATION"]


def test_playback_api_rejects_mismatched_scenario_and_non_one_second_contract() -> None:
    mismatch = _contract(scenario_id="OTHER-SCENARIO")
    with pytest.raises(ValueError, match="scenario IDs must match"):
        InProcessGoldenDemoPlaybackApi(contract=mismatch)

    half_second = _contract(
        scenario_id="RKTU_GOLDEN_DEMO_V1",
        frame_interval_seconds=0.5,
    )
    with pytest.raises(ValueError, match="exactly one-second"):
        InProcessGoldenDemoPlaybackApi(contract=half_second)
