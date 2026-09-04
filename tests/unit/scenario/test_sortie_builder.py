"""13단계 소티가 시뮬레이터에서 도는지 — 규정 계층이 낸 것과 같은 채로.

여기서 지키려는 것은 하나다. **옮기는 과정에서 사실이 바뀌지 않았는가.** 활주로
순서와 시각은 규정 계층이 정했고, 이 모듈은 좌표계와 시간축만 옮긴다. 옮기면서
값이 조금씩 달라지면 화면과 근거가 어긋나는데, 둘 다 그럴듯해서 눈에 띄지 않는다.

밀도도 함께 고정한다. 청주는 시간당 8회인 공항이라 하늘이 몇 분씩 빈다. 그것을
메우려고 교통을 늘리면 이 시연에서 나오는 모든 숫자가 거짓이 된다.
"""

import math

import pytest

from sentry_atm.domain import EmergencyStatus, WakeCategory
from sentry_atm.geo.coordinate import rktu_geodetic_to_local
from sentry_atm.scenario import build_scenario_simulation
from sentry_atm.scenario.sortie_builder import (
    SORTIE_SCENARIO_ID,
    SORTIE_START_UTC,
    build_sortie_plan,
)

FIGHTER = "ROKAF01"


@pytest.fixture(scope="module")
def plan():
    return build_sortie_plan()


@pytest.fixture(scope="module")
def definition(plan):
    return plan.definition


def _offset(timestamp) -> float:
    return (timestamp - SORTIE_START_UTC).total_seconds()


class TestShape:
    def test_the_scenario_is_identified(self, definition):
        assert definition.scenario_id == SORTIE_SCENARIO_ID

    def test_fifteen_aircraft(self, definition):
        """활주로 사용은 16회지만 전투기가 출격과 복귀로 두 번 쓴다."""
        assert len(definition.aircraft) == 15

    def test_aircraft_ids_are_unique(self, definition):
        ids = [item.aircraft_id for item in definition.aircraft]
        assert len(set(ids)) == len(ids)

    def test_the_first_aircraft_enters_at_the_scenario_start(self, definition):
        assert min(_offset(a.initial_state.timestamp_utc) for a in definition.aircraft) == 0.0

    def test_the_scenario_spans_about_an_operating_hour(self, definition):
        last = max(w[1] for a in definition.aircraft for w in a.presence)
        assert 3_600.0 < _offset(last) < 5_400.0

    def test_every_aircraft_carries_a_wake_category(self, definition):
        """등급이 비면 후류 종렬 요건이 조용히 짧아진다."""
        for item in definition.aircraft:
            assert isinstance(item.metadata.wake_category, WakeCategory)
            assert item.initial_state.wake_category is item.metadata.wake_category

    def test_every_aircraft_has_a_performance_profile(self, definition):
        assert all(a.metadata.performance_class for a in definition.aircraft)


class TestDeterminism:
    def test_the_same_seed_gives_the_same_scenario(self):
        first = build_sortie_plan(seed=4).definition
        second = build_sortie_plan(seed=4).definition
        assert [a.aircraft_id for a in first.aircraft] == [
            a.aircraft_id for a in second.aircraft
        ]
        assert [a.initial_state for a in first.aircraft] == [
            a.initial_state for a in second.aircraft
        ]

    def test_a_different_seed_gives_a_different_scenario(self):
        """seed 가 무시되고 있으면 시나리오를 바꿀 수단이 없는 것이다."""
        other = build_sortie_plan(seed=11).definition
        base = build_sortie_plan(seed=4).definition
        assert [a.initial_state for a in other.aircraft] != [
            a.initial_state for a in base.aircraft
        ]


class TestPresence:
    """항공기는 들어오고 나간다 — 골든 데모에는 없던 성질이다."""

    def test_every_aircraft_declares_when_it_is_present(self, definition):
        assert all(item.presence for item in definition.aircraft)

    def test_presence_starts_with_the_initial_state(self, definition):
        for item in definition.aircraft:
            assert item.presence[0][0] == item.initial_state.timestamp_utc

    def test_only_the_fighter_leaves_and_returns(self, definition):
        """출격 소티만 관할을 벗어났다 돌아온다."""
        split = [a.aircraft_id for a in definition.aircraft if len(a.presence) > 1]
        assert split == [FIGHTER]

    def test_the_fighter_is_absent_while_on_station(self, definition):
        fighter = next(a for a in definition.aircraft if a.aircraft_id == FIGHTER)
        (_, out), (back, _) = fighter.presence
        assert back > out
        assert (back - out).total_seconds() > 300.0

    def test_landed_aircraft_disappear(self, definition):
        """퇴장이 없으면 착륙한 항공기가 활주로를 지나 계속 직진한다."""
        simulation = build_scenario_simulation(definition)
        simulation.clock.play()
        seen_then_gone = set()
        present_before: set[str] = set()
        for _ in range(0, 4_600, 20):
            present = {s.aircraft_id for s in simulation.engine.snapshot().states}
            seen_then_gone |= present_before - present
            present_before = present
            simulation.clock.tick(20)
        assert len(seen_then_gone) >= 14


