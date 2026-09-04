"""13단계 소티를 시뮬레이터가 돌릴 수 있는 시나리오로 만든다.

골든 데모는 8대가 5분 동안 전부 떠 있는 고정 배치였다. 소티는 다르다 — 75분에
15대가 들고 나며, 동시에 떠 있는 것은 많아야 다섯 대다. 그것이 청주의 실제
교통량(시간당 8회)이고, 밀도를 부풀리면 아래에서 나오는 숫자가 전부 거짓이 된다.

이 모듈은 규정 계층이 이미 만들어 놓은 것을 옮겨 담기만 한다. 활주로 순서도,
체공도, 복귀 경로도 여기서 다시 계산하지 않는다 — 시나리오가 규정을 다시
해석하기 시작하면 두 벌이 되고, 두 벌은 반드시 어긋난다.

옮기면서 세 가지를 다룬다.

**좌표계.** 규정 계층은 위경도로, 시뮬레이터는 RKTU 중심 국지 x/y 로 항적을
다룬다. `geo.coordinate` 의 WGS84 접평면을 쓴다.

**퇴장.** 시뮬레이터의 항공기는 등장은 하지만 퇴장할 수단이 없었다. 착륙한
항공기가 활주로를 지나 계속 직진하면 그 유령이 계속 분리 판정 대상이 된다.
`ScenarioAircraft.exit_time_utc` 를 이번에 추가해 그것을 막는다.

**출격과 복귀 사이.** 전투기는 출격 항적과 복귀 항적 사이에 13분의 공백이 있다.
그 사이 항공기는 터미널 구역을 떠나 작전지역에서 임무를 수행한다. 두 항적은
서로 47 NM 떨어진 곳에서 끝나고 시작하므로, 이으려면 규정 계층이 만들지 않은
항적을 지어내야 한다. 그러지 않는다 — SENTRY 는 터미널 구역 판단 도구이고,
작전지역의 항공기는 애초에 이 도구의 관할이 아니다. 그 구간에는 항공기가 화면에
없고, 그것이 사실에 가깝다. `ScenarioAircraft.presence` 가 그 구조를 담는다.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

from sentry_atm.domain import (
    AircraftMetadata,
    AircraftState,
    DataSource,
    EmergencyStatus,
    EmergencyType,
    FlightPhase,
)
from sentry_atm.geo.coordinate import rktu_geodetic_to_local
from sentry_atm.reference_data import (
    POC_AIRCRAFT_TYPES,
    PROFILE_ID_BY_CATEGORY,
    wake_category_for,
)
from sentry_atm.regulation import data as regulation_data
from sentry_atm.regulation import schedule as schedule_module
from sentry_atm.regulation import sortie as sortie_module
from sentry_atm.regulation import synth as synth_module
from sentry_atm.scenario.event import (
    EmergencyDeclaredPayload,
    EmergencyReasonCategory,
    ScenarioEvent,
    ScenarioEventType,
)
from sentry_atm.scenario.model import ScenarioAircraft, ScenarioDefinition

SORTIE_SCENARIO_ID = "RKTU_SORTIE_V1"
SORTIE_START_UTC = datetime(2026, 9, 1, 0, 0, tzinfo=UTC)
"""시나리오 t=0. 한국시 09:00 에 해당한다 (KST = UTC+9)."""

SORTIE_DEFAULT_SEED = 4
SORTIE_DEFAULT_WINDOW = ("09:00", "10:00")
SORTIE_DEFAULT_AREA = "MOA 3A"
SORTIE_DEFAULT_PATROL_SORTIES = 3

# 앵커를 새로 찍는 기준. 표본을 전부 앵커로 두면 같은 항적을 표본 수만큼의
# 객체로 들고 있게 되고, 성기게 잡으면 등속 직선이 실제 항적에서 벗어난다.
#
# 값은 재구성 오차를 재서 정했다. 수평 오차는 어떤 값에서도 약 277 m 아래로
# 내려가지 않는데, 그것은 압축 손실이 아니라 원본 표본에 실린 관측잡음이다
# (합성기의 `radar_noise_nm` 0.03 NM ≈ 56 m — ASR 정확도 규모). 연속한 두
# 표본만 등속으로 이어도 최대 301 m 가 나오므로 그 아래로는 줄일 수 없다.
#
# 실제로 줄일 수 있는 것은 고도 오차뿐이다. 200 fpm 에서 371 ft 였던 것이
# 50 fpm 에서 23 ft 가 된다. 수직 최저치가 1,000 ft 이므로 371 ft 는 판정을
# 뒤집을 수 있고 23 ft 는 그럴 수 없다. 그 대가는 앵커 595 → 848 개다.
_TRACK_TOLERANCE_DEG = 0.5
_SPEED_TOLERANCE_KT = 2.0
_VERTICAL_TOLERANCE_FPM = 50.0

_CATEGORY_BY_TYPE = {t.type_code: t.category for t in POC_AIRCRAFT_TYPES}


def _phase_of(state, *, departure: bool) -> FlightPhase:
    """수직속도와 고도로 비행단계를 정한다.

    규정 계층의 항적은 단계를 들고 다니지 않는다 — 규정 판정에 필요 없기
    때문이다. 시뮬레이터 쪽은 필요하므로 여기서 붙인다.
    """
    if state.vs_fpm > 300.0:
        return FlightPhase.CLIMB
    if state.vs_fpm < -300.0:
        return FlightPhase.FINAL if state.alt_ft < 3_000.0 else FlightPhase.DESCENT
    if departure and state.alt_ft < 3_000.0:
        return FlightPhase.CLIMB
    if state.alt_ft < 3_000.0:
        return FlightPhase.APPROACH
    return FlightPhase.LEVEL


def _to_local_state(
    aircraft_id: str,
    state,
    t_s: float,
    *,
    departure: bool,
    emergency: bool = False,
) -> AircraftState:
    """규정 계층 항적 하나를 시뮬레이터 항적으로."""
    position = rktu_geodetic_to_local(state.lat, state.lon)
    return AircraftState(
        aircraft_id=aircraft_id,
        timestamp_utc=SORTIE_START_UTC + timedelta(seconds=t_s),
        x_nm=position.x_nm,
        y_nm=position.y_nm,
        altitude_ft=state.alt_ft,
        ground_speed_kt=state.gs_kt,
        # 바람이 없다는 가정 아래 항적각을 침로로 쓴다. `regulation.bridge` 가
        # 반대 방향으로 같은 가정을 쓰므로, 바람이 들어오면 양쪽이 함께 틀린다.
        heading_deg=state.track_deg % 360.0,
        vertical_speed_fpm=state.vs_fpm,
        source=DataSource.SYNTHETIC,
        flight_phase=_phase_of(state, departure=departure),
        emergency_status=(
            EmergencyStatus.DECLARED if emergency else EmergencyStatus.NONE
        ),
        emergency_type=EmergencyType.PRIORITY_RETURN if emergency else None,
        wake_category=wake_category_for(state.actype),
    )


def _needs_anchor(previous, current) -> bool:
    """이 표본에서 등속 구간이 끊기는가."""
    track_change = abs((current.track_deg - previous.track_deg + 180.0) % 360.0 - 180.0)
    return (
        track_change > _TRACK_TOLERANCE_DEG
        or abs(current.gs_kt - previous.gs_kt) > _SPEED_TOLERANCE_KT
        or abs(current.vs_fpm - previous.vs_fpm) > _VERTICAL_TOLERANCE_FPM
    )


def _decimate(samples) -> list:
    """등속 구간의 시작점만 남긴다.

    시뮬레이터는 앵커 사이를 등속 직선으로 채운다. 그러므로 운동이 변하지 않는
    표본은 앵커로 둘 이유가 없다 — 같은 항적을 표본 수만큼의 객체로 들고 있게
    될 뿐이다. 마지막 표본은 항상 남긴다. 그것이 퇴장 시각을 정한다.
    """
    if not samples:
        return []
    kept = [samples[0]]
    for sample in samples[1:-1]:
        if _needs_anchor(kept[-1], sample):
            kept.append(sample)
    if len(samples) > 1:
        kept.append(samples[-1])
    return kept


def _runway_events(sortie_scenario) -> list:
    """실제로 활주로를 쓰는 사건 전부 — (기체, 확정 시각).

    `with_sortie` 가 전체 교통이고 `final` 은 비상 이후 재배치된 꼬리다. 둘을
    합치되 재배치된 항적은 `final` 의 시각을 쓴다. 비상기는 **출격과 복귀로 두
    번** 활주로를 쓰므로 도착 사건을 따로 더한다 — 한 번만 세면 복귀 항적이
    통째로 사라진다.
    """
    final_by = {slot.op.callsign: slot for slot in sortie_scenario.final.slots}
    out = []
    for slot in sortie_scenario.with_sortie.slots:
        matched = final_by.get(slot.op.callsign)
        time_s = (
            matched.time_s
            if (matched is not None and matched.op.op is slot.op.op)
            else slot.time_s
        )
        out.append((slot.op, time_s))
    recovery = final_by.get(sortie_scenario.fighter_callsign)
    if recovery is not None and not recovery.op.is_departure:
        out.append((recovery.op, recovery.time_s))
    return out


def _make_tracks(dataset, generator, events, rng) -> list:
    """활주로 사건마다 항적 하나. 같은 콜사인이 두 번 나올 수 있다."""
    out = []
    for op, time_s in events:
        if op.is_departure:
            roll_s = dataset.fleet.departure_roll_s(op.actype, op.wake_cat)
            intent = generator.departure_intent(rng, op.callsign, 0.0, actype=op.actype)
            track = generator.synth.fly_departure(intent, rng)
            # 도착의 `shift_to` 는 마지막 표본(시단)을 맞추지만, 출발은 첫
            # 표본이 부양 시점이므로 기준이 반대다.
            delta = (time_s + roll_s) - track.samples[0].t_s
            track = synth_module.Trajectory(
                track.callsign,
                track.actype,
                track.wake_cat,
                [replace(s, t_s=s.t_s + delta) for s in track.samples],
                track.dt_s,
            )
            out.append((op, True, track))
        else:
            intent = generator.random_intent(rng, op.callsign, 0.0)
            intent = replace(intent, actype=op.actype, wake_cat=op.wake_cat)
            track = generator.synth.fly(intent, rng)
            out.append((op, False, synth_module.shift_to(track, time_s)))
    return out


def _metadata(aircraft_id: str, actype: str) -> AircraftMetadata:
    category = _CATEGORY_BY_TYPE.get(actype)
    if category is None:
        raise ValueError(f"성능 포락선이 없는 기종: {actype}")
    return AircraftMetadata(
        aircraft_id=aircraft_id,
        aircraft_type=actype,
        category=category,
        performance_class=PROFILE_ID_BY_CATEGORY[category],
        wake_category=wake_category_for(actype),
    )


@dataclass(frozen=True, slots=True)
class SortiePlan:
    """시나리오와 13단계를 **같은 시간축 위에서** 함께 들고 있는다.

    둘을 따로 만들면 각자 시간 원점을 정하게 되고, 그러면 시연에서 짚는 단계와
    화면의 항적이 어긋난다. 어긋난 것은 눈에 잘 띄지 않는다 — 둘 다 그럴듯하게
    움직이기 때문이다.
    """

    definition: ScenarioDefinition
    steps: tuple[sortie_module.Step, ...]
    """시각이 시나리오 원점 기준으로 옮겨진 13단계."""


def build_sortie_plan(
    *,
    window: tuple[str, str] = SORTIE_DEFAULT_WINDOW,
    seed: int = SORTIE_DEFAULT_SEED,
    area_id: str = SORTIE_DEFAULT_AREA,
    patrol_sorties: int = SORTIE_DEFAULT_PATROL_SORTIES,
    dataset=None,
) -> SortiePlan:
    """13단계 소티를 시나리오와 단계 목록으로.

    같은 seed 는 같은 결과를 낸다. 시연에서 매번 다른 항적이 나오면 무엇을
    보여 주는지 설명할 수 없고, 시험도 고정할 수 없다.
    """
    dataset = dataset or regulation_data.load()
    timetable = schedule_module.build(dataset, window=window, seed=seed)
    scenario = sortie_module.build(
        dataset, timetable, area_id=area_id, patrol_sorties=patrol_sorties
    )
    steps = tuple(scenario.build())

    rng = random.Random(seed)
    generator = synth_module.build(dataset)
    tracks = _make_tracks(dataset, generator, _runway_events(scenario), rng)

    # 시간축을 0 부터. 시나리오 시각이 근무일의 초 단위라 그대로 두면 시작이
    # 09:15 같은 값이 되고, 시연에서 경과시간을 읽기 어렵다.
    shift_s = -min(track.samples[0].t_s for _, _, track in tracks)

    fighter = scenario.fighter_callsign
    by_callsign: dict[str, list] = {}
    departure_flag: dict[str, bool] = {}
    actype: dict[str, str] = {}
    for op, is_departure, track in tracks:
        samples = [replace(s, t_s=s.t_s + shift_s) for s in track.samples]
        by_callsign.setdefault(op.callsign, []).append((is_departure, samples))
        departure_flag.setdefault(op.callsign, is_departure)
        actype[op.callsign] = op.actype

    recovery_t_s: float | None = None
    aircraft: list[ScenarioAircraft] = []

    for callsign, legs in by_callsign.items():
        legs.sort(key=lambda item: item[1][0].t_s)
        merged: list = []
        windows: list[tuple[datetime, datetime]] = []
        for _, samples in legs:
            merged.extend(samples)
            windows.append(
                (
                    SORTIE_START_UTC + timedelta(seconds=samples[0].t_s),
                    # 마지막 표본에서 1초 뒤에 화면을 뜬다. 같은 시각으로 두면
                    # 반열린 구간이라 착륙 순간이 통째로 빠진다.
                    SORTIE_START_UTC + timedelta(seconds=samples[-1].t_s + 1.0),
                )
            )
        is_departure = departure_flag[callsign]

        # 비상 선언 시각은 규정 계층의 소티 모델이 정한다. 복귀 항적이 시작하는
        # 시각을 쓰면 안 된다 — 합성된 접근 항적은 임무 시간선보다 길어서, 아직
        # 정상으로 들어오는 구간까지 비상으로 칠하게 된다. 그러면 화면에서 비상
        # 선언이라는 사건 자체가 사라지고, 항공기는 처음부터 비상인 채로 나타난다.
        emergency_from_t_s: float | None = None
        if callsign == fighter and scenario.sortie.recovery_declared_s is not None:
            emergency_from_t_s = scenario.sortie.recovery_declared_s + shift_s
            recovery_t_s = emergency_from_t_s

        anchors = _decimate(merged)
        states = [
            _to_local_state(
                callsign,
                sample,
                sample.t_s,
                departure=is_departure,
                emergency=(
                    emergency_from_t_s is not None and sample.t_s >= emergency_from_t_s
                ),
            )
            for sample in anchors
        ]
        aircraft.append(
            ScenarioAircraft(
                metadata=_metadata(callsign, actype[callsign]),
                initial_state=states[0],
                scheduled_states=tuple(states[1:]),
                presence=tuple(windows),
            )
        )

    aircraft.sort(key=lambda item: (item.initial_state.timestamp_utc, item.aircraft_id))

    events: tuple[ScenarioEvent, ...] = ()
    if recovery_t_s is not None:
        events = (
            ScenarioEvent(
                event_id=f"EVT-{fighter}-EMERGENCY",
                event_type=ScenarioEventType.EMERGENCY_DECLARED,
                scheduled_time_utc=SORTIE_START_UTC + timedelta(seconds=recovery_t_s),
                target_aircraft_id=fighter,
                payload=EmergencyDeclaredPayload(
                    emergency_type=EmergencyType.PRIORITY_RETURN,
                    reason_category=EmergencyReasonCategory.AIRCRAFT_CONDITION,
                ),
            ),
        )

    return SortiePlan(
        definition=ScenarioDefinition(
            scenario_id=SORTIE_SCENARIO_ID,
            start_time_utc=SORTIE_START_UTC,
            aircraft=tuple(aircraft),
            events=events,
        ),
        # 단계 시각도 항적과 같은 만큼 옮긴다. 규정 계층은 근무일의 초 단위로
        # 세고(09:00 = 32,400) 시나리오는 0 부터 세므로, 옮기지 않으면 13단계가
        # 전부 시나리오 끝 너머에 놓인다.
        steps=tuple(replace(step, t_s=step.t_s + shift_s) for step in steps),
    )


def build_sortie_scenario(**kwargs) -> ScenarioDefinition:
    """13단계 소티를 하나의 `ScenarioDefinition` 으로."""
    return build_sortie_plan(**kwargs).definition


def build_sortie_steps(**kwargs) -> tuple[sortie_module.Step, ...]:
    """시연에서 짚고 넘어갈 13단계. 시각은 시나리오 원점 기준이다."""
    return build_sortie_plan(**kwargs).steps


__all__ = [
    "SORTIE_DEFAULT_AREA",
    "SORTIE_DEFAULT_PATROL_SORTIES",
    "SORTIE_DEFAULT_SEED",
    "SORTIE_DEFAULT_WINDOW",
    "SORTIE_SCENARIO_ID",
    "SORTIE_START_UTC",
    "SortiePlan",
    "build_sortie_plan",
    "build_sortie_scenario",
    "build_sortie_steps",
]
