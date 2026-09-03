"""충돌 기하 — CPA 해석해와 보호실린더 침범 구간.

이 모듈은 순수 기하만 다룬다. 분리 최저치가 얼마인지는 규정(rules.py)이 정하고,
여기서는 "주어진 실린더를 언제 침범하는가"만 계산한다. 안전 판정을 규정과
기하로 나눠 두면 AIRAC/고시가 바뀌어도 기하 코드는 손대지 않는다.

**시간 루프를 돌지 않는다.** 등속 가정 하에서 침범 구간은 이차부등식의 해이므로
닫힌 형태로 나온다. 1초 간격 샘플링은 실린더를 스쳐 지나가는 조우를 놓치지만
(샘플 사이에서만 위반), 해석해는 놓치지 않는다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .state import AircraftState, RelativeState, relative_state

# 등속 가정이 무너지는 지점. 고시가 정하는 값이 아니라 모델의 유효 범위다.
DEFAULT_LOOKAHEAD_S = 600.0

_EPS = 1e-12


@dataclass(frozen=True)
class CPA:
    """최근접점 (Closest Point of Approach)."""

    t_s: float
    """최근접 시각 (초). 음수면 이미 지나 이격 중."""

    horizontal_nm: float
    """최근접 시각의 수평 이격."""

    vertical_ft: float
    """최근접 시각의 수직 이격 (절댓값)."""

    @property
    def is_diverging(self) -> bool:
        """이미 최근접점을 지나 벌어지는 중인가."""
        return self.t_s < 0.0


@dataclass(frozen=True)
class ConflictWindow:
    """보호실린더를 동시에 침범하는 시간 구간.

    수평·수직 최저치를 **동시에** 위반해야 충돌이다. 실린더이지 구가 아니므로
    수평 접근 구간과 수직 접근 구간의 교집합을 구한다. CPA 한 시점만 보면
    수평 최근접과 수직 최근접이 다른 시각에 오는 조우를 오판한다.
    """

    entry_s: float
    """침범 시작 시각 (초). 0 이면 이미 위반 중."""

    exit_s: float
    """침범 종료 시각 (초)."""

    cpa: CPA
    h_min_nm: float
    v_min_ft: float

    @property
    def time_to_violation_s(self) -> float:
        """예지시간 — 지금부터 분리위반까지 남은 시간."""
        return max(0.0, self.entry_s)

    @property
    def is_active(self) -> bool:
        """이미 분리위반 상태인가."""
        return self.entry_s <= 0.0 < self.exit_s

    @property
    def duration_s(self) -> float:
        return self.exit_s - self.entry_s


def _interval_horizontal(
    rel: RelativeState, h_min_nm: float
) -> tuple[float, float] | None:
    """수평 이격이 h_min 미만인 시간 구간 (초). 없으면 None.

    |r + v·t| < H  ⟺  (v·v)t² + 2(r·v)t + (r·r − H²) < 0
    """
    # kt(NM/h) → NM/s
    vx = rel.v_east_kt / 3600.0
    vy = rel.v_north_kt / 3600.0
    rx, ry = rel.r_east_nm, rel.r_north_nm

    a = vx * vx + vy * vy
    b = 2.0 * (rx * vx + ry * vy)
    c = rx * rx + ry * ry - h_min_nm * h_min_nm

    if a < _EPS:
        # 상대속도 0 — 이격이 변하지 않는다. 지금 위반이면 영원히 위반.
        return (-math.inf, math.inf) if c < 0.0 else None

    disc = b * b - 4.0 * a * c
    if disc <= 0.0:
        return None  # 실린더에 닿지 않거나 스치기만 함
    root = math.sqrt(disc)
    return ((-b - root) / (2.0 * a), (-b + root) / (2.0 * a))


def _interval_vertical(rel: RelativeState, v_min_ft: float) -> tuple[float, float] | None:
    """수직 이격이 v_min 미만인 시간 구간 (초). 없으면 None.

    상대 상승률이 일정하다는 전제 — 수평면 유지가 있으면
    `_vertical_intervals_piecewise` 를 쓴다.
    """
    vz = rel.v_alt_fpm / 60.0  # fpm → ft/s
    rz = rel.r_alt_ft

    if abs(vz) < _EPS:
        return (-math.inf, math.inf) if abs(rz) < v_min_ft else None

    t1 = (-v_min_ft - rz) / vz
    t2 = (v_min_ft - rz) / vz
    return (t1, t2) if t1 <= t2 else (t2, t1)


def _vertical_breakpoints(a: AircraftState, b: AircraftState, horizon_s: float) -> list[float]:
    """상대 고도 프로파일이 꺾이는 시각들 — 각 기의 수평면 유지 도달 시점."""
    out = [0.0]
    for ac in (a, b):
        t = ac.level_off_time_s
        if t is not None and 0.0 < t < horizon_s:
            out.append(t)
    out.append(horizon_s)
    return sorted(set(out))


def _vertical_intervals_piecewise(
    a: AircraftState, b: AircraftState, v_min_ft: float, horizon_s: float
) -> list[tuple[float, float]]:
    """수직 이격이 v_min 미만인 구간들 — 수평면 유지를 반영한 구간선형 해.

    각 기의 고도는 배정고도에서 멈추므로 상대 고도는 꺾임점이 최대 2개인
    구간선형 함수다. 구간마다 일차부등식을 풀어 합집합을 만든다.
    등속 외삽만 쓰면 "1,000ft 상승" 지시가 지평 끝에서 10,000ft 상승이 되어
    회피안이 실제보다 훨씬 효과적으로 보인다.
    """
    out: list[tuple[float, float]] = []
    for t0, t1 in zip(bp := _vertical_breakpoints(a, b, horizon_s), bp[1:], strict=False):
        rz0 = b.altitude_at(t0) - a.altitude_at(t0)
        span = t1 - t0
        if span <= 0.0:
            continue
        rz1 = b.altitude_at(t1) - a.altitude_at(t1)
        vz = (rz1 - rz0) / span  # ft/s

        if abs(vz) < _EPS:
            if abs(rz0) < v_min_ft:
                out.append((t0, t1))
            continue

        s1 = (-v_min_ft - rz0) / vz
        s2 = (v_min_ft - rz0) / vz
        lo, hi = (s1, s2) if s1 <= s2 else (s2, s1)
        lo, hi = max(lo, 0.0) + t0, min(hi, span) + t0
        if lo < hi:
            out.append((lo, hi))

    # 인접 구간 병합
    merged: list[tuple[float, float]] = []
    for lo, hi in out:
        if merged and lo <= merged[-1][1] + _EPS:
            merged[-1] = (merged[-1][0], max(merged[-1][1], hi))
        else:
            merged.append((lo, hi))
    return merged


def cpa(rel: RelativeState) -> CPA:
    """최근접점 해석해.

    t* = −(r·v)/(v·v). 수평 기준으로 잡는다 — 분리 판정의 1차 기준이 수평이고,
    수직은 실린더 판정에서 따로 본다.
    """
    vx = rel.v_east_kt / 3600.0
    vy = rel.v_north_kt / 3600.0
    rx, ry = rel.r_east_nm, rel.r_north_nm

    vv = vx * vx + vy * vy
    if vv < _EPS:
        t = 0.0
    else:
        t = -(rx * vx + ry * vy) / vv

    hx = rx + vx * t
    hy = ry + vy * t
    vert = abs(rel.r_alt_ft + (rel.v_alt_fpm / 60.0) * t)
    return CPA(t_s=t, horizontal_nm=math.hypot(hx, hy), vertical_ft=vert)


def detect_conflict(
    rel: RelativeState,
    h_min_nm: float,
    v_min_ft: float,
    lookahead_s: float = DEFAULT_LOOKAHEAD_S,
) -> ConflictWindow | None:
    """보호실린더 침범 구간을 구한다. 침범이 없으면 None.

    Args:
        rel: 상대 기하.
        h_min_nm: 수평 분리 최저치 (고시 5-5-4).
        v_min_ft: 수직 분리 최저치 (고시 4-5-1).
        lookahead_s: 등속 가정의 유효 범위. 이 시간 이후의 침범은 보지 않는다.
    """
    hi = _interval_horizontal(rel, h_min_nm)
    if hi is None:
        return None
    vi = _interval_vertical(rel, v_min_ft)
    if vi is None:
        return None

    entry = max(hi[0], vi[0])
    exit_ = min(hi[1], vi[1])
    if entry >= exit_:
        return None  # 수평·수직 침범 구간이 겹치지 않음 — 충돌 아님

    # 과거 구간은 잘라내되, 이미 위반 중(entry<0<exit)인 경우는 살린다.
    if exit_ <= 0.0:
        return None
    if entry > lookahead_s:
        return None

    return ConflictWindow(
        entry_s=entry,
        exit_s=min(exit_, math.inf),
        cpa=cpa(rel),
        h_min_nm=h_min_nm,
        v_min_ft=v_min_ft,
    )


def pair_conflict(
    a: AircraftState,
    b: AircraftState,
    h_min_nm: float,
    v_min_ft: float,
    lookahead_s: float = DEFAULT_LOOKAHEAD_S,
) -> ConflictWindow | None:
    """항적 두 기의 보호실린더 침범 구간.

    어느 한쪽이라도 배정고도(수평면 유지)를 가지고 있으면 구간선형 수직 해를 쓴다.
    """
    rel = relative_state(a, b)
    if a.target_alt_ft is None and b.target_alt_ft is None:
        return detect_conflict(rel, h_min_nm, v_min_ft, lookahead_s)

    hi = _interval_horizontal(rel, h_min_nm)
    if hi is None:
        return None
    verticals = _vertical_intervals_piecewise(a, b, v_min_ft, lookahead_s)
    if not verticals:
        return None

    best: tuple[float, float] | None = None
    for vlo, vhi in verticals:
        entry = max(hi[0], vlo)
        exit_ = min(hi[1], vhi)
        if entry < exit_ and exit_ > 0.0 and entry <= lookahead_s:
            if best is None or entry < best[0]:
                best = (entry, exit_)
    if best is None:
        return None

    return ConflictWindow(
        entry_s=best[0],
        exit_s=best[1],
        cpa=cpa(rel),
        h_min_nm=h_min_nm,
        v_min_ft=v_min_ft,
    )


# 진로선은 평면의 직선이 아니라 측지선(대권)이다. RNAV TF 구간과 로컬라이저
# 연장선 모두 대권이므로, 평면 직선으로 근사하면 8NM 에서 10m, 30NM 에서 수백 m
# 어긋난다. 아래 두 함수는 대권 기준으로 계산한다.
#
#   XTD = asin(sin δ₁₃ · sin(θ₁₃ − θ₁₂)) · R
#   ATD = acos(cos δ₁₃ / cos(XTD/R)) · R
#
# δ₁₃·θ₁₃ 는 타원체(Vincenty)로 구하고 투영 관계만 구면식을 쓴다.

_R_NM = 3440.069528437724  # 지구 평균반경 (NM)


def cross_track_offset_nm(
    aircraft: AircraftState, ref_lat: float, ref_lon: float, course_deg: float
) -> float:
    """기준점에서 진로 방향으로 뻗은 대권에서 벗어난 측방 거리 (NM). 우측이 양수.

    최종접근 연장 중심선 정렬(JOIN) 판정, 항적난기류 측방 게이트(고시 5-5-4 사 1),
    비행계획 대비 이탈 감시에 쓴다.
    """
    from .geo import vincenty_inverse

    dist_m, brg, _ = vincenty_inverse(ref_lat, ref_lon, aircraft.lat, aircraft.lon)
    if dist_m == 0.0:
        return 0.0
    delta = (dist_m / 1852.0) / _R_NM
    dtheta = math.radians(brg - course_deg)
    return math.asin(max(-1.0, min(1.0, math.sin(delta) * math.sin(dtheta)))) * _R_NM


def _along_track_nm(
    ref_lat: float, ref_lon: float, lat: float, lon: float, course_deg: float
) -> float:
    """기준점에서 진로 방향으로 잰 종방향 거리 (NM). 진로 반대쪽이면 음수."""
    from .geo import vincenty_inverse

    dist_m, brg, _ = vincenty_inverse(ref_lat, ref_lon, lat, lon)
    if dist_m == 0.0:
        return 0.0
    delta = (dist_m / 1852.0) / _R_NM
    dtheta = math.radians(brg - course_deg)
    xtd = math.asin(max(-1.0, min(1.0, math.sin(delta) * math.sin(dtheta))))
    ratio = math.cos(delta) / math.cos(xtd)
    atd = math.acos(max(-1.0, min(1.0, ratio))) * _R_NM
    return atd if math.cos(dtheta) >= 0.0 else -atd


def along_track_separation_nm(
    leader: AircraftState, follower: AircraftState, course_deg: float
) -> float:
    """지정한 진로 기준 종렬(along-track) 이격.

    항적난기류 분리는 실린더가 아니라 **같은 진로 위의 종렬 거리** 요건이다
    (고시 5-5-4 사·아항). 최종접근 종렬 판정에 쓴다.

    Returns:
        선행기가 앞선 거리 (NM). 음수면 후행기가 앞서 있다는 뜻이므로
        호출부가 선후 관계를 잘못 잡았다는 신호다.
    """
    return _along_track_nm(
        follower.lat, follower.lon, leader.lat, leader.lon, course_deg
    )
