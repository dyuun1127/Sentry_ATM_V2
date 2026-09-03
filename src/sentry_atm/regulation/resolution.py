"""충돌 회피(CD&R) — 관제 지시 단위 회피 후보와 재검증.

두 갈래로 나뉜다. 어느 쪽이든 **후보를 적용한 뒤 전체 항적과 다시 검사**해서
2차 충돌(회피가 만드는 새 충돌)을 걸러낸다.

1. **전술적 회피** — 침로·고도·속도 변경. 후보를 관제 지시 단위로 이산화한다.
   연속 최적화로 임의의 값을 내면 관제사가 그대로 읽을 수 없다.
   "AAA, turn right heading 260" 은 지시가 되지만 "turn right 17.3 degrees" 는 아니다.

2. **시퀀스 재배정** — 도착 흐름 안의 충돌은 회피 기동이 아니라 슬롯 재배정과
   사다리 재정렬로 푼다. 측방 오프셋만 키우면 **발산한다** — 오프셋을 준 기체가
   옆 기체와 새 충돌을 만들고, 그걸 또 오프셋으로 풀면서 위반 쌍이 늘어난다.
   이전 구현에서 80회 반복에도 수렴하지 않고 위반이 2쌍에서 4쌍으로 늘었다.

학습(Phase 5)이 낸 회피안도 반드시 이 재검증을 통과해야 관제사에게 상신된다.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field, replace

from .conflict import Conflict, ConflictKind, Detector
from .state import AircraftState, relative_state


@dataclass(frozen=True)
class Maneuver:
    """관제 지시 하나에 대응하는 회피 기동."""

    callsign: str
    kind: str
    """'HEADING' | 'ALTITUDE' | 'SPEED'"""

    delta: float
    """침로 deg (우선회 양수) / 고도 ft / 속도 kt"""

    def apply(self, ac: AircraftState, *, climb_rate_fpm: float = 1000.0) -> AircraftState:
        """기동을 적용한 상태."""
        if self.kind == "HEADING":
            return replace(ac, track_deg=(ac.track_deg + self.delta) % 360.0)
        if self.kind == "SPEED":
            return replace(ac, gs_kt=max(ac.gs_kt + self.delta, 60.0))
        if self.kind == "ALTITUDE":
            target = ac.alt_ft + self.delta
            rate = math.copysign(climb_rate_fpm, self.delta)
            return replace(ac, vs_fpm=rate, target_alt_ft=target)
        raise ValueError(f"알 수 없는 기동 종류: {self.kind!r}")

    def instruction(self, ac: AircraftState, mag_var: float = 9.0) -> str:
        """관제 문구. 침로는 자방위로 낸다 — 조종사가 듣는 값이다."""
        if self.kind == "HEADING":
            new_true = (ac.track_deg + self.delta) % 360.0
            mag = (new_true + mag_var) % 360.0
            side = "우선회" if self.delta > 0 else "좌선회"
            return f"{self.callsign}, {side} 침로 {round(mag):03d}"
        if self.kind == "ALTITUDE":
            target = ac.alt_ft + self.delta
            verb = "상승" if self.delta > 0 else "강하"
            return f"{self.callsign}, {verb} 고도 {round(target / 100) * 100:,}피트 유지"
        speed = round(ac.gs_kt + self.delta)
        return f"{self.callsign}, 속도 {speed}노트 유지"

    def __str__(self) -> str:
        unit = {"HEADING": "°", "ALTITUDE": "ft", "SPEED": "kt"}[self.kind]
        return f"{self.callsign} {self.kind} {self.delta:+g}{unit}"


@dataclass(frozen=True)
class Resolution:
    """검증을 통과한 회피안."""

    maneuver: Maneuver
    cost: float
    resolved: tuple[tuple[str, str], ...]
    """이 기동으로 해소된 충돌 쌍."""

    collision_probability: float = 0.0
    """회피 후 잔여 충돌확률 (불확실성 반영). σ=0 이면 0."""

    rationale: str = ""

    def describe(self, ac: AircraftState, mag_var: float = 9.0) -> str:
        return f"{self.maneuver.instruction(ac, mag_var)}  [{self.rationale}]"


# ----------------------------------------------------------------------
# 예측 불확실성
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class UncertaintyModel:
    """예측 불확실성 — 몬테카를로 충돌확률의 입력.

    Phase 5 의 항적예측이 지평별 σ 를 산출하면 그 값으로 대체한다.
    기본값 0 은 **결정론** — 불확실성을 가정하지 않는다는 뜻이며,
    근거 없는 σ 를 지어내지 않기 위한 선택이다.
    """

    horizontal_nm_per_s: float = 0.0
    vertical_ft_per_s: float = 0.0
    horizontal_nm_0: float = 0.0
    vertical_ft_0: float = 0.0

    def sigma_at(self, t_s: float) -> tuple[float, float]:
        return (
            self.horizontal_nm_0 + self.horizontal_nm_per_s * t_s,
            self.vertical_ft_0 + self.vertical_ft_per_s * t_s,
        )

    @property
    def is_deterministic(self) -> bool:
        return (
            self.horizontal_nm_per_s == 0.0
            and self.vertical_ft_per_s == 0.0
            and self.horizontal_nm_0 == 0.0
            and self.vertical_ft_0 == 0.0
        )


def collision_probability(
    a: AircraftState,
    b: AircraftState,
    h_min_nm: float,
    v_min_ft: float,
    uncertainty: UncertaintyModel,
    horizon_s: float,
    *,
    samples: int = 400,
    step_s: float = 15.0,
    seed: int | None = 20260902,
) -> float:
    """예측 불확실성을 반영한 충돌확률 (몬테카를로).

    두 기의 위치에 시간에 따라 커지는 가우시안 오차를 넣고, 지평 안에서
    보호실린더를 한 번이라도 침범하는 표본의 비율을 돌려준다.

    σ 가 0 이면(기본) 결정론 판정과 같아지므로 0 또는 1 만 나온다.
    """
    if uncertainty.is_deterministic:
        from .geometry import pair_conflict

        return 1.0 if pair_conflict(a, b, h_min_nm, v_min_ft, horizon_s) else 0.0

    rng = random.Random(seed)
    times = [t for t in _frange(0.0, horizon_s, step_s)]
    # 상대 기하를 미리 풀어 둔다 — 표본마다 다시 계산할 필요가 없다
    rels = [relative_state(a.advance(t), b.advance(t)) for t in times]

    k = math.sqrt(2.0)  # 두 기의 오차가 독립이므로 상대 오차의 분산은 두 배
    hits = 0
    for _ in range(samples):
        # **표본마다 하나의 오차 실현을 뽑아 시간에 걸쳐 일관되게 키운다.**
        # 시각마다 독립으로 다시 뽑으면 "예측보다 앞서가는 기체는 계속 앞서간다"는
        # 시간 상관이 사라져, 시간 구간을 잘게 나눌수록 확률이 부풀려진다.
        zx, zy, zz = rng.gauss(0, 1), rng.gauss(0, 1), rng.gauss(0, 1)
        for t, rel in zip(times, rels):
            sh, sv = uncertainty.sigma_at(t)
            horiz = math.hypot(
                rel.r_east_nm + zx * sh * k, rel.r_north_nm + zy * sh * k
            )
            vert = abs(rel.r_alt_ft + zz * sv * k)
            if horiz < h_min_nm and vert < v_min_ft:
                hits += 1
                break
    return hits / samples


def _frange(start: float, stop: float, step: float):
    t = start
    while t <= stop + 1e-9:
        yield t
        t += step


# ----------------------------------------------------------------------
# 회피 탐색
# ----------------------------------------------------------------------


@dataclass
class Resolver:
    """회피안 생성기.

    후보는 관제 지시 단위로만 만든다. 연속값 최적화는 하지 않는다.
    """

    detector: Detector

    heading_options_deg: tuple[float, ...] = (10.0, 20.0, 30.0)
    altitude_options_ft: tuple[float, ...] = (1000.0, 2000.0)
    speed_options_kt: tuple[float, ...] = (20.0, 40.0)

    uncertainty: UncertaintyModel = field(default_factory=UncertaintyModel)

    # 비용 가중치. 접근관제에서 관제사가 실제로 선호하는 순서를 반영한다 —
    # 속도 조절이 가장 덜 방해되고, 벡터링(침로)이 그다음, 고도 변경이 가장 크다.
    # 고도 변경은 배정고도 사다리를 흔들어 뒤 순번까지 영향이 번지기 때문이다.
    cost_speed: float = 1.0
    cost_heading: float = 2.0
    cost_altitude: float = 4.0
    cost_per_unit: dict = field(
        default_factory=lambda: {"HEADING": 0.03, "ALTITUDE": 0.001, "SPEED": 0.02}
    )

    fleet: object | None = None
    """기종 제원 접근자. 주면 성능·절차 한계를 벗어난 후보를 걸러낸다."""

    procedure_speed_max_kt: float = 230.0
    """접근 절차 속도 제한. AIP RNP RWY 24R 의 'Max 230 kt IAS'."""

    def is_feasible(self, ac: AircraftState, m: Maneuver) -> tuple[bool, str]:
        """관제 지시로 실제로 낼 수 있는 기동인가.

        낼 수 없는 지시를 상신하면 관제사가 곧바로 신뢰를 거둔다.
        B737 을 최종접근에서 125노트로 늦추라는 안은 성능상 불가능하다.
        """
        if m.kind == "SPEED":
            new_v = ac.gs_kt + m.delta
            if self.fleet is not None:
                floor = self.fleet.final_gs_kt(ac.actype, ac.wake_cat)
                if new_v < floor:
                    return False, (
                        f"{ac.actype} 최종접근속도 {floor:g}kt 미만 — 성능 한계"
                    )
            if new_v > self.procedure_speed_max_kt:
                return False, (
                    f"절차 속도 제한 {self.procedure_speed_max_kt:g}kt 초과 (AIP)"
                )
            return True, ""

        if m.kind == "ALTITUDE":
            target = ac.alt_ft + m.delta
            sector = self.detector.sector
            if target > sector.handoff_alt_ft:
                return False, (
                    f"T17 상한 {sector.handoff_alt_ft:g}ft 초과 — "
                    f"{sector.upper_unit} 협의 필요 (고시 2-1-15)"
                )
            probe = replace(ac, alt_ft=target, vs_fpm=0.0, target_alt_ft=None)
            if not sector.is_under_control(probe):
                return False, "회피 후 담당 공역을 벗어남"
            return True, ""

        return True, ""

    def candidates(self, ac: AircraftState) -> list[Maneuver]:
        """한 기체에 낼 수 있는 관제 지시 후보 — 성능·절차 한계 안에서만."""
        out: list[Maneuver] = []
        for d in self.heading_options_deg:
            out.append(Maneuver(ac.callsign, "HEADING", +d))
            out.append(Maneuver(ac.callsign, "HEADING", -d))
        for d in self.altitude_options_ft:
            out.append(Maneuver(ac.callsign, "ALTITUDE", +d))
            out.append(Maneuver(ac.callsign, "ALTITUDE", -d))
        for d in self.speed_options_kt:
            out.append(Maneuver(ac.callsign, "SPEED", -d))
            out.append(Maneuver(ac.callsign, "SPEED", +d))
        return [m for m in out if self.is_feasible(ac, m)[0]]

    def all_candidates(self, ac: AircraftState) -> list[Maneuver]:
        """한계 적용 전 후보 전부 — 필터 효과를 보고할 때 쓴다."""
        out: list[Maneuver] = []
        for d in self.heading_options_deg:
            out += [Maneuver(ac.callsign, "HEADING", +d), Maneuver(ac.callsign, "HEADING", -d)]
        for d in self.altitude_options_ft:
            out += [Maneuver(ac.callsign, "ALTITUDE", +d), Maneuver(ac.callsign, "ALTITUDE", -d)]
        for d in self.speed_options_kt:
            out += [Maneuver(ac.callsign, "SPEED", -d), Maneuver(ac.callsign, "SPEED", +d)]
        return out

    def cost(self, m: Maneuver) -> float:
        base = {
            "HEADING": self.cost_heading,
            "ALTITUDE": self.cost_altitude,
            "SPEED": self.cost_speed,
        }[m.kind]
        return base + self.cost_per_unit[m.kind] * abs(m.delta)

    def resolve(
        self,
        conflict: Conflict,
        traffic: list[AircraftState],
        *,
        final_course_deg: float | None = None,
        max_options: int = 3,
    ) -> list[Resolution]:
        """한 충돌에 대한 회피안 목록 — 비용이 낮은 순.

        충돌 당사자 두 기 모두에 대해 후보를 만들고, **적용 후 전체 항적과
        재검사**해서 2차 충돌이 없는 것만 남긴다.
        """
        by_cs = {ac.callsign: ac for ac in traffic}
        if conflict.first not in by_cs or conflict.second not in by_cs:
            return []

        found: list[Resolution] = []
        for cs in (conflict.first, conflict.second):
            subject = by_cs[cs]
            others = [ac for ac in traffic if ac.callsign != cs]
            for m in self.candidates(subject):
                moved = m.apply(subject)
                if not self._clears_the_conflict(moved, conflict, by_cs, cs):
                    continue
                if not self.detector.is_clear(
                    moved, others, final_course_deg=final_course_deg
                ):
                    continue  # 2차 충돌 — 버린다
                found.append(
                    Resolution(
                        maneuver=m,
                        cost=self.cost(m),
                        resolved=(conflict.pair,),
                        collision_probability=self._residual_probability(
                            moved, by_cs, conflict, cs
                        ),
                        rationale=(
                            f"{conflict.pair[0]}↔{conflict.pair[1]} 해소, "
                            f"타 항적과 2차 충돌 없음"
                        ),
                    )
                )

        found.sort(key=lambda r: (r.collision_probability, r.cost))
        return found[:max_options]

    def _clears_the_conflict(
        self,
        moved: AircraftState,
        conflict: Conflict,
        by_cs: dict[str, AircraftState],
        subject_cs: str,
    ) -> bool:
        other_cs = conflict.second if subject_cs == conflict.first else conflict.first
        other = by_cs[other_cs]
        return self.detector.check_radar(moved, other) is None

    def _residual_probability(
        self,
        moved: AircraftState,
        by_cs: dict[str, AircraftState],
        conflict: Conflict,
        subject_cs: str,
    ) -> float:
        if self.uncertainty.is_deterministic:
            return 0.0
        other_cs = conflict.second if subject_cs == conflict.first else conflict.first
        other = by_cs[other_cs]
        std = self.detector.rules.separation_standard(moved, other)
        return collision_probability(
            moved, other, std.horizontal_nm, std.vertical_ft,
            self.uncertainty, self.detector.lookahead_s,
        )

    # ------------------------------------------------------------------
    # 시퀀스 재배정 기반 디컨플릭션
    # ------------------------------------------------------------------

    def deconflict_arrival_stream(
        self,
        traffic: list[AircraftState],
        sequencer,
        now_s: float = 0.0,
        max_rounds: int = 20,
        initial=None,
    ) -> tuple[object, list[str], int]:
        """도착 흐름의 충돌을 **슬롯 재배정**으로 푼다.

        측방 오프셋을 주지 않는다. 오프셋은 준 기체가 옆 기체와 새 충돌을 만들고,
        그걸 또 오프셋으로 풀면서 발산한다. 대신 시퀀서를 다시 돌려 슬롯 시각과
        배정고도 사다리를 재정렬한다 — 슬롯 간격 요건이 분리를 구조적으로 보장하므로
        수렴이 보장된다.

        Returns:
            (스케줄, 조치 로그, 반복 횟수)
        """
        log: list[str] = []
        schedule = initial if initial is not None else sequencer.build(traffic, now_s)

        for round_ in range(1, max_rounds + 1):
            found = self.scan_schedule(sequencer, traffic, schedule, now_s)
            if not found:
                if round_ > 1:
                    log.append(f"{round_ - 1}회 재배정으로 해소")
                return schedule, log, round_ - 1

            worst, at_t = found[0]
            log.append(f"{round_}회차 (t={at_t:.0f}s): {worst.describe()}")
            schedule = _push_slot(sequencer, schedule, worst, traffic, now_s)

        log.append(f"{max_rounds}회 반복에도 미해소 — 관제사 판단 필요")
        return schedule, log, max_rounds

    def scan_schedule(
        self,
        sequencer,
        traffic: list[AircraftState],
        schedule,
        now_s: float = 0.0,
        step_s: float = 10.0,
    ) -> list[tuple[Conflict, float]]:
        """스케줄을 **실행했을 때** 전 구간에서 발생하는 위반.

        한 시점만 보면 안 된다. 스케줄은 계획이고, 위반은 그 계획이 흘러가면서
        발생한다. 게다가 도착 항적 대부분은 지금 이 순간 청주 GCA 담당 공역
        밖(시단 10NM 바깥)에 있어, 현재 시점만 훑으면 아무것도 잡히지 않는다.
        """
        out: list[tuple[Conflict, float]] = []
        seen: set[tuple[str, str]] = set()
        end = now_s + schedule.makespan_s + step_s
        t = now_s
        while t <= end:
            flown = _project_onto_schedule(sequencer, traffic, schedule, t)
            for c in self.detector.scan(
                flown,
                final_course_deg=sequencer.final_course_deg,
                landing_sequence=schedule.order,
            ):
                key = tuple(sorted(c.pair))
                if key not in seen:
                    seen.add(key)
                    out.append((c, t))
            t += step_s
        return out


def _project_onto_schedule(sequencer, traffic, schedule, now_s):
    """스케줄대로 최종접근에 정렬했을 때의 항적 배치."""
    from .geo import vincenty_direct

    by_cs = {ac.callsign: ac for ac in traffic}
    out = []
    for slot in schedule.slots:
        ac = by_cs[slot.callsign]
        v = sequencer.final_gs_kt(ac)
        remaining = (slot.threshold_time_s - now_s) / 3600.0 * v
        if remaining <= 0:
            continue
        lat, lon = vincenty_direct(
            *sequencer.thr,
            (sequencer.final_course_deg + 180.0) % 360.0,
            remaining * 1852.0,
        )
        out.append(
            replace(
                ac,
                lat=lat,
                lon=lon,
                alt_ft=sequencer.glidepath_altitude_ft(remaining),
                track_deg=sequencer.final_course_deg,
                gs_kt=v,
                vs_fpm=0.0,
                target_alt_ft=None,
            )
        )
    return out


def _push_slot(sequencer, schedule, conflict, traffic, now_s):
    """충돌 쌍 중 뒤 순번의 슬롯을 요구 간격만큼 뒤로 밀고 전체를 재정렬."""
    order = schedule.order
    idx = {cs: i for i, cs in enumerate(order)}
    a, b = conflict.pair
    later = a if idx.get(a, 0) > idx.get(b, 0) else b

    by_cs = {ac.callsign: ac for ac in traffic}
    pinned = {
        s.callsign: s.threshold_time_s
        for s in schedule.slots
        if idx[s.callsign] < idx[later]
    }
    prev_cs = order[idx[later] - 1] if idx[later] > 0 else None
    if prev_cs is not None:
        gap = sequencer.gap_requirement(by_cs[prev_cs], by_cs[later])
        pinned[later] = pinned[prev_cs] + gap.seconds * 1.05  # 5% 여유를 두고 민다

    ordered = [by_cs[cs] for cs in order]
    return sequencer._lay_out(ordered, now_s, pinned=pinned)


def build(ds, runway: str = "24R") -> Resolver:
    from . import conflict as cf

    iap = ds.procedures.iap("RNP_24R")
    limits = [
        leg["speed_max_kt"]
        for legs in iap.get("transitions", {}).values()
        for leg in legs
        if "speed_max_kt" in leg
    ]
    return Resolver(
        detector=cf.build(ds, runway),
        fleet=ds.fleet,
        procedure_speed_max_kt=min(limits) if limits else 230.0,
    )


def analytic_collision_probability(
    a: AircraftState,
    b: AircraftState,
    h_min_nm: float,
    v_min_ft: float,
    uncertainty: UncertaintyModel,
    horizon_s: float,
    *,
    step_s: float = 20.0,
) -> float:
    """충돌확률의 해석적 근사 — 몬테카를로 대신 쓴다.

    두 기의 위치오차가 각각 등방 2차원 가우시안이면 상대 위치는 평균 r,
    성분분산 2σ² 인 가우시안이다. 그때 수평거리가 최저치 미만일 확률은
    비중심 카이제곱 분포의 CDF 로 **정확히** 나온다.

        ‖X‖²/s² ~ χ'²(자유도 2, 비중심모수 ‖r‖²/s²)

    수직은 1차원 가우시안으로 보고 독립 가정하에 곱한다. 시각별 확률의
    최댓값을 취하므로 시간 상관을 무시하는 보수적 근사다.

    몬테카를로(`collision_probability`)와 같은 값을 훨씬 싸게 낸다 —
    MBE 특성을 수만 건 계산할 때 필요하다.
    """
    if uncertainty.is_deterministic:
        from .geometry import pair_conflict

        return 1.0 if pair_conflict(a, b, h_min_nm, v_min_ft, horizon_s) else 0.0

    from scipy.stats import ncx2, norm

    best = 0.0
    t = 0.0
    while t <= horizon_s + 1e-9:
        sh, sv = uncertainty.sigma_at(t)
        rel = relative_state(a.advance(t), b.advance(t))
        s2 = 2.0 * sh * sh          # 두 기의 오차가 독립이므로 분산은 두 배
        if s2 <= 0.0:
            t += step_s
            continue
        lam = (rel.r_east_nm ** 2 + rel.r_north_nm ** 2) / s2
        p_h = float(ncx2.cdf(h_min_nm * h_min_nm / s2, 2, lam))

        sv2 = math.sqrt(2.0) * sv
        if sv2 > 0.0:
            p_v = float(
                norm.cdf((v_min_ft - rel.r_alt_ft) / sv2)
                - norm.cdf((-v_min_ft - rel.r_alt_ft) / sv2)
            )
        else:
            p_v = 1.0 if abs(rel.r_alt_ft) < v_min_ft else 0.0

        best = max(best, p_h * p_v)
        t += step_s
    return best
