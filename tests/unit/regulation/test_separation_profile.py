"""규정 기반 분리 프로파일 검증.

PoC 는 수평 5NM 을 `ASM-018 PROVISIONAL POC ASSUMPTION` 으로 두었다. 이 프로파일은
그 자리에 고시 5-5-4 가의 3NM 을 넣는다. 값 자체보다 중요한 것은 **어디서 왔는지**다 —
프로파일이 조항을 출처로 밝히고, 수치는 전사 데이터에서만 읽어야 한다.

쌍별 판정이 되는지도 함께 고정한다. 고정 프로파일과 달리 편대비행(5-5-8)처럼 쌍에
따라 최저치가 달라지는 경우가 있고, 정보가 없을 때 좁은 쪽으로 넘어가면 안 된다.
"""

from dataclasses import dataclass

import pytest

from sentry_atm.conflict.detector import PairwiseConflictDetector
from sentry_atm.domain import (
    POC_TERMINAL_V1_RULE_PROFILE,
    ConflictStatus,
    SeparationMinimum,
    SeparationRuleProfile,
)
from sentry_atm.regulation import data as sdata
from sentry_atm.regulation import separation as sep


@pytest.fixture(scope="module")
def ds():
    return sdata.load()


@pytest.fixture(scope="module")
def profile(ds):
    return sep.build(ds)


@dataclass
class Stub:
    """규정 판정에 필요한 속성만 가진 항적 대역.

    `sentry_atm.AircraftState` 는 아직 후류등급을 갖고 있지 않다. 어댑터가 그 정보를
    받았을 때 무엇을 하는지 여기서 고정해 두고, 도메인에 필드가 생기면 그대로 붙는다.
    """

    aircraft_id: str = "AC1"
    altitude_ft: float = 5_000.0
    heading_deg: float = 240.0
    ground_speed_kt: float = 200.0
    wake_category: str | None = "중형"
    is_formation: bool = False


class TestProvenance:
    """수치가 어디서 왔는지 밝힐 수 없으면 쓰지 않는다."""

    def test_profile_names_the_regulation_not_an_assumption(self, profile):
        assert "GOSI" in profile.profile_id
        assert "2022-534" in profile.source_reference
        assert "ASSUMPTION" not in profile.source_reference.upper()

    def test_thresholds_come_from_transcribed_data(self, ds, profile):
        sepdata = ds.airspace.raw["separation"]
        assert profile.horizontal_threshold_nm == (
            sepdata["radar_horizontal"]["within_40nm_of_asr_nm"]
        )
        assert profile.vertical_threshold_ft == sepdata["vertical"]["below_fl410_ft"]

    def test_terminal_minima_are_three_miles_and_a_thousand_feet(self, profile):
        assert profile.horizontal_threshold_nm == 3.0
        assert profile.vertical_threshold_ft == 1_000.0

    def test_clauses_are_reported_for_escalation(self, profile):
        assert profile.clauses_for() == ("5-5-4 가", "4-5-1")

    def test_requires_a_rulebook(self):
        with pytest.raises((ValueError, TypeError)):
            sep.RegulatorySeparationProfile(
                profile_id="X",
                horizontal_threshold_nm=3.0,
                vertical_threshold_ft=1_000.0,
                source_reference="X",
            )


class TestClassification:
    @pytest.mark.parametrize(
        "horizontal_nm,vertical_ft,expected",
        [
            (2.5, 500.0, ConflictStatus.PREDICTED),   # 양쪽 다 미달
            (3.5, 500.0, ConflictStatus.SAFE),        # 수평 확보
            (2.5, 1_500.0, ConflictStatus.SAFE),      # 수직 확보
            (3.0, 999.0, ConflictStatus.SAFE),        # 최저치와 같으면 위반이 아니다
        ],
    )
    def test_conjunctive_rule(self, profile, horizontal_nm, vertical_ft, expected):
        minimum = SeparationMinimum(horizontal_nm=horizontal_nm, vertical_ft=vertical_ft)
        assert profile.classify(minimum) is expected

    def test_stricter_than_the_poc_assumption_between_three_and_five_miles(self, profile):
        """가정값 5NM 은 이 구간을 전부 충돌로 봤다. 고시 기준으로는 아니다."""
        for horizontal_nm in (3.5, 4.0, 4.9):
            minimum = SeparationMinimum(horizontal_nm=horizontal_nm, vertical_ft=500.0)
            assert POC_TERMINAL_V1_RULE_PROFILE.classify(minimum) is ConflictStatus.PREDICTED
            assert profile.classify(minimum) is ConflictStatus.SAFE

    def test_agrees_with_the_poc_assumption_below_three_miles(self, profile):
        minimum = SeparationMinimum(horizontal_nm=2.0, vertical_ft=500.0)
        assert profile.classify(minimum) is ConflictStatus.PREDICTED
        assert POC_TERMINAL_V1_RULE_PROFILE.classify(minimum) is ConflictStatus.PREDICTED

    def test_rejects_a_non_minimum(self, profile):
        with pytest.raises(TypeError):
            profile.classify(object())


