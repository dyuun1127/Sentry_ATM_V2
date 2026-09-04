"""국지 x/y 항적을 규정 엔진이 읽는 위경도 항적으로 옮긴다.

`sentry_atm` 은 RKTU 기준점 중심의 국지 x/y NM 으로 항적을 다루고, 규정 엔진은
AIP 전사 좌표와 같은 위경도로 다룬다. 활주로 시단·공고 체공장주·제한구역·고시
픽스가 전부 위경도에 있으므로, 그것들과 무엇 하나라도 대조하려면 이 변환을
거쳐야 한다.

변환 자체의 정확도는 `geo.coordinate` 가 책임진다 — WGS84 곡률반경을 쓰며 쌍 거리
오차가 2m 미만이다.

**침로와 항적각을 구분하지 않는다.** 합성 시뮬레이터에 바람이 없어 둘이 같기
때문이며, 바람이 들어오면 여기가 먼저 틀린다. 그때는 풍향수정각을 반영해야 한다.
"""

from __future__ import annotations

from sentry_atm.domain.aircraft import AircraftState as LocalAircraftState
from sentry_atm.domain.enums import EmergencyStatus
from sentry_atm.geo.coordinate import LocalPosition, LocalTangentPlane, rktu_local_to_geodetic

from .state import AircraftState as GeodeticAircraftState

# 후류 등급을 모르는 항적의 기본값. 규정 엔진의 상태 객체가 등급을 요구하므로
# 무언가는 넣어야 하지만, 이 값으로 후류 종렬을 판정하면 안 된다 —
# `wake_category_known` 로 걸러서 쓴다.
_UNKNOWN_WAKE_PLACEHOLDER = "중형"


def wake_category_known(state: LocalAircraftState) -> bool:
    """이 항적의 후류 등급이 실제로 알려져 있는가.

    모르는 등급을 기본값으로 메운 채 후류 종렬(5-5-4 사·아)을 판정하면 요건이
    실제보다 짧아질 수 있고, 그 오차는 드러나지 않는다.
    """
    return getattr(state, "wake_category", None) is not None


def to_geodetic_state(
    state: LocalAircraftState,
    *,
    frame: LocalTangentPlane | None = None,
    t_s: float = 0.0,
) -> GeodeticAircraftState:
    """국지 항적 하나를 규정 엔진 항적으로."""
    if frame is None:
        position = rktu_local_to_geodetic(state.x_nm, state.y_nm)
    else:
        position = frame.to_geodetic(LocalPosition(x_nm=state.x_nm, y_nm=state.y_nm))

    wake = getattr(state, "wake_category", None)
    return GeodeticAircraftState(
        callsign=state.aircraft_id,
        lat=position.latitude_deg,
        lon=position.longitude_deg,
        alt_ft=state.altitude_ft,
        # 바람이 없으므로 침로를 항적각으로 그대로 쓴다.
        track_deg=state.heading_deg,
        gs_kt=state.ground_speed_kt,
        vs_fpm=state.vertical_speed_fpm,
        actype=getattr(state, "aircraft_type", "") or "",
        wake_cat=str(wake) if wake is not None else _UNKNOWN_WAKE_PLACEHOLDER,
        emergency=state.emergency_status is EmergencyStatus.DECLARED,
        t_s=t_s,
    )


def to_geodetic_states(
    states,
    *,
    frame: LocalTangentPlane | None = None,
    t_s: float = 0.0,
) -> tuple[GeodeticAircraftState, ...]:
    """여러 항적을 한 번에."""
    return tuple(to_geodetic_state(s, frame=frame, t_s=t_s) for s in states)


__all__ = ["to_geodetic_state", "to_geodetic_states", "wake_category_known"]
