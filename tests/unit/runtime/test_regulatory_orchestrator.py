"""고시 계층이 실제 교통에 붙는지 검증 — 관할·활주로·체공·복귀경로.

규정 모듈들은 각자 단위시험을 가지고 있다. 여기서 확인하는 것은 다른 것이다:
**시뮬레이터가 만든 항적을 그 모듈들이 읽을 수 있는 형태로 넘기고 있는가.**
좌표계가 어긋나거나 후류 등급이 빠지면 모듈은 조용히 잘못된 답을 낸다 —
예외를 던지지 않고, 그럴듯한 숫자를 준다. 그래서 값이 아니라 관계를 본다.
"""

import pytest

from sentry_atm.domain import FlightPhase
from sentry_atm.domain.approach_sequence import STABILISED_PHASES
from sentry_atm.regulation.bridge import to_geodetic_states, wake_category_known
from sentry_atm.runtime import RegulatoryAdvisoryOrchestrator
from sentry_atm.runtime.composition import build_golden_demo_runtime
from sentry_atm.runtime.orchestrator import GoldenDemoStepOrchestrator

EMERGENCY = "MIL-T01"
STABILISED = "CIV-A01"


def run_to(seconds: int):
    """골든 데모를 주어진 시각까지 진행하고 규정 권고를 낸다."""
    runtime = build_golden_demo_runtime()
    runtime.simulation.clock.play()
    result = GoldenDemoStepOrchestrator(runtime).step(advance_steps=seconds)
    return result, RegulatoryAdvisoryOrchestrator().advise(result)


@pytest.fixture(scope="module")
def declared():
    """비상 선언 직후 (T+245)."""
    return run_to(245)


@pytest.fixture(scope="module")
def quiet():
    """비상 이전 (T+60)."""
    return run_to(60)


class TestControlUnitAssignment:
    """고시 2-1-15 — 고도와 위치가 관할을 정한다."""

    def test_every_aircraft_gets_a_unit(self, declared):
        _, advisory = declared
        assert advisory.control_units
        assert all(a.unit for a in advisory.control_units)

    def test_the_unit_set_is_from_the_transcribed_chain(self, declared):
        """지어낸 기관 이름이 섞이면 여기서 걸린다."""
        _, advisory = declared
        known = {"CHEONGJU GCA", "JUNGWON APP", "OSAN APP", "INCHEON ACC"}
        assert set(advisory.units_in_use) <= known

    def test_lower_traffic_is_not_handed_to_a_higher_unit(self, declared):
        """장주 고도의 항공기가 접근관제소로 넘어가면 사슬이 뒤집힌 것이다."""
        _, advisory = declared
        low = [a for a in advisory.control_units if a.altitude_ft <= 3_000 and not a.lateral]
        assert all(a.unit == "CHEONGJU GCA" for a in low)

    def test_unit_of_raises_for_an_unknown_aircraft(self, declared):
        _, advisory = declared
        with pytest.raises(KeyError):
            advisory.unit_of("NO-SUCH-AIRCRAFT")


class TestRunwaySequence:
    """고시 3-10-3 — 활주로 사용 간격."""

    def test_positions_are_dense_and_start_at_one(self, declared):
        _, advisory = declared
        assert [s.position for s in advisory.runway_slots] == list(
            range(1, len(advisory.runway_slots) + 1)
        )

    def test_the_sequence_is_ordered_by_distance_to_threshold(self, declared):
        _, advisory = declared
        distances = [s.distance_to_threshold_nm for s in advisory.runway_slots]
        assert distances == sorted(distances)

    def test_the_leader_carries_no_gap_requirement(self, declared):
        """앞에 아무도 없으면 벌릴 대상도 없다."""
        _, advisory = declared
        leader = advisory.runway_slots[0]
        assert leader.required_gap_seconds == 0.0
        assert leader.clauses == ()

    def test_every_follower_cites_a_clause(self, declared):
        _, advisory = declared
        for slot in advisory.runway_slots[1:]:
            assert slot.clauses, f"{slot.aircraft_id} 근거 조항 없음"
            assert slot.required_gap_seconds > 0.0

    def test_climbing_traffic_does_not_take_an_arrival_slot(self, declared):
        _, advisory = declared
        occupants = {s.aircraft_id for s in advisory.runway_slots}
        assert "CIV-D01" not in occupants
        assert "MIL-F01" not in occupants

    def test_distances_are_plausible_for_the_terminal_area(self, declared):
        """좌표 변환이 어긋나면 시단 거리가 터무니없이 커진다."""
        _, advisory = declared
        assert all(0.0 < s.distance_to_threshold_nm < 60.0 for s in advisory.runway_slots)


class TestHolding:
    """고시 4-6-1 ~ 4-6-7 — 공고 체공장주."""

    def test_no_holding_without_an_emergency(self, quiet):
        """자리를 비켜 줄 이유가 없으면 붙들지 않는다."""
        _, advisory = quiet
        assert advisory.holdings == ()
        assert advisory.holding_refused == ()

    def test_the_emergency_aircraft_is_never_held(self, declared):
        _, advisory = declared
        assert all(h.aircraft_id != EMERGENCY for h in advisory.holdings)

    def test_stabilised_aircraft_are_not_held(self, declared):
        """순서 재구성에서 밀지 않기로 한 항공기를 체공으로 밀면 같은 규칙을 어긴다."""
        step, advisory = declared
        stabilised = {
            s.aircraft_id
            for s in step.traffic_snapshot.states
            if s.flight_phase in STABILISED_PHASES
        }
        assert stabilised, "안정된 항공기가 없으면 이 시험이 아무것도 안 지킨다"
        assert stabilised.isdisjoint({h.aircraft_id for h in advisory.holdings})

    def test_levels_do_not_collide(self, declared):
        """같은 픽스에 같은 고도를 두 대에 주면 체공이 충돌을 만든다."""
        _, advisory = declared
        pairs = [(h.fix, h.level_ft) for h in advisory.holdings]
        assert len(pairs) == len(set(pairs))

    def test_every_hold_names_a_published_fix(self, declared):
        _, advisory = declared
        assert all(h.fix for h in advisory.holdings)

    def test_the_phraseology_names_the_aircraft_and_the_fix(self, declared):
        _, advisory = declared
        for hold in advisory.holdings:
            assert hold.aircraft_id in hold.phraseology
            assert hold.fix in hold.phraseology

    def test_delay_covers_at_least_one_circuit(self, declared):
        _, advisory = declared
        for hold in advisory.holdings:
            assert hold.circuits >= 1
            assert hold.delay_seconds > 0.0


