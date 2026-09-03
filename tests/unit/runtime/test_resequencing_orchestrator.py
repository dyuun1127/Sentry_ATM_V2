"""접근 순서 재구성과 비상 구간 종료 검증 (시나리오 8.9 ~ 8.11).

두 가지가 함께 성립해야 한다. 비상기는 앞으로 와야 하고(고시 2-1-4 가), 이미
최종접근에 안정된 항공기는 움직이지 않아야 한다(`ASM-023`, `ASM-026`). 하나만
지키면 우선권이 이름뿐이거나, 안전을 한 곳에서 빼서 다른 곳에 넣는 것이 된다.

종료 판정도 함께 고정한다. 순서를 바꾼 것만으로 끝났다고 보면 비상기가 아직
위험한 상태인데 화면은 정상으로 돌아간다.
"""

from datetime import UTC, datetime

import pytest

from sentry_atm.domain import (
    ApproachOrderReasonCode,
    DataSource,
    EmergencyStatus,
    EmergencyType,
    FlightPhase,
)
from sentry_atm.domain.aircraft import AircraftState
from sentry_atm.runtime import ApproachSequenceOrchestrator
from sentry_atm.runtime.composition import build_golden_demo_runtime
from sentry_atm.runtime.orchestrator import GoldenDemoStepOrchestrator

EMERGENCY = "MIL-T01"
STABILISED = "CIV-A01"


def run_to(seconds: int):
    """골든 데모를 주어진 시각까지 진행하고 재구성 결과를 낸다."""
    runtime = build_golden_demo_runtime()
    runtime.simulation.clock.play()
    step = GoldenDemoStepOrchestrator(runtime)
    result = step.step(advance_steps=seconds)
    return ApproachSequenceOrchestrator().resequence(result)


@pytest.fixture(scope="module")
def declared():
    """비상 선언 직후 (T+245)."""
    return run_to(245)


@pytest.fixture(scope="module")
def established():
    """비상기가 최종접근에 안정된 뒤 (T+280)."""
    return run_to(280)


class TestEmergencyPriority:
    """고시 2-1-4 가 — 조난 항공기 최우선 통행권."""

    def test_the_emergency_aircraft_is_identified(self, declared):
        assert declared.result.emergency_aircraft_id == EMERGENCY

    def test_the_emergency_aircraft_moves_up(self, declared):
        assert declared.result.moved_up(EMERGENCY)

    def test_the_order_actually_changes(self, declared):
        assert declared.result.changed

    def test_the_emergency_slot_cites_its_clause(self, declared):
        slot = next(s for s in declared.result.slots if s.aircraft_id == EMERGENCY)
        assert ApproachOrderReasonCode.EMERGENCY_PRIORITY in slot.reason_codes
        assert ApproachOrderReasonCode.EARLIEST_REACHABLE in slot.reason_codes


class TestStabilisedAircraftIsNotDisplaced:
    """이미 최종접근에 안정된 항공기는 흔들지 않는다."""

    def test_the_stabilised_aircraft_keeps_first_place(self, declared):
        assert declared.result.recommended_order[0] == STABILISED

    def test_it_is_reported_as_stabilised(self, declared):
        assert STABILISED in declared.result.stabilised_aircraft_ids

    def test_it_is_not_in_the_displaced_list(self, declared):
        assert STABILISED not in declared.result.displaced_aircraft_ids

    def test_its_slot_says_why(self, declared):
        slot = next(s for s in declared.result.slots if s.aircraft_id == STABILISED)
        assert ApproachOrderReasonCode.STABILISED_ON_APPROACH in slot.reason_codes

    def test_the_emergency_goes_behind_every_stabilised_aircraft(self, declared):
        order = declared.result.recommended_order
        for aircraft_id in declared.result.stabilised_aircraft_ids:
            if aircraft_id == EMERGENCY:
                continue
            assert order.index(aircraft_id) < order.index(EMERGENCY)


class TestOrderIntegrity:
    def test_recommended_is_a_permutation_of_baseline(self, declared):
        assert sorted(declared.result.recommended_order) == sorted(
            declared.result.baseline_order
        )

    def test_positions_are_dense_and_start_at_one(self, declared):
        positions = [slot.position for slot in declared.result.slots]
        assert positions == list(range(1, len(positions) + 1))

    def test_every_slot_carries_a_reason(self, declared):
        assert all(slot.reason_codes for slot in declared.result.slots)

    def test_displaced_aircraft_actually_moved_back(self, declared):
        result = declared.result
        for aircraft_id in result.displaced_aircraft_ids:
            assert result.recommended_order.index(aircraft_id) > result.baseline_order.index(
                aircraft_id
            )

    def test_climbing_traffic_is_not_in_the_arrival_sequence(self, declared):
        """상승 중인 항적은 도착 열이 아니다."""
        assert "CIV-D01" not in declared.result.recommended_order
        assert "MIL-F01" not in declared.result.recommended_order


