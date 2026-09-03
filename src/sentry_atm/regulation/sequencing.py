"""도착 시퀀싱 — 착륙 순서, 슬롯 시각, 배정고도 사다리, 중심선 합류.

이전 구현에서 실패했던 세 가지를 구조로 막는다.

1. **배정고도 사다리** — 고도를 잔여거리만으로 정하면 여러 기가 같은 고도에 몰려
   분리위반이 계속 난다. 착륙 순번이 뒤일수록 높은 고도를 유지하다 자기 차례에
   순차 강하하면, 인접 순번 간 1,000ft 수직분리(고시 4-5-1)가 구조적으로 확보된다.

2. **연장 중심선 합류(JOIN)** — 착륙 간격만 맞추면 합류부에서 측방으로 붙는다.
   양쪽에서 중심선으로 모여드는 두 기는 종렬 거리가 맞아도 실제 이격이 작다.
   합류점 이전에 중심선에 정렬시켜 종렬을 먼저 성립시킨다.

3. **슬롯 간격은 조합별 계산** — 등급별 고정값을 쓰면 안 된다. 필요 종렬거리는
   선행·후행 등급 조합으로 정해지고, 그 거리를 소화하는 시간은 **후행기의**
   최종접근속도로 나눈 값이다. 청주는 전투기(소형 등급)가 민항기보다 빠르므로
   등급과 속도의 상관을 가정할 수 없다.

우선권 삽입(고시 2-1-4)도 여기 있다. 순번으로 밀어넣으면 활주로가 비고 뒤 항적이
전부 무너지므로, **물리적 최단 도달시각**을 기준으로 삽입하고 이미 접근이 확정된
항적은 건드리지 않는다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

from .geo import separation_distance_nm, vincenty_direct
from .geometry import cross_track_offset_nm
from .rules import RuleBook
from .state import AircraftState

FT_PER_NM = 6076.11548556


@dataclass(frozen=True)
class GapRequirement:
    """선행기 시단 통과 후 후행기가 통과하기까지의 최소 시간과 그 근거."""

    seconds: float
    required_nm: float
    clauses: tuple[str, ...]
    rationale: str
    driver: str
    """'후류' / '레이더' / '활주로' — 필요 거리를 무엇이 정했는가."""

    binding: str = "시단"
    """'시단' / '합류부' / '활주로' — 최소 이격이 어디서 나오는가.

    선행기가 후행기보다 빠르면 간격이 시간에 따라 벌어지므로 최소 이격이
    합류부에서 나온다. 시단 시점만 보면 그 구간을 놓친다.
    """


@dataclass(frozen=True)
class Slot:
    """한 항공기의 착륙 슬롯."""

    callsign: str
    order: int
    threshold_time_s: float
    earliest_time_s: float
    """물리적 최단 도달시각. threshold_time_s 와의 차이가 곧 지연이다."""

    assigned_alt_ft: int
    holding_above: bool
    """사다리를 넘어선 순번 — 상위 섹터 대기 대상."""

    gap: GapRequirement | None = None
    """앞 순번과의 간격 요건. 첫 순번은 None."""

    priority: bool = False

    @property
    def delay_s(self) -> float:
        return self.threshold_time_s - self.earliest_time_s


@dataclass
class Schedule:
    """착륙 순서 전체."""

    slots: list[Slot]
    join_dist_nm: float
    final_course_deg: float

    def by_callsign(self, callsign: str) -> Slot:
        for s in self.slots:
            if s.callsign == callsign:
                return s
        raise KeyError(callsign)

    @property
    def order(self) -> list[str]:
        return [s.callsign for s in self.slots]

    @property
    def total_delay_s(self) -> float:
        return sum(s.delay_s for s in self.slots)

    @property
    def mean_gap_s(self) -> float:
        """평균 착륙 간격 — 처리율 지표."""
        gaps = [
            b.threshold_time_s - a.threshold_time_s
            for a, b in zip(self.slots, self.slots[1:])
        ]
        return sum(gaps) / len(gaps) if gaps else 0.0

    @property
    def makespan_s(self) -> float:
        if not self.slots:
            return 0.0
        return self.slots[-1].threshold_time_s - self.slots[0].threshold_time_s


@dataclass
class ArrivalSequencer:
    """도착 시퀀서."""

    ds: object
    rules: RuleBook

    runway: str = "24R"
    approach: str = "RNP_24R"

    join_dist_nm: float | None = None
    """연장 중심선 합류점의 시단 거리. 기본값은 절차의 IF(중간접근픽스) 거리."""

    _cfg: dict = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._cfg = self.ds.fleet.sequencing
        rwy = self.ds.procedures.runways[self.runway]
        self.thr = (rwy.thr_lat, rwy.thr_lon)
        self.thr_elev_ft = rwy.thr_elev_ft
        self.final_course_deg = rwy.true_brg
        iap = self.ds.procedures.iap(self.approach)
        self.gs_angle_deg = iap["gs_angle_deg"]
        self.tch_ft = iap["tch_ft"]
        self.faf_dist_nm = iap["faf_to_thr_nm"]
        if self.join_dist_nm is None:
            self.join_dist_nm = self._if_distance_nm(iap)

    # ------------------------------------------------------------------
    # 기하
    # ------------------------------------------------------------------

    def _if_distance_nm(self, iap: dict) -> float:
        """절차의 IF(중간접근픽스)가 시단에서 몇 NM 인가.

        IF 부터 최종접근진로에 정렬되므로 자연스러운 합류점이다.
        """
        for leg in iap.get("final", []):
            if leg.get("role") == "IF":
                w = self.ds.procedures.fix(leg["wpt"])
                return separation_distance_nm(w.lat, w.lon, *self.thr)
        return self.faf_dist_nm + 5.0

    @property
    def join_point(self) -> tuple[float, float]:
        """연장 중심선 위 합류점 좌표."""
        return vincenty_direct(
            *self.thr, (self.final_course_deg + 180.0) % 360.0, self.join_dist_nm * 1852.0
        )

    def distance_to_threshold_nm(self, ac: AircraftState) -> float:
        return separation_distance_nm(ac.lat, ac.lon, *self.thr)

    def glidepath_altitude_ft(self, dist_from_thr_nm: float) -> float:
        """시단 거리에 대응하는 활공로 고도."""
        return (
            dist_from_thr_nm * FT_PER_NM * math.tan(math.radians(self.gs_angle_deg))
            + self.tch_ft
            + self.thr_elev_ft
        )

    def centreline_offset_nm(self, ac: AircraftState) -> float:
        """연장 중심선에서 벗어난 측방 거리. 우측이 양수."""
        return cross_track_offset_nm(ac, *self.thr, self.final_course_deg)

    def is_established(self, ac: AircraftState) -> bool:
        """연장 중심선에 정렬되어 종렬이 성립했는가.

        합류점 안쪽이면서 측방 허용오차 안에 있어야 한다. 이 조건을 만족한 뒤에야
        종렬 거리가 곧 실제 이격이 된다.
        """
        if self.distance_to_threshold_nm(ac) > self.join_dist_nm:
            return False
        return abs(self.centreline_offset_nm(ac)) <= self._cfg["join_tolerance_nm"]

    # ------------------------------------------------------------------
    # 기종 제원
    # ------------------------------------------------------------------

    def final_gs_kt(self, ac: AircraftState) -> float:
        return self.ds.fleet.final_gs_kt(ac.actype, ac.wake_cat)

    def runway_occupancy_s(self, ac: AircraftState) -> float:
        return self.ds.fleet.runway_occupancy_s(ac.actype, ac.wake_cat)

    # ------------------------------------------------------------------
    # 도달시각과 간격
    # ------------------------------------------------------------------

    def earliest_threshold_time_s(self, ac: AircraftState, now_s: float = 0.0) -> float:
        """물리적 최단 도달시각.

        합류점까지는 현재 지상속도로 직선, 합류 이후는 최종접근속도로 본다.
        지연을 전혀 주지 않았을 때 도달 가능한 가장 이른 시각이며,
        우선권 삽입(고시 2-1-4)의 기준이 되는 값이다.
        """
        d_thr = self.distance_to_threshold_nm(ac)
        v_final = self.final_gs_kt(ac)

        if d_thr <= self.join_dist_nm:
            return now_s + d_thr / max(v_final, 1.0) * 3600.0

        jlat, jlon = self.join_point
        d_join = separation_distance_nm(ac.lat, ac.lon, jlat, jlon)
        v_now = max(ac.gs_kt, 1.0)
        return now_s + d_join / v_now * 3600.0 + self.join_dist_nm / max(v_final, 1.0) * 3600.0

    def gap_requirement(self, leader: AircraftState, follower: AircraftState) -> GapRequirement:
        """선행기 시단 통과 후 후행기가 통과하기까지의 최소 시간.

        필요 종렬거리는 레이더 최저치(5-5-4 가)와 항적난기류 요건(5-5-4 사·아) 중
        큰 값이다. 다만 **그 거리는 최종접근 전 구간에서 유지되어야 하고**,
        속도가 다르면 이격이 시간에 따라 변한다.

            이격(t) = (T_후 − t)·v_후/3600 − (T_선 − t)·v_선/3600
            d(이격)/dt = (v_선 − v_후)/3600

        후행기가 더 빠르면(압축) 이격이 줄어들어 **시단**에서 최소가 되고,
        선행기가 더 빠르면 이격이 벌어져 **합류부**에서 최소가 된다.
        두 지점을 모두 만족하는 시간 간격을 구한다. 시단만 보면 후자를 놓친다.
        """
        radar_nm = self.rules.separation_standard(leader, follower).horizontal_nm
        wake = self.rules.wake_by_category(
            leader.wake_cat, follower.wake_cat, same_landing_runway=True
        )

        if wake.applies and wake.required_nm > radar_nm:
            required_nm = wake.required_nm
            clauses = wake.clauses
            rationale = wake.rationale
            distance_driver = "후류"
        else:
            required_nm = radar_nm
            clauses = ("5-5-4 가",)
            rationale = f"레이더 분리 최저치 {radar_nm:g}마일"
            distance_driver = "레이더"

        v_lead = self.final_gs_kt(leader)
        v_follow = self.final_gs_kt(follower)
        d_join = self.join_dist_nm

        # 시단 통과 시점: 선행기가 시단에 닿을 때 후행기가 required_nm 뒤에 있어야 한다.
        gap_at_threshold_s = required_nm / v_follow * 3600.0

        # 합류 시점: 후행기가 합류점(d_join)에 들어설 때의 이격도 required_nm 이상.
        #   이격 = d_join·(1 − v_선/v_후) + v_선·ΔT/3600
        gap_at_join_s = (
            3600.0 / v_lead * (required_nm - d_join * (1.0 - v_lead / v_follow))
        )

        if gap_at_join_s > gap_at_threshold_s:
            distance_gap_s = gap_at_join_s
            binding = "합류부"
            why = (
                f"{rationale}; 선행기 {v_lead:g}kt 가 후행기 {v_follow:g}kt 보다 빨라 "
                f"최소 이격이 합류부({d_join:.1f}NM)에서 발생"
            )
        else:
            distance_gap_s = gap_at_threshold_s
            binding = "시단"
            why = f"{rationale} ÷ 후행기 최종접근속도 {v_follow:g}kt"

        runway_gap_s = self.runway_occupancy_s(leader) + self._cfg["runway_gap_buffer_s"]

        if distance_gap_s >= runway_gap_s:
            return GapRequirement(
                seconds=distance_gap_s,
                required_nm=required_nm,
                clauses=clauses,
                rationale=why,
                driver=distance_driver,
                binding=binding,
            )
        return GapRequirement(
            seconds=runway_gap_s,
            required_nm=required_nm,
            clauses=clauses,
            rationale=(
                f"활주로 점유 {self.runway_occupancy_s(leader):g}s + 여유 "
                f"{self._cfg['runway_gap_buffer_s']:g}s "
                f"(종렬 요건 {distance_gap_s:.0f}s 보다 큼)"
            ),
            driver="활주로",
            binding="활주로",
        )

    # ------------------------------------------------------------------
    # 스케줄 생성
    # ------------------------------------------------------------------

    def build(self, arrivals: list[AircraftState], now_s: float = 0.0) -> Schedule:
        """도착 항적 집합에서 착륙 순서와 슬롯을 만든다.

        순서는 고시 2-1-4 — 조난 항공기 최우선, 그 외는 선착순(도달시각 순).
        """
        ordered = sorted(
            arrivals,
            key=lambda ac: (
                self.rules.priority_rank(ac)[0],
                self.earliest_threshold_time_s(ac, now_s),
            ),
        )
        return self._lay_out(ordered, now_s)

    def build_unsequenced(
        self, arrivals: list[AircraftState], now_s: float = 0.0
    ) -> Schedule:
        """간격 조정 없이 도달시각 순으로만 늘어놓은 스케줄 — 현행 대비 기준선.

        각 기가 지연 없이 자기 속도로 들어오는 경우다. 도착 흐름이 촘촘하면
        분리·후류 요건을 만족하지 못하며, 그 상태를 무엇으로 푸는지가
        디컨플릭션 설계의 갈림길이다 — 측방 오프셋이 아니라 슬롯 재배정이다.
        """
        ordered = sorted(
            arrivals,
            key=lambda ac: (
                self.rules.priority_rank(ac)[0],
                self.earliest_threshold_time_s(ac, now_s),
            ),
        )
        pinned = {
            ac.callsign: self.earliest_threshold_time_s(ac, now_s) for ac in ordered
        }
        return self._lay_out(ordered, now_s, pinned=pinned)

    def _lay_out(
        self,
        ordered: list[AircraftState],
        now_s: float,
        pinned: dict[str, float] | None = None,
    ) -> Schedule:
        """주어진 순서대로 슬롯 시각을 밀어낸다.

        Args:
            pinned: 시각을 고정할 콜사인 → 시단 통과시각. 이미 접근이 확정되어
                건드리면 안 되는 항적에 쓴다.
        """
        pinned = pinned or {}
        slots: list[Slot] = []
        prev: AircraftState | None = None
        prev_t = -math.inf

        for i, ac in enumerate(ordered):
            earliest = self.earliest_threshold_time_s(ac, now_s)
            gap = None if prev is None else self.gap_requirement(prev, ac)

            if ac.callsign in pinned:
                t = pinned[ac.callsign]
            else:
                t = earliest if gap is None else max(earliest, prev_t + gap.seconds)

            slots.append(
                Slot(
                    callsign=ac.callsign,
                    order=i,
                    threshold_time_s=t,
                    earliest_time_s=earliest,
                    assigned_alt_ft=self.rules.assigned_altitude_ft(i),
                    holding_above=self.rules.ladder_exhausted(i),
                    gap=gap,
                    priority=ac.emergency,
                )
            )
            prev, prev_t = ac, t

        return Schedule(
            slots=slots,
            join_dist_nm=self.join_dist_nm,
            final_course_deg=self.final_course_deg,
        )

    # ------------------------------------------------------------------
    # 우선권 삽입 (고시 2-1-4 가)
    # ------------------------------------------------------------------

    def insert_priority(
        self,
        arrivals: list[AircraftState],
        emergency_callsign: str,
        now_s: float = 0.0,
        freeze_nm: float | None = None,
    ) -> Schedule:
        """조난 항공기를 물리적 최단 도달시각 기준으로 삽입한다.

        **순번으로 밀어넣지 않는다.** 비상기를 1번으로 놓으면 그 기체가 아직 멀리
        있는 동안 활주로가 비고, 뒤 항적 전체가 그만큼 밀린다. 대신 비상기가
        물리적으로 도달 가능한 가장 이른 시각에 넣고, 그 시각 이전에 착륙하는
        항적은 그대로 둔다.

        시단 `freeze_nm` 안쪽 항적은 이미 접근이 확정된 것으로 보고 슬롯을 고정한다.
        """
        if freeze_nm is None:
            freeze_nm = self._cfg["priority_freeze_nm"]

        by_cs = {ac.callsign: ac for ac in arrivals}
        emergency = replace(by_cs[emergency_callsign], emergency=True)

        normal = [ac for ac in arrivals if ac.callsign != emergency_callsign]
        baseline = self.build(normal, now_s)
        emg_earliest = self.earliest_threshold_time_s(emergency, now_s)

        # 삽입 위치는 **순번이 아니라 시각**으로 정한다.
        #
        # 비상기를 1번으로 밀어넣으면, 비상기가 아직 멀리 있는 동안 활주로가 비고
        # 뒤 항적 전체가 그 공백만큼 밀린다. 대신 비상기가 물리적으로 도달 가능한
        # 가장 이른 시각(emg_earliest)을 기준으로, 그 전에 이미 착륙하는 항적은
        # 그대로 두고 그 뒤부터 밀어낸다.
        idx_time = sum(1 for s in baseline.slots if s.threshold_time_s <= emg_earliest)

        # 시단 freeze_nm 안쪽 항적은 이미 접근이 확정된 것으로 보고 무조건 앞에 둔다.
        idx_frozen = max(
            (
                i + 1
                for i, s in enumerate(baseline.slots)
                if self.distance_to_threshold_nm(by_cs[s.callsign]) <= freeze_nm
            ),
            default=0,
        )
        idx = max(idx_time, idx_frozen)

        states = [by_cs[s.callsign] for s in baseline.slots]
        ordered = states[:idx] + [emergency] + states[idx:]
        pinned = {s.callsign: s.threshold_time_s for s in baseline.slots[:idx]}
        return self._lay_out(ordered, now_s, pinned=pinned)


@dataclass(frozen=True)
class SequenceComparison:
    """두 스케줄 비교 — 우선권 적용 효과 측정."""

    subject: str
    order_before: int
    order_after: int
    time_before_s: float
    time_after_s: float
    displaced: list[str]
    mean_added_delay_s: float

    @property
    def time_saved_s(self) -> float:
        return self.time_before_s - self.time_after_s


def compare(before: Schedule, after: Schedule, subject: str) -> SequenceComparison:
    """우선권 삽입 전후를 비교한다 — 순번 변화, 시간 단축, 소산 항적, 추가 지연."""
    b = before.by_callsign(subject)
    a = after.by_callsign(subject)

    displaced: list[str] = []
    added: list[float] = []
    for slot_after in after.slots:
        if slot_after.callsign == subject:
            continue
        try:
            slot_before = before.by_callsign(slot_after.callsign)
        except KeyError:
            continue
        delta = slot_after.threshold_time_s - slot_before.threshold_time_s
        if delta > 1.0:
            displaced.append(slot_after.callsign)
            added.append(delta)

    return SequenceComparison(
        subject=subject,
        order_before=b.order,
        order_after=a.order,
        time_before_s=b.threshold_time_s,
        time_after_s=a.threshold_time_s,
        displaced=displaced,
        mean_added_delay_s=sum(added) / len(added) if added else 0.0,
    )


def build(ds) -> ArrivalSequencer:
    return ArrivalSequencer(ds=ds, rules=RuleBook(ds))


# ----------------------------------------------------------------------
# 착륙순서 최적화 — 순번 이동 제한(CPS) 내 국소 탐색
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class OrderingResult:
    """순서 최적화 결과."""

    order: list[str]
    baseline_order: list[str]
    completion_s: float
    """마지막 착륙 시각. 이것이 최소화 대상이다."""

    baseline_completion_s: float
    mean_gap_s: float
    baseline_mean_gap_s: float
    max_shift: int
    swaps: int
    iterations: int

    @property
    def improvement(self) -> float:
        """선착순 대비 총 소요 단축률. 단조 개선이므로 음수가 될 수 없다."""
        if self.baseline_completion_s == 0.0:
            return 0.0
        return (
            (self.baseline_completion_s - self.completion_s) / self.baseline_completion_s
        )

    @property
    def gap_improvement(self) -> float:
        """평균 착륙 간격 단축률."""
        if self.baseline_mean_gap_s == 0.0:
            return 0.0
        return (self.baseline_mean_gap_s - self.mean_gap_s) / self.baseline_mean_gap_s

    def shifts(self) -> dict[str, int]:
        """콜사인별 순번 이동량 (양수 = 뒤로 밀림)."""
        base = {cs: i for i, cs in enumerate(self.baseline_order)}
        return {cs: i - base[cs] for i, cs in enumerate(self.order)}


def _completion_s(sequencer, order: list[AircraftState], now_s: float) -> float:
    """이 순서로 늘어놓았을 때 마지막 착륙 시각."""
    schedule = sequencer._lay_out(order, now_s)
    return schedule.slots[-1].threshold_time_s if schedule.slots else 0.0


def _within_cps(
    order: list[AircraftState], base_index: dict[str, int], max_shift: int
) -> bool:
    """순번 이동 제한 — 고시 2-1-4 의 선착순 원칙을 지키기 위한 제약.

    선착순에서 몇 자리까지 벗어날 수 있는지를 정한다. 제한이 없으면 형식적으로는
    선착순 원칙을 지킬 수 없고, 뒤에 온 항적이 무한정 밀릴 수 있다.
    """
    for i, ac in enumerate(order):
        if abs(i - base_index[ac.callsign]) > max_shift:
            return False
    return True


def optimize_order(
    sequencer: ArrivalSequencer,
    arrivals: list[AircraftState],
    *,
    max_shift: int = 1,
    now_s: float = 0.0,
    max_iterations: int = 200,
) -> OrderingResult:
    """순번 이동 제한 안에서 총 소요를 줄인다.

    **선착순에서 출발해 개선되는 인접 교환만 받아들인다.** 탐욕법으로 처음부터
    재배열하면 앞쪽에서 제약을 다 써버려 뒤쪽이 움직이지 못하고, 결과가 선착순보다
    나빠질 수 있다. 여기서는 매 교환이 목적함수를 엄격히 줄일 때만 채택하므로
    **단조 개선이 보장되어 선착순보다 나빠질 수 없다.**

    항적난기류 요건이 선행·후행 등급 조합으로 정해지므로, 같은 항공기 집합이라도
    순서에 따라 총 소요가 달라진다(고시 5-5-4 사·아항). 그 차이만 회수한다.

    비상 항공기는 뒤로 밀지 않는다 (고시 2-1-4 가).
    """
    baseline = sorted(
        arrivals,
        key=lambda ac: (
            sequencer.rules.priority_rank(ac)[0],
            sequencer.earliest_threshold_time_s(ac, now_s),
        ),
    )
    base_index = {ac.callsign: i for i, ac in enumerate(baseline)}
    base_completion = _completion_s(sequencer, baseline, now_s)
    base_schedule = sequencer._lay_out(baseline, now_s)

    current = list(baseline)
    best = base_completion
    swaps = 0
    iterations = 0

    # 제한을 1부터 단계적으로 넓히며, 각 단계는 이전 단계의 해에서 출발한다.
    #
    # 국소 탐색은 경로 의존적이라 제한을 넓히면 다른 국소최적으로 빠져 오히려
    # 나빠질 수 있다. CPS 제약은 선착순 기준이므로 ±(k−1) 에서 유효한 해는
    # ±k 에서도 유효하다. 따라서 이전 단계 해에서 출발하면 **제한을 넓혔을 때
    # 나빠지지 않음이 구조적으로 보장된다.**
    for limit in range(1, max(max_shift, 0) + 1):
        improved = True
        while improved and iterations < max_iterations:
            improved = False
            iterations += 1
            # 최급강하 — 개선 폭이 가장 큰 교환을 고른다. 첫 개선을 즉시 받으면
            # 결과가 항적 나열 순서에 따라 달라져 재현성이 떨어진다.
            best_swap = None
            for i in range(len(current) - 1):
                a, b = current[i], current[i + 1]
                if a.emergency or b.emergency:
                    continue  # 우선권 항적의 순번은 건드리지 않는다 (고시 2-1-4 가)
                trial = list(current)
                trial[i], trial[i + 1] = trial[i + 1], trial[i]
                if not _within_cps(trial, base_index, limit):
                    continue
                value = _completion_s(sequencer, trial, now_s)
                if value < best - 1e-6 and (best_swap is None or value < best_swap[1]):
                    best_swap = (trial, value)
            if best_swap is not None:
                current, best = best_swap
                swaps += 1
                improved = True

    schedule = sequencer._lay_out(current, now_s)
    return OrderingResult(
        order=[ac.callsign for ac in current],
        baseline_order=[ac.callsign for ac in baseline],
        completion_s=best,
        baseline_completion_s=base_completion,
        mean_gap_s=schedule.mean_gap_s,
        baseline_mean_gap_s=base_schedule.mean_gap_s,
        max_shift=max_shift,
        swaps=swaps,
        iterations=iterations,
    )
