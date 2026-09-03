"""소티 시나리오 — 13단계를 하나의 시간선으로 엮는다.

지금까지의 모듈은 각자 한 가지씩 한다. 활주로는 활주로만, 체공은 체공만 안다.
이 모듈이 그것들을 순서대로 불러 **출격에서 정상 운항 복귀까지** 한 줄로 만든다.

여기서 새로 판단하는 것은 없다. 분리 최저치도, 체공 장주도, 우선권 기준도 전부
해당 모듈이 규정에서 낸 값을 그대로 받아 쓴다 — 시나리오가 규정을 다시 해석하기
시작하면 두 벌이 되고, 두 벌은 반드시 어긋난다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .hold import HoldAssignment, HoldingBook
from .mission import MissionBook, MissionKind, Sortie, SortiePhase
from .route import Route, RoutePlanner
from .runway import Operation, RunwayOp, RunwaySchedule, RunwaySequencer
from .schedule import Timetable


@dataclass(frozen=True)
class Step:
    """시나리오 한 단계 — 시연에서 짚고 넘어갈 지점."""

    n: int
    t_s: float
    name: str
    detail: str
    clauses: tuple[str, ...] = ()

    def hhmm(self) -> str:
        m = int(self.t_s // 60)
        return f"{m // 60 % 24:02d}:{m % 60:02d}"

    def describe(self) -> str:
        tag = f"  [{', '.join(self.clauses)}]" if self.clauses else ""
        return f"{self.n:2d}. {self.hhmm()}  {self.name} — {self.detail}{tag}"


@dataclass
class SortieScenario:
    """13단계 시나리오 구성기."""

    ds: object
    timetable: Timetable
    runway_seq: RunwaySequencer
    mission: MissionBook
    router: RoutePlanner
    holding: HoldingBook

    area_id: str = "MOA 3A"
    fighter_type: str = "F35A"
    fighter_callsign: str = "ROKAF01"
    kind: MissionKind = MissionKind.PATROL

    takeoff_offset_s: float = 15 * 60.0
    """운항 구간 시작 후 언제 출격하는가."""

    on_station_s: float = 20 * 60.0
    """작전지역 체공 시간. 이 뒤에 비상복귀가 발생한다."""

    patrol_sorties: int = 3
    """같은 구간에 있는 다른 순찰 소티 수.

    민항 시간표만 쓰면 청주 교통을 절반만 세는 것이다. 17전투비행단이 주둔하고
    "매일 있는 주기적인 순찰 임무"가 돌아가므로, 군 항적이 활주로 경합의 상당
    부분을 만든다. 이 값이 0 이면 민항만 있는 가상의 공항이 된다.
    """

    patrol_types: tuple[str, ...] = ("F35A", "KF16", "FA50")

    steps: list[Step] = field(default_factory=list, init=False)
    sortie: Sortie = field(init=False)
    baseline: RunwaySchedule | None = field(default=None, init=False)
    with_sortie: RunwaySchedule | None = field(default=None, init=False)
    final: RunwaySchedule | None = field(default=None, init=False)
    recovery_route: Route | None = field(default=None, init=False)
    holds: list[HoldAssignment] = field(default_factory=list, init=False)
    hold_refused: list[str] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        self.sortie = Sortie(
            callsign=self.fighter_callsign,
            actype=self.fighter_type,
            wake_cat=self.ds.fleet.wake_cat(self.fighter_type),
            kind=self.kind,
            area=self.mission.designate(self.area_id),
        )

    # ------------------------------------------------------------------

    @property
    def t0(self) -> float:
        return self.timetable.window_from_s

    def _step(self, n, t, name, detail, clauses=()) -> None:
        self.steps.append(Step(n, t, name, detail, tuple(clauses)))

    # ------------------------------------------------------------------

    def build(self) -> list[Step]:
        """13단계를 순서대로 실행하고 시간선을 만든다."""
        self.steps.clear()
        fleet = self.ds.fleet

        # 1. 민항 정상 운항 (+ 상시 순찰 소티)
        civil = self.timetable.to_runway_ops(fleet)
        patrol = self._patrol_ops()
        traffic = civil + patrol
        self.baseline = self.runway_seq.first_come_first_served(traffic, now_s=self.t0)
        span_h = max(
            self.timetable.window_to_s - self.timetable.window_from_s, 1.0
        ) / 3600.0
        self._step(
            1, self.t0, "민항 정상 운항",
            f"민항 {len(civil)}편 (도착 {len(self.timetable.arrivals)} / "
            f"출발 {len(self.timetable.departures)}) + 순찰 소티 {len(patrol)}회 "
            f"= 시간당 {len(traffic) / span_h:.1f}회 — {self.timetable.provenance()}",
        )

        # 2. 군 작전지역 지정
        area = self.sortie.area
        overlaps = area in self.mission.areas_conflicting_with_approach()
        self._step(
            2, self.t0 + 5 * 60.0, "군 작전지역 지정",
            f"{area.id} {area.lower_ft:,.0f}~{area.upper_ft:,.0f}ft, "
            f"공항기준점에서 {area.distance_from_nm(*self.ds.procedures.arp):.1f}NM"
            + ("  · 도착 배정고도와 고도 중첩" if overlaps else "  · 도착과 고도 분리"),
            ("ENR 5.2",),
        )

        # 3. 전투기 출격 및 활주로 우선권
        t_dep = self.t0 + self.takeoff_offset_s
        dep_op = RunwayOp(
            callsign=self.fighter_callsign,
            actype=self.fighter_type,
            wake_cat=self.sortie.wake_cat,
            op=Operation.DEPARTURE,
            earliest_s=t_dep,
        )
        self.with_sortie = self.runway_seq.first_come_first_served(
            traffic + [dep_op], now_s=self.t0
        )
        slot = self.with_sortie.by_callsign(self.fighter_callsign)
        self.sortie.takeoff_s = slot.time_s
        cost = self.with_sortie.total_delay_s - self.baseline.total_delay_s
        self._step(
            3, slot.time_s, "전투기 출격 · 활주로 우선권",
            f"{self.fighter_callsign} ({self.fighter_type}) 이륙 — "
            f"민항 추가지연 총 {cost / 60.0:.1f}분"
            + (f", 선행 요건 {slot.requirement}" if slot.requirement else ""),
            ("3-9-6",),
        )

        # 4. 공역·민항 고려 경로 계획
        outbound = self.router.plan(
            self.ds.procedures.arp, self._area_entry_fix(), 6000.0
        )
        if outbound is not None:
            self._step(
                4, slot.time_s + 60.0, "경로 계획",
                f"진출 {outbound.describe()}", ("ENR 5.1",),
            )

        # 5. 관제 이양
        self._step(
            5, slot.time_s + 90.0, "관제 이양",
            "CHEONGJU TWR → CHEONGJU GCA → OSAN APP (T17 상한 6,500ft) "
            "· 남동측 이탈 시 JUNGWON APP",
            ("2-1-15",),
        )

        # 6. 작전지역 진입
        t_on = slot.time_s + 7 * 60.0
        self.sortie.on_station_s = t_on
        self.sortie.phase = SortiePhase.ON_STATION
        self._step(6, t_on, "작전지역 진입", f"{area.id} 진입 — 임무 수행", ())

        # 7. 비상복귀 발생
        t_emg = t_on + self.on_station_s
        self.mission.declare_recovery(self.sortie, t_emg, emergency=True)
        self.sortie.off_station_s = t_emg
        tcas = "미장착" if not fleet.has_tcas(self.fighter_type) else "장착"
        self._step(
            7, t_emg, "비상복귀 발생",
            f"{self.fighter_callsign} 비상 선언 (TCAS {tcas}) — "
            f"작전 체공 {(t_emg - t_on) / 60.0:.0f}분",
            ("2-1-4 가",),
        )

        # 8. 최단 복귀경로 생성
        self.recovery_route = self._plan_recovery()
        if self.recovery_route is not None:
            gs = fleet.final_gs_kt(self.fighter_type)
            self._step(
                8, t_emg + 30.0, "최단 복귀경로",
                f"{self.recovery_route.describe()} — 예상 소요 "
                f"{self.recovery_route.ete_s(gs) / 60.0:.1f}분",
            )

        # 9~10. 충돌 탐지와 해소 (체공·순서 조정)
        eta = t_emg + (
            self.recovery_route.ete_s(fleet.final_gs_kt(self.fighter_type))
            if self.recovery_route else 10 * 60.0
        )
        contested = [
            s for s in self.with_sortie.arrivals()
            if abs(s.time_s - eta) < 8 * 60.0 and s.op.callsign != self.fighter_callsign
        ]
        self._step(
            9, t_emg + 60.0, "민항 도착기와 충돌 탐지",
            f"복귀 예상 착륙 {int(eta // 3600):02d}:{int(eta % 3600 // 60):02d} 전후 "
            f"8분 이내 도착 {len(contested)}편 — 경합 대상",
            ("5-5-4 가", "4-5-1"),
        )

        self._plan_holds(contested, eta)
        held = ", ".join(f"{h.callsign}({h.pattern.fix} {h.level_ft:,.0f}ft)" for h in self.holds)
        self._step(
            10, t_emg + 90.0, "체공 · 벡터 · 재시퀀싱",
            (f"체공 {len(self.holds)}편 — {held}" if self.holds else "체공 불필요")
            + (f" · 자리 없음 {len(self.hold_refused)}편(벡터·순서조정 대상)"
               if self.hold_refused else ""),
            ("4-6-1", "4-6-4"),
        )

        # 11. 비상기 우선 착륙
        emg_op = RunwayOp(
            callsign=self.fighter_callsign,
            actype=self.fighter_type,
            wake_cat=self.sortie.wake_cat,
            op=Operation.ARRIVAL,
            earliest_s=eta,
            emergency=True,
        )
        remaining = [
            s.op for s in self.with_sortie.slots
            if s.op.callsign != self.fighter_callsign and s.time_s >= t_emg
        ]
        self.final = self.runway_seq.insert_emergency(
            remaining + [emg_op], self.fighter_callsign, now_s=t_emg
        )
        landed = self.final.by_callsign(self.fighter_callsign)
        self.sortie.landed_s = landed.time_s
        self._step(
            11, landed.time_s, "비상 전투기 우선 착륙",
            f"물리적 최단 도달시각 기준 삽입 — 순번 "
            f"{self.final.order.index(self.fighter_callsign) + 1}/{len(self.final.order)}, "
            f"도달 하한 대비 {(landed.time_s - eta):.0f}초",
            ("2-1-4 가",),
        )

        # 12. 민항 도착 순서 재구성
        added = self.final.total_delay_s / max(len(self.final.slots), 1)
        self._step(
            12, landed.time_s + 60.0, "민항 도착 순서 재구성",
            f"잔여 {len(self.final.slots) - 1}편 재배치 — 평균 추가지연 "
            f"{added / 60.0:.1f}분, 최대 슬롯 간격 {self.final.max_gap_s():.0f}초",
            ("2-1-4",),
        )

        # 13. 정상 운항 복귀
        t_end = max(s.time_s for s in self.final.slots)
        self.sortie.phase = SortiePhase.LANDED
        self._step(
            13, t_end, "정상 운항 복귀",
            f"전 항적 착륙·이륙 완료 — 총 소요 {(t_end - self.t0) / 60.0:.0f}분",
        )
        return list(self.steps)

    # ------------------------------------------------------------------

    def _patrol_ops(self) -> list[RunwayOp]:
        """상시 순찰 소티 — 출격과 복귀를 한 쌍으로 넣는다.

        나가기만 하고 돌아오지 않으면 활주로 부담을 절반만 세게 된다. 순찰은
        구간 안에서 나갔다 들어오므로 출발·도착이 모두 활주로를 쓴다.
        """
        if self.patrol_sorties <= 0:
            return []
        span = self.timetable.window_to_s - self.timetable.window_from_s
        out: list[RunwayOp] = []
        for i in range(self.patrol_sorties):
            actype = self.patrol_types[i % len(self.patrol_types)]
            cat = self.ds.fleet.wake_cat(actype)
            # 출격은 구간 앞쪽에, 복귀는 뒤쪽에 고르게 편다.
            t_out = self.t0 + span * (0.08 + 0.18 * i)
            t_back = self.t0 + span * (0.55 + 0.14 * i)
            out.append(RunwayOp(
                f"ROKAF{10 + i}", actype, cat, Operation.DEPARTURE, earliest_s=t_out
            ))
            out.append(RunwayOp(
                f"ROKAF{10 + i}", actype, cat, Operation.ARRIVAL, earliest_s=t_back
            ))
        # 같은 콜사인이 두 번 나오면 슬롯 조회가 모호해지므로 구분한다.
        return [
            RunwayOp(
                f"{o.callsign}{'D' if o.is_departure else 'A'}",
                o.actype, o.wake_cat, o.op, earliest_s=o.earliest_s,
            )
            for o in out
        ]

    def _area_entry_fix(self) -> str:
        """작전지역에 가장 가까운 고시 픽스 — 진출 경로의 목적지."""
        area = self.sortie.area
        return min(
            self.router.nodes,
            key=lambda n: area.distance_from_nm(*self.router.nodes[n]),
        )

    def _plan_recovery(self) -> Route | None:
        from .state import AircraftState

        area = self.sortie.area
        alt = (area.lower_ft + area.upper_ft) / 2.0
        ac = AircraftState(
            self.fighter_callsign, area.centroid[0], area.centroid[1], alt,
            240.0, self.ds.fleet.final_gs_kt(self.fighter_type),
            actype=self.fighter_type, wake_cat=self.sortie.wake_cat, emergency=True,
        )
        return self.router.recovery(ac)

    def _plan_holds(self, contested, eta: float) -> None:
        """경합 도착기를 체공시킨다.

        필요한 시간은 '비상기가 활주로를 쓰는 동안'이다 — 비상기 착륙 전후로
        활주로가 막히는 만큼만 붙들고, 그 이상 세우지 않는다.
        """
        self.holds.clear()
        self.hold_refused.clear()
        if not contested:
            return
        rot = self.ds.fleet.runway_occupancy_s(self.fighter_type, self.sortie.wake_cat)
        requests = []
        for s in contested:
            gs = self.ds.fleet.final_gs_kt(s.op.actype, s.op.wake_cat)
            need = max(0.0, eta + rot - s.time_s)
            if need > 0.0:
                requests.append((s.op.callsign, gs, need))
        placed, refused = self.holding.stack(requests, now_s=eta)
        self.holds.extend(placed)
        self.hold_refused.extend(refused)


def build(ds, timetable: Timetable, **kw) -> SortieScenario:
    from . import hold as hold_mod
    from . import mission as mission_mod
    from . import route as route_mod
    from . import runway as runway_mod

    return SortieScenario(
        ds=ds,
        timetable=timetable,
        runway_seq=runway_mod.build(ds),
        mission=mission_mod.build(ds),
        router=route_mod.build(ds),
        holding=hold_mod.build(ds),
        **kw,
    )