class TestRecoveryRoute:
    """비상기 복귀 경로."""

    def test_no_route_without_an_emergency(self, quiet):
        _, advisory = quiet
        assert advisory.recovery_route is None

    def test_the_route_belongs_to_the_emergency_aircraft(self, declared):
        _, advisory = declared
        assert advisory.recovery_route is not None
        assert advisory.recovery_route.aircraft_id == EMERGENCY

    def test_the_route_names_fixes_and_a_positive_distance(self, declared):
        _, advisory = declared
        route = advisory.recovery_route
        assert route.fixes
        assert route.total_nm > 0.0

    def test_detour_is_never_negative(self, declared):
        """우회량이 음수면 직선보다 짧다는 뜻이라 계산이 틀린 것이다."""
        _, advisory = declared
        assert advisory.recovery_route.detour_nm >= 0.0

    def test_the_clearance_names_the_aircraft(self, declared):
        _, advisory = declared
        assert EMERGENCY in advisory.recovery_route.clearance


class TestBridgeFidelity:
    """국지 x/y → 위경도 변환이 항적의 의미를 보존하는가."""

    def test_every_state_survives_the_conversion(self, declared):
        step, _ = declared
        states = tuple(step.traffic_snapshot.states)
        assert len(to_geodetic_states(states)) == len(states)

    def test_identity_and_kinematics_are_carried_over(self, declared):
        step, _ = declared
        for local, geo in zip(
            step.traffic_snapshot.states,
            to_geodetic_states(step.traffic_snapshot.states),
            strict=True,
        ):
            assert geo.callsign == local.aircraft_id
            assert geo.alt_ft == local.altitude_ft
            assert geo.gs_kt == local.ground_speed_kt

    def test_the_scenario_supplies_real_wake_categories(self, declared):
        """등급이 비면 기본값으로 메워지고, 후류 종렬이 실제보다 짧아진다."""
        step, _ = declared
        assert all(wake_category_known(s) for s in step.traffic_snapshot.states)

    def test_positions_land_near_the_aerodrome(self, declared):
        step, _ = declared
        for geo in to_geodetic_states(step.traffic_snapshot.states):
            assert 36.0 < geo.lat < 37.5
            assert 126.5 < geo.lon < 128.5


class TestContract:
    """앞 단계들과 같은 규약 — 계산만 하고 상태를 바꾸지 않는다."""

    def test_runtime_is_not_mutated(self):
        runtime = build_golden_demo_runtime()
        runtime.simulation.clock.play()
        result = GoldenDemoStepOrchestrator(runtime).step(advance_steps=245)
        before = tuple(result.traffic_snapshot.states)
        RegulatoryAdvisoryOrchestrator().advise(result)
        assert tuple(result.traffic_snapshot.states) == before

    def test_advising_twice_gives_the_same_answer(self, declared):
        step, first = declared
        second = RegulatoryAdvisoryOrchestrator().advise(step)
        assert first == second

    def test_the_advisory_carries_its_step_id(self, declared):
        step, advisory = declared
        assert advisory.step_id == step.step_id

    def test_rejects_a_non_step_result(self):
        with pytest.raises(TypeError):
            RegulatoryAdvisoryOrchestrator().advise(object())

    def test_empty_traffic_yields_an_empty_advisory(self):
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
        advisory = RegulatoryAdvisoryOrchestrator().advise(empty)
        assert advisory.control_units == ()
        assert advisory.runway_slots == ()
        assert advisory.holdings == ()
        assert advisory.recovery_route is None


class TestAgreementWithResequencing:
    """두 오케스트레이터가 같은 교통을 두고 서로 다른 말을 하지 않는가."""

    def test_the_arrival_sets_match(self, declared):
        """활주로 열과 접근 순서에 같은 항공기가 들어와야 한다."""
        from sentry_atm.runtime import ApproachSequenceOrchestrator

        step, advisory = declared
        run = ApproachSequenceOrchestrator().resequence(step)
        assert {s.aircraft_id for s in advisory.runway_slots} == set(
            run.result.recommended_order
        )

    def test_nothing_is_both_held_and_kept_in_place(self, declared):
        from sentry_atm.runtime import ApproachSequenceOrchestrator

        step, advisory = declared
        run = ApproachSequenceOrchestrator().resequence(step)
        held = {h.aircraft_id for h in advisory.holdings}
        assert held.isdisjoint(run.result.stabilised_aircraft_ids)


def test_arriving_phases_cover_the_stabilised_ones():
    """안정 단계가 도착 단계의 부분집합이 아니면 체공 제외가 아무 일도 안 한다."""
    from sentry_atm.runtime.regulatory_orchestrator import _ARRIVING

    assert STABILISED_PHASES <= _ARRIVING
    assert FlightPhase.FINAL in STABILISED_PHASES
