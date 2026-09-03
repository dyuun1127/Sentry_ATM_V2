"""항적예측 검증.

브리프가 "이게 없으면 학습이 전혀 안 된다"고 못박은 두 가지 —
자기기 기준 좌표계와 필수 특성 — 이 실제로 구현되어 있는지를 본다.
"""

import math

import pytest

from sentry_atm.regulation import data as sdata
from sentry_atm.regulation import predict as pr
from sentry_atm.regulation import synth
from sentry_atm.regulation.geo import separation_distance_nm, vincenty_direct
from sentry_atm.regulation.state import AircraftState

torch = pytest.importorskip("torch")


@pytest.fixture(scope="module")
def ds():
    return sdata.load()


@pytest.fixture(scope="module")
def baseline(ds):
    return pr.PhysicsBaseline.from_dataset(ds)


@pytest.fixture(scope="module")
def trajectories(ds):
    return synth.build(ds).arrivals(40, seed=1234)


class TestPhysicsBaseline:
    def test_matches_aip_glidepath_at_the_faf(self, baseline, ds):
        faf = ds.procedures.iap("RNP_24R")["faf_to_thr_nm"]
        assert baseline.glidepath_alt_ft(faf) == pytest.approx(2100, abs=15)

    def test_extrapolates_constant_velocity(self, baseline):
        ac = AircraftState("A", 36.9, 127.7, 5000, 232.43, 180)
        out = baseline.predict(ac, 60.0)
        d = separation_distance_nm(ac.lat, ac.lon, out.lat, out.lon)
        assert d == pytest.approx(3.0, abs=0.02)

    def test_altitude_floor_is_the_glidepath(self, baseline):
        """강하 중인 도착기가 지평 끝에서 지면 아래로 내려가면 안 된다."""
        ac = AircraftState("A", 36.78, 127.60, 2500, 232.43, 150, vs_fpm=-3000)
        out = baseline.predict(ac, 600.0)
        d = separation_distance_nm(out.lat, out.lon, *baseline.thr)
        assert out.alt_ft >= baseline.glidepath_alt_ft(d) - 1e-6
        assert out.alt_ft > 0


class TestFeatures:
    def test_vector_length_matches_names(self, baseline):
        ac = AircraftState("A", 36.9, 127.7, 5000, 232.43, 180)
        assert len(pr.features(ac, None, baseline, 4.0)) == len(pr.FEATURE_NAMES)

    def test_relative_bearing_is_zero_when_heading_at_the_airport(self, baseline):
        """공항을 정면으로 향하면 상대 방위 sin=0, cos=1."""
        from sentry_atm.regulation.geo import bearing_true

        lat, lon = vincenty_direct(*baseline.thr, 52.43, 12 * 1852.0)
        track = bearing_true(lat, lon, *baseline.thr)
        ac = AircraftState("A", lat, lon, 4000, track, 200)
        f = pr.features(ac, None, baseline, 4.0)
        i_sin = pr.FEATURE_NAMES.index("rel_brg_sin")
        i_cos = pr.FEATURE_NAMES.index("rel_brg_cos")
        assert f[i_sin] == pytest.approx(0.0, abs=1e-6)
        assert f[i_cos] == pytest.approx(1.0, abs=1e-6)

    def test_relative_bearing_sign_distinguishes_left_and_right(self, baseline):
        from sentry_atm.regulation.geo import bearing_true

        lat, lon = vincenty_direct(*baseline.thr, 52.43, 12 * 1852.0)
        to_thr = bearing_true(lat, lon, *baseline.thr)
        i_sin = pr.FEATURE_NAMES.index("rel_brg_sin")
        left = pr.features(
            AircraftState("L", lat, lon, 4000, (to_thr + 30) % 360, 200),
            None, baseline, 4.0,
        )
        right = pr.features(
            AircraftState("R", lat, lon, 4000, (to_thr - 30) % 360, 200),
            None, baseline, 4.0,
        )
        assert left[i_sin] * right[i_sin] < 0

    def test_glidepath_margin_is_zero_on_the_glidepath(self, baseline):
        lat, lon = vincenty_direct(*baseline.thr, 52.43, 8 * 1852.0)
        alt = baseline.glidepath_alt_ft(
            separation_distance_nm(lat, lon, *baseline.thr)
        )
        f = pr.features(AircraftState("A", lat, lon, alt, 232.43, 150), None, baseline, 4.0)
        assert f[pr.FEATURE_NAMES.index("gp_margin")] == pytest.approx(0.0, abs=1e-3)

    def test_glidepath_margin_sign(self, baseline):
        lat, lon = vincenty_direct(*baseline.thr, 52.43, 8 * 1852.0)
        i = pr.FEATURE_NAMES.index("gp_margin")
        gp = baseline.glidepath_alt_ft(separation_distance_nm(lat, lon, *baseline.thr))
        high = pr.features(
            AircraftState("H", lat, lon, gp + 1500, 232.43, 150), None, baseline, 4.0
        )
        low = pr.features(
            AircraftState("L", lat, lon, gp - 500, 232.43, 150), None, baseline, 4.0
        )
        assert high[i] > 0 > low[i]


