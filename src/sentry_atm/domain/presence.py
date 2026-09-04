"""항공기가 관할 구역 안에 있는 시간 구간.

시뮬레이터의 항공기는 등장할 줄만 알고 사라질 줄을 몰랐다. 골든 데모에서는
문제가 되지 않았다 — 8대가 5분 내내 떠 있었기 때문이다. 75분짜리 소티에서는
착륙한 항공기가 활주로를 지나 계속 직진하고, 그 유령이 끝까지 분리 판정의
대상으로 남는다.

구간을 **여러 개** 두는 이유는 출격 소티다. 전투기는 이륙 후 터미널 구역을 떠나
작전지역에서 임무를 수행하고 돌아온다. 그 사이는 우리 관할이 아니다.

구간은 **반열린 구간** `[시작, 끝)` 이다. 한 구간의 끝과 다음 구간의 시작이 같은
시각이면 그 시각에 항공기가 두 번 세어지거나 한 번도 안 세어지는 경계 문제가
생기는데, 반열린 구간에서는 그런 시각이 없다.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from sentry_atm.domain.time_policy import to_utc


def normalize_presence(
    presence: Iterable[tuple[datetime, datetime]],
) -> tuple[tuple[datetime, datetime], ...]:
    """구간을 검증하고 UTC 로 맞춘다.

    겹치는 구간을 거부하는 이유는, 겹친 구간이 있어도 판정은 조용히 성립하기
    때문이다 — 같은 항공기가 한 번만 세어지므로 결과가 그럴듯하고, 구간을 잘못
    쓴 사실이 드러나지 않는다.
    """
    if isinstance(presence, (str, bytes)):
        raise TypeError("presence must be an iterable of (start, end) pairs")
    try:
        materialized = tuple(presence)
    except TypeError:
        raise TypeError("presence must be an iterable of (start, end) pairs") from None

    windows: list[tuple[datetime, datetime]] = []
    for window in materialized:
        if not isinstance(window, tuple) or len(window) != 2:
            raise TypeError("each presence window must be a (start, end) tuple")
        start, end = window
        if not isinstance(start, datetime) or not isinstance(end, datetime):
            raise TypeError("presence window bounds must be datetimes")
        start = to_utc(start, field_name="presence start")
        end = to_utc(end, field_name="presence end")
        if end <= start:
            raise ValueError("presence window end must follow its start")
        windows.append((start, end))

    windows.sort()
    for previous, current in zip(windows, windows[1:], strict=False):
        if current[0] < previous[1]:
            raise ValueError("presence windows must not overlap")
    return tuple(windows)


__all__ = ["normalize_presence"]
