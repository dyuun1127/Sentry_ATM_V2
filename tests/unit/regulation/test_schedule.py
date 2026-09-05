"""민항 운항 시간표 (`ASM-043`).

여기서 지키려는 것은 시간표의 내용이 아니라 **출처를 숨기지 않는가**다.
실제 시간표를 확보하지 못해 합성값을 쓰고 있으므로, 그 사실이 화면과 발표에서
사라지면 심사자가 합성 교통량을 실측으로 읽게 된다.
"""

from __future__ import annotations

import json
from pathlib import Path

from sentry_atm.regulation.data import load as load_dataset
from sentry_atm.regulation.runway import Operation
from sentry_atm.regulation.schedule import build


def test_synthetic_timetable_says_it_is_synthetic() -> None:
    """합성으로 떨어졌다는 사실이 결과에 남는가.

    `synthetic` 만 참이고 사람이 읽는 문장에 그 말이 없으면, 발표 화면에는
    아무 표시 없이 시간표가 뜬다. 표시는 사람이 읽는 자리에 있어야 한다.
    """
    timetable = build(load_dataset(), path="does-not-exist.json", seed=4)

    assert timetable.synthetic is True
    assert "합성" in timetable.provenance()
    assert "실제 운항 시간표가 아니다" in timetable.provenance()
    assert "seed=4" in timetable.source


def test_synthetic_timetable_is_reproducible_and_respects_the_slot_limit() -> None:
    """같은 seed 는 같은 시간표를, 다른 seed 는 다른 시간표를 낸다.

    시연에서 매번 다른 항적이 나오면 무엇을 보여 주는지 설명할 수 없다.
    그리고 밀도를 부풀리면 그 위에서 나오는 분리·순서 판정이 전부 거짓이 된다 —
    청주는 활주로 공용 구조상 시간당 8회다.
    """
    dataset = load_dataset()
    window = ("09:00", "10:00")

    same = [
        build(dataset, path="does-not-exist.json", window=window, seed=4).flights
        for _ in range(2)
    ]
    other = build(dataset, path="does-not-exist.json", window=window, seed=5).flights

    assert same[0] == same[1]
    assert same[0] != other

    # 한 시간 창이므로 슬롯 제약과 같은 편수여야 한다.
    assert len(same[0]) == 8
    # 출발과 도착이 섞인다 — 도착만 있으면 활주로 경합이 나타나지 않는다.
    operations = {flight.operation for flight in same[0]}
    assert operations == {Operation.ARRIVAL, Operation.DEPARTURE}
    # 계획시각은 창 안에서 오름차순이다.
    times = [flight.scheduled_s for flight in same[0]]
    assert times == sorted(times)
    assert 9 * 3600.0 <= times[0] and times[-1] <= 10 * 3600.0


def test_real_timetable_takes_precedence_over_the_synthetic_one(tmp_path: Path) -> None:
    """실제 시간표를 확보하면 코드를 고치지 않고 파일만 놓으면 되는가.

    `ASM-043` 의 교체 경로다. 이 경로가 막혀 있으면 실제 자료를 구해도 합성값이
    계속 쓰이고, 그 사실을 아무도 알아채지 못한다.
    """
    path = tmp_path / "schedule.json"
    path.write_text(
        json.dumps(
            {
                "date": "2026-07-04",
                "window": {"from": "09:00", "to": "10:00"},
                "source": "한국공항공사 청주공항 운항시간표",
                "flights": [
                    {
                        "callsign": "KAL1401",
                        "actype": "B738",
                        "operation": "도착",
                        "scheduled": "09:15",
                        "other_end": "ICN",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    timetable = build(load_dataset(), path=path)

    assert timetable.synthetic is False
    assert "합성" not in timetable.provenance()
    assert timetable.flights[0].callsign == "KAL1401"
