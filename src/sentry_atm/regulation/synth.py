"""합성 항적 생성기 — 학습 3축의 토대.

**설계의 핵심은 "잔차가 학습 가능해야 한다"는 것이다.**

물리 기준선(등속 외삽)과 같은 모델로 항적을 만들고 백색잡음만 얹으면 잔차에
구조가 없어 학습이 아무것도 배우지 못한다. 이전 구현에서 항적예측 개선이
0.7% 에 그친 것이 그 경우다. 그래서 여기서는 등속 외삽으로는 표현되지 않는
**구조화된 편차**를 넣는다.

    바람장          위치·고도에 따라 변하며 예측기는 이 값을 모른다.
                    풍향수정각이 생겨 기수와 항적이 어긋난다.
    선회 유도        다음 픽스를 향해 선회하며, 픽스 도달 전에 미리 돈다.
                    → "공항 상대 방위" 특성이 있어야 학습되는 신호
    강하 프로파일     배정고도를 유지하다 최종접근에서 3° 활공로를 따른다.
                    → "활공로 대비 고도 여유" 특성이 있어야 학습되는 신호
    속도 스케줄       시단 거리에 따라 최종접근속도로 감속한다.
    조종기법 편차     기체마다 선회 시점·강하 시점·속도가 조금씩 다르다.
    레이더 관측잡음   위치에 무작위 오차.

항공역학 모델은 기수(heading) + 진대기속도(TAS) + 바람 = 대지속도로 제대로 푼다.
관측되는 것은 항적(track)과 대지속도이며, 예측기는 바람과 조종기법을 모른다.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from .geo import (
    M_PER_NM,
    angular_diff,
    bearing_true,
    curvature_radii,
    separation_distance_nm,
    vincenty_direct,
)
from .rules import RuleBook
from .state import AircraftState

FT_PER_NM = 6076.11548556


# ----------------------------------------------------------------------
# 바람장
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class WindField:
    """고도·위치에 따라 변하는 바람. 예측기는 이 값을 모른다.

    실제 바람은 고도에 따라 세지고 방향이 도는(에크만 나선) 경향이 있으므로
    그 구조를 단순화해 넣는다. 공간 변화는 완만한 정현파로 준다 — 난류가 아니라
    **계통 편차**여야 학습이 잡아낼 수 있다.
    """

    surface_dir_deg: float = 250.0
    """지표 풍향 (바람이 불어오는 방향, 진북 기준)."""

    surface_speed_kt: float = 12.0
    shear_kt_per_1000ft: float = 3.5
    veer_deg_per_1000ft: float = 4.0
    spatial_amp_kt: float = 4.0
    spatial_scale_nm: float = 25.0
    origin: tuple[float, float] = (36.71639, 127.4992)

    def at(self, lat: float, lon: float, alt_ft: float) -> tuple[float, float]:
        """(동쪽, 북쪽) 바람 성분 (kt)."""
        kft = alt_ft / 1000.0
        speed = self.surface_speed_kt + self.shear_kt_per_1000ft * kft
        direction = (self.surface_dir_deg + self.veer_deg_per_1000ft * kft) % 360.0

        # 풍향은 불어오는 방향이므로 벡터는 그 반대
        rad = math.radians(direction + 180.0)
        east = speed * math.sin(rad)
        north = speed * math.cos(rad)

        r_mer, r_pri = curvature_radii(self.origin[0])
        dy = math.radians(lat - self.origin[0]) * r_mer / M_PER_NM
        dx = (
            math.radians(lon - self.origin[1])
            * r_pri
            * math.cos(math.radians(self.origin[0]))
            / M_PER_NM
        )
        k = 2.0 * math.pi / self.spatial_scale_nm
        east += self.spatial_amp_kt * math.sin(k * dy)
        north += self.spatial_amp_kt * math.cos(k * dx)
        return east, north


# ----------------------------------------------------------------------
# 조종기법 편차
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class PilotTechnique:
    """기체·조종사마다 다른 습관. 예측기는 이 값을 모른다."""

    turn_anticipation_nm: float = 1.0
    """픽스 도달 전 미리 선회를 시작하는 거리."""

    bank_deg: float = 22.0
    """선회 뱅크각. 클수록 빨리 돈다."""

    descent_start_bias_nm: float = 0.0
    """활공로 **포착 시점**을 앞당기거나 늦추는 편차.

    포착 이후에는 활공로를 따라간다 — 편차가 영구 평행 이탈이 되면 안 된다.
    """

    speed_bias_kt: float = 0.0
    """목표 속도 편차."""

    vs_limit_fpm: float = 1800.0

    climb_bias: float = 1.0
    """SID 상승구배 대비 실제 상승률 배수.

    고시된 구배는 **최저** 요구치이고 실제로는 그보다 가파르게 오른다. 기체 중량과
    추력 설정에 따라 차이가 크며(전투기는 훨씬 크다), 예측기는 이 값을 모른다 —
    강하 쪽의 `descent_start_bias_nm` 에 대응하는 상승 쪽 미지 편차다.
    """

    @classmethod
    def sample(cls, rng: random.Random) -> PilotTechnique:
        return cls(
            turn_anticipation_nm=rng.uniform(0.4, 2.0),
            bank_deg=rng.uniform(18.0, 27.0),
            descent_start_bias_nm=rng.gauss(0.0, 0.8),
            speed_bias_kt=rng.gauss(0.0, 4.0),
            vs_limit_fpm=rng.uniform(1200.0, 2200.0),
            climb_bias=rng.uniform(1.05, 1.45),
        )


# ----------------------------------------------------------------------
# 비행 의도
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class ControlEvent:
    """비행 중 내려오는 관제 지시.

    **항적예측이 원리적으로 맞힐 수 없는 부분**이다. 관제사의 판단은 항공기
    상태에 담겨 있지 않으므로, 이 사건이 예측 정확도의 상한을 만든다.
    이런 사건이 없으면 합성 항적은 현재 상태로부터 미래가 거의 완전히 결정되어
    학습이 유도 법칙을 외우는 문제가 되고, 개선율이 비현실적으로 높게 나온다.
    또한 σ 가 표현할 환원 불가능한 불확실성 자체가 사라진다.
    """

    kind: str
    """'PATH_STRETCH' (경로 연장 벡터링) | 'SPEED' (속도 지시)"""

    trigger_dist_nm: float
    """시단까지 이 거리에서 발효."""

    magnitude: float
    """경로 연장이면 측방 오프셋 NM, 속도 지시면 속도 변화 kt."""


@dataclass
class FlightIntent:
    """한 대의 도착 계획."""

    callsign: str
    actype: str
    wake_cat: str
    entry_lat: float
    entry_lon: float
    entry_alt_ft: float
    entry_tas_kt: float
    route: list[tuple[float, float]]
    """통과할 지점들. 마지막은 활주로 시단."""

    assigned_alt_ft: float
    technique: PilotTechnique
    start_time_s: float = 0.0
    emergency: bool = False
    events: tuple[ControlEvent, ...] = ()


@dataclass
class DepartureIntent:
    """한 대의 출발 계획.

    도착과 달리 **지상 활주 구간은 항적에 넣지 않는다.** 활주로 위의 항공기는
    레이더 분리 대상이 아니라 활주로 자원 문제이고(고시 3-9-6), 그쪽은
    `runway.RunwayRules` 가 따로 계산한다. 여기서 만드는 것은 부양 이후의
    항적이며, `start_time_s` 는 **부양 시각**이다 — 이륙활주 시작 시각이 아니다.
    """

    callsign: str
    actype: str
    wake_cat: str
    sid: str
    transition: str
    cruise_alt_ft: float
    technique: PilotTechnique
    start_time_s: float = 0.0
    emergency: bool = False


# ----------------------------------------------------------------------
# 항적 생성
# ----------------------------------------------------------------------


@dataclass
class Trajectory:
    """한 대의 시계열."""

    callsign: str
    actype: str
    wake_cat: str
    samples: list[AircraftState]
    dt_s: float

    def at(self, t_s: float) -> AircraftState | None:
        i = int(round((t_s - self.samples[0].t_s) / self.dt_s))
        return self.samples[i] if 0 <= i < len(self.samples) else None

    @property
    def duration_s(self) -> float:
        return self.samples[-1].t_s - self.samples[0].t_s

    def __len__(self) -> int:
        return len(self.samples)


@dataclass
class TrajectorySynthesizer:
    """유도 법칙 + 바람 + 조종기법으로 항적을 만든다."""

    ds: object
    wind: WindField = field(default_factory=WindField)
    dt_s: float = 4.0
    radar_noise_nm: float = 0.03
    """레이더 관측잡음 표준편차. ASR 정확도 규모."""

    max_steps: int = 2000

    def __post_init__(self) -> None:
        rwy = self.ds.procedures.runways["24R"]
        self.thr = (rwy.thr_lat, rwy.thr_lon)
        self.thr_elev_ft = rwy.thr_elev_ft
        self.final_course = rwy.true_brg
        iap = self.ds.procedures.iap("RNP_24R")
        self.gs_angle = iap["gs_angle_deg"]
        self.tch_ft = iap["tch_ft"]
        turtu = self.ds.procedures.fix("TURTU")
        self.join_dist_nm = separation_distance_nm(turtu.lat, turtu.lon, *self.thr)
        self.faf_dist_nm = iap["faf_to_thr_nm"]
        self.faf_alt_ft = next(
            leg["alt_ft"] for leg in iap["final"] if leg.get("role") == "FAF"
        )
        self.if_alt_ft = next(
            leg["alt_ft"] for leg in iap["final"] if leg.get("role") == "IF"
        )

    # --- 프로파일 ---

    def glidepath_alt_ft(self, dist_nm: float) -> float:
        return (
            dist_nm * FT_PER_NM * math.tan(math.radians(self.gs_angle))
            + self.tch_ft
            + self.thr_elev_ft
        )

    def profile_alt_ft(self, dist_nm: float, assigned_ft: float) -> float:
        """시단 거리에 대응하는 절차 고도.

        AIP 의 RNP RWY 24R 수직 프로파일을 따른다 — 배정고도를 유지하다
        IF(TURTU, 3,700ft)로 강하하고, FAF(APAKI, 2,100ft)에서 3° 활공로에 올라탄다.
        FAF 바깥에서는 절차 고도가 활공로 연장선보다 **아래**에 있으므로
        "활공로 대비 고도 여유"가 구간마다 다른 값이 되고, 그것이 학습 신호가 된다.
        """
        if dist_nm <= self.faf_dist_nm:
            return self.glidepath_alt_ft(dist_nm)
        if dist_nm >= self.join_dist_nm:
            return assigned_ft
        # FAF ~ IF 구간을 선형으로 잇는다
        f = (dist_nm - self.faf_dist_nm) / (self.join_dist_nm - self.faf_dist_nm)
        top = max(self.if_alt_ft, min(assigned_ft, self.if_alt_ft))
        return self.faf_alt_ft + (top - self.faf_alt_ft) * f

    def target_speed_kt(self, dist_nm: float, final_kt: float, cruise_kt: float) -> float:
        """시단 거리에 따른 목표 속도.

        절차 속도 제한(230kt)과 최종접근속도 사이를 선형으로 잇는다.
        """
        if dist_nm <= 5.0:
            return final_kt
        if dist_nm >= 25.0:
            return cruise_kt
        f = (dist_nm - 5.0) / 20.0
        return final_kt + (cruise_kt - final_kt) * f

    # --- 생성 ---

    def fly(self, intent: FlightIntent, rng: random.Random) -> Trajectory:
        """의도대로 비행시켜 시계열을 만든다."""
        tech = intent.technique
        final_kt = self.ds.fleet.final_gs_kt(intent.actype, intent.wake_cat)
        cruise_kt = min(intent.entry_tas_kt, 230.0)

        lat, lon = intent.entry_lat, intent.entry_lon
        alt = intent.entry_alt_ft
        tas = intent.entry_tas_kt
        heading = bearing_true(lat, lon, *intent.route[0])
        t = intent.start_time_s
        leg = 0
        captured = False
        route = list(intent.route)
        pending = sorted(intent.events, key=lambda e: -e.trigger_dist_nm)
        speed_instruction = 0.0

        samples: list[AircraftState] = []
        for _ in range(self.max_steps):
            dist_thr = separation_distance_nm(lat, lon, *self.thr)

            # --- 관제 지시 발효 ---
            # 항공기 상태에 담겨 있지 않은 외부 개입. 예측기가 맞힐 수 없다.
            while pending and dist_thr <= pending[0].trigger_dist_nm:
                ev = pending.pop(0)
                if ev.kind == "SPEED":
                    speed_instruction = ev.magnitude
                elif ev.kind == "PATH_STRETCH":
                    # 경로 연장 벡터링 — 측방으로 벌렸다가 **연장 중심선에 재합류**시킨다.
                    # 벌린 지점에서 시단으로 직행시키면 정대하지 못한 채 착륙하게 된다.
                    side = (self.final_course + 90.0 * (1 if ev.magnitude > 0 else -1))
                    dog_lat, dog_lon = vincenty_direct(
                        lat, lon, side % 360.0, abs(ev.magnitude) * M_PER_NM
                    )
                    rejoin_nm = max(self.join_dist_nm, dist_thr * 0.55)
                    rj_lat, rj_lon = vincenty_direct(
                        *self.thr,
                        (self.final_course + 180.0) % 360.0,
                        rejoin_nm * M_PER_NM,
                    )
                    route[leg:leg] = [(dog_lat, dog_lon), (rj_lat, rj_lon)]

            # --- 활성 구간 갱신 (선회 예측) ---
            while leg < len(route) - 1:
                d_wpt = separation_distance_nm(lat, lon, *route[leg])
                if d_wpt <= tech.turn_anticipation_nm:
                    leg += 1
                else:
                    break

            target_track = bearing_true(lat, lon, *route[leg])

            # --- 바람과 풍향수정각 ---
            w_e, w_n = self.wind.at(lat, lon, alt)
            heading = self._steer(heading, target_track, tas, (w_e, w_n), tech)

            air_e = tas * math.sin(math.radians(heading))
            air_n = tas * math.cos(math.radians(heading))
            gnd_e, gnd_n = air_e + w_e, air_n + w_n
            gs = math.hypot(gnd_e, gnd_n)
            track = math.degrees(math.atan2(gnd_e, gnd_n)) % 360.0

            # --- 수직 프로파일 ---
            # 절차 고도가 현재 고도까지 내려오면 그때부터 절차를 따라 강하한다.
            # 조종기법 편차는 그 포착 시점만 앞당기거나 늦춘다.
            profile_now = self.profile_alt_ft(dist_thr, intent.assigned_alt_ft)
            trigger = self.profile_alt_ft(
                max(dist_thr + tech.descent_start_bias_nm, 0.0), intent.assigned_alt_ft
            )
            if not captured and trigger <= alt:
                captured = True
            target_alt = profile_now if captured else intent.assigned_alt_ft
            target_alt = max(min(target_alt, alt), self.thr_elev_ft)  # 재상승 금지
            vs = _rate_toward(alt, target_alt, tech.vs_limit_fpm, self.dt_s)

            # --- 속도 스케줄 ---
            # 속도 지시는 최종접근에 들어서면 해제된다 ("resume normal speed").
            # 유지시키면 B777 이 114kt 로 착륙하는 물리적으로 불가능한 항적이 나온다.
            fade = _clamp((dist_thr - 5.0) / 5.0, 0.0, 1.0)
            want = (
                self.target_speed_kt(dist_thr, final_kt, cruise_kt)
                + tech.speed_bias_kt
                + speed_instruction * fade
            )
            if dist_thr <= 10.0:
                want = max(want, final_kt)  # Vref 아래로는 날 수 없다
            tas += _clamp(want - tas, -1.2 * self.dt_s, 0.8 * self.dt_s)
            tas = max(tas, 60.0)

            # --- 관측 (레이더 잡음) ---
            olat, olon = lat, lon
            if self.radar_noise_nm > 0.0:
                olat, olon = vincenty_direct(
                    lat, lon, rng.uniform(0.0, 360.0),
                    abs(rng.gauss(0.0, self.radar_noise_nm)) * M_PER_NM,
                )

            samples.append(
                AircraftState(
                    callsign=intent.callsign, lat=olat, lon=olon, alt_ft=alt,
                    track_deg=track, gs_kt=gs, vs_fpm=vs,
                    actype=intent.actype, wake_cat=intent.wake_cat,
                    emergency=intent.emergency, t_s=t,
                )
            )

            if dist_thr < 0.4:
                break

            # --- 적분 ---
            lat, lon = _advance_latlon(lat, lon, gnd_e, gnd_n, self.dt_s)
            alt += vs * self.dt_s / 60.0
            t += self.dt_s

        return Trajectory(intent.callsign, intent.actype, intent.wake_cat, samples, self.dt_s)

    # --- 출발 ---

    def sid_route(self, sid: str, transition: str) -> tuple[list[tuple[float, float]], list[dict]]:
        """SID 전이의 통과 지점과 각 구간의 제약.

        좌표는 AIP 전사 웨이포인트에서 가져온다 — 침로·거리를 다시 적분하지 않는다.
        차트의 course/dist 는 검증용이고(`tools/validate_aip.py`), 비행에는 좌표를 쓴다.
        """
        legs = self.ds.procedures.sid(sid)["transitions"][transition]
        pts, cons = [], []
        for leg in legs:
            w = self.ds.procedures.fix(leg["wpt"])
            pts.append((w.lat, w.lon))
            cons.append(leg)
        return pts, cons

    def fly_departure(self, intent: DepartureIntent, rng: random.Random) -> Trajectory:
        """SID 를 따라 상승시켜 시계열을 만든다.

        상승률은 값을 지어내지 않고 **AIP 가 고시한 SID 상승구배**에서 낸다:
        rate_fpm = gradient_ft_per_nm × 대지속도(kt) / 60. 임의의 상승률을 쓰면
        구간 고도제약(AT / AT_OR_ABOVE)을 물리적으로 못 맞추는 항적이 나온다.
        """
        tech = intent.technique
        sid = self.ds.procedures.sid(intent.sid)
        gradient = sid["climb_gradient_ft_per_nm"]
        route, cons = self.sid_route(intent.sid, intent.transition)

        # 부양 지점 — 24R 의 이륙 종단(= 06L 시단 쪽). 활주 구간은 항적에 넣지 않는다.
        rwy = self.ds.procedures.runways["24R"]
        lat, lon = vincenty_direct(
            rwy.thr_lat, rwy.thr_lon, self.final_course, rwy.length_m
        )
        final_kt = self.ds.fleet.final_gs_kt(intent.actype, intent.wake_cat)
        climb_kt = self.ds.fleet.initial_climb_kt(intent.actype, intent.wake_cat)

        alt = self.thr_elev_ft + 50.0
        tas = 1.15 * final_kt  # 부양 속도 — Vref 보다 조금 빠르다
        heading = self.final_course
        t = intent.start_time_s
        leg = 0

        samples: list[AircraftState] = []
        for _ in range(self.max_steps):
            target_track = bearing_true(lat, lon, *route[leg])

            w_e, w_n = self.wind.at(lat, lon, alt)
            heading = self._steer(heading, target_track, tas, (w_e, w_n), tech)
            air_e = tas * math.sin(math.radians(heading))
            air_n = tas * math.cos(math.radians(heading))
            gnd_e, gnd_n = air_e + w_e, air_n + w_n
            gs = math.hypot(gnd_e, gnd_n)
            track = math.degrees(math.atan2(gnd_e, gnd_n)) % 360.0

            # --- 상승 제약 ---
            # 구간 고도제약이 있으면 그 고도가 상한이고, 없으면 SID 상승 상한까지,
            # 그 위로는 배정 순항고도까지 올라간다.
            ceiling = intent.cruise_alt_ft
            for c in cons[leg:]:
                if c.get("alt_cons") == "AT" and "alt_ft" in c:
                    ceiling = min(ceiling, c["alt_ft"])
                    break
            target_alt = min(ceiling, intent.cruise_alt_ft)
            climb_fpm = gradient * gs / 60.0 * tech.climb_bias
            vs = _rate_toward(alt, target_alt, min(climb_fpm, tech.vs_limit_fpm), self.dt_s)
            vs = max(vs, 0.0)  # SID 구간에서 강하하지 않는다

            # --- 속도 제약 ---
            want = climb_kt
            speed_max = cons[leg].get("speed_max_kt")
            if speed_max:
                want = min(want, speed_max)
            tas += _clamp(want - tas, -1.0 * self.dt_s, 1.5 * self.dt_s)

            olat, olon = lat, lon
            if self.radar_noise_nm > 0.0:
                olat, olon = vincenty_direct(
                    lat, lon, rng.uniform(0.0, 360.0),
                    abs(rng.gauss(0.0, self.radar_noise_nm)) * M_PER_NM,
                )

            samples.append(
                AircraftState(
                    callsign=intent.callsign, lat=olat, lon=olon, alt_ft=alt,
                    track_deg=track, gs_kt=gs, vs_fpm=vs,
                    actype=intent.actype, wake_cat=intent.wake_cat,
                    emergency=intent.emergency, t_s=t,
                )
            )

            # --- 구간 전환 ---
            if separation_distance_nm(lat, lon, *route[leg]) <= tech.turn_anticipation_nm:
                if leg >= len(route) - 1:
                    break
                leg += 1

            lat, lon = _advance_latlon(lat, lon, gnd_e, gnd_n, self.dt_s)
            alt += vs * self.dt_s / 60.0
            t += self.dt_s

        return Trajectory(intent.callsign, intent.actype, intent.wake_cat, samples, self.dt_s)

    def _steer(self, heading, target_track, tas, wind, tech) -> float:
        """목표 항적을 만들도록 기수를 돌린다 — 풍향수정각이 자연히 생긴다."""
        w_e, w_n = wind
        # 목표 항적 방향의 단위벡터에 수직한 바람 성분을 상쇄하는 기수
        rad = math.radians(target_track)
        cross = w_e * math.cos(rad) - w_n * math.sin(rad)
        wca = math.degrees(math.asin(_clamp(-cross / max(tas, 1.0), -0.9, 0.9)))
        want = (target_track + wca) % 360.0

        rate = _turn_rate_deg_per_s(tas, tech.bank_deg)
        return (heading + _clamp(angular_diff(want, heading), -rate * self.dt_s,
                                 rate * self.dt_s)) % 360.0


def _turn_rate_deg_per_s(tas_kt: float, bank_deg: float) -> float:
    """뱅크각과 속도로 정해지는 선회율. ω = g·tan(φ)/V"""
    g = 9.80665
    v = max(tas_kt, 1.0) * M_PER_NM / 3600.0
    return math.degrees(g * math.tan(math.radians(bank_deg)) / v)


def _rate_toward(current: float, target: float, limit_fpm: float, dt_s: float) -> float:
    need_fpm = (target - current) / (dt_s / 60.0)
    return _clamp(need_fpm, -limit_fpm, limit_fpm)


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _advance_latlon(lat, lon, gnd_e_kt, gnd_n_kt, dt_s):
    r_mer, r_pri = curvature_radii(lat)
    dn = gnd_n_kt * dt_s / 3600.0 * M_PER_NM
    de = gnd_e_kt * dt_s / 3600.0 * M_PER_NM
    return (
        lat + math.degrees(dn / r_mer),
        lon + math.degrees(de / (r_pri * math.cos(math.radians(lat)))),
    )


# ----------------------------------------------------------------------
# 시나리오
# ----------------------------------------------------------------------

CIVIL_TYPES = ["B738", "B38M", "A320", "A321", "B77W", "A333"]
MILITARY_TYPES = ["F35A", "KF16", "FA50", "F15K", "C130", "KC30", "CN35"]

# 진입 경로는 AIP 에 고시된 RNP RWY 24R 전이와 레이더 유도 두 갈래다.
#   HYEIN 전이 : HYEIN(IAF) → TURTU(IF) → 최종접근
#   IKAPO 전이 : IKAPO(IAF) → MENOL → TURTU(IF) → 최종접근
#   레이더 유도 : 청주 GCA 가 연장 중심선으로 유도 (CHEONGJU 1D 는 RADAR required)
#
# 고시되지 않은 픽스를 진입점으로 쓰면 TURTU 에서 급선회가 생겨 오버슈트한다.
TRANSITIONS = {
    "HYEIN": ["HYEIN", "TURTU"],
    "IKAPO": ["IKAPO", "MENOL", "TURTU"],
}


@dataclass
class ScenarioGenerator:
    """다수 항적 시나리오 생성."""

    ds: object
    synth: TrajectorySynthesizer

    military_ratio: float = 0.45
    """청주는 민·군 공용이며 17전투비행단이 주둔한다."""

    path_stretch_rate: float = 0.35
    """비행 중 경로 연장 벡터링을 받는 항적의 비율."""

    speed_instruction_rate: float = 0.45
    """비행 중 속도 지시를 받는 항적의 비율."""

    radar_vector_ratio: float = 0.5
    """레이더 유도 진입 비율. CHEONGJU 1D 는 RADAR required 이며
    청주 GCA 가 실제로 벡터링으로 정대시킨다."""

    def random_intent(
        self, rng: random.Random, callsign: str, start_time_s: float
    ) -> FlightIntent:
        military = rng.random() < self.military_ratio
        actype = rng.choice(MILITARY_TYPES if military else CIVIL_TYPES)
        cat = self.ds.fleet.wake_cat(actype)

        # 10분 지평 학습 표본을 뽑으려면 항적이 충분히 길어야 하므로
        # 진입 픽스 바깥에서 시작한다.
        route: list[tuple[float, float]] = []
        if rng.random() < self.radar_vector_ratio:
            # 레이더 유도 — 연장 중심선 16~24NM 지점으로 유도해 정대시킨다
            intercept_nm = rng.uniform(16.0, 24.0)
            ix, iy = vincenty_direct(
                *self.synth.thr,
                (self.synth.final_course + 180.0) % 360.0,
                intercept_nm * M_PER_NM,
            )
            # 중심선 한쪽에서 완만한 각도로 접근
            side = rng.choice([-1.0, 1.0])
            entry_lat, entry_lon = vincenty_direct(
                ix, iy,
                (self.synth.final_course + 180.0 + side * rng.uniform(30.0, 60.0)) % 360.0,
                rng.uniform(12.0, 22.0) * M_PER_NM,
            )
            route = [(ix, iy), self.synth.thr]
        else:
            names = TRANSITIONS[rng.choice(list(TRANSITIONS))]
            first = self.ds.procedures.fix(names[0])
            outbound = bearing_true(*self.synth.thr, first.lat, first.lon)
            entry_lat, entry_lon = vincenty_direct(
                first.lat, first.lon,
                (outbound + rng.gauss(0.0, 15.0)) % 360.0,
                rng.uniform(12.0, 26.0) * M_PER_NM,
            )
            route = [
                (self.ds.procedures.fix(n).lat, self.ds.procedures.fix(n).lon)
                for n in names
            ] + [self.synth.thr]

        entry_alt = rng.choice([7000.0, 8000.0, 9000.0, 10000.0, 11000.0])
        entry_tas = rng.uniform(230.0, 280.0)

        # 비행 중 관제 지시 — 예측기가 원리적으로 맞힐 수 없는 부분
        events: list[ControlEvent] = []
        if rng.random() < self.path_stretch_rate:
            events.append(
                ControlEvent(
                    "PATH_STRETCH",
                    trigger_dist_nm=rng.uniform(14.0, 28.0),
                    magnitude=rng.choice([-1.0, 1.0]) * rng.uniform(2.5, 7.0),
                )
            )
        if rng.random() < self.speed_instruction_rate:
            events.append(
                ControlEvent(
                    "SPEED",
                    trigger_dist_nm=rng.uniform(10.0, 30.0),
                    magnitude=rng.choice([-1.0, 1.0]) * rng.uniform(15.0, 35.0),
                )
            )

        return FlightIntent(
            callsign=callsign, actype=actype, wake_cat=cat,
            entry_lat=entry_lat, entry_lon=entry_lon,
            entry_alt_ft=entry_alt, entry_tas_kt=entry_tas,
            route=route,
            assigned_alt_ft=rng.choice(self.ds.airspace.altitude_ladder_ft),
            technique=PilotTechnique.sample(rng),
            start_time_s=start_time_s,
            events=tuple(events),
        )

    def arrivals(
        self, n: int, seed: int = 0, mean_interval_s: float = 110.0
    ) -> list[Trajectory]:
        """도착 항적 n 대. 진입 간격은 지수분포.

        슬롯 개념이 없으므로 시단에 동시 도달하는 쌍이 많이 생긴다.
        항적예측 학습에는 적합하지만 예외 판정 학습에는 편향이 크다 —
        그쪽은 `sequenced_arrivals` 를 쓴다.
        """
        rng = random.Random(seed)
        out: list[Trajectory] = []
        t = 0.0
        for i in range(n):
            cs = f"SIM{i:03d}"
            out.append(self.synth.fly(self.random_intent(rng, cs, t), rng))
            t += rng.expovariate(1.0 / mean_interval_s)
        return out

    def departure_intent(
        self,
        rng: random.Random,
        callsign: str,
        start_time_s: float,
        actype: str | None = None,
        transition: str | None = None,
        cruise_alt_ft: float | None = None,
    ) -> DepartureIntent:
        """출발 계획 하나. SID 전이는 AIP 에 고시된 것 중에서만 고른다."""
        if actype is None:
            military = rng.random() < self.military_ratio
            actype = rng.choice(MILITARY_TYPES if military else CIVIL_TYPES)
        sid = self.ds.procedures.raw["sid"]["UPTIL1"]
        if transition is None:
            transition = rng.choice(sorted(sid["transitions"]))
        if cruise_alt_ft is None:
            # 순항고도를 지어내지 않는다 — T17 상한(관할 이양 고도) 위에서
            # 고시 4-5-2 의 비행방향별 배정을 만족하는 최저 고도를 쓴다.
            outbound = sid["transitions"][transition][-1]["course_true"]
            floor = self.ds.airspace.raw["handoff"]["t17_upper_ft_amsl"]
            cruise_alt_ft = RuleBook(self.ds).cruise_altitude_ft(outbound, floor)
        return DepartureIntent(
            callsign=callsign,
            actype=actype,
            wake_cat=self.ds.fleet.wake_cat(actype),
            sid="UPTIL1",
            transition=transition,
            cruise_alt_ft=float(cruise_alt_ft),
            technique=PilotTechnique.sample(rng),
            start_time_s=start_time_s,
        )

    def departures(
        self, n: int, seed: int = 0, mean_interval_s: float = 180.0
    ) -> list[Trajectory]:
        """출발 항적 n 대.

        간격을 활주로 요건과 맞추지 않는다 — 여기서는 항적만 만들고, 언제 이륙할 수
        있는지는 `runway.RunwaySequencer` 가 정한다. 두 관심사를 섞으면 활주로
        규정을 항적 생성기 안에 중복 구현하게 된다.
        """
        rng = random.Random(seed)
        out: list[Trajectory] = []
        t = 0.0
        for i in range(n):
            cs = f"DEP{i:03d}"
            out.append(self.synth.fly_departure(self.departure_intent(rng, cs, t), rng))
            t += rng.expovariate(1.0 / mean_interval_s)
        return out

    def sequenced_arrivals(
        self,
        n: int,
        sequencer,
        seed: int = 0,
        jitter_s: float = 25.0,
        deviation_rate: float = 0.12,
        spacing_buffer: float = 1.65,
    ) -> list[Trajectory]:
        """계획은 있고 그 뒤 개입이 없는 도착 흐름 — 예외 판정 학습용.

        관제 개입이 **전혀** 없는 흐름은 모두 같은 최종접근로로 수렴해 위반율이
        50%를 넘는 비현실적 데이터가 된다. 실제는 그게 아니라, 관제사가 슬롯
        계획을 세워 두었고 그 뒤 바람·조종기법·기종 차이로 계획이 어긋나면서
        일부 쌍에서만 예외가 발생하는 것이다.

        여기서는 필요 슬롯 간격대로 시단 도달 시각을 배치하고 계획 오차(jitter)와
        일부 항적의 이탈(deviation)을 넣는다. 그 뒤로는 아무 개입도 하지 않으므로
        결과 라벨이 곧 무개입 롤아웃 결과가 된다.

        Args:
            jitter_s: 계획 대비 도달시각 오차 표준편차.
            deviation_rate: 계획을 크게 벗어나는 항적의 비율.
            spacing_buffer: 최저 간격 대비 계획 여유. 기본값 1.65 는 결과 위반율이
                시드에 따라 10~21%, 평균 약 15% 가 되는 지점으로, 기획서가 인용한
                실제 개입 필요 13.8% 와
                부합하도록 잡았다. 1.0 으로 두면 작은 오차에도 전부 위반이 된다.
            (원문) 관제사는 최저치에 딱 맞추지
                않고 여유를 둔다 — 1.0 으로 두면 작은 오차에도 전부 위반이 된다.
        """
        rng = random.Random(seed)
        flown = [
            self.synth.fly(self.random_intent(rng, f"SIM{i:03d}", 0.0), rng)
            for i in range(n)
        ]

        out: list[Trajectory] = []
        t_slot = 0.0
        prev = None
        for traj in flown:
            if prev is not None:
                gap = sequencer.gap_requirement(prev.samples[-1], traj.samples[-1])
                t_slot += gap.seconds * spacing_buffer
            error = rng.gauss(0.0, jitter_s)
            if rng.random() < deviation_rate:
                error += rng.choice([-1.0, 1.0]) * rng.uniform(40.0, 110.0)
            shifted = shift_to(traj, t_slot + error)
            out.append(shifted)
            prev = shifted
        return out


def build(ds, seed: int = 0, **wind_kwargs) -> ScenarioGenerator:
    wind = WindField(**wind_kwargs) if wind_kwargs else WindField()
    return ScenarioGenerator(ds=ds, synth=TrajectorySynthesizer(ds=ds, wind=wind))


# ----------------------------------------------------------------------
# 무개입 롤아웃 라벨링 (MBE 학습용)
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class PairSample:
    """한 시점의 항적 쌍 — MBE 학습 표본.

    라벨은 임계치가 아니라 **결과**다. 개입 없이 그대로 두었을 때 실제로
    분리위반이 발생했는가를 정답으로 쓴다. 관제사 개인의 습관이 아니라
    "결과가 좋았던 판단"을 학습하므로 편향이 전이되지 않는다.
    """

    t_s: float
    a: AircraftState
    b: AircraftState
    violated: bool
    """개입 없이 두었을 때 지평 안에서 실제로 분리위반이 발생했는가."""

    time_to_violation_s: float
    """실제 위반까지 남은 시간. 위반이 없으면 무한대."""

    min_separation_nm: float
    """지평 안 실제 최소 수평 이격 (수직분리 여부와 무관)."""

    min_vertical_ft: float
    """지평 안 실제 최소 수직 이격."""

    already_violating: bool = False
    """표본 시점에 이미 분리위반 상태인가.

    예외 판정 학습에서는 이 표본을 빼야 한다. 이미 위반 중인 쌍은 관제사가
    화면에서 곧바로 보므로 예측이 필요 없고, 결정론 기하만으로 완벽히 잡힌다.
    섞어 두면 과제가 '현재 위반 탐지'로 바뀌어 학습의 여지가 사라진다.
    MBE 가 답해야 하는 것은 '지금 괜찮아 보이는 쌍 중 무엇이 문제가 되는가'다.
    """


def rollout_labels(
    trajectories: list[Trajectory],
    detector,
    *,
    horizon_s: float = 600.0,
    stride: int = 3,
    h_min_nm: float | None = None,
    v_min_ft: float | None = None,
) -> list[PairSample]:
    """생성된 항적을 그대로 흘려보내며 쌍별 표본과 결과 라벨을 만든다.

    항적은 관제 개입 없이 각자의 의도대로 비행한 것이므로, 그 자체가
    **무개입 롤아웃**이다. 별도 시뮬레이션이 필요 없다.

    Args:
        stride: 몇 샘플마다 표본을 뽑을지. 인접 시점은 거의 같은 정보를 담는다.
    """
    from .geo import separation_distance_nm as _sep

    out: list[PairSample] = []
    dt = trajectories[0].dt_s if trajectories else 4.0
    steps = int(round(horizon_s / dt))

    for i, ta in enumerate(trajectories):
        for tb in trajectories[i + 1:]:
            t0 = max(ta.samples[0].t_s, tb.samples[0].t_s)
            t1 = min(ta.samples[-1].t_s, tb.samples[-1].t_s)
            if t1 <= t0:
                continue

            k = 0
            t = t0
            while t <= t1:
                k += 1
                if k % stride:
                    t += dt
                    continue
                a, b = ta.at(t), tb.at(t)
                if a is None or b is None:
                    t += dt
                    continue
                if not (
                    detector.sector.is_under_control(a)
                    and detector.sector.is_under_control(b)
                ):
                    t += dt
                    continue

                std = detector.rules.separation_standard(a, b)
                hmin = h_min_nm if h_min_nm is not None else std.horizontal_nm
                vmin = v_min_ft if v_min_ft is not None else std.vertical_ft

                worst_h = math.inf
                worst_v = math.inf
                first = math.inf
                for s in range(steps + 1):
                    fa, fb = ta.at(t + s * dt), tb.at(t + s * dt)
                    if fa is None or fb is None:
                        break
                    d = _sep(fa.lat, fa.lon, fb.lat, fb.lon)
                    dv = abs(fa.alt_ft - fb.alt_ft)
                    worst_h = min(worst_h, d)
                    worst_v = min(worst_v, dv)
                    if d < hmin and dv < vmin and first is math.inf:
                        first = s * dt

                out.append(
                    PairSample(
                        t_s=t, a=a, b=b,
                        violated=first is not math.inf,
                        time_to_violation_s=first,
                        min_separation_nm=worst_h if worst_h is not math.inf else 99.0,
                        min_vertical_ft=worst_v if worst_v is not math.inf else 99000.0,
                        already_violating=(
                            _sep(a.lat, a.lon, b.lat, b.lon) < hmin
                            and abs(a.alt_ft - b.alt_ft) < vmin
                        ),
                    )
                )
                t += dt
    return out


def shift_to(traj: Trajectory, threshold_time_s: float) -> Trajectory:
    """시단 도달 시각이 주어진 값이 되도록 시계열 전체를 평행이동한다.

    바람장이 시간에 무관하므로 시각 이동은 동역학을 바꾸지 않는다.
    """
    from dataclasses import replace as _replace

    delta = threshold_time_s - traj.samples[-1].t_s
    return Trajectory(
        traj.callsign, traj.actype, traj.wake_cat,
        [_replace(s, t_s=s.t_s + delta) for s in traj.samples],
        traj.dt_s,
    )
