"""예외 판정(MBE) 검증.

핵심은 두 가지다.
1. 라벨이 임계치가 아니라 **결과**인가 (편향 전이 방지).
2. 판정 방식 비교가 **같은 상신 부하**에서 이뤄지는가 (임계치를 각자 유리하게
   잡으면 비교가 성립하지 않는다).
"""

import pytest

from sentry_atm.regulation import conflict as cf
from sentry_atm.regulation import data as sdata
from sentry_atm.regulation import mbe, synth
from sentry_atm.regulation import resolution as res
from sentry_atm.regulation import sequencing as seq
from sentry_atm.regulation.geo import vincenty_direct
from sentry_atm.regulation.state import AircraftState

RKTU = (36.71639, 127.4992)


@pytest.fixture(scope="module")
def ds():
    return sdata.load()


@pytest.fixture(scope="module")
def det(ds):
    return cf.build(ds)


@pytest.fixture(scope="module")
def unc():
    return res.UncertaintyModel(
        horizontal_nm_per_s=4.25 / 600.0, vertical_ft_per_s=300.0 / 600.0
    )


@pytest.fixture(scope="module")
def fb(det, unc):
    return mbe.FeatureBuilder(det, unc)


def at(cs, brg, dist_nm, alt, track, gs, **kw):
    lat, lon = vincenty_direct(*RKTU, brg, dist_nm * 1852.0)
    return AircraftState(cs, lat, lon, alt, track, gs, **kw)


class TestAnalyticProbability:
    def test_agrees_with_monte_carlo(self, unc):
        """해석해와 몬테카를로가 일치해야 한다 — 둘 다 같은 물리를 푼다."""
        a = at("A", 90, 8, 4000, 270, 250)
        blat, blon = vincenty_direct(a.lat, a.lon, 0.0, 3.6 * 1852.0)
        b = AircraftState("B", blat, blon, 4000, 270, 250)
        mc = res.collision_probability(a, b, 3.0, 1000.0, unc, 300.0, samples=4000)
        an = res.analytic_collision_probability(a, b, 3.0, 1000.0, unc, 300.0)
        assert abs(mc - an) < 0.06, f"MC {mc:.3f} vs 해석 {an:.3f}"

    def test_monte_carlo_error_is_time_correlated(self):
        """예측오차는 시간에 상관된다 — 시각마다 독립으로 뽑으면 확률이 부풀려진다.

        상관 모델이면 시간 간격을 잘게 나눠도 확률이 크게 변하지 않아야 한다.
        """
        a = at("A", 90, 8, 4000, 270, 250)
        blat, blon = vincenty_direct(a.lat, a.lon, 0.0, 3.6 * 1852.0)
        b = AircraftState("B", blat, blon, 4000, 270, 250)
        u = res.UncertaintyModel(horizontal_nm_per_s=1.0 / 600.0)
        coarse = res.collision_probability(a, b, 3.0, 1000.0, u, 300.0,
                                           samples=3000, step_s=30.0)
        fine = res.collision_probability(a, b, 3.0, 1000.0, u, 300.0,
                                         samples=3000, step_s=5.0)
        assert abs(coarse - fine) < 0.05, f"거친 {coarse:.3f} vs 촘촘 {fine:.3f}"

    def test_deterministic_falls_back_to_binary(self):
        a = at("A", 90, 6, 4000, 270, 250)
        b = at("B", 270, 6, 4000, 90, 250)
        p = res.analytic_collision_probability(
            a, b, 3.0, 1000.0, res.UncertaintyModel(), 600.0
        )
        assert p == 1.0

    def test_probability_increases_with_uncertainty(self):
        a = at("A", 90, 8, 4000, 270, 250)
        blat, blon = vincenty_direct(a.lat, a.lon, 0.0, 4.0 * 1852.0)
        b = AircraftState("B", blat, blon, 4000, 270, 250)
        lo = res.analytic_collision_probability(
            a, b, 3.0, 1000.0,
            res.UncertaintyModel(horizontal_nm_per_s=0.3 / 600.0), 300.0)
        hi = res.analytic_collision_probability(
            a, b, 3.0, 1000.0,
            res.UncertaintyModel(horizontal_nm_per_s=3.0 / 600.0), 300.0)
        assert 0.0 <= lo < hi <= 1.0


class TestFeatures:
    def test_vector_length(self, fb):
        f = fb.build(at("A", 90, 8, 4000, 270, 250), at("B", 270, 8, 4000, 90, 250))
        assert len(f) == len(mbe.FEATURE_NAMES)

    def test_all_finite(self, fb):
        """예지시간이 무한대인 경우도 유한값으로 잘려야 한다 — 학습기가 NaN 을 못 받는다."""
        import math

        far = fb.build(at("A", 0, 5, 4000, 0, 200), at("B", 180, 9, 6000, 180, 200))
        assert all(math.isfinite(v) for v in far)

    def test_converging_pair_scores_higher_than_diverging(self, fb):
        i = mbe.FEATURE_NAMES.index("collision_prob")
        conv = fb.build(at("A", 90, 7, 4000, 270, 250), at("B", 270, 7, 4000, 90, 250))
        div = fb.build(at("A", 90, 7, 4000, 90, 250), at("B", 270, 7, 4000, 270, 250))
        assert conv[i] > div[i]

    def test_closing_speed_sign(self, fb):
        i = mbe.FEATURE_NAMES.index("closing_speed_kt")
        conv = fb.build(at("A", 90, 7, 4000, 270, 250), at("B", 270, 7, 4000, 90, 250))
        assert conv[i] > 0


