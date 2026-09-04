"""판단 연쇄가 시나리오에 묶여 있지 않은가.

이 연쇄는 골든 데모의 보정된 순간에 못박혀 있었다 — 상신 T+75, 승인 T+90,
적용은 "CAND-A 고도 9,000 ft" 라는 특정 후보. 그 값들은 시연 대본을 재현하기
위한 것이었고, 다른 시나리오에서는 상신 자체가 성립하지 않게 만들었다. 75분짜리
소티에서 T+75 는 아무 일도 없는 시각이다.

여기서 고정하는 것은 두 가지다. **소티에서 상신부터 적용까지 끝까지 간다** —
그것이 안 되면 이 과제의 주장인 "판단은 관제사에게" 를 시연에서 보여줄 자리가
없다. 그리고 **시각 고정이 우연히 지켜 주던 성질이 명시적으로 남아 있다** —
판단과 증거가 같은 시각의 것이어야 한다는 조건이다.
"""

import pytest

from sentry_atm.api.session import GoldenDemoSessionCommand
from sentry_atm.domain import EmergencyStatus
from sentry_atm.runtime import (
    build_golden_demo_session_runtime,
    build_sortie_session_runtime,
)

# 비상 선언 직후. 이 시각에 ROKAF01 과 TWB1317 이 접근 경합에 들어간다.
_SORTIE_CONFLICT_OFFSET_S = 3_420


def _primary(current):
    """상신된 안 하나. 읽기 모델은 목록과 식별자로 준다."""
    recommendation_set = current.recommendation
    if recommendation_set is None:
        return None
    return next(
        (
            item
            for item in recommendation_set.recommendations
            if item.recommendation_id == recommendation_set.primary_recommendation_id
        ),
        None,
    )


@pytest.fixture(scope="module")
def sortie():
    session = build_sortie_session_runtime()
    session.command_service.execute(GoldenDemoSessionCommand.START)
    session.command_service.execute(
        GoldenDemoSessionCommand.ADVANCE, seconds=_SORTIE_CONFLICT_OFFSET_S
    )
    return session


class TestSortieReachesARecommendation:
    def test_the_conflict_is_detected(self, sortie):
        current = sortie.read_api.get_current()
        assert current.stage == "CONFLICT_DETECTED"
        assert current.active_exception_count >= 1

    def test_a_safe_recommendation_is_published(self, sortie):
        current = sortie.command_service.execute(
            GoldenDemoSessionCommand.GENERATE_RECOMMENDATION
        )
        assert current.stage == "RECOMMENDATION_AVAILABLE"
        assert current.recommendation is not None
        assert current.recommendation.availability == "AVAILABLE"
        assert _primary(current) is not None

    def test_the_emergency_aircraft_is_not_the_one_told_to_manoeuvre(self, sortie):
        """고시 2-1-4 가 — 조난 항공기에 우선 통행권이 있다.

        비상기를 벡터로 돌리는 회피안을 상신하면 우선권이 이름뿐이 된다.
        """
        current = sortie.read_api.get_current()
        primary = _primary(current)
        emergency_ids = {
            state.aircraft_id
            for state in current.traffic
            if state.emergency_status == EmergencyStatus.DECLARED.value
        }
        assert emergency_ids, "비상기가 없으면 이 시험이 아무것도 지키지 않는다"
        assert primary.target_aircraft_id not in emergency_ids

    def test_descending_the_emergency_further_is_refused(self, sortie):
        """이미 잠정 최저고도 아래에 있는 항공기를 더 내리는 안은 안전하지 않다."""
        current = sortie.read_api.get_current()
        by_id = {item.candidate_id: item for item in current.candidate_comparisons}
        descending = [
            item
            for item in by_id.values()
            if item.maneuver_type == "ALTITUDE"
            and item.verdict == "UNSAFE"
            and item.rule_violation_ids
        ]
        assert descending, "최저고도 규칙이 한 번도 걸리지 않으면 규칙이 죽은 것이다"

    def test_accept_and_apply_reach_a_resolved_conflict(self, sortie):
        accepted = sortie.command_service.execute(
            GoldenDemoSessionCommand.ACCEPT_RECOMMENDATION
        )
        assert accepted.stage == "DECISION_ACCEPTED"

        applied = sortie.command_service.execute(
            GoldenDemoSessionCommand.APPLY_APPROVED_MANEUVER
        )
        assert applied.stage == "CONFLICT_RESOLVED"
        assert applied.revalidation is not None
        # 적용된 것이 승인된 것과 같은 항공기여야 한다.
        assert applied.revalidation.applied_aircraft_id == _primary(accepted).target_aircraft_id


