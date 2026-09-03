"""민항 운항 시간표 — 계획된 교통을 읽는다.

지금까지의 시나리오는 도착 항적을 지수분포로 뿌렸다. 실제 공항은 그렇지 않다.
편별로 계획시각이 있고, 청주는 활주로 공용 구조 때문에 시간당 슬롯이 7~8회로
제한된다. 그 제약 안에서 출발과 도착이 섞이는 것이 실제 모습이다.

**실제 시간표가 있으면 그것을 쓰고, 없으면 합성한다.** 합성일 때는 반드시
합성임을 표시한다 — 실측처럼 보이게 하지 않는다. `data/schedule.json` 이 있으면
읽고, 없으면 슬롯 제약을 지키는 합성 시간표를 만든다.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path

from .runway import Operation, RunwayOp


@dataclass(frozen=True)
class ScheduledFlight:
    """계획된 한 편."""

    callsign: str
    actype: str
    operation: Operation
    scheduled_s: float
    """운항 기준시각. 도착이면 STA, 출발이면 STD."""

    other_end: str = ""
    """상대 공항 — 표출용."""

    operator: str = "civil"

    @property
    def is_departure(self) -> bool:
        return self.operation is Operation.DEPARTURE

    def hhmm(self) -> str:
        m = int(self.scheduled_s // 60)
        return f"{m // 60 % 24:02d}:{m % 60:02d}"


@dataclass(frozen=True)
class Timetable:
    """한 구간의 운항 계획."""

    flights: tuple[ScheduledFlight, ...]
    date: str
    window_from_s: float
    window_to_s: float
    synthetic: bool
    source: str

    @property
    def arrivals(self) -> list[ScheduledFlight]:
        return [f for f in self.flights if not f.is_departure]

    @property
    def departures(self) -> list[ScheduledFlight]:
        return [f for f in self.flights if f.is_departure]

    def movements_per_hour(self) -> float:
        span_h = max(self.window_to_s - self.window_from_s, 1.0) / 3600.0
        return len(self.flights) / span_h

    def provenance(self) -> str:
        """이 시간표가 어디서 왔는가 — 발표에서 반드시 밝혀야 할 사항."""
        if self.synthetic:
            return f"합성 시간표 ({self.source}) — 실제 운항 시간표가 아니다"
        return f"실제 시간표 — {self.source}"

    def to_runway_ops(self, fleet) -> list[RunwayOp]:
        """활주로 배치에 넣을 수 있는 형태로.

        계획시각을 `earliest_s` 로 둔다 — 그보다 일찍 활주로를 쓸 수는 없고,
        늦어지는 것은 활주로 요건이 정한다.
        """
        return [
            RunwayOp(
                callsign=f.callsign,
                actype=f.actype,
                wake_cat=fleet.wake_cat(f.actype),
                op=f.operation,
                earliest_s=f.scheduled_s,
            )
            for f in self.flights
        ]


def _hhmm_to_s(text: str) -> float:
    h, m = text.strip().split(":")
    return int(h) * 3600.0 + int(m) * 60.0


def load(path: str | Path) -> Timetable:
    """`data/schedule.json` 을 읽는다.

    형식:
        {
          "date": "2026-07-04",
          "window": {"from": "09:00", "to": "10:00"},
          "source": "어디서 온 자료인가",
          "flights": [
            {"callsign": "KAL1401", "actype": "B738",
             "operation": "도착", "scheduled": "09:15", "other_end": "ICN"}
          ]
        }
    """
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    kinds = {"도착": Operation.ARRIVAL, "출발": Operation.DEPARTURE,
             "arrival": Operation.ARRIVAL, "departure": Operation.DEPARTURE}
    flights = []
    for f in raw["flights"]:
        flights.append(
            ScheduledFlight(
                callsign=f["callsign"],
                actype=f["actype"],
                operation=kinds[f["operation"]],
                scheduled_s=_hhmm_to_s(f["scheduled"]),
                other_end=f.get("other_end", ""),
                operator=f.get("operator", "civil"),
            )
        )
    flights.sort(key=lambda x: x.scheduled_s)
    return Timetable(
        flights=tuple(flights),
        date=raw.get("date", ""),
        window_from_s=_hhmm_to_s(raw["window"]["from"]),
        window_to_s=_hhmm_to_s(raw["window"]["to"]),
        synthetic=bool(raw.get("synthetic", False)),
        source=raw.get("source", str(path)),
    )


@dataclass
class TimetableSynthesizer:
    """실제 시간표가 없을 때 쓰는 합성기.

    청주의 실제 제약을 지킨다 — 시간당 슬롯 7~8회, 출발과 도착이 섞임.
    편명은 실재 항공사 코드를 쓰되 편번호는 임의이며, 결과에 합성 표시가 붙는다.
    """

    ds: object

    airlines: tuple[tuple[str, str], ...] = (
        ("KAL", "ICN"), ("AAR", "CJU"), ("TWB", "CJU"),
        ("JJA", "CJU"), ("ABL", "PUS"), ("ESR", "CJU"),
    )
    types: tuple[str, ...] = ("B738", "B38M", "A320", "A321")

    movements_per_hour: int = 8
    """청주 활주로 공용 구조상의 시간당 슬롯 제약."""

    def build(
        self, window_from_s: float, window_to_s: float, seed: int = 0
    ) -> Timetable:
        rng = random.Random(seed)
        span_h = (window_to_s - window_from_s) / 3600.0
        n = max(2, int(round(self.movements_per_hour * span_h)))

        flights: list[ScheduledFlight] = []
        # 슬롯을 균등 배치하고 편차를 준다 — 완전 균등은 실제 시간표와 다르다.
        step = (window_to_s - window_from_s) / n
        for i in range(n):
            code, other = rng.choice(self.airlines)
            actype = rng.choice(self.types)
            t = window_from_s + step * i + rng.uniform(-step * 0.25, step * 0.25)
            op = Operation.ARRIVAL if i % 2 == 0 else Operation.DEPARTURE
            flights.append(
                ScheduledFlight(
                    callsign=f"{code}{rng.randint(1000, 1999)}",
                    actype=actype,
                    operation=op,
                    scheduled_s=max(window_from_s, t),
                    other_end=other,
                )
            )
        flights.sort(key=lambda x: x.scheduled_s)
        return Timetable(
            flights=tuple(flights),
            date="",
            window_from_s=window_from_s,
            window_to_s=window_to_s,
            synthetic=True,
            source=f"슬롯 제약 {self.movements_per_hour}회/시 기준 합성, seed={seed}",
        )


DEFAULT_PATH = "data/schedule.json"


def build(ds, *, path: str | Path | None = None,
          window: tuple[str, str] = ("09:00", "10:00"),
          seed: int = 0) -> Timetable:
    """실제 시간표가 있으면 읽고, 없으면 합성한다.

    합성으로 떨어졌다는 사실은 `Timetable.synthetic` 과 `provenance()` 에 남는다.
    """
    p = Path(path or DEFAULT_PATH)
    if p.exists():
        return load(p)
    return TimetableSynthesizer(ds=ds).build(
        _hhmm_to_s(window[0]), _hhmm_to_s(window[1]), seed=seed
    )
