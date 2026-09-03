"""충돌 탐지 — 기하·규정·공역을 묶어 항적 집합 전체를 훑는다.

Phase 2 의 출구. 여기서 나오는 `Conflict` 는 전부 결정론이고 근거 조항을 달고 있다.
Phase 4(CD&R)가 회피 후보를 만들면 다시 이 탐지기로 재검증해서 2차 충돌을 막고,
Phase 5(MBE)는 이 결과에 위험 점수를 붙여 상신 여부를 판단한다.

책임 범위: **청주 GCA 가 분리를 제공해야 하는 항적 쌍만** 본다. 인접 기관 관할
항적은 교통정보 대상이지 분리 대상이 아니다 (고시 2-1-15 — 통신 인수가 곧 책임 인수).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

from .geometry import (
    DEFAULT_LOOKAHEAD_S,
    ConflictWindow,
    along_track_separation_nm,
    pair_conflict,
)
from .rules import InTrailRequirement, RuleBook, SeparationStandard
from .sector import SectorModel
from .state import AircraftState


class ConflictKind(Enum):
    """분리 종류. 근거 조항이 다르므로 구분한다."""

    RADAR = "레이더 분리"          # 고시 5-5-4 가 + 4-5-1 (보호실린더)
    WAKE = "항적난기류 분리"        # 고시 5-5-4 사·아 (종렬 거리)


@dataclass(frozen=True)
class Conflict:
    """한 쌍의 분리 위반 또는 예상 위반."""

    kind: ConflictKind
    first: str
    second: str
    clauses: tuple[str, ...]
    rationale: str

    window: ConflictWindow | None = None
    """레이더 분리 침범 구간. 항적난기류는 None."""

    required_nm: float = 0.0
    actual_nm: float = 0.0
    """항적난기류 종렬 요건과 실제 거리. 레이더 분리는 window 를 본다."""

    @property
    def pair(self) -> tuple[str, str]:
        return (self.first, self.second)

    @property
    def time_to_violation_s(self) -> float:
        """예지시간. 이미 위반이면 0."""
        return self.window.time_to_violation_s if self.window else 0.0

    @property
    def is_active(self) -> bool:
        """이미 분리위반 상태인가."""
        if self.kind is ConflictKind.WAKE:
            return True  # 종렬 요건은 현재 상태 판정이다
        return bool(self.window and self.window.is_active)

    def describe(self) -> str:
        """관제사에게 상신할 때 붙일 한 줄 근거."""
        if self.kind is ConflictKind.WAKE:
            return (
                f"{self.first} → {self.second} 종렬 {self.actual_nm:.1f}NM "
                f"(요건 {self.required_nm:.0f}NM) — {self.rationale} "
                f"[{', '.join(self.clauses)}]"
            )
        w = self.window
        assert w is not None
        when = "위반 중" if w.is_active else f"{w.time_to_violation_s:.0f}초 후"
        return (
            f"{self.first} ↔ {self.second} {when}, "
            f"CPA {w.cpa.horizontal_nm:.1f}NM / {w.cpa.vertical_ft:.0f}ft "
            f"(최저치 {w.h_min_nm:g}NM / {w.v_min_ft:g}ft) [{', '.join(self.clauses)}]"
        )


@dataclass
class Detector:
    """결정론 충돌 탐지기."""

    rules: RuleBook
    sector: SectorModel
    lookahead_s: float = DEFAULT_LOOKAHEAD_S

    threshold: tuple[float, float] | None = None
    """도착 활주로 시단 좌표. 주면 **최종접근에 정렬된** 항적의 예측 지평을
    착륙 시점에서 끊는다.

    등속 외삽은 항공기가 영원히 직진한다고 본다. 도착기의 궤적은 시단에서
    끝나므로, 그 뒤까지 외삽하면 이미 착륙한 선행기를 후행기가 따라잡는
    가짜 충돌이 잡힌다. 최종접근 종렬은 원래 뒤로 갈수록 붙는 구조라
    이 오탐이 대량으로 나온다.

    다만 공항 쪽으로 향한다고 다 착륙하는 것은 아니다. 공역을 통과하는
    교차 항적까지 지평을 끊으면 실재하는 충돌을 놓친다. 그래서 조건을
    **연장 중심선 정렬**로 좁힌다.
    """

    final_course_deg: float | None = None
    """최종접근 진로 (진방위). 지평 제한의 정렬 판정에 쓴다."""

    established_offset_nm: float = 1.0
    """연장 중심선에서 이 안쪽이어야 '접근 중'으로 본다."""

    established_track_deg: float = 10.0
    """침로가 최종접근 진로와 이 안쪽이어야 '접근 중'으로 본다."""

    # --- 예측 지평 ---

    def is_on_final(self, ac: AircraftState) -> bool:
        """최종접근에 정렬되어 곧 착륙할 항적인가.

        중심선 정렬과 침로 일치를 모두 본다. 둘 중 하나만 보면 활주로 위를
        가로지르는 항적이나 중심선과 나란히 지나가는 항적을 잘못 넣는다.
        """
        if self.threshold is None or self.final_course_deg is None:
            return False
        from .geo import angular_diff, bearing_true, separation_distance_nm
        from .geometry import cross_track_offset_nm

        if abs(angular_diff(ac.track_deg, self.final_course_deg)) > self.established_track_deg:
            return False
        if abs(cross_track_offset_nm(ac, *self.threshold, self.final_course_deg)) > (
            self.established_offset_nm
        ):
            return False
        # 시단을 지나쳐 이륙 방향으로 나가는 항적은 제외
        brg = bearing_true(ac.lat, ac.lon, *self.threshold)
        if separation_distance_nm(ac.lat, ac.lon, *self.threshold) < 1e-6:
            return False
        return abs(angular_diff(brg, ac.track_deg)) <= 90.0

    def time_to_threshold_s(self, ac: AircraftState) -> float | None:
        """최종접근 정렬 항적이 시단에 닿기까지의 시간. 그 외에는 None."""
        if not self.is_on_final(ac) or ac.gs_kt <= 0:
            return None
        from .geo import separation_distance_nm

        return separation_distance_nm(ac.lat, ac.lon, *self.threshold) / ac.gs_kt * 3600.0

    def _horizon_s(self, a: AircraftState, b: AircraftState) -> float:
        """이 쌍에 적용할 예측 지평."""
        limits = [self.lookahead_s]
        for ac in (a, b):
            t = self.time_to_threshold_s(ac)
            if t is not None:
                limits.append(t)
        return max(0.0, min(limits))

    # --- 한 쌍 ---

    def check_radar(
        self, a: AircraftState, b: AircraftState, *, on_final_within_10nm: bool = False
    ) -> Conflict | None:
        """보호실린더 침범 (고시 5-5-4 가 + 4-5-1)."""
        std: SeparationStandard = self.rules.separation_standard(
            a, b, on_final_within_10nm=on_final_within_10nm
        )
        w = pair_conflict(a, b, std.horizontal_nm, std.vertical_ft, self._horizon_s(a, b))
        if w is None:
            return None
        return Conflict(
            kind=ConflictKind.RADAR,
            first=a.callsign,
            second=b.callsign,
            clauses=std.clauses,
            rationale=std.rationale,
            window=w,
        )

    def check_wake(
        self,
        leader: AircraftState,
        follower: AircraftState,
        course_deg: float,
        *,
        same_landing_runway: bool = False,
    ) -> Conflict | None:
        """항적난기류 종렬 부족 (고시 5-5-4 사·아)."""
        violated, req, actual = self.rules.wake_violation(
            leader, follower, course_deg, same_landing_runway=same_landing_runway
        )
        if not violated:
            return None
        return Conflict(
            kind=ConflictKind.WAKE,
            first=leader.callsign,
            second=follower.callsign,
            clauses=req.clauses,
            rationale=req.rationale,
            required_nm=req.required_nm,
            actual_nm=actual,
        )

    # --- 전체 훑기 ---

    def scan(
        self,
        traffic: list[AircraftState],
        *,
        final_course_deg: float | None = None,
        landing_sequence: list[str] | None = None,
    ) -> list[Conflict]:
        """책임 항적 전체를 훑어 위반·예상위반을 모은다.

        Args:
            traffic: 현재 항적 집합.
            final_course_deg: 최종접근 진로. 주면 항적난기류 종렬도 함께 본다.
            landing_sequence: 착륙 순서(콜사인). 주면 인접 순번 쌍만 종렬 판정한다.

        Returns:
            예지시간이 짧은 순 — 급한 것이 먼저.
        """
        mine = [ac for ac in traffic if self.sector.is_under_control(ac)]
        out: list[Conflict] = []

        for i, a in enumerate(mine):
            for b in mine[i + 1:]:
                c = self.check_radar(a, b)
                if c is not None:
                    out.append(c)

        if final_course_deg is not None:
            out.extend(self._scan_wake(mine, final_course_deg, landing_sequence))

        out.sort(key=lambda c: (not c.is_active, c.time_to_violation_s))
        return out

    def _scan_wake(
        self,
        mine: list[AircraftState],
        course_deg: float,
        landing_sequence: list[str] | None,
    ) -> list[Conflict]:
        by_cs = {ac.callsign: ac for ac in mine}
        out: list[Conflict] = []

        if landing_sequence is not None:
            pairs = [
                (by_cs[x], by_cs[y])
                for x, y in zip(landing_sequence, landing_sequence[1:])
                if x in by_cs and y in by_cs
            ]
        else:
            # 순서를 안 주면 진로 방향 앞뒤 관계로 선후를 정한다.
            pairs = []
            for i, a in enumerate(mine):
                for b in mine[i + 1:]:
                    d = along_track_separation_nm(a, b, course_deg)
                    pairs.append((a, b) if d > 0 else (b, a))

        for leader, follower in pairs:
            c = self.check_wake(leader, follower, course_deg, same_landing_runway=True)
            if c is not None:
                out.append(c)
        return out

    # --- 회피 후보 재검증 ---

    def is_clear(
        self,
        candidate: AircraftState,
        others: list[AircraftState],
        *,
        final_course_deg: float | None = None,
    ) -> bool:
        """회피 후보를 적용했을 때 다른 모든 항적과 분리가 유지되는가.

        학습이 낸 회피안도 반드시 이 재검증을 통과해야 관제사에게 상신된다.
        2차 충돌(회피가 만드는 새 충돌)을 여기서 걸러낸다.
        """
        for other in others:
            if other.callsign == candidate.callsign:
                continue
            if not self.sector.is_under_control(other):
                continue
            if self.check_radar(candidate, other) is not None:
                return False
            if final_course_deg is not None:
                d = along_track_separation_nm(candidate, other, final_course_deg)
                leader, follower = (
                    (candidate, other) if d > 0 else (other, candidate)
                )
                if self.check_wake(
                    leader, follower, final_course_deg, same_landing_runway=True
                ) is not None:
                    return False
        return True


def build(ds, runway: str = "24R") -> Detector:
    """Dataset 하나로 탐지기를 만든다.

    도착 활주로 시단을 넘겨 예측 지평이 착륙 시점에서 끊기도록 한다.
    """
    rwy = ds.procedures.runways[runway]
    return Detector(
        rules=RuleBook(ds),
        sector=SectorModel.from_dataset(ds),
        threshold=(rwy.thr_lat, rwy.thr_lon),
        final_course_deg=rwy.true_brg,
    )
