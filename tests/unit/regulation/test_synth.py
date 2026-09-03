"""합성 항적 생성기 검증.

가장 중요한 검사는 "잔차에 학습할 구조가 있는가"다. 물리 기준선과 같은 모델로
항적을 만들면 학습이 아무것도 배우지 못한다(이전 구현 개선 0.7%).
"""

import math

import pytest

from sentry_atm.regulation import conflict as cf
from sentry_atm.regulation import data as sdata
from sentry_atm.regulation import sequencing as seq
from sentry_atm.regulation import synth
from sentry_atm.regulation.geo import angular_diff, bearing_true, separation_distance_nm


@pytest.fixture(scope="module")
def ds():
    return sdata.load()


@pytest.fixture(scope="module")
def gen(ds):
    return synth.build(ds)


@pytest.fixture(scope="module")
def trajectories(gen):
    return gen.arrivals(20, seed=11)


class TestWindField:
    def test_speed_increases_with_altitude(self):
        w = synth.WindField()
        lo = math.hypot(*w.at(36.7, 127.5, 1000))
        hi = math.hypot(*w.at(36.7, 127.5, 10000))
        assert hi > lo, "고도가 높을수록 바람이 세야 한다 (윈드시어)"

    def test_direction_veers_with_altitude(self):
        w = synth.WindField()
        e0, n0 = w.at(36.7, 127.5, 0)
        e1, n1 = w.at(36.7, 127.5, 12000)
        d0 = math.degrees(math.atan2(e0, n0))
        d1 = math.degrees(math.atan2(e1, n1))
        assert abs(angular_diff(d1, d0)) > 1.0, "고도에 따라 풍향이 돌아야 한다"

    def test_varies_in_space(self):
        w = synth.WindField()
        assert w.at(36.5, 127.3, 5000) != w.at(36.9, 127.7, 5000)

    def test_is_deterministic(self):
        w = synth.WindField()
        assert w.at(36.7, 127.5, 5000) == w.at(36.7, 127.5, 5000)