@pytest.fixture(scope="module")
def counts(definition):
    """10초마다 센 동시 항적 수."""
    simulation = build_scenario_simulation(definition)
    simulation.clock.play()
    out = []
    for _ in range(0, 4_520, 10):
        out.append(len(simulation.engine.snapshot().states))
        simulation.clock.tick(10)
    return out


class TestTrafficDensity:
    """청주의 실제 교통량 — 부풀리지 않는다."""

    def test_the_sky_is_never_crowded(self, counts):
        """동시 항적이 여덟 대가 되면 청주가 아니라 다른 공항이다."""
        assert max(counts) <= 6

    def test_the_average_matches_an_eight_movement_hour(self, counts):
        assert 1.5 <= sum(counts) / len(counts) <= 3.5

    def test_there_are_quiet_stretches(self, counts):
        """시간당 8회인 공항에서는 하늘이 비는 시간이 있다. 그것이 정상이다."""
        assert any(count == 0 for count in counts)


class TestEmergency:
    def test_exactly_one_emergency_event(self, definition):
        assert len(definition.events) == 1
        assert definition.events[0].target_aircraft_id == FIGHTER

    def test_the_declaration_time_comes_from_the_mission_model(self, plan):
        """복귀 항적 시작이 아니라 임무 시간선이 정한다."""
        declared = _offset(plan.definition.events[0].scheduled_time_utc)
        step_seven = next(step for step in plan.steps if step.n == 7)
        assert declared == pytest.approx(step_seven.t_s, abs=1.0)

    def test_the_fighter_is_not_emergency_before_it_declares(self, plan):
        declared = plan.definition.events[0].scheduled_time_utc
        fighter = next(a for a in plan.definition.aircraft if a.aircraft_id == FIGHTER)
        anchors = (fighter.initial_state, *fighter.scheduled_states)
        early = [a for a in anchors if a.timestamp_utc < declared]
        assert early, "선언 이전 구간이 없으면 선언이라는 사건이 화면에 없다"
        assert all(a.emergency_status is EmergencyStatus.NONE for a in early)

    def test_the_fighter_stays_emergency_after_it_declares(self, plan):
        declared = plan.definition.events[0].scheduled_time_utc
        fighter = next(a for a in plan.definition.aircraft if a.aircraft_id == FIGHTER)
        anchors = (fighter.initial_state, *fighter.scheduled_states)
        late = [a for a in anchors if a.timestamp_utc >= declared]
        assert late
        assert all(a.emergency_status is EmergencyStatus.DECLARED for a in late)


class TestSteps:
    """13단계와 항적이 같은 시간축 위에 있는가."""

    def test_there_are_thirteen_steps(self, plan):
        assert [step.n for step in plan.steps] == list(range(1, 14))

    def test_steps_are_ordered_in_time(self, plan):
        times = [step.t_s for step in plan.steps]
        assert times == sorted(times)

    def test_steps_fall_inside_the_scenario(self, plan):
        """근무일의 초(09:00 = 32,400)를 옮기지 않으면 전부 시나리오 밖에 놓인다."""
        last = max(
            _offset(w[1]) for a in plan.definition.aircraft for w in a.presence
        )
        assert all(0.0 <= step.t_s <= last for step in plan.steps)

    def test_the_landing_step_matches_the_fighter_leaving(self, plan):
        """11단계는 비상기 착륙이다. 그 시각에 전투기가 아직 있어야 한다."""
        landing = next(step for step in plan.steps if step.n == 11)
        fighter = next(a for a in plan.definition.aircraft if a.aircraft_id == FIGHTER)
        assert _offset(fighter.presence[-1][1]) >= landing.t_s


