"""체공(홀딩) — 도착 흐름에 시간을 만들어 넣는 수단.

벡터링은 항적을 옆으로 늘려 시간을 벌지만, 밀집 상황에서는 늘릴 자리가 없다.
그때 쓰는 것이 체공이며 고시 제4장 제6절이 절차를 정한다.

**장주를 지어내지 않는다.** 청주 RNP RWY 24R 에는 IKAPO(7,000ft)와 COWON(6,000ft)
두 곳의 체공장주가 AIP 에 공고되어 있고(AD CHART 2-25), 공고된 장주가 있으면
고시 4-6-1 나 2)에 따라 "AS PUBLISHED" 로 지시할 수 있다. 이 모듈은 그 공고값을
읽어 장주를 재현할 뿐이다.

체공은 **비상기 우선권을 만들어 주는 대가를 민항기가 치르는 방식**이기도 하다.
누가 얼마나 도는지가 그대로 지연이 되므로, 배정 결과에 지연을 함께 낸다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .geo import separation_distance_nm

M_PER_NM = 1852.0


@dataclass(frozen=True)
class HoldingPattern:
    """AIP 에 공고된 체공장주 하나."""

    fix: str
    lat: float
    lon: float
    inbound_course_true: float
    leg_nm: float
    alt_ft: float
    alt_cons: str
    max_alt_ft: float | None = None
    speed_max_kt: float | None = None
    right_turns: bool = True
    """공고에 좌선회 명시가 없으면 우선회 (고시 4-6-4 마)."""

    def turn_rate_deg_per_s(self, gs_kt: float, standard_deg_s: float, bank_deg: float) -> float:
        """표준선회율과 뱅크각 한계 중 **느린 쪽**.

        빠른 기종일수록 뱅크 한계가 먼저 걸려 한 바퀴가 길어진다 — 전투기를
        체공시키면 민항기보다 오래 걸린다는 뜻이고, 시퀀싱에서 실제로 차이가 난다.
        """
        v = max(gs_kt, 1.0) * M_PER_NM / 3600.0
        bank_limited = math.degrees(9.80665 * math.tan(math.radians(bank_deg)) / v)
        return min(standard_deg_s, bank_limited)

    def circuit_time_s(self, gs_kt: float, standard_deg_s: float, bank_deg: float) -> float:
        """장주 한 바퀴 소요.

        인바운드 구간 + 180° 선회 + 아웃바운드 구간 + 180° 선회.
        공고 장주길이는 마일 단위이므로(고시 4-6-4 라) 거리로 계산한다.
        """
        rate = self.turn_rate_deg_per_s(gs_kt, standard_deg_s, bank_deg)
        leg_s = self.leg_nm / max(gs_kt, 1.0) * 3600.0
        return 2.0 * leg_s + 2.0 * (180.0 / rate)

    def speed_for(self, gs_kt: float) -> float:
        """장주 속도 — 공고 제한이 있으면 그 아래로 낮춘다."""
        if self.speed_max_kt is None:
            return gs_kt
        return min(gs_kt, self.speed_max_kt)

    def levels_ft(self, step_ft: float) -> list[float]:
        """이 픽스에 쌓을 수 있는 고도들 (고시 4-5-1 수직분리).

        공고 고도가 바닥이고 공고 상한까지 올린다. 상한이 없으면 한 층뿐이다.
        """
        if self.max_alt_ft is None:
            return [self.alt_ft]
        out, a = [], self.alt_ft
        while a <= self.max_alt_ft + 1e-6:
            out.append(a)
            a += step_ft
        return out


@dataclass(frozen=True)
class HoldAssignment:
    """한 대에게 내린 체공 지시와 그 대가."""

    callsign: str
    pattern: HoldingPattern
    level_ft: float
    circuits: int
    delay_s: float
    efc_s: float | None
    """허가예상시간 (고시 4-6-1 다). 지연이 예상되지 않으면 None."""

    def phraseology(self, published_term: str = "AS PUBLISHED") -> str:
        """관제용어 (고시 4-6-1 나 2), 4-6-4).

        공고된 장주이므로 방향과 'AS PUBLISHED' 만 쓰고 나머지 지시는 생략한다.
        """
        turn = "" if self.pattern.right_turns else ", LEFT TURNS"
        efc = ""
        if self.efc_s is not None:
            efc = f", EXPECT FURTHER CLEARANCE AT {_hhmm(self.efc_s)}"
        return (
            f"{self.callsign}, HOLD AT {self.pattern.fix}, "
            f"MAINTAIN {self.level_ft:,.0f}, {published_term}{turn}{efc}"
        )

    def describe(self) -> str:
        return (
            f"{self.callsign} — {self.pattern.fix} {self.level_ft:,.0f}ft, "
            f"{self.circuits}바퀴, 지연 {self.delay_s / 60.0:.1f}분"
        )


def _hhmm(t_s: float) -> str:
    m = int(t_s // 60) % (24 * 60)
    return f"{m // 60:02d}{m % 60:02d}"


@dataclass
class HoldingBook:
    """공고 장주 조회와 체공 배정.

    수치는 procedures.json(장주)과 airspace.json(절차 상수)에서만 읽는다.
    """

    ds: object
    approach: str = "RNP_24R"

    _cfg: dict = field(init=False, repr=False)
    patterns: tuple[HoldingPattern, ...] = field(init=False, default=())

    def __post_init__(self) -> None:
        self._cfg = self.ds.airspace.raw["holding"]
        out = []
        for h in self.ds.procedures.iap(self.approach).get("holdings", []):
            w = self.ds.procedures.fix(h["fix"])
            out.append(
                HoldingPattern(
                    fix=h["fix"],
                    lat=w.lat,
                    lon=w.lon,
                    inbound_course_true=h["inbound_course_true"],
                    leg_nm=h["leg_nm"],
                    alt_ft=h["alt_ft"],
                    alt_cons=h.get("alt_cons", "AT_OR_ABOVE"),
                    max_alt_ft=h.get("max_alt_ft"),
                    speed_max_kt=h.get("speed_max_kt"),
                    right_turns=h.get("turns", self._cfg["default_turns"]) == "우선회",
                )
            )
        self.patterns = tuple(out)

    # ------------------------------------------------------------------

    def pattern(self, fix: str) -> HoldingPattern:
        for p in self.patterns:
            if p.fix == fix:
                return p
        raise KeyError(f"공고된 체공장주가 아니다: {fix}")

    def nearest(self, lat: float, lon: float) -> HoldingPattern:
        """가장 가까운 공고 장주. 없는 곳에 세우지 않기 위한 것이다."""
        if not self.patterns:
            raise LookupError(f"{self.approach} 에 공고된 체공장주가 없다")
        return min(self.patterns, key=lambda p: separation_distance_nm(lat, lon, p.lat, p.lon))

    def circuit_time_s(self, pattern: HoldingPattern, gs_kt: float) -> float:
        gs = pattern.speed_for(gs_kt)
        return pattern.circuit_time_s(
            gs, self._cfg["standard_rate_deg_per_s"], self._cfg["max_bank_deg"]
        )

    def levels(self, pattern: HoldingPattern) -> list[float]:
        return pattern.levels_ft(self._cfg["level_step_ft"])

    def needs_delay_info(self, delay_s: float) -> bool:
        """고시 4-6-3 나 — 도착지연 30분 이상이면 지연정보를 발부해야 한다."""
        return delay_s >= self._cfg["delay_info_threshold_min"] * 60.0

    # ------------------------------------------------------------------

    def assign(
        self,
        callsign: str,
        gs_kt: float,
        need_s: float,
        *,
        lat: float | None = None,
        lon: float | None = None,
        fix: str | None = None,
        occupied_levels: dict[str, set[float]] | None = None,
        now_s: float = 0.0,
    ) -> HoldAssignment | None:
        """`need_s` 만큼 시간을 벌기 위한 체공 지시.

        장주는 한 바퀴 단위로만 돌 수 있으므로 필요한 시간 이상으로 올림한다 —
        반 바퀴에서 빠져나오는 지시는 규정 용어에 없다.

        같은 픽스에 이미 다른 항적이 있으면 1,000ft 씩 쌓되(4-5-1), 공고 상한을
        넘으면 자리가 없는 것으로 보고 None 을 돌려준다. 지어낸 고도에 세우지 않는다.
        """
        if need_s <= 0.0:
            return None
        pat = self.pattern(fix) if fix else self.nearest(lat, lon)

        taken = (occupied_levels or {}).get(pat.fix, set())
        level = next((lv for lv in self.levels(pat) if lv not in taken), None)
        if level is None:
            return None

        circuit = self.circuit_time_s(pat, gs_kt)
        circuits = max(1, math.ceil(need_s / circuit))
        delay = circuits * circuit
        efc = now_s + delay if self.needs_delay_info(delay) else None
        return HoldAssignment(
            callsign=callsign,
            pattern=pat,
            level_ft=level,
            circuits=circuits,
            delay_s=delay,
            efc_s=efc,
        )

    @property
    def capacity(self) -> int:
        """전체 체공 수용량 — 공고 장주 × 쌓을 수 있는 층.

        이것이 도착 흐름을 얼마나 붙들 수 있는지의 상한이다. 넘으면 체공이
        아니라 순서 조정이나 인접 관제소 이양으로 풀어야 한다.
        """
        return sum(len(self.levels(p)) for p in self.patterns)

    def stack(
        self,
        requests: list[tuple[str, float, float]],
        *,
        fix: str | None = None,
        now_s: float = 0.0,
    ) -> tuple[list[HoldAssignment], list[str]]:
        """여러 대를 한 번에 세운다. `requests` 는 (콜사인, 대지속도, 필요시간).

        `fix` 를 주면 그 장주에만 쌓고, 주지 않으면 공고 장주를 순서대로 채운다.
        자리가 없는 항적은 두 번째 반환값에 콜사인으로 남는다 — 조용히 겹쳐
        세우지 않는다. 호출자는 그 사실을 보고 다른 수단(벡터링·순서 조정·
        인접 관제소 이양)으로 넘어가야 한다.
        """
        pool = [self.pattern(fix)] if fix else list(self.patterns)
        occupied: dict[str, set[float]] = {}
        placed: list[HoldAssignment] = []
        refused: list[str] = []

        for cs, gs, need in requests:
            a = None
            for pat in pool:
                a = self.assign(
                    cs, gs, need, fix=pat.fix,
                    occupied_levels=occupied, now_s=now_s,
                )
                if a is not None:
                    break
            if a is None:
                refused.append(cs)
                continue
            occupied.setdefault(a.pattern.fix, set()).add(a.level_ft)
            placed.append(a)
        return placed, refused


def build(ds, approach: str = "RNP_24R") -> HoldingBook:
    return HoldingBook(ds=ds, approach=approach)