class TestTrajectory:
    def test_all_reach_the_threshold(self, gen, trajectories):
        for tr in trajectories:
            last = tr.samples[-1]
            d = separation_distance_nm(last.lat, last.lon, *gen.synth.thr)
            assert d < 0.5, f"{tr.callsign} 이 시단에 도달하지 못했다 ({d:.2f}NM)"

    def test_terminal_altitude_is_near_the_glidepath(self, gen, trajectories):
        for tr in trajectories:
            last = tr.samples[-1]
            d = separation_distance_nm(last.lat, last.lon, *gen.synth.thr)
            gp = gen.synth.glidepath_alt_ft(d)
            assert abs(last.alt_ft - gp) < 150, (
                f"{tr.callsign} 종료 고도 {last.alt_ft:.0f}ft, 활공로 {gp:.0f}ft"
            )

    def test_decelerates_to_final_approach_speed(self, gen, ds, trajectories):
        for tr in trajectories:
            want = ds.fleet.final_gs_kt(tr.actype, tr.wake_cat)
            assert abs(tr.samples[-1].gs_kt - want) < 25, (
                f"{tr.callsign}({tr.actype}) 종료 속도 {tr.samples[-1].gs_kt:.0f}kt, "
                f"최종접근속도 {want:g}kt"
            )

    def test_aligns_with_the_final_approach_course(self, gen, trajectories):
        for tr in trajectories:
            last = tr.samples[-1]
            assert abs(angular_diff(last.track_deg, gen.synth.final_course)) < 15

    def test_long_enough_for_ten_minute_horizon(self, trajectories):
        for tr in trajectories:
            assert tr.duration_s >= 600, f"{tr.callsign} {tr.duration_s:.0f}s"

    def test_path_stretch_is_bounded(self, gen, trajectories):
        """경로 연장 벡터링은 시단에서 멀어지게 하지만 지시 크기 안이어야 한다.

        대부분의 항적은 후퇴가 없고, 벡터링을 받은 항적만 측방 오프셋 크기만큼
        멀어진다. 그보다 큰 후퇴는 선회 오버슈트로 모델 결함이다.
        """
        backs = []
        for tr in trajectories:
            d = [separation_distance_nm(s.lat, s.lon, *gen.synth.thr) for s in tr.samples]
            backs.append(max((max(d[i:]) - d[i] for i in range(len(d))), default=0.0))
        backs.sort()
        assert backs[len(backs) // 2] < 1.0, "대부분의 항적은 후퇴가 없어야 한다"
        assert max(backs) < 9.0, f"최대 후퇴 {max(backs):.1f}NM"

    def test_is_reproducible(self, gen):
        a = gen.arrivals(4, seed=99)
        b = gen.arrivals(4, seed=99)
        assert [x.callsign for x in a] == [x.callsign for x in b]
        assert a[0].samples[10].lat == b[0].samples[10].lat

    def test_lookup_by_time(self, trajectories):
        tr = trajectories[0]
        s = tr.samples[5]
        assert tr.at(s.t_s) is s
        assert tr.at(s.t_s - 1e6) is None


def _baseline_errors(trajectories, horizon_s, stride=7):
    steps = int(horizon_s / trajectories[0].dt_s)
    out = []
    for tr in trajectories:
        for i in range(0, len(tr) - steps, stride):
            pred = tr.samples[i].advance(horizon_s)
            truth = tr.samples[i + steps]
            out.append(separation_distance_nm(pred.lat, pred.lon, truth.lat, truth.lon))
    return out


class TestLearnableResidual:
    """물리 기준선이 못 맞히는 부분이 있어야 학습할 것이 있다."""

    def test_baseline_error_grows_with_horizon(self, trajectories):
        means = {
            hz: sum(v) / len(v)
            for hz in (60, 300, 600)
            for v in [_baseline_errors(trajectories, hz)]
        }
        assert means[60] < means[300] < means[600]

    def test_ten_minute_baseline_leaves_room_to_learn(self, trajectories):
        vals = _baseline_errors(trajectories, 600)
        mean = sum(vals) / len(vals)
        assert 5.0 < mean < 40.0, f"10분 지평 물리 오차 {mean:.1f}NM"

    def test_residual_correlates_with_airport_relative_bearing(self, gen, trajectories):
        """잔차가 '공항 상대 방위'와 상관을 가져야 한다.

        이 특성이 없어서 이전 구현의 학습이 실패했다. 상관이 없다면
        어떤 특성을 넣어도 배울 것이 없다는 뜻이다.
        """
        steps = int(300 / trajectories[0].dt_s)
        xs, ys = [], []
        for tr in trajectories:
            for i in range(0, len(tr) - steps, 5):
                s = tr.samples[i]
                brg = bearing_true(s.lat, s.lon, *gen.synth.thr)
                pred = s.advance(300)
                truth = tr.samples[i + steps]
                xs.append(abs(angular_diff(brg, s.track_deg)))
                ys.append(
                    separation_distance_nm(pred.lat, pred.lon, truth.lat, truth.lon)
                )

        n = len(xs)
        mx, my = sum(xs) / n, sum(ys) / n
        cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
        sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
        sy = math.sqrt(sum((y - my) ** 2 for y in ys))
        r = cov / (sx * sy)
        assert r > 0.2, f"상대 방위와 잔차의 상관 r={r:.3f} — 학습 신호가 약하다"


class TestRolloutLabels:
    def test_labels_are_outcome_based(self, ds, gen):
        """라벨은 임계치가 아니라 결과 — 실제로 위반이 났는가."""
        sq = seq.build(ds)
        det = cf.build(ds)
        trs = gen.sequenced_arrivals(24, sq, seed=5)
        samples = synth.rollout_labels(trs, det, stride=4)
        assert samples

        for s in samples:
            if s.violated:
                assert s.time_to_violation_s < math.inf
                assert s.min_separation_nm < 3.0 + 1e-6
            else:
                assert s.time_to_violation_s == math.inf

    def test_violation_rate_is_realistic(self, ds, gen):
        """계획 여유 기본값에서 위반율이 기획서 인용값(13.8%) 근방이어야 한다.

        시드에 따라 10~21% 로 흔들리며 평균 15% 수준이다. 정확히 13.8% 로
        맞추려 여유값을 미세조정하지 않는다 — 다른 구현의 수치에 맞추는 것은
        데이터를 결과에 맞추는 일이다.
        """
        sq = seq.build(ds)
        det = cf.build(ds)
        trs = gen.sequenced_arrivals(28, sq, seed=7, jitter_s=20.0, deviation_rate=0.15)
        samples = synth.rollout_labels(trs, det, stride=3)
        rate = sum(s.violated for s in samples) / len(samples)
        assert 0.05 < rate < 0.30, f"위반율 {rate:.1%}"

    def test_unplanned_flow_is_unrealistically_conflicted(self, ds, gen):
        """슬롯 계획이 없으면 위반율이 비현실적으로 높아진다 — 설계 근거."""
        det = cf.build(ds)
        trs = gen.arrivals(24, seed=7, mean_interval_s=110.0)
        samples = synth.rollout_labels(trs, det, stride=3)
        rate = sum(s.violated for s in samples) / len(samples)
        assert rate > 0.35, f"위반율 {rate:.1%} — 계획 없는 흐름의 특성"

    def test_only_controlled_pairs_are_sampled(self, ds, gen):
        sq = seq.build(ds)
        det = cf.build(ds)
        trs = gen.sequenced_arrivals(12, sq, seed=3)
        for s in synth.rollout_labels(trs, det, stride=6):
            assert det.sector.is_under_control(s.a)
            assert det.sector.is_under_control(s.b)


class TestSequencedArrivals:
    def test_slots_are_spaced_by_requirement(self, ds, gen):
        sq = seq.build(ds)
        trs = gen.sequenced_arrivals(10, sq, seed=1, jitter_s=0.0, deviation_rate=0.0)
        times = [tr.samples[-1].t_s for tr in trs]
        assert times == sorted(times)
        for a, b in zip(trs, trs[1:]):
            gap = sq.gap_requirement(a.samples[-1], b.samples[-1])
            assert b.samples[-1].t_s - a.samples[-1].t_s >= gap.seconds - 1.0

    def test_shift_preserves_geometry(self, gen):
        tr = gen.arrivals(1, seed=2)[0]
        shifted = synth.shift_to(tr, 5000.0)
        assert shifted.samples[-1].t_s == pytest.approx(5000.0)
        assert shifted.samples[0].lat == tr.samples[0].lat
        assert len(shifted) == len(tr)