class TestTimeIsNoLongerPinnedButFreshnessIs:
    """시각 고정을 걷어낸 자리에 무엇이 남았는가."""

    def test_resolution_no_longer_waits_for_a_calibrated_moment(self):
        """골든 데모에서 HIGH 충돌은 T+60 에 생긴다. T+75 고정은 15초를 기다렸다."""
        session = build_golden_demo_session_runtime()
        session.command_service.execute(GoldenDemoSessionCommand.START)
        session.command_service.execute(GoldenDemoSessionCommand.ADVANCE, seconds=60)
        current = session.command_service.execute(
            GoldenDemoSessionCommand.GENERATE_RECOMMENDATION
        )
        assert current.recommendation is not None
        # GENERATE 는 5초를 더 진행한 뒤 상신한다 (세션 명령의 정의).
        assert current.elapsed_seconds == 65.0

    def test_a_decision_from_an_earlier_moment_cannot_be_applied(self):
        """SAFE 판정은 그 시점의 교통에 대해 계산된 것이다.

        시간이 흐른 뒤 그대로 적용하면 검증하지 않은 상황에 검증된 기동을 넣는
        것이 된다. 예전에는 T+90 고정이 이것을 우연히 막고 있었다.
        """
        session = build_golden_demo_session_runtime()
        session.command_service.execute(GoldenDemoSessionCommand.START)
        session.command_service.execute(GoldenDemoSessionCommand.ADVANCE, seconds=70)
        session.command_service.execute(GoldenDemoSessionCommand.GENERATE_RECOMMENDATION)
        session.command_service.execute(GoldenDemoSessionCommand.ACCEPT_RECOMMENDATION)

        session.command_service.execute(GoldenDemoSessionCommand.ADVANCE, seconds=5)
        with pytest.raises(ValueError, match="contemporaneous"):
            session.command_service.execute(
                GoldenDemoSessionCommand.APPLY_APPROVED_MANEUVER
            )

    def test_evidence_behind_the_clock_blocks_every_command(self):
        """시계만 움직이고 단계가 계산되지 않으면 화면과 시각이 어긋난다."""
        session = build_golden_demo_session_runtime()
        session.command_service.execute(GoldenDemoSessionCommand.START)
        session.runtime.simulation.engine.tick()

        with pytest.raises(ValueError, match="behind the Clock"):
            session.command_service.execute(GoldenDemoSessionCommand.ADVANCE, seconds=1)

        # RESET 은 어긋난 상태를 되돌리는 것이 그 명령의 일이다.
        assert (
            session.command_service.execute(GoldenDemoSessionCommand.RESET).stage
            == "READY"
        )


class TestGoldenDemoIsUnchanged:
    """일반화가 보정된 시연을 바꾸지 않았는가.

    회귀 고정물이 흔들리면 일반화가 무엇을 바꿨는지 말할 수 없게 된다.
    """

    def test_the_calibrated_walkthrough_still_produces_cand_a_at_9000_ft(self):
        session = build_golden_demo_session_runtime()
        session.command_service.execute(GoldenDemoSessionCommand.START)
        session.command_service.execute(GoldenDemoSessionCommand.ADVANCE_TO_CONFLICT)
        current = session.command_service.execute(
            GoldenDemoSessionCommand.GENERATE_RECOMMENDATION
        )
        primary = _primary(current)
        assert primary.candidate_id == "CAND-A"
        assert primary.target_aircraft_id == "MIL-F01"
        assert primary.maneuver.target_altitude_ft == 9_000.0

    def test_nine_thousand_feet_is_now_derived_not_configured(self):
        """9,000 ft 는 손으로 고른 값이 아니라 배정 가능한 고도로 나온 값이다.

        MIL-F01 은 7,446 ft 에서 상승 중이고, 증분 1,000 ft 를 더하면 8,446 ft 다.
        그것은 관제사가 지시할 수 없는 값이라 위쪽 1,000 ft 단위인 9,000 이 된다.
        """
        from sentry_atm.resolution.generator import _assignable_altitude_ft

        assert _assignable_altitude_ft(8_446.25, climbing=True, ceiling_ft=50_000.0) == 9_000.0
        assert _assignable_altitude_ft(7_200.0, climbing=False, ceiling_ft=50_000.0) == 7_000.0
        # 상한을 넘지 않는다 — 올림한 고도가 갈 수 없는 고도이면 안 된다.
        assert _assignable_altitude_ft(9_400.0, climbing=True, ceiling_ft=9_500.0) == 9_000.0
