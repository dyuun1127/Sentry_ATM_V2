"""존재 구간 검증 — 항공기가 언제 관할 안에 있는가.

구간 하나만 있으면 등장과 퇴장이고, 여럿이면 나갔다 돌아온 것이다. 겹치는 구간을
거부하는 이유는 겹쳐도 판정이 조용히 성립하기 때문이다 — 같은 항공기가 한 번만
세어지므로 결과가 그럴듯하고, 잘못 쓴 사실이 드러나지 않는다.
"""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from sentry_atm.domain.presence import normalize_presence

T0 = datetime(2026, 9, 1, tzinfo=UTC)


def at(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


class TestNormalization:
    def test_empty_means_always_present(self):
        assert normalize_presence(()) == ()

    def test_windows_are_sorted(self):
        out = normalize_presence([(at(100), at(200)), (at(0), at(50))])
        assert out == ((at(0), at(50)), (at(100), at(200)))

    def test_naive_datetimes_are_refused(self):
        """UTC 로 가정하지 않는다. 가정하면 다른 시간대의 시각이 조용히 밀린다."""
        naive = datetime(2026, 9, 1, 0, 0, 0)
        with pytest.raises(ValueError, match="timezone-aware"):
            normalize_presence([(naive, naive + timedelta(seconds=10))])

    def test_other_timezones_are_converted(self):
        kst = timezone(timedelta(hours=9))
        start = datetime(2026, 9, 1, 9, 0, tzinfo=kst)
        out = normalize_presence([(start, start + timedelta(seconds=10))])
        assert out[0][0] == T0

    def test_a_generator_is_accepted(self):
        out = normalize_presence((at(t), at(t + 10)) for t in (0, 100))
        assert len(out) == 2


class TestRejection:
    def test_touching_windows_are_allowed(self):
        """반열린 구간이라 끝과 시작이 같아도 겹치지 않는다."""
        assert len(normalize_presence([(at(0), at(10)), (at(10), at(20))])) == 2

    def test_overlapping_windows_are_refused(self):
        with pytest.raises(ValueError, match="must not overlap"):
            normalize_presence([(at(0), at(20)), (at(10), at(30))])

    def test_a_window_must_move_forward(self):
        with pytest.raises(ValueError, match="end must follow its start"):
            normalize_presence([(at(10), at(10))])
        with pytest.raises(ValueError, match="end must follow its start"):
            normalize_presence([(at(10), at(5))])

    def test_bounds_must_be_datetimes(self):
        with pytest.raises(TypeError, match="bounds must be datetimes"):
            normalize_presence([(0.0, 10.0)])

    def test_a_window_must_be_a_pair(self):
        with pytest.raises(TypeError, match="\(start, end\) tuple"):
            normalize_presence([(at(0), at(10), at(20))])

    def test_a_string_is_not_a_window_list(self):
        with pytest.raises(TypeError, match="iterable of"):
            normalize_presence("09:00-10:00")
