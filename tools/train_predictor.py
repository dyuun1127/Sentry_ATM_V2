"""항적예측 학습 — 물리 + 잔차 LSTM.

    python tools/train_predictor.py [--flights 400] [--epochs 60]

훈련·검증·시험을 **항적 단위로** 나눈다. 같은 항적의 인접 시점을 훈련과 시험에
섞어 넣으면 사실상 같은 상황을 외운 것을 성능으로 착각한다.
"""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sentry_atm.regulation import data as sdata  # noqa: E402
from sentry_atm.regulation import predict as pr  # noqa: E402
from sentry_atm.regulation import synth  # noqa: E402


def split_by_flight(trajectories, seed=20260903, ratios=(0.7, 0.15, 0.15)):
    """항적 단위 분할 — 시점 단위로 나누면 누설이 생긴다."""
    rng = random.Random(seed)
    order = list(trajectories)
    rng.shuffle(order)
    n = len(order)
    a = int(n * ratios[0])
    b = a + int(n * ratios[1])
    return order[:a], order[a:b], order[b:]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--flights", type=int, default=400)
    ap.add_argument("--epochs", type=int, default=60)
    ap.add_argument("--seed", type=int, default=20260903)
    ap.add_argument("--out", default=str(ROOT / "models" / "predictor.pt"))
    args = ap.parse_args()

    ds = sdata.load()
    gen = synth.build(ds)
    baseline = pr.PhysicsBaseline.from_dataset(ds)
    builder = pr.DatasetBuilder(baseline)

    print(f"합성 항적 {args.flights}대 생성 중…")
    trajectories = gen.arrivals(args.flights, seed=args.seed)
    tr_f, va_f, te_f = split_by_flight(trajectories, seed=args.seed)
    print(f"  항적 분할 — 훈련 {len(tr_f)} / 검증 {len(va_f)} / 시험 {len(te_f)}")

    tr = builder.build(tr_f, stride=1)
    va = builder.build(va_f, stride=2)
    te = builder.build(te_f, stride=2)
    print(f"  표본 — 훈련 {len(tr)} / 검증 {len(va)} / 시험 {len(te)}")

    normalizer = pr.Normalizer.fit(tr, len(builder.horizons_s))
    print(f"  지평별 정규화 스케일 {[round(s, 2) for s in normalizer.scales]}")

    model = pr.build_model(len(pr.FEATURE_NAMES), len(builder.horizons_s))
    n_params = sum(p.numel() for p in model.parameters())
    print(f"\n잔차 LSTM 학습 (파라미터 {n_params:,}, 에폭 {args.epochs})")
    report = pr.train(
        model, tr, va, normalizer,
        epochs=args.epochs, seed=args.seed, verbose=True,
    )

    print("\n시험 집합 성능 — 물리 기준선 대비")
    print(f"{'지평':>6}{'물리':>10}{'물리+학습':>11}{'개선':>9}"
          f"{'평균 σ':>10}{'1σ 포함률':>11}{'반경 1σ':>10}")
    print("-" * 68)
    cal = pr.calibrate_sigma(model, va, normalizer, len(builder.horizons_s))
    raw = pr.evaluate(model, te, normalizer, builder.horizons_s)
    results = pr.evaluate(model, te, normalizer, builder.horizons_s, sigma_calibration=cal)
    for r in results:
        print(f"{r.horizon_s:5.0f}s{r.baseline_nm:9.2f}N{r.model_nm:10.2f}N"
              f"{r.improvement:8.1%}{r.sigma_mean_nm:9.2f}N"
              f"{r.coverage_1sigma:10.1%}{r.coverage_radial_1sigma:9.1%}")
    print("-" * 68)
    print("  σ 보정 계수 (검증 집합 산출) "
          + " / ".join(f"{c:.2f}" for c in cal)
          + "  — 1보다 크면 학습 σ 가 실제 오차보다 작았다는 뜻이며 늘리는 보정이다")
    print("  보정 전 1σ 포함률: "
          + " / ".join(f"{r.coverage_1sigma:.1%}" for r in raw))
    print("  성분별 1σ 포함률 이론값 68.3% (1차원 가우시안)")
    print("  반경 1σ 포함률 이론값 39.3% (등방 2차원, 레일리 분포)")
    print()
    print("  [해석] 포함률이 이론값보다 높은 것은 오차 분포의 꼬리가 두껍기 때문이다.")
    print("         대부분의 항적은 계획대로 날고 일부만 벡터링으로 크게 이탈하는")
    print("         혼합 분포이므로, RMS 로 맞춘 σ 는 본체에 대해 보수적이 된다.")
    print("         충돌확률은 2차 모멘트로 적분되므로 RMS 보정이 적절하며,")
    print("         보수적인 방향이라 위험을 과소평가하지 않는다.")
    print()
    print("  [주의] 개선율은 합성 데이터의 난이도에 전적으로 의존한다. 실 ADS-B 나")
    print("         실 관제 로그에서의 값이 아니며, 다른 구현의 개선율과 직접")
    print("         비교할 수 없다. 비교 가능한 것은 물리 기준선 오차의 규모다.")

    u = pr.Predictor(baseline, model, normalizer).uncertainty_model(results)
    print(f"\nCD&R 연결 — σ 증가율 {u.horizontal_nm_per_s * 600:.2f} NM / 10분")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    import torch

    torch.save(
        {
            "state_dict": model.state_dict(),
            "scales": normalizer.scales,
            "horizons_s": list(builder.horizons_s),
            "history": builder.history,
            "n_features": len(pr.FEATURE_NAMES),
            "sigma_calibration": cal,
            "sigma_slope_nm_per_s": u.horizontal_nm_per_s,
            "sigma_by_horizon_nm": [r.sigma_mean_nm for r in results],
            "best_epoch": report.best_epoch,
            "best_val_loss": report.best_val_loss,
        },
        out,
    )
    print(f"모델 저장 — {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
