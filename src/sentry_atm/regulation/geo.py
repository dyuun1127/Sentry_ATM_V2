"""측지 계산 — AIP 좌표 파싱, WGS84 거리·방위, 국지 평면 좌표계.

세 가지 용도에 각각 다른 도구를 쓴다. 정확도 수치는 tests/unit/regulation/test_geo.py 에서 실측한다.

1. AIP 절차 검증 — `vincenty_inverse`
   AIP가 고시한 구간 거리·트랙은 WGS84 측지선 값이므로 역해로 대조한다.

2. 분리 판정·CPA — `enu_offset_nm` / `separation_distance_nm`
   두 항공기의 평균위도에서 타원체 곡률반경을 잡는 평면 근사. 이격 3NM 에서
   오차 0.01cm, 30NM 에서 15cm 로 사실상 정확하다. 안전 판정은 전부 이것을 쓴다.

3. 지도 표출 — `LocalFrame`
   공항 기준점 하나를 원점으로 고정한 좌표계. 원점에서 멀어질수록 축척이 어긋나
   30NM 지점에서 반경거리 오차가 0.037NM 이다. 화면 좌표용이며 분리 판정에는
   쓰지 않는다.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

# WGS84 타원체 제원
WGS84_A = 6_378_137.0           # 장반경 (m)
WGS84_F = 1.0 / 298.257223563   # 편평률
WGS84_B = WGS84_A * (1.0 - WGS84_F)

M_PER_NM = 1852.0
FT_PER_M = 3.280839895013123

# AIP 좌표 표기 두 가지를 모두 받는다.
#   AD 2.12 형식: 364330.38N / 1273040.05E   (도분초 붙여쓰기)
#   차트 형식:    36°43'30.4"N / 127°30'40.1"E
_RE_PACKED = re.compile(r"^(?P<d>\d{2,3})(?P<m>\d{2})(?P<s>\d{2}(?:\.\d+)?)(?P<h>[NSEW])$")
_RE_SYMBOL = re.compile(
    "^(?P<d>\\d{1,3})\\s*[°º]\\s*(?P<m>\\d{1,2})\\s*['′]\\s*"
    "(?P<s>\\d{1,2}(?:\\.\\d+)?)\\s*[\"″’']{0,2}\\s*(?P<h>[NSEW])$"
)


def parse_latlon(text: str) -> float:
    """AIP 좌표 문자열 하나를 십진도로 변환한다. 남위·서경은 음수."""
    t = text.strip().replace(" ", "")
    m = _RE_SYMBOL.match(t) or _RE_PACKED.match(t)
    if not m:
        raise ValueError("AIP 좌표 형식이 아님: " + repr(text))
    deg = int(m["d"]) + int(m["m"]) / 60.0 + float(m["s"]) / 3600.0
    return -deg if m["h"] in ("S", "W") else deg


def parse_point(lat_text: str, lon_text: str) -> tuple[float, float]:
    """(위도, 경도) 문자열 쌍을 십진도 튜플로."""
    return parse_latlon(lat_text), parse_latlon(lon_text)


def vincenty_inverse(
    lat1: float, lon1: float, lat2: float, lon2: float
) -> tuple[float, float, float]:
    """WGS84 측지선 역해.

    Returns:
        (거리 m, 시작점 정방위 deg, 도착점 정방위 deg). 방위는 0~360 진북 기준.
    """
    if abs(lat1 - lat2) < 1e-12 and abs(lon1 - lon2) < 1e-12:
        return 0.0, 0.0, 0.0

    f = WGS84_F
    L = math.radians(lon2 - lon1)
    U1 = math.atan((1 - f) * math.tan(math.radians(lat1)))
    U2 = math.atan((1 - f) * math.tan(math.radians(lat2)))
    sinU1, cosU1 = math.sin(U1), math.cos(U1)
    sinU2, cosU2 = math.sin(U2), math.cos(U2)

    lam = L
    sin_sigma = cos_sigma = sigma = sin_alpha = cos2_alpha = cos_2sigma_m = 0.0
    for _ in range(200):
        sin_lam, cos_lam = math.sin(lam), math.cos(lam)
        sin_sigma = math.hypot(cosU2 * sin_lam, cosU1 * sinU2 - sinU1 * cosU2 * cos_lam)
        if sin_sigma == 0.0:
            return 0.0, 0.0, 0.0
        cos_sigma = sinU1 * sinU2 + cosU1 * cosU2 * cos_lam
        sigma = math.atan2(sin_sigma, cos_sigma)
        sin_alpha = cosU1 * cosU2 * sin_lam / sin_sigma
        cos2_alpha = 1.0 - sin_alpha * sin_alpha
        cos_2sigma_m = (
            cos_sigma - 2.0 * sinU1 * sinU2 / cos2_alpha if cos2_alpha != 0.0 else 0.0
        )
        C = f / 16.0 * cos2_alpha * (4.0 + f * (4.0 - 3.0 * cos2_alpha))
        lam_prev = lam
        lam = L + (1.0 - C) * f * sin_alpha * (
            sigma
            + C * sin_sigma * (cos_2sigma_m + C * cos_sigma * (-1.0 + 2.0 * cos_2sigma_m**2))
        )
        if abs(lam - lam_prev) < 1e-12:
            break
    else:  # pragma: no cover - 대척점 근처에서만 발생, 본 과제 범위 밖
        raise ValueError("Vincenty 역해가 수렴하지 않음")

    u2 = cos2_alpha * (WGS84_A**2 - WGS84_B**2) / WGS84_B**2
    A = 1.0 + u2 / 16384.0 * (4096.0 + u2 * (-768.0 + u2 * (320.0 - 175.0 * u2)))
    B = u2 / 1024.0 * (256.0 + u2 * (-128.0 + u2 * (74.0 - 47.0 * u2)))
    d_sigma = (
        B
        * sin_sigma
        * (
            cos_2sigma_m
            + B
            / 4.0
            * (
                cos_sigma * (-1.0 + 2.0 * cos_2sigma_m**2)
                - B
                / 6.0
                * cos_2sigma_m
                * (-3.0 + 4.0 * sin_sigma**2)
                * (-3.0 + 4.0 * cos_2sigma_m**2)
            )
        )
    )
    dist = WGS84_B * A * (sigma - d_sigma)

    sin_lam, cos_lam = math.sin(lam), math.cos(lam)
    brg1 = math.atan2(cosU2 * sin_lam, cosU1 * sinU2 - sinU1 * cosU2 * cos_lam)
    brg2 = math.atan2(cosU1 * sin_lam, -sinU1 * cosU2 + cosU1 * sinU2 * cos_lam)
    return dist, math.degrees(brg1) % 360.0, math.degrees(brg2) % 360.0


def distance_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """두 점 사이 측지 거리 (NM)."""
    return vincenty_inverse(lat1, lon1, lat2, lon2)[0] / M_PER_NM


def bearing_true(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """시작점에서의 진방위 (deg)."""
    return vincenty_inverse(lat1, lon1, lat2, lon2)[1]


def vincenty_direct(
    lat: float, lon: float, bearing_deg: float, distance_m: float
) -> tuple[float, float]:
    """WGS84 측지선 정해 — 한 점에서 방위·거리만큼 나아간 점."""
    f, a, b = WGS84_F, WGS84_A, WGS84_B
    alpha1 = math.radians(bearing_deg)
    sin_a1, cos_a1 = math.sin(alpha1), math.cos(alpha1)
    tanU1 = (1 - f) * math.tan(math.radians(lat))
    cosU1 = 1 / math.hypot(1, tanU1)
    sinU1 = tanU1 * cosU1
    sigma1 = math.atan2(tanU1, cos_a1)
    sin_alpha = cosU1 * sin_a1
    cos2_alpha = 1 - sin_alpha**2
    u2 = cos2_alpha * (a**2 - b**2) / b**2
    A = 1 + u2 / 16384 * (4096 + u2 * (-768 + u2 * (320 - 175 * u2)))
    B = u2 / 1024 * (256 + u2 * (-128 + u2 * (74 - 47 * u2)))

    sigma = distance_m / (b * A)
    for _ in range(200):
        cos_2sm = math.cos(2 * sigma1 + sigma)
        sin_s, cos_s = math.sin(sigma), math.cos(sigma)
        d_sigma = (
            B
            * sin_s
            * (
                cos_2sm
                + B
                / 4
                * (
                    cos_s * (-1 + 2 * cos_2sm**2)
                    - B / 6 * cos_2sm * (-3 + 4 * sin_s**2) * (-3 + 4 * cos_2sm**2)
                )
            )
        )
        sigma_new = distance_m / (b * A) + d_sigma
        if abs(sigma_new - sigma) < 1e-12:
            sigma = sigma_new
            break
        sigma = sigma_new

    cos_2sm = math.cos(2 * sigma1 + sigma)
    sin_s, cos_s = math.sin(sigma), math.cos(sigma)
    lat2 = math.atan2(
        sinU1 * cos_s + cosU1 * sin_s * cos_a1,
        (1 - f) * math.hypot(sin_alpha, sinU1 * sin_s - cosU1 * cos_s * cos_a1),
    )
    lam = math.atan2(sin_s * sin_a1, cosU1 * cos_s - sinU1 * sin_s * cos_a1)
    C = f / 16 * cos2_alpha * (4 + f * (4 - 3 * cos2_alpha))
    L = lam - (1 - C) * f * sin_alpha * (
        sigma + C * sin_s * (cos_2sm + C * cos_s * (-1 + 2 * cos_2sm**2))
    )
    return math.degrees(lat2), (lon + math.degrees(L) + 540) % 360 - 180


def curvature_radii(lat_deg: float) -> tuple[float, float]:
    """주어진 위도에서의 자오선·묘유선 곡률반경 (m)."""
    phi = math.radians(lat_deg)
    e2 = WGS84_F * (2.0 - WGS84_F)
    w = math.sqrt(1.0 - e2 * math.sin(phi) ** 2)
    return WGS84_A * (1.0 - e2) / w**3, WGS84_A / w


def enu_offset_nm(
    lat_ref: float, lon_ref: float, lat: float, lon: float
) -> tuple[float, float]:
    """기준점에서 대상점까지의 (동쪽, 북쪽) 변위 (NM).

    두 점의 평균위도에서 곡률반경을 잡으므로 짧은 이격에서 사실상 정확하다.
    분리 판정과 CPA 상대기하의 원시 연산 — 항공기 쌍마다 새로 계산한다.
    """
    r_mer, r_pri = curvature_radii((lat_ref + lat) / 2.0)
    north = math.radians(lat - lat_ref) * r_mer / M_PER_NM
    east = (
        math.radians(lon - lon_ref)
        * r_pri
        * math.cos(math.radians((lat_ref + lat) / 2.0))
        / M_PER_NM
    )
    return east, north


def separation_distance_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """분리 판정용 수평거리 (NM). 고시 5-5-4 의 수평 분리 최저치와 비교하는 값."""
    east, north = enu_offset_nm(lat1, lon1, lat2, lon2)
    return math.hypot(east, north)


@dataclass(frozen=True)
class LocalFrame:
    """공항 중심 국지 평면 좌표계 (ENU, 단위 NM) — 지도 표출용.

    원점 위도의 곡률반경으로 선형화하므로 원점에서 멀어질수록 축척이 어긋난다.
    30NM 지점에서 반경거리 오차 0.037NM. 화면 좌표 산출에는 충분하지만
    분리 판정에는 쓰지 않는다 — 그쪽은 `separation_distance_nm` 을 쓴다.
    """

    lat0: float
    lon0: float

    @property
    def _radii(self) -> tuple[float, float]:
        return curvature_radii(self.lat0)

    def to_xy(self, lat: float, lon: float) -> tuple[float, float]:
        """위경도 → (동쪽 x, 북쪽 y) NM."""
        r_mer, r_pri = self._radii
        y = math.radians(lat - self.lat0) * r_mer / M_PER_NM
        x = math.radians(lon - self.lon0) * r_pri * math.cos(math.radians(self.lat0)) / M_PER_NM
        return x, y

    def to_latlon(self, x_nm: float, y_nm: float) -> tuple[float, float]:
        """(동쪽 x, 북쪽 y) NM → 위경도."""
        r_mer, r_pri = self._radii
        lat = self.lat0 + math.degrees(y_nm * M_PER_NM / r_mer)
        lon = self.lon0 + math.degrees(
            x_nm * M_PER_NM / (r_pri * math.cos(math.radians(self.lat0)))
        )
        return lat, lon


def true_to_magnetic(true_deg: float, var_deg_west: float) -> float:
    """진방위 → 자방위. 편차는 서편차를 양수로 준다 (RKTU: 9°W → 9.0)."""
    return (true_deg + var_deg_west) % 360.0


def magnetic_to_true(mag_deg: float, var_deg_west: float) -> float:
    """자방위 → 진방위."""
    return (mag_deg - var_deg_west) % 360.0


def angular_diff(a_deg: float, b_deg: float) -> float:
    """두 방위의 부호 있는 최소 차이 [-180, 180).

    정확히 180° 벌어진 경우 -180 을 돌려준다 (좌우 구분이 없는 경우이므로 무방).
    """
    return (a_deg - b_deg + 180.0) % 360.0 - 180.0