class TestFidelityToTheRegulationLayer:
    """옮기는 동안 규정 계층의 값이 바뀌지 않았는가."""

    def test_landing_order_matches_the_runway_schedule(self, plan):
        """활주로 순서는 규정 계층이 정한다. 여기서 다시 정하지 않는다."""
        import random

        from sentry_atm.regulation import data as regulation_data
        from sentry_atm.regulation import schedule as schedule_module
        from sentry_atm.regulation import sortie as sortie_module
        from sentry_atm.scenario import sortie_builder as builder

        dataset = regulation_data.load()
        timetable = schedule_module.build(
            dataset, window=builder.SORTIE_DEFAULT_WINDOW, seed=builder.SORTIE_DEFAULT_SEED
        )
        scenario = sortie_module.build(
            dataset,
            timetable,
            area_id=builder.SORTIE_DEFAULT_AREA,
            patrol_sorties=builder.SORTIE_DEFAULT_PATROL_SORTIES,
        )
        scenario.build()
        events = builder._runway_events(scenario)
        rng = random.Random(builder.SORTIE_DEFAULT_SEED)
        from sentry_atm.regulation import synth as synth_module

        builder._make_tracks(dataset, synth_module.build(dataset), events, rng)

        expected = [op.callsign for op, _ in sorted(events, key=lambda item: item[1])]

        # 시나리오에서 각 구간이 활주로를 쓰는 시각. 출발은 구간이 **시작하는**
        # 순간이 부양이고, 도착은 구간이 **끝나는** 순간이 접지다. 하나로 묶어
        # 비교하면 도착기가 착륙 13분 전에 나타난다는 사실 때문에 순서가 어긋난다.
        departures = {
            op.callsign for op, _ in events if op.is_departure
        }
        used = []
        for item in plan.definition.aircraft:
            for index, window in enumerate(item.presence):
                first_leg = index == 0
                if item.aircraft_id in departures and first_leg:
                    used.append((item.aircraft_id, _offset(window[0])))
                else:
                    used.append((item.aircraft_id, _offset(window[1])))
        actual = [name for name, _ in sorted(used, key=lambda item: item[1])]
        assert actual == expected

    def test_positions_land_in_the_terminal_area(self, definition):
        """좌표 변환이 어긋나면 항적이 엉뚱한 곳에 놓인다."""
        for item in definition.aircraft:
            for state in (item.initial_state, *item.scheduled_states):
                assert math.hypot(state.x_nm, state.y_nm) < 80.0

    def test_altitudes_are_plausible(self, definition):
        for item in definition.aircraft:
            for state in (item.initial_state, *item.scheduled_states):
                assert -100.0 <= state.altitude_ft <= 45_000.0

    def test_the_conversion_round_trips(self):
        """국지 좌표와 위경도가 서로를 되돌리지 못하면 두 계층이 다른 곳을 본다."""
        from sentry_atm.geo.coordinate import rktu_local_to_geodetic

        for x_nm, y_nm in ((0.0, 0.0), (12.5, -8.25), (-30.0, 22.0)):
            position = rktu_local_to_geodetic(x_nm, y_nm)
            back = rktu_geodetic_to_local(position.latitude_deg, position.longitude_deg)
            assert back.x_nm == pytest.approx(x_nm, abs=1e-6)
            assert back.y_nm == pytest.approx(y_nm, abs=1e-6)


class TestAnchorCompression:
    """표본을 앵커로 줄이면서 항적이 달라지지 않았는가."""

    def test_anchors_are_fewer_than_samples_but_not_trivially_few(self, definition):
        anchors = sum(1 + len(a.scheduled_states) for a in definition.aircraft)
        assert 500 <= anchors <= 1_200

    def test_reconstruction_stays_within_the_observation_noise(self, definition):
        """수평 오차는 원본 표본의 관측잡음(약 56 m/표본)보다 크면 안 된다."""
        import random

        from sentry_atm.domain.units import knots_to_nm_per_second
        from sentry_atm.regulation import data as regulation_data
        from sentry_atm.regulation import schedule as schedule_module
        from sentry_atm.regulation import sortie as sortie_module
        from sentry_atm.regulation import synth as synth_module
        from sentry_atm.scenario import sortie_builder as builder

        dataset = regulation_data.load()
        timetable = schedule_module.build(
            dataset, window=builder.SORTIE_DEFAULT_WINDOW, seed=builder.SORTIE_DEFAULT_SEED
        )
        scenario = sortie_module.build(
            dataset,
            timetable,
            area_id=builder.SORTIE_DEFAULT_AREA,
            patrol_sorties=builder.SORTIE_DEFAULT_PATROL_SORTIES,
        )
        scenario.build()
        rng = random.Random(builder.SORTIE_DEFAULT_SEED)
        tracks = builder._make_tracks(
            dataset, synth_module.build(dataset), builder._runway_events(scenario), rng
        )

        worst_nm = 0.0
        worst_ft = 0.0
        for _, _, track in tracks:
            kept = builder._decimate(track.samples)
            index = 0
            for sample in track.samples:
                while index + 1 < len(kept) and kept[index + 1].t_s <= sample.t_s:
                    index += 1
                anchor = kept[index]
                elapsed = sample.t_s - anchor.t_s
                distance = knots_to_nm_per_second(anchor.gs_kt) * elapsed
                heading = math.radians(anchor.track_deg)
                origin = rktu_geodetic_to_local(anchor.lat, anchor.lon)
                truth = rktu_geodetic_to_local(sample.lat, sample.lon)
                worst_nm = max(
                    worst_nm,
                    math.hypot(
                        origin.x_nm + distance * math.sin(heading) - truth.x_nm,
                        origin.y_nm + distance * math.cos(heading) - truth.y_nm,
                    ),
                )
                worst_ft = max(
                    worst_ft,
                    abs(anchor.alt_ft + anchor.vs_fpm * elapsed / 60.0 - sample.alt_ft),
                )

        # 수평 최저치 3 NM, 수직 최저치 1,000 ft 에 견주어 판정을 뒤집을 수 없는
        # 크기여야 한다.
        assert worst_nm < 0.2
        assert worst_ft < 100.0
