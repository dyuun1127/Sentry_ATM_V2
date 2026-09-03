"""항적 상태 표현.

단위 규약 — 이 규약을 프로젝트 전체에서 지킨다.

    거리   NM
    고도   ft (AMSL. AGL 이 필요한 곳은 이름에 명시)
    속도   kt (= NM/h) 지상속도
    상승률 ft/min
    시간   s
    방위   deg, 진북 기준 0~360
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

KT_TO_NM_PER_S = 1.0 / 3600.0
FPM_TO_FT_PER_S = 1.0 / 60.0

# 후류 등급 — 고시 5-5-4 사·아항 (민·군 공통 적용되는 초대형/대형/중형/소형)
WAKE_CATEGORIES = ("초대형", "대형", "중형", "소형")


@dataclass(frozen=True)
class AircraftState:
    """한 시점의 항적 상태.

    불변 객체로 두고 `advance()` 가 새 인스턴스를 돌려준다. 시뮬레이터가
    상태를 덮어쓰지 못하게 해서, 예측·회피 후보 평가에서 원본이 오염되지 않도록 한다.
    """

    callsign: str
    lat: float
    lon: float
    alt_ft: float
    track_deg: float
    gs_kt: float
    vs_fpm: float = 0.0
    actype: str = ""
    wake_cat: str = "중형"
    emergency: bool = False
    t_s: float = 0.0

    target_alt_ft: float | None = None
    """배정고도. 주어지면 여기서 수평면 유지(level-off)하고 상승·강하를 멈춘다.

    등속 외삽만 쓰면 "1,000ft 상승" 지시가 600초 뒤 10,000ft 상승으로 계산되어
    회피안 평가가 통째로 틀린다. 관제 지시는 목표고도까지의 지시이지
    무한정 상승하라는 지시가 아니다.
    """

    def __post_init__(self) -> None:
        if self.wake_cat not in WAKE_CATEGORIES:
            raise ValueError(
                f"{self.callsign}: 후류 등급 {self.wake_cat!r} 은 고시 등급이 아니다 "
                f"(허용: {', '.join(WAKE_CATEGORIES)})"
            )
        if self.gs_kt < 0:
            raise ValueError(f"{self.callsign}: 지상속도가 음수")

    # --- 속도 성분 ---

    @property
    def v_east_kt(self) -> float:
        return self.gs_kt * math.sin(math.radians(self.track_deg))

    @property
    def v_north_kt(self) -> float:
        return self.gs_kt * math.cos(math.radians(self.track_deg))

    @property
    def level_off_time_s(self) -> float | None:
        """목표고도에 도달하는 시각 (현재로부터 초). 없으면 None."""
        if self.target_alt_ft is None or self.vs_fpm == 0.0:
            return None
        remaining = self.target_alt_ft - self.alt_ft
        if remaining == 0.0:
            return 0.0
        if remaining * self.vs_fpm <= 0.0:
            return None  # 목표에서 멀어지는 방향 — 지시와 상승률이 어긋남
        return remaining / self.vs_fpm * 60.0

    def altitude_at(self, dt_s: float) -> float:
        """dt 초 뒤 고도. 목표고도에서 멈춘다."""
        alt = self.alt_ft + self.vs_fpm * dt_s * FPM_TO_FT_PER_S
        if self.target_alt_ft is None:
            return alt
        if self.vs_fpm > 0.0:
            return min(alt, max(self.target_alt_ft, self.alt_ft))
        if self.vs_fpm < 0.0:
            return max(alt, min(self.target_alt_ft, self.alt_ft))
        return alt

    @property
    def flight_level(self) -> str:
        """전이고도(14,000ft) 이상은 FL 표기, 미만은 ft 표기 — 관제 용어."""
        if self.alt_ft >= 14000:
            return f"FL{round(self.alt_ft / 100):03d}"
        return f"{round(self.alt_ft / 100) * 100:,} ft"

    def advance(self, dt_s: float) -> AircraftState:
        """등속·등침로·등상승률로 dt 초 진행한 상태.

        물리 예측의 기준선이자 CPA 해석해의 전제이기도 하다. 선회·강하 프로파일은
        상위 계층(항적예측)이 침로·상승률을 갱신해 반영한다.
        """
        from .geo import curvature_radii, M_PER_NM

        r_mer, r_pri = curvature_radii(self.lat)
        d_north_nm = self.v_north_kt * dt_s * KT_TO_NM_PER_S
        d_east_nm = self.v_east_kt * dt_s * KT_TO_NM_PER_S
        lat = self.lat + math.degrees(d_north_nm * M_PER_NM / r_mer)
        lon = self.lon + math.degrees(
            d_east_nm * M_PER_NM / (r_pri * math.cos(math.radians(self.lat)))
        )
        alt = self.altitude_at(dt_s)
        vs = self.vs_fpm
        if self.target_alt_ft is not None and alt == self.target_alt_ft:
            vs = 0.0  # 수평면 유지 도달
        return replace(
            self, lat=lat, lon=lon, alt_ft=alt, vs_fpm=vs, t_s=self.t_s + dt_s
        )


@dataclass(frozen=True)
class RelativeState:
    """두 항적의 상대 기하 — CPA 판정의 입력.

    상대 위치는 두 기의 평균위도에서 잡은 타원체 평면 변위이므로
    분리 최저치 규모에서 사실상 정확하다 (geo.enu_offset_nm 참조).
    """

    r_east_nm: float
    r_north_nm: float
    r_alt_ft: float
    v_east_kt: float
    v_north_kt: float
    v_alt_fpm: float

    @property
    def horizontal_nm(self) -> float:
        """현재 수평 이격."""
        return math.hypot(self.r_east_nm, self.r_north_nm)

    @property
    def vertical_ft(self) -> float:
        """현재 수직 이격 (절댓값)."""
        return abs(self.r_alt_ft)

    @property
    def closing_speed_kt(self) -> float:
        """수평 접근률. 양수면 접근 중, 음수면 이격 중."""
        h = self.horizontal_nm
        if h == 0.0:
            return math.hypot(self.v_east_kt, self.v_north_kt)
        return -(self.r_east_nm * self.v_east_kt + self.r_north_nm * self.v_north_kt) / h


def relative_state(a: AircraftState, b: AircraftState) -> RelativeState:
    """a 에서 본 b 의 상대 상태."""
    from .geo import enu_offset_nm

    east, north = enu_offset_nm(a.lat, a.lon, b.lat, b.lon)
    return RelativeState(
        r_east_nm=east,
        r_north_nm=north,
        r_alt_ft=b.alt_ft - a.alt_ft,
        v_east_kt=b.v_east_kt - a.v_east_kt,
        v_north_kt=b.v_north_kt - a.v_north_kt,
        v_alt_fpm=b.vs_fpm - a.vs_fpm,
    )
