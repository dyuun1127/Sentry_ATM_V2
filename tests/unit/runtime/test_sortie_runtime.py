"""파이프라인이 시나리오에 묶여 있지 않은지 — 소티에서도 그대로 도는가.

골든 데모용 배선과 소티용 배선이 따로 있으면, 시험에서 도는 코드와 시연에서 도는
코드가 서로 다른 것이 된다. 그때 시험이 통과하는 것은 시연이 된다는 뜻이 아니다.
그래서 둘 다 `build_scenario_runtime` 하나를 지나게 해 두고, 여기서 그 사실을
고정한다.

소티에서만 나타나는 성질도 함께 본다 — 항공기가 들고 나는 것, 하늘이 비는 시간,
그리고 비상 선언이 시나리오 도중에 일어나는 것.
"""

import pytest

from sentry_atm.api.playback import build_sortie_playback_contract
from sentry_atm.domain import EmergencyStatus, OperationalPriorityLevel
from sentry_atm.runtime import (
    ApproachSequenceOrchestrator,
    RegulatoryAdvisoryOrchestrator,
    build_golden_demo_runtime,
    build_sortie_runtime,
)
from sentry_atm.runtime.orchestrator import GoldenDemoStepOrchestrator
from sentry_atm.scenario.sortie_builder import SORTIE_SCENARIO_ID, build_sortie_plan

FIGHTER = "ROKAF01"


@pytest.fixture(scope="module")
def plan():
    return build_sortie_plan()


@pytest.fixture(scope="module")
def declared(plan):
    """비상 선언 직후의 단계 결과."""
    offset = int(
        (plan.definition.events[0].scheduled_time_utc - plan.definition.start_time_utc)
        .total_seconds()
    )
    runtime = build_sortie_runtime()
    runtime.simulation.clock.play()
    return GoldenDemoStepOrchestrator(runtime).step(advance_steps=offset + 60)


class TestWiring:
    def test_the_runtime_carries_the_sortie_scenario(self):
        runtime = build_sortie_runtime()
        assert runtime.definition.scenario_id == SORTIE_SCENARIO_ID
        assert len(runtime.definition.aircraft) == 15

    def test_both_scenarios_use_the_same_components(self):
        """구성이 다르면 시험에서 도는 코드와 시연에서 도는 코드가 달라진다."""
        sortie = build_sortie_runtime()
        golden = build_golden_demo_runtime()
        for field in (
            "prediction_scheduler",
            "conflict_scheduler",
            "risk_evaluator",
            "priority_evaluator",
            "candidate_generator",
            "safety_validator",
            "recommendation_service",
        ):
            assert type(getattr(sortie, field)) is type(getattr(golden, field))

    def test_the_playback_contract_belongs_to_the_sortie(self):
        runtime = build_sortie_runtime()
        contract = runtime.playback_api.get_playback().contract
        assert contract.scenario_id == SORTIE_SCENARIO_ID

    def test_the_contract_covers_every_aircraft(self, plan):
        """마지막 항공기가 빠지기 전에 재생이 끝나면 교통이 화면에서 잘린다."""
        contract = build_sortie_playback_contract(plan)
        last_exit = max(
            (window[1] - plan.definition.start_time_utc).total_seconds()
            for item in plan.definition.aircraft
            for window in item.presence
        )
        assert contract.duration_seconds >= last_exit

    def test_cues_are_anchored_to_the_thirteen_steps(self, plan):
        contract = build_sortie_playback_contract(plan)
        step_times = {step.n: step.t_s for step in plan.steps}
        for cue in contract.cues:
            number = int(cue.cue_id.removeprefix("CUE-S"))
            if number == 1:
                assert cue.offset_seconds == 0.0
            else:
                assert cue.offset_seconds == pytest.approx(step_times[number])


class TestTrafficOverTime:
    """골든 데모에는 없던 성질 — 항공기가 들고 난다."""

    def test_aircraft_enter_over_the_hour(self):
        runtime = build_sortie_runtime()
        runtime.simulation.clock.play()
        step = GoldenDemoStepOrchestrator(runtime)
        first = step.step(advance_steps=1)
        later = step.step(advance_steps=2_000)
        assert {s.aircraft_id for s in first.traffic_snapshot.states} != {
            s.aircraft_id for s in later.traffic_snapshot.states
        }

    def test_an_empty_sky_is_not_an_error(self):
        """시간당 8회인 공항에서는 몇 분씩 아무도 없다. 그때도 단계는 돌아야 한다."""
        runtime = build_sortie_runtime()
        runtime.simulation.clock.play()
        step = GoldenDemoStepOrchestrator(runtime)
        empty = None
        elapsed = 0
        while elapsed < 1_200:
            result = step.step(advance_steps=20)
            elapsed += 20
            if not result.traffic_snapshot.states:
                empty = result
                break
        assert empty is not None, "빈 하늘이 한 번도 없으면 이 시험이 아무것도 안 지킨다"
        assert empty.risk_assessments == ()
        assert empty.priority_assessments == ()

    def test_no_aircraft_flies_past_the_field_forever(self):
        """퇴장이 없던 시절에는 착륙한 항공기가 계속 직진했다."""
        runtime = build_sortie_runtime()
        runtime.simulation.clock.play()
        result = GoldenDemoStepOrchestrator(runtime).step(advance_steps=4_600)
        assert result.traffic_snapshot.states == ()