class TestEmergencySegmentTermination:
    """시나리오 8.11 — 최종접근 도달과 충돌 해소가 함께 성립해야 끝난다."""

    def test_not_complete_while_the_emergency_is_still_level(self, declared):
        status = declared.segment_status
        assert status is not None
        assert not status.complete
        assert not status.established_on_approach
        assert "최종접근 미도달" in status.reason

    def test_complete_once_established_on_approach(self, established):
        status = established.segment_status
        assert status is not None
        assert status.complete
        assert status.established_on_approach
        assert status.conflict_free

    def test_completion_names_the_aircraft(self, established):
        assert established.segment_status.aircraft_id == EMERGENCY

    def test_completion_requires_both_conditions(self):
        """한쪽만 참인데 완료로 표시되면 도메인이 거부해야 한다."""
        from sentry_atm.domain import EmergencySegmentStatus

        with pytest.raises(ValueError):
            EmergencySegmentStatus(
                aircraft_id=EMERGENCY,
                complete=True,
                established_on_approach=True,
                conflict_free=False,
                reason="모순",
            )


class TestScenarioWiring:
    """오케스트레이터가 실제 데모 흐름에 붙어 있는가."""

    def test_the_emergency_aircraft_reaches_approach_in_the_scenario(self, established):
        """예정 상태가 없으면 비상기가 공항 위를 그대로 지나가 종료가 영원히 안 된다."""
        slot = next(s for s in established.result.slots if s.aircraft_id == EMERGENCY)
        assert slot.flight_phase in (FlightPhase.APPROACH, FlightPhase.FINAL)

    def test_resequencing_is_stable_across_the_emergency_window(self):
        for seconds in (240, 245, 260):
            run = run_to(seconds)
            assert run is not None
            assert run.result.recommended_order[0] == STABILISED
            assert run.result.moved_up(EMERGENCY)

    def test_runtime_is_not_mutated_by_resequencing(self):
        runtime = build_golden_demo_runtime()
        runtime.simulation.clock.play()
        result = GoldenDemoStepOrchestrator(runtime).step(advance_steps=245)
        before = tuple(result.traffic_snapshot.states)
        ApproachSequenceOrchestrator().resequence(result)
        assert tuple(result.traffic_snapshot.states) == before


class TestNoArrivals:
    def test_returns_none_when_nothing_is_arriving(self):
        """도착 열이 없으면 추천할 순서도 없다."""
        runtime = build_golden_demo_runtime()
        runtime.simulation.clock.play()
        result = GoldenDemoStepOrchestrator(runtime).step(advance_steps=1)
        empty = type(result)(
            step_id=result.step_id,
            timestamp_utc=result.timestamp_utc,
            traffic_snapshot=type(result.traffic_snapshot)(
                timestamp_utc=result.traffic_snapshot.timestamp_utc, states=()
            ),
            due_events=(),
            prediction_run=None,
            conflict_run=None,
            risk_assessments=(),
            priority_assessments=(),
            exception_queue_snapshot=result.exception_queue_snapshot,
        )
        assert ApproachSequenceOrchestrator().resequence(empty) is None

    def test_rejects_a_non_step_result(self):
        with pytest.raises(TypeError):
            ApproachSequenceOrchestrator().resequence(object())


class TestEmergencyDetection:
    def test_declared_state_is_enough_without_a_priority_assessment(self):
        """선언 시점과 평가 시점이 한 틱 어긋나도 놓치지 않는다."""
        runtime = build_golden_demo_runtime()
        runtime.simulation.clock.play()
        result = GoldenDemoStepOrchestrator(runtime).step(advance_steps=280)
        stripped = type(result)(
            step_id=result.step_id,
            timestamp_utc=result.timestamp_utc,
            traffic_snapshot=result.traffic_snapshot,
            due_events=result.due_events,
            prediction_run=result.prediction_run,
            conflict_run=result.conflict_run,
            risk_assessments=result.risk_assessments,
            priority_assessments=(),
            exception_queue_snapshot=result.exception_queue_snapshot,
        )
        run = ApproachSequenceOrchestrator().resequence(stripped)
        assert run.result.emergency_aircraft_id == EMERGENCY

    def test_no_emergency_yields_first_come_first_served(self):
        run = run_to(60)
        assert run is not None
        assert run.result.emergency_aircraft_id is None
        assert run.segment_status is None
        assert not run.result.changed
        assert all(
            ApproachOrderReasonCode.EMERGENCY_PRIORITY not in slot.reason_codes
            for slot in run.result.slots
        )


def test_declared_emergency_state_shape_is_valid():
    """예정 상태가 도메인 규칙을 만족하는지 — 시나리오가 잘못된 상태를 넣지 않는다."""
    state = AircraftState(
        aircraft_id=EMERGENCY,
        timestamp_utc=datetime(2026, 9, 1, 3, 4, 40, tzinfo=UTC),
        x_nm=3.85,
        y_nm=-3.83,
        altitude_ft=5_000.0,
        ground_speed_kt=150.0,
        heading_deg=300.0,
        vertical_speed_fpm=-1_200.0,
        source=DataSource.SYNTHETIC,
        flight_phase=FlightPhase.APPROACH,
        emergency_status=EmergencyStatus.DECLARED,
        emergency_type=EmergencyType.PRIORITY_RETURN,
    )
    assert state.flight_phase is FlightPhase.APPROACH
    assert state.emergency_status is EmergencyStatus.DECLARED