class TestOwnFrame:
    """전역 좌표로 잔차를 예측하면 회전 불변성이 깨져 학습이 안 된다."""

    def test_forward_residual_is_rotation_invariant(self, baseline):
        """같은 기동이면 방위가 달라도 같은 (전방, 좌측) 값이 나와야 한다."""
        results = []
        for track in (0.0, 90.0, 180.0, 270.0, 47.0):
            origin = AircraftState("A", 36.8, 127.6, 5000, track, 180)
            pred = origin.advance(300)
            # 예측 위치에서 진로 방향으로 2NM, 좌측으로 1NM 어긋난 실제 위치
            lat, lon = vincenty_direct(pred.lat, pred.lon, track, 2 * 1852.0)
            lat, lon = vincenty_direct(lat, lon, (track - 90) % 360, 1 * 1852.0)
            truth = AircraftState("A", lat, lon, 5000, track, 180)
            results.append(pr.own_frame_residual(origin, pred, truth))

        for fwd, left in results:
            assert fwd == pytest.approx(2.0, abs=0.02)
            assert left == pytest.approx(1.0, abs=0.02)

    def test_residual_round_trip(self, baseline):
        origin = AircraftState("A", 36.8, 127.6, 5000, 137.0, 180)
        pred = origin.advance(300)
        lat, lon = pr.apply_residual(origin, pred, 3.5, -1.2)
        truth = AircraftState("A", lat, lon, 5000, 137.0, 180)
        fwd, left = pr.own_frame_residual(origin, pred, truth)
        assert fwd == pytest.approx(3.5, abs=0.01)
        assert left == pytest.approx(-1.2, abs=0.01)


class TestNormalizer:
    def test_scales_differ_by_horizon(self, baseline, trajectories):
        """60초와 600초 잔차는 크기가 두 자릿수 다르다."""
        samples = pr.DatasetBuilder(baseline).build(trajectories[:10], stride=4)
        nz = pr.Normalizer.fit(samples, 4)
        assert nz.scales[0] < nz.scales[-1] / 5, f"{nz.scales}"

    def test_encode_decode_round_trip(self):
        nz = pr.Normalizer(scales=[0.5, 2.0, 8.0, 20.0])
        targets = [(1.0, -0.5), (3.0, 2.0), (-4.0, 1.0), (10.0, -3.0)]
        back = nz.decode(nz.encode(targets))
        for (a, b), (c, d) in zip(targets, back):
            assert a == pytest.approx(c)
            assert b == pytest.approx(d)