class TestEmergencyInFlight:
    """비상이 시나리오 도중에 일어난다 — 처음부터 비상인 것이 아니다."""

    def test_the_fighter_is_normal_before_it_declares(self, plan):
        runtime = build_sortie_runtime()
        runtime.simulation.clock.play()
        offset = int(
            (
                plan.definition.events[0].scheduled_time_utc
                - plan.definition.start_time_utc
            ).total_seconds()
        )
        before = GoldenDemoStepOrchestrator(runtime).step(advance_steps=offset - 120)
        fighter = [
            s for s in before.traffic_snapshot.states if s.aircraft_id == FIGHTER
        ]
        assert fighter, "선언 이전에 전투기가 화면에 없으면 선언이 사건이 아니다"
        assert fighter[0].emergency_status is EmergencyStatus.NONE

    def test_the_fighter_is_an_emergency_after_it_declares(self, declared):
        fighter = [
            s for s in declared.traffic_snapshot.states if s.aircraft_id == FIGHTER
        ]
        assert fighter
        assert fighter[0].emergency_status is EmergencyStatus.DECLARED

    def test_the_priority_evaluator_sees_it(self, declared):
        emergency = [
            a
            for a in declared.priority_assessments
            if a.priority_level is OperationalPriorityLevel.EMERGENCY
        ]
        assert [a.aircraft_id for a in emergency] == [FIGHTER]


class TestOrchestratorsAgreeOnTheSortie:
    """5단계에서 만든 두 오케스트레이터가 이 시나리오에서도 서로 맞는가."""

    def test_the_emergency_leads_the_runway_sequence(self, declared):
        advisory = RegulatoryAdvisoryOrchestrator().advise(declared)
        assert advisory.runway_slots
        assert advisory.runway_slots[0].aircraft_id == FIGHTER

    def test_followers_cite_a_clause(self, declared):
        advisory = RegulatoryAdvisoryOrchestrator().advise(declared)
        for slot in advisory.runway_slots[1:]:
            assert slot.clauses
            assert slot.required_gap_seconds > 0.0

    def test_the_emergency_is_never_held(self, declared):
        advisory = RegulatoryAdvisoryOrchestrator().advise(declared)
        assert all(hold.aircraft_id != FIGHTER for hold in advisory.holdings)

    def test_the_recovery_route_belongs_to_the_fighter(self, declared):
        advisory = RegulatoryAdvisoryOrchestrator().advise(declared)
        assert advisory.recovery_route is not None
        assert advisory.recovery_route.aircraft_id == FIGHTER
        assert advisory.recovery_route.total_nm > 0.0

    def test_the_resequencer_finds_the_same_emergency(self, declared):
        run = ApproachSequenceOrchestrator().resequence(declared)
        assert run is not None
        assert run.result.emergency_aircraft_id == FIGHTER

    def test_the_two_orchestrators_see_the_same_arrivals(self, declared):
        run = ApproachSequenceOrchestrator().resequence(declared)
        advisory = RegulatoryAdvisoryOrchestrator().advise(declared)
        assert {s.aircraft_id for s in advisory.runway_slots} == set(
            run.result.recommended_order
        )

    def test_nothing_is_both_held_and_left_in_place(self, declared):
        run = ApproachSequenceOrchestrator().resequence(declared)
        advisory = RegulatoryAdvisoryOrchestrator().advise(declared)
        held = {hold.aircraft_id for hold in advisory.holdings}
        assert held.isdisjoint(run.result.stabilised_aircraft_ids)


class TestContract:
    def test_the_runtime_is_not_started(self):
        """배선은 시계를 돌리지 않는다. 골든 데모와 같은 규약이다."""
        runtime = build_sortie_runtime()
        assert not runtime.simulation.clock.is_running
        assert runtime.simulation.clock.elapsed_seconds == 0.0

    def test_two_runtimes_do_not_share_state(self):
        first = build_sortie_runtime()
        second = build_sortie_runtime()
        first.simulation.clock.play()
        GoldenDemoStepOrchestrator(first).step(advance_steps=100)
        assert second.simulation.clock.elapsed_seconds == 0.0

    def test_a_different_seed_reaches_the_runtime(self):
        other = build_sortie_runtime(seed=11)
        base = build_sortie_runtime(seed=4)
        assert [a.initial_state for a in other.definition.aircraft] != [
            a.initial_state for a in base.definition.aircraft
        ]
