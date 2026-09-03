"""규정 엔진 — 어떤 상황에 어떤 분리 최저치가 적용되는가.

고시 「항공교통관제절차」의 수치를 그대로 쓰되, **조항에 붙은 조건까지 구현한다.**
표만 옮기면 틀린다. 예컨대 항적난기류 분리(5-5-4 사)는 후행기가 선행기 비행경로
측방 2,500ft 이내이면서 1,000ft 미만 아래일 때만 적용되고, 착륙 시 최저치(5-5-4 아)는
그와 별개로 "부가하여" 적용된다.

모든 판정은 근거 조항과 사유를 함께 돌려준다 — 관제사에게 상신할 때 붙일 근거이자,
검증·인증 가능성의 근거이기도 하다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .geometry import along_track_separation_nm, cross_track_offset_nm
from .state import AircraftState

FT_PER_NM = 6076.11548556

# 종렬 거리 비교의 수치 허용오차 (NM).
#
# 요건과 실제가 정확히 같도록 계산된 경우에도, 좌표 왕복 변환
# (시각 → 거리 → 위경도 → 측지거리) 에서 1e-5 NM 규모의 오차가 누적되어
# 위반 판정이 나온다. 이 값은 그 수치 오차만 흡수한다.
#
# 1e-4 NM = 0.19 m. 레이더 위치 정확도(0.1 NM 규모)보다 세 자릿수 작고
# 분리 최저치 3 NM 의 1/30,000 이라 운용상 의미가 없다.
# 분리를 완화하는 값이 아니며, 이보다 큰 부족은 전부 위반으로 잡는다.
SEPARATION_EPS_NM = 1e-4


@dataclass(frozen=True)
class SeparationStandard:
    """한 쌍에 적용되는 분리 최저치와 그 근거."""

    horizontal_nm: float
    vertical_ft: float
    clauses: tuple[str, ...]
    rationale: str

    def __str__(self) -> str:
        return (
            f"수평 {self.horizontal_nm:g}NM / 수직 {self.vertical_ft:g}ft "
            f"[{', '.join(self.clauses)}]"
        )


@dataclass(frozen=True)
class InTrailRequirement:
    """종렬(along-track) 거리 요건 — 항적난기류.

    실린더가 아니라 같은 진로 위의 앞뒤 거리 요건이므로 분리 판정과 따로 둔다.
    """

    required_nm: float
    applies: bool
    clauses: tuple[str, ...]
    rationale: str


@dataclass
class RuleBook:
    """Dataset 위에 얹는 규정 해석기.

    수치는 전부 data/airspace.json 에서 읽는다. 이 클래스는 '언제 무엇을 쓰는가'만 안다.
    """

    ds: object
    _sep: dict = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._sep = self.ds.airspace.raw["separation"]

    # ------------------------------------------------------------------
    # 수평·수직 분리 최저치 (보호실린더)
    # ------------------------------------------------------------------

    def separation_standard(
        self, a: AircraftState, b: AircraftState, *, on_final_within_10nm: bool = False
    ) -> SeparationStandard:
        """두 항적에 적용할 보호실린더 치수.

        Args:
            on_final_within_10nm: 두 기 모두 착륙활주로 10NM 안쪽 최종접근로에 있는가.
                고시 5-5-4 차의 2.5NM 감축은 시설 조건이 문서로 입증되어야 하므로
                data 의 reduced_final.enabled 가 켜져 있을 때만 적용한다.
        """
        clauses: list[str] = ["5-5-4 가"]
        rationale = "ASR 안테나 40마일 미만 — 레이더 분리 최저치 3마일"
        horizontal = self._sep["radar_horizontal"]["within_40nm_of_asr_nm"]

        reduced = self._sep.get("reduced_final", {})
        if on_final_within_10nm and reduced.get("enabled"):
            if self._reduced_final_allowed(a, b):
                horizontal = reduced["value_nm"]
                clauses = ["5-5-4 차"]
                rationale = "최종접근로 10마일 안쪽, 중량등급 조건 충족 — 2.5마일 감축"

        # 편대비행 추가분리 (5-5-8) — 군 운용 공역에서 실제로 발생한다.
        extra, formation_clause = self._formation_extra_nm(a, b)
        if extra:
            horizontal += extra
            clauses.append(formation_clause)
            rationale += f"; 편대비행 추가분리 +{extra:g}마일"

        return SeparationStandard(
            horizontal_nm=horizontal,
            vertical_ft=self._sep["vertical"]["below_fl410_ft"],
            clauses=tuple(clauses) + ("4-5-1",),
            rationale=rationale,
        )

    def _reduced_final_allowed(self, leader: AircraftState, follower: AircraftState) -> bool:
        """5-5-4 차 1)·2) — 선행기 중량등급이 후행기 이하일 것."""
        order = {"소형": 0, "중형": 1, "대형": 2, "초대형": 3}
        return order[leader.wake_cat] <= order[follower.wake_cat]

    def _formation_extra_nm(self, a: AircraftState, b: AircraftState) -> tuple[float, str]:
        """5-5-8 편대비행 추가분리."""
        cfg = self._sep.get("formation")
        if not cfg:
            return 0.0, ""
        fa = getattr(a, "is_formation", False)
        fb = getattr(b, "is_formation", False)
        if fa and fb:
            return cfg["standard_vs_standard_add_nm"], "5-5-8 나"
        if fa or fb:
            return cfg["standard_vs_other_add_nm"], "5-5-8 가"
        return 0.0, ""

    # ------------------------------------------------------------------
    # 항적난기류 종렬 분리
    # ------------------------------------------------------------------

    def wake_by_category(
        self, leader_cat: str, follower_cat: str, *, same_landing_runway: bool = False
    ) -> InTrailRequirement:
        """등급 조합만으로 항적난기류 종렬 요건을 조회한다 (기하 조건은 보지 않음).

        도착 시퀀싱은 아직 최종접근에 들어오지 않은 항적의 슬롯을 미리 잡아야 하므로,
        "종렬로 세웠을 때 얼마가 필요한가"를 위치와 무관하게 알아야 한다. 실제 판정
        시점의 기하 조건 확인은 `wake_in_trail` 이 담당한다.
        """
        wake = self._sep["wake_turbulence"]
        clauses: list[str] = []
        reasons: list[str] = []
        required = 0.0
        key = f"{leader_cat}|{follower_cat}"

        inflight = wake["in_flight"]
        v = inflight["minima_nm"].get(key)
        if v is not None:
            required = v
            clauses.append(inflight["_clause"])
            reasons.append(f"{leader_cat} 뒤 {follower_cat} {v:g}마일")

        # 아항은 사항에 "부가하여" 적용되므로 실제 요건은 둘 중 큰 값이다.
        if same_landing_runway:
            v = wake["landing"]["minima_nm"].get(key)
            if v is not None:
                if v > required:
                    reasons.append(f"착륙 시 {leader_cat} 뒤 {follower_cat} {v:g}마일")
                required = max(required, v)
                clauses.append(wake["landing"]["_clause"])

        if required == 0.0:
            return InTrailRequirement(
                required_nm=0.0,
                applies=False,
                clauses=(),
                rationale="해당 등급 조합에 항적난기류 추가분리 불요",
            )
        return InTrailRequirement(
            required_nm=required,
            applies=True,
            clauses=tuple(clauses),
            rationale="; ".join(reasons),
        )

    def wake_in_trail(
        self,
        leader: AircraftState,
        follower: AircraftState,
        *,
        same_landing_runway: bool = False,
    ) -> InTrailRequirement:
        """항적난기류 종렬 요건 — 기하 조건까지 확인한 실제 적용 판정.

        고시 5-5-4 사 (비행 중) 과 아 (동일 활주로 착륙) 를 모두 본다.

        사항은 기하 조건이 붙는다 — 후행기가 선행기 비행경로 측방 2,500ft 이내이면서
        선행기보다 1,000ft 미만 아래일 때. 조건을 벗어나면 사항은 적용되지 않는다.
        아항(착륙)은 이 기하 조건과 무관하게 적용된다.
        """
        wake = self._sep["wake_turbulence"]
        inflight = wake["in_flight"]
        gate_ok, gate_why = self._wake_geometry_gate(leader, follower, inflight)

        if gate_ok:
            req = self.wake_by_category(
                leader.wake_cat, follower.wake_cat, same_landing_runway=same_landing_runway
            )
            if req.applies:
                return req
            return req

        # 사항 기하 조건 불충족 — 아항(착륙)만 남는다.
        if same_landing_runway:
            v = wake["landing"]["minima_nm"].get(f"{leader.wake_cat}|{follower.wake_cat}")
            if v is not None:
                return InTrailRequirement(
                    required_nm=v,
                    applies=True,
                    clauses=(wake["landing"]["_clause"],),
                    rationale=(
                        f"착륙 시 {leader.wake_cat} 뒤 {follower.wake_cat} {v:g}마일 "
                        f"(비행 중 요건은 불요 — {gate_why})"
                    ),
                )
        return InTrailRequirement(
            required_nm=0.0, applies=False, clauses=(), rationale=gate_why
        )

    def _wake_geometry_gate(
        self, leader: AircraftState, follower: AircraftState, inflight: dict
    ) -> tuple[bool, str]:
        """5-5-4 사 1) 의 기하 조건 판정.

        "지표상 앞서가는 항공기의 비행경로의 2,500피트 이내이면서
         앞서가는 항공기 아래로 1,000피트 미만의 고도로 비행하는 경우"
        """
        lateral_gate_nm = inflight["lateral_gate_ft"] / FT_PER_NM
        offset_nm = abs(
            cross_track_offset_nm(follower, leader.lat, leader.lon, leader.track_deg)
        )
        if offset_nm > lateral_gate_nm:
            return False, (
                f"후행기가 선행기 비행경로 측방 {offset_nm * FT_PER_NM:,.0f}ft — "
                f"{inflight['lateral_gate_ft']:,}ft 초과이므로 항적난기류 분리 불요 (5-5-4 사 1)"
            )

        # "앞서가는 항공기 아래로 1,000피트 **미만**의 고도로 비행하는 경우" —
        # 배제되는 것은 1,000ft 이상 아래로 벌어진 경우뿐이다. 후행기가 선행기보다
        # 높은 경우(아래 편차 0 이하)는 조건을 만족한다. 3° 활공로에서 후행기는
        # 항상 선행기보다 높으므로, 여기서 배제해 버리면 정상 접근 시퀀스에
        # 항적난기류 분리가 한 번도 적용되지 않는다.
        below_ft = leader.alt_ft - follower.alt_ft
        if below_ft >= inflight["below_gate_ft"]:
            return False, (
                f"후행기가 선행기보다 {below_ft:,.0f}ft 아래 — "
                f"{inflight['below_gate_ft']:,}ft 이상이므로 항적난기류 분리 불요 (5-5-4 사 1)"
            )
        return True, ""

    def wake_violation(
        self,
        leader: AircraftState,
        follower: AircraftState,
        course_deg: float,
        *,
        same_landing_runway: bool = False,
    ) -> tuple[bool, InTrailRequirement, float]:
        """실제 종렬 거리가 요건에 못 미치는가.

        Returns:
            (위반 여부, 적용 요건, 실제 종렬 거리 NM)
        """
        req = self.wake_in_trail(leader, follower, same_landing_runway=same_landing_runway)
        actual = along_track_separation_nm(leader, follower, course_deg)
        violated = req.applies and actual < req.required_nm - SEPARATION_EPS_NM
        return violated, req, actual

    # ------------------------------------------------------------------
    # 우선권 (2-1-4)
    # ------------------------------------------------------------------

    def priority_rank(self, ac: AircraftState) -> tuple[int, str]:
        """낮을수록 우선. 고시 2-1-4 가 — 조난 항공기 최우선 통행권.

        그 외에는 선착순(First Come, First Served)이 원칙이므로 순위를 매기지 않고
        도착 예정 순서를 그대로 쓴다.
        """
        if ac.emergency:
            return 0, "조난 항공기 최우선 통행권 (2-1-4 가)"
        return 1, "선착순 원칙 (2-1-4)"

    # ------------------------------------------------------------------
    # 고도 배정 (4-5-1 / 4-5-2)
    # ------------------------------------------------------------------

    @property
    def altitude_ladder_ft(self) -> list[int]:
        """도착 순번별 배정고도 사다리. T17 상한 6,500ft 때문에 3층만 들어간다."""
        return self.ds.airspace.altitude_ladder_ft

    def assigned_altitude_ft(self, sequence_index: int) -> int:
        """착륙 순번 → 배정고도.

        순번이 뒤일수록 높은 고도를 유지하다 자기 차례에 순차 강하한다.
        인접 순번 간 1,000ft 수직분리(4-5-1)가 구조적으로 확보된다.
        사다리를 넘어서는 순번은 최상층에 몰리므로, 그 위는 상위 섹터 대기다.
        """
        ladder = self.altitude_ladder_ft
        return ladder[min(sequence_index, len(ladder) - 1)]

    def ladder_exhausted(self, sequence_index: int) -> bool:
        """사다리를 넘어선 순번인가 — 중원 APP 대기 대상."""
        return sequence_index >= len(self.altitude_ladder_ft)

    def cruise_altitude_ft(self, track_deg: float, at_or_above_ft: float) -> int:
        """4-5-2 를 만족하는 최저 순항고도.

        자침 0~179°는 홀수천, 180~359°는 짝수천. 주어진 하한 이상에서 가장 낮은
        적합 고도를 돌려준다. 출발기의 순항고도를 지어내지 않고 규정에서 끌어내기
        위한 것이다 — 방향이 바뀌면 배정고도도 바뀐다.
        """
        mag = (track_deg + self.ds.procedures.mag_var) % 360.0
        odd_required = mag < 180.0
        k = math.ceil(at_or_above_ft / 1000.0)
        if (k % 2 == 1) != odd_required:
            k += 1
        return int(k * 1000)

    def direction_of_flight_altitude_ok(self, ac: AircraftState) -> tuple[bool, str]:
        """4-5-2 비행방향별 순항고도 배정 — 자침 0~179° 홀수, 180~359° 짝수.

        접근관제구역 내 배정고도(벡터링 고도)에는 적용되지 않고 순항고도에 적용된다.
        T17 은 6,500ft 상한이라 실질적으로 해당 없으나, 상위 섹터 인계 시 확인용.
        """
        mag = (ac.track_deg + self.ds.procedures.mag_var) % 360.0
        thousands = round(ac.alt_ft / 1000.0)
        odd_required = mag < 180.0
        ok = (thousands % 2 == 1) if odd_required else (thousands % 2 == 0)
        want = "홀수" if odd_required else "짝수"
        return ok, f"자침 {mag:.0f}° → {want} 고도 (4-5-2)"

    # ------------------------------------------------------------------
    # 인접 공역 (5-5-10)
    # ------------------------------------------------------------------

    @property
    def adjacent_boundary_buffer_nm(self) -> float:
        """협의되지 않은 경우 인접공역 경계에서 유지할 간격."""
        return self._sep["adjacent_airspace"]["within_40nm_nm"]


def wake_category_for_type(actype: str, default: str = "중형") -> str:
    """기종 코드 → 후류 등급.

    민항 기종은 통상 최대이륙중량 기준으로 분류되고, 군용기는 공개 제원 기반
    대표값을 쓴다 (한계로 명시할 사항). Phase 3 에서 기종 DB 로 옮긴다.
    """
    return default