class TestPairDependence:
    """고정 프로파일과 갈리는 지점."""

    def test_formation_pair_gets_additional_separation(self, profile):
        """고시 5-5-8 — 편대비행에는 추가분리를 적용한다."""
        plain = profile.thresholds_for(Stub(), Stub(aircraft_id="AC2"))
        formation = profile.thresholds_for(
            Stub(is_formation=True), Stub(aircraft_id="AC2")
        )
        assert formation[0] > plain[0]

    def test_both_formation_adds_more_than_one(self, profile):
        one = profile.thresholds_for(Stub(is_formation=True), Stub(aircraft_id="AC2"))
        both = profile.thresholds_for(
            Stub(is_formation=True), Stub(aircraft_id="AC2", is_formation=True)
        )
        assert both[0] >= one[0]

    def test_formation_changes_the_verdict(self, profile):
        minimum = SeparationMinimum(horizontal_nm=3.5, vertical_ft=500.0)
        assert profile.classify(minimum, Stub(), Stub("AC2")) is ConflictStatus.SAFE
        assert (
            profile.classify(minimum, Stub(is_formation=True), Stub("AC2"))
            is ConflictStatus.PREDICTED
        )

    def test_unknown_wake_category_falls_back_to_the_base_minimum(self, profile):
        """모르는 값을 채워 넣어 좁은 기준으로 판정하지 않는다."""
        assert profile.thresholds_for(Stub(wake_category=None), Stub("AC2")) == (
            profile.horizontal_threshold_nm,
            profile.vertical_threshold_ft,
        )

    def test_missing_pair_falls_back_to_the_base_minimum(self, profile):
        assert profile.thresholds_for(None, None) == (
            profile.horizontal_threshold_nm,
            profile.vertical_threshold_ft,
        )

    def test_fixed_profile_ignores_the_pair(self):
        """기존 프로파일의 동작은 바뀌지 않아야 한다."""
        base = POC_TERMINAL_V1_RULE_PROFILE.thresholds_for()
        assert POC_TERMINAL_V1_RULE_PROFILE.thresholds_for(Stub(), Stub("AC2")) == base


class TestDetectorIntegration:
    def test_profile_is_accepted_by_the_detector(self, profile):
        """상속 덕분에 기존 isinstance 검증을 그대로 통과한다."""
        assert isinstance(profile, SeparationRuleProfile)
        detector = PairwiseConflictDetector(rule_profile=profile)
        assert detector.rule_profile.profile_id == profile.profile_id

    def test_detector_now_defaults_to_the_regulation(self):
        """기본값이 고시 프로파일이다. 주입하면 여전히 덮어쓸 수 있다."""
        from sentry_atm.regulation.policy import active_separation_profile

        assert PairwiseConflictDetector().rule_profile is active_separation_profile()
        assert (
            PairwiseConflictDetector(rule_profile=POC_TERMINAL_V1_RULE_PROFILE).rule_profile
            is POC_TERMINAL_V1_RULE_PROFILE
        )

    def test_events_carry_the_regulatory_profile_id(self, profile):
        from datetime import UTC, datetime

        from sentry_atm.domain import AircraftState, DataSource

        def state(aircraft_id, x_nm, y_nm):
            return AircraftState(
                aircraft_id=aircraft_id,
                timestamp_utc=datetime(2026, 1, 1, tzinfo=UTC),
                x_nm=x_nm,
                y_nm=y_nm,
                altitude_ft=5_000.0,
                ground_speed_kt=200.0,
                heading_deg=0.0,
                vertical_speed_fpm=0.0,
                source=DataSource.SYNTHETIC,
            )

        events = PairwiseConflictDetector(rule_profile=profile).assess(
            [state("AC1", 0.0, 0.0), state("AC2", 0.0, 4.0)]
        )
        assert events
        assert all(e.rule_profile_id == profile.profile_id for e in events)
