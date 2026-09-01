from datetime import datetime, timedelta, timezone

import pytest

from sentry_atm.domain.time_policy import KST, UTC, to_kst, to_utc


def test_to_utc_normalizes_an_aware_timestamp() -> None:
    source = datetime(2026, 9, 1, 12, 0, tzinfo=KST)

    result = to_utc(source)

    assert result == datetime(2026, 9, 1, 3, 0, tzinfo=UTC)
    assert result.tzinfo is UTC


def test_to_utc_rejects_a_naive_timestamp() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        to_utc(datetime(2026, 9, 1, 3, 0))


def test_to_utc_rejects_a_non_datetime_value() -> None:
    with pytest.raises(TypeError, match="must be a datetime"):
        to_utc("2026-09-01T03:00:00Z")  # type: ignore[arg-type]


def test_to_kst_converts_from_another_aware_timezone() -> None:
    source = datetime(2026, 9, 1, 1, 0, tzinfo=timezone(timedelta(hours=-4)))

    result = to_kst(source)

    assert result == datetime(2026, 9, 1, 14, 0, tzinfo=KST)