class TestRoc:
    def test_perfect_separation(self):
        assert mbe.roc_auc([1.0, 2.0, 3.0, 4.0], [False, False, True, True]) == 1.0

    def test_inverted(self):
        assert mbe.roc_auc([4.0, 3.0, 2.0, 1.0], [False, False, True, True]) == 0.0

    def test_ties_give_half(self):
        assert mbe.roc_auc([1.0, 1.0, 1.0, 1.0], [False, False, True, True]) == 0.5

    def test_degenerate_labels(self):
        assert mbe.roc_auc([1.0, 2.0], [False, False]) == 0.5


class TestEvaluation:
    def test_escalation_load_is_fixed(self):
        """상신 부하를 고정해야 방식 간 비교가 성립한다."""
        scores = [float(i) for i in range(100)]
        labels = [i >= 90 for i in range(100)]
        r = mbe.evaluate_scores("test", scores, labels, escalation_rate=0.20)
        assert r.escalation_rate == pytest.approx(0.20, abs=0.01)
        assert r.miss_rate == 0.0
        assert r.auc == 1.0

    def test_miss_rate_counts_unescalated_positives(self):
        scores = [float(i) for i in range(100)]
        labels = [i < 10 for i in range(100)]   # 점수가 낮은 쪽이 실제 위반
        r = mbe.evaluate_scores("bad", scores, labels, escalation_rate=0.20)
        assert r.miss_rate == 1.0
        assert r.recall == 0.0


class TestThresholds:
    def test_derived_from_distribution_not_constants(self):
        """임계는 임의 상수가 아니라 분포와 운용 목표에서 나온다."""
        scores = [i / 100.0 for i in range(100)]
        labels = [i >= 80 for i in range(100)]
        th = mbe.derive_thresholds(scores, labels, escalation_rate=0.20,
                                   caution_recall=0.95)
        assert 0.0 <= th.caution <= th.danger <= 1.0
        assert th.escalation_rate == 0.20

    def test_changing_the_target_moves_the_threshold(self):
        scores = [i / 100.0 for i in range(100)]
        labels = [i >= 80 for i in range(100)]
        tight = mbe.derive_thresholds(scores, labels, escalation_rate=0.10)
        loose = mbe.derive_thresholds(scores, labels, escalation_rate=0.40)
        assert tight.danger > loose.danger

    def test_emergency_overrides_score(self):
        th = mbe.Thresholds(caution=0.1, danger=0.9, escalation_rate=0.2,
                            caution_recall=0.95)
        assert th.level(0.0, emergency=True) == "비상"
        assert th.level(0.95) == "위험"
        assert th.level(0.5) == "주의"
        assert th.level(0.01) == "정상"

    def test_level_report_is_monotone_in_violation_rate(self):
        """위험 > 주의 > 정상 순으로 실제 위반율이 낮아져야 임계가 타당하다."""
        scores = [i / 100.0 for i in range(100)]
        labels = [i >= 70 for i in range(100)]
        th = mbe.derive_thresholds(scores, labels, escalation_rate=0.20)
        rates = [rate for _, n, rate in mbe.level_report(th, scores, labels) if n]
        assert rates == sorted(rates, reverse=True)


class TestTraining:
    """작은 데이터로 학습이 실제로 동작하는지 확인한다."""

    @pytest.fixture(scope="class")
    def dataset(self, ds):
        det_ = cf.build(ds)
        sq = seq.build(ds)
        gen = synth.build(ds)
        u = res.UncertaintyModel(horizontal_nm_per_s=4.25 / 600.0,
                                 vertical_ft_per_s=300.0 / 600.0)
        fb_ = mbe.FeatureBuilder(det_, u)
        x, y = [], []
        for i in range(8):
            trs = gen.sequenced_arrivals(20, sq, seed=900 + i * 13)
            for ps in synth.rollout_labels(trs, det_, stride=4):
                x.append(fb_.build(ps.a, ps.b))
                y.append(ps.violated)
        return x, y

    def test_dataset_has_both_classes(self, dataset):
        x, y = dataset
        assert len(x) > 100
        assert 0 < sum(y) < len(y)

    def test_boosting_separates_better_than_chance(self, dataset):
        x, y = dataset
        n = int(len(x) * 0.7)
        m = mbe.train_boosting(x[:n], y[:n])
        r = mbe.evaluate_scores("부스팅", m.score(x[n:]), y[n:])
        assert r.auc > 0.7, f"AUC {r.auc:.3f}"

    def test_importances_sum_to_one_and_are_named(self, dataset):
        x, y = dataset
        m = mbe.train_boosting(x, y)
        imps = m.importances()
        assert {n for n, _ in imps} == set(mbe.FEATURE_NAMES)
        assert sum(v for _, v in imps) == pytest.approx(1.0, abs=0.01)
        assert imps[0][1] >= imps[-1][1]

    def test_logistic_also_trains(self, dataset):
        x, y = dataset
        n = int(len(x) * 0.7)
        m = mbe.train_logistic(x[:n], y[:n])
        r = mbe.evaluate_scores("로지스틱", m.score(x[n:]), y[n:])
        assert r.auc > 0.6


class TestUncertaintyWiring:
    def test_missing_checkpoint_falls_back_to_deterministic(self):
        """근거 없는 σ 를 지어내지 않는다 — 체크포인트가 없으면 결정론."""
        u = mbe.build_uncertainty_from_checkpoint("__no_such_checkpoint__.pt")
        assert u.is_deterministic