class TestDataset:
    def test_sample_shape(self, baseline, trajectories):
        b = pr.DatasetBuilder(baseline)
        s = b.build(trajectories[:5], stride=5)[0]
        assert len(s.history) == b.history
        assert len(s.history[0]) == len(pr.FEATURE_NAMES)
        assert len(s.targets) == len(b.horizons_s)
        assert len(s.baseline_error_nm) == len(b.horizons_s)

    def test_baseline_error_grows_with_horizon(self, baseline, trajectories):
        samples = pr.DatasetBuilder(baseline).build(trajectories[:15], stride=4)
        means = [
            sum(s.baseline_error_nm[h] for s in samples) / len(samples)
            for h in range(4)
        ]
        assert means == sorted(means)

    def test_residual_matches_baseline_error(self, baseline, trajectories):
        """잔차 크기가 곧 물리 기준선 오차여야 한다 — 정의의 일관성."""
        samples = pr.DatasetBuilder(baseline).build(trajectories[:5], stride=7)
        for s in samples[:50]:
            for h in range(4):
                fwd, left = s.targets[h]
                assert math.hypot(fwd, left) == pytest.approx(
                    s.baseline_error_nm[h], rel=0.02, abs=0.01
                )


class TestTraining:
    """학습이 실제로 물리 기준선을 개선하는지 — 짧게 돌려 확인한다."""

    @pytest.fixture(scope="class")
    def trained(self, ds):
        gen = synth.build(ds)
        base = pr.PhysicsBaseline.from_dataset(ds)
        builder = pr.DatasetBuilder(base)
        flights = gen.arrivals(60, seed=555)
        tr = builder.build(flights[:42], stride=2)
        va = builder.build(flights[42:51], stride=3)
        te = builder.build(flights[51:], stride=3)
        nz = pr.Normalizer.fit(tr, 4)
        model = pr.build_model(len(pr.FEATURE_NAMES), 4)
        pr.train(model, tr, va, nz, epochs=25, seed=7)
        return base, model, nz, te, va, builder

    def test_beats_the_physics_baseline(self, trained):
        _, model, nz, te, _, b = trained
        results = pr.evaluate(model, te, nz, b.horizons_s)
        for r in results:
            assert r.model_nm < r.baseline_nm, (
                f"{r.horizon_s:.0f}s 에서 학습이 물리보다 나쁘다"
            )

    def test_long_horizon_improves_most(self, trained):
        """장기 지평일수록 개선 폭이 커야 한다 — 물리 외삽이 무너지는 구간이다."""
        _, model, nz, te, _, b = trained
        results = pr.evaluate(model, te, nz, b.horizons_s)
        assert results[-1].improvement > results[0].improvement

    def test_sigma_is_positive_and_grows(self, trained):
        _, model, nz, te, _, b = trained
        results = pr.evaluate(model, te, nz, b.horizons_s)
        for r in results:
            assert r.sigma_mean_nm > 0
        assert results[-1].sigma_mean_nm > results[0].sigma_mean_nm

    def test_calibration_is_computed_on_validation_only(self, trained):
        _, model, nz, _, va, b = trained
        cal = pr.calibrate_sigma(model, va, nz, len(b.horizons_s))
        assert len(cal) == len(b.horizons_s)
        assert all(c > 0 for c in cal)

    def test_predictor_produces_positions_and_sigma(self, trained, ds):
        base, model, nz, _, _, b = trained
        gen = synth.build(ds)
        tr = gen.arrivals(1, seed=4242)[0]
        p = pr.Predictor(base, model, nz, b.horizons_s, b.history)
        preds = p.predict(tr.samples[:40], dt_s=tr.dt_s)
        assert len(preds) == len(b.horizons_s)
        for pred in preds:
            assert 36.0 < pred.lat < 38.0
            assert 126.0 < pred.lon < 129.0
            assert pred.sigma_nm > 0

    def test_uncertainty_model_feeds_cdr(self, trained):
        """Phase 4 가 0(결정론)으로 비워 둔 σ 자리를 학습 결과가 채운다."""
        base, model, nz, te, _, b = trained
        results = pr.evaluate(model, te, nz, b.horizons_s)
        u = pr.Predictor(base, model, nz).uncertainty_model(results)
        assert not u.is_deterministic
        assert u.horizontal_nm_per_s > 0
        s600 = u.sigma_at(600.0)[0]
        assert 0.5 < s600 < 20.0, f"10분 σ {s600:.2f}NM"
