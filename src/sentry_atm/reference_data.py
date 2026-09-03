"""청주(RKTU) 운용 기종과 성능 프로파일.

기종 목록은 지어내지 않는다. `sentry_atm.regulation` 의 전사 데이터
(`reference/aircraft.json`)에서 읽으며, 그 파일이 유일한 출처다. 여기서 이름과
등급을 다시 적으면 두 벌이 되고 언젠가 어긋난다.

**성능 프로파일은 여전히 가정값이고, 범주 단위로 둔다.** 전사 데이터가 가진 것은
최종접근속도·활주로 점유시간처럼 분리 판정에 쓰는 값이고, 후보 기동의 실행가능성을
보는 데 필요한 포락선(최저·최고속도, 상승·강하 한계, 상승한도)은 아니다. 기종마다
포락선을 만들면 같은 범주 안에서 전부 같은 수치가 복제될 뿐이므로, 출처가 밝히는
대로(`CATEGORY_ENVELOPE`) 범주당 하나만 둔다. 실제 제원을 확보하면 기종별로
쪼개면 된다.
"""

from __future__ import annotations

from sentry_atm.domain import (
    AircraftCategory,
    AircraftPerformanceProfile,
    AircraftType,
    PerformanceDataSource,
    WakeCategory,
)
from sentry_atm.regulation.data import load

FLEET_SOURCE_REFERENCE = (
    "AIP RKTU + OpenAP / 제작사 공개 성능자료 "
    "(regulation/reference/aircraft.json)"
)
ENVELOPE_SOURCE_REFERENCE = "ASM-013:SENTRY_POC_CATEGORY_ENVELOPE_V1"
POC_SOURCE_REFERENCE = ENVELOPE_SOURCE_REFERENCE

# 전사 데이터의 role → sentry_atm 의 운용 범주.
_ROLE_TO_CATEGORY = {
    "airliner": AircraftCategory.AIRLINER,
    "fast_jet": AircraftCategory.FAST_JET,
    "transport": AircraftCategory.TRANSPORT,
    "rotorcraft": AircraftCategory.UNKNOWN,
}

# 후류 등급 문자열 → 도메인 Enum.
_WAKE = {c.value: c for c in WakeCategory}

# 역할별 성능 포락선. 후보 기동이 기체 성능을 넘지 않는지 보는 용도이며,
# 분리 최저치와 달리 고시에 수치가 없어 대표값으로 둔다.
_ENVELOPE = {
    AircraftCategory.AIRLINER: dict(
        min_speed_kt=130.0, max_speed_kt=350.0,
        max_climb_rate_fpm=2_500.0, max_descent_rate_fpm=3_000.0,
        max_turn_rate_deg_per_second=3.0, ceiling_ft=39_000.0,
    ),
    AircraftCategory.FAST_JET: dict(
        min_speed_kt=160.0, max_speed_kt=480.0,
        max_climb_rate_fpm=6_000.0, max_descent_rate_fpm=6_000.0,
        max_turn_rate_deg_per_second=6.0, ceiling_ft=50_000.0,
    ),
    AircraftCategory.TRANSPORT: dict(
        min_speed_kt=110.0, max_speed_kt=320.0,
        max_climb_rate_fpm=2_000.0, max_descent_rate_fpm=2_500.0,
        max_turn_rate_deg_per_second=3.0, ceiling_ft=35_000.0,
    ),
}


# 범주 → 포락선 프로파일 id. 기존 식별자를 유지한다 — 포락선의 내용이 아니라
# 기종 목록이 바뀐 것이므로, 이 id 를 바꾸면 무관한 참조가 함께 깨진다.
PROFILE_ID_BY_CATEGORY = {
    AircraftCategory.AIRLINER: "AIRLINER-POC-V1",
    AircraftCategory.FAST_JET: "FAST-JET-POC-V1",
    AircraftCategory.TRANSPORT: "TRANSPORT-POC-V1",
}


def _build() -> tuple[
    tuple[AircraftType, ...],
    tuple[AircraftPerformanceProfile, ...],
    dict[str, WakeCategory],
]:
    fleet = load().fleet.raw["types"]
    types: list[AircraftType] = []
    wake: dict[str, WakeCategory] = {}

    for code, spec in fleet.items():
        role = spec.get("role", "airliner")
        category = _ROLE_TO_CATEGORY.get(role, AircraftCategory.UNKNOWN)
        wake[code] = _WAKE[spec["wake_cat"]]
        if category is AircraftCategory.UNKNOWN:
            # 회전익은 고정익 시퀀스와 분리 처리 대상이라 본 과제 범위 밖이다.
            # 등급은 남기되 기종 목록에는 넣지 않는다.
            continue
        name = spec.get("name", code)
        manufacturer, _, model = name.partition(" ")
        types.append(
            AircraftType(
                type_code=code,
                category=category,
                manufacturer=manufacturer or None,
                model=model or name,
            )
        )

    profiles = tuple(
        AircraftPerformanceProfile(
            profile_id=PROFILE_ID_BY_CATEGORY[category],
            category=category,
            source=PerformanceDataSource.SIMULATION_ASSUMPTION,
            source_reference=ENVELOPE_SOURCE_REFERENCE,
            **envelope,
        )
        for category, envelope in _ENVELOPE.items()
    )
    return tuple(types), profiles, wake


POC_AIRCRAFT_TYPES, POC_PERFORMANCE_PROFILES, WAKE_BY_TYPE_CODE = _build()


def wake_category_for(type_code: str | None) -> WakeCategory | None:
    """기종 코드 → 후류 등급. 모르는 기종은 None 이다.

    모르는 기종을 중형으로 메우지 않는다. 등급을 잘못 짚으면 후류 종렬 요건이
    실제보다 짧아질 수 있고, 그 오차는 조용히 흐른다.
    """
    if type_code is None:
        return None
    return WAKE_BY_TYPE_CODE.get(type_code)


__all__ = [
    "ENVELOPE_SOURCE_REFERENCE",
    "PROFILE_ID_BY_CATEGORY",
    "FLEET_SOURCE_REFERENCE",
    "POC_AIRCRAFT_TYPES",
    "POC_PERFORMANCE_PROFILES",
    "POC_SOURCE_REFERENCE",
    "WAKE_BY_TYPE_CODE",
    "wake_category_for",
]
