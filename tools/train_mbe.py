"""예외 판정(MBE) 학습 — 결과 기반 라벨로 위험 스코어러를 만든다.

    python tools/train_mbe.py [--scenarios 40] [--flights 26]

규칙 임계와 학습 모델을 **같은 상신 부하**에서 비교한다. 임계치를 각자 유리하게
잡으면 비교가 되지 않는다.
"""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sentry_atm.regulation import conflict as cf  # noqa: E402
from sentry_atm.regulation import data as sdata  # noqa: E402
from sentry_atm.regulation import (  # noqa: E402
    mbe,  # noqa: E402
    synth,  # noqa: E402
)
from sentry_atm.regulation import sequencing as seq  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenarios", type=int, default=40)
    ap.add_argument("--flights", type=int, default=26)
    ap.add_argument("--seed", type=int, default=20260903)
    ap.add_argument("--escalation", type=float, default=0.05)
    ap.add_argument("--caution-recall", type=float, default=0.99)
    ap.add_argument("--predictor", default=str(ROOT / "models" / "predictor.pt"))
    ap.add_argument("--out", default=str(ROOT / "models" / "mbe.pkl"))
    args = ap.parse_args()

    ds = sdata.load()
    det = cf.build(ds)
    sq = seq.build(ds)
    gen = synth.build(ds)

    unc = mbe.build_uncertainty_from_checkpoint(args.predictor)
    if unc.is_deterministic:
        print("경고 — 항적예측 체크포인트가 없어 σ=0(결정론)으로 진행한다.")
        print("      충돌확률 특성이 0/1 이 되어 학습 성능이 과소평가된다.")
        print("      먼저 tools/train_predictor.py 를 돌릴 것.\n")
    else:
        print(f"항적예측 σ 연결 — 10분 지평 {unc.sigma_at(600)[0]:.2f} NM\n")

    fb = mbe.FeatureBuilder(det, unc)

    print(f"시나리오 {args.scenarios}개 × 항적 {args.flights}대 생성 중…")
    rng = random.Random(args.seed)
    scenario_ids = list(range(args.scenarios))
    rng.shuffle(scenario_ids)
    cut = int(len(scenario_ids) * 0.7)
    train_ids, _test_ids = set(scenario_ids[:cut]), set(scenario_ids[cut:])

    xtr, ytr, xte, yte = [], [], [], []
    for i in range(args.scenarios):
        trs = gen.sequenced_arrivals(args.flights, sq, seed=args.seed + i * 17)
        for ps in synth.rollout_labels(trs, det, stride=2):
            if ps.already_violating:
                # 이미 위반 중인 쌍은 예측 과제가 아니다 — 관제사가 화면에서 본다.
                # 섞어 두면 과제가 '현재 위반 탐지'가 되어 결정론 기하만으로 풀린다.
                continue
            f = fb.build(ps.a, ps.b)
            if i in train_ids:
                xtr.append(f)
                ytr.append(ps.violated)
            else:
                xte.append(f)
                yte.append(ps.violated)

    print(f"  훈련 {len(xtr)}건 (위반 {sum(ytr)}건, {sum(ytr)/max(len(ytr),1):.1%})")
    print(f"  시험 {len(xte)}건 (위반 {sum(yte)}건, {sum(yte)/max(len(yte),1):.1%})")
    print("  시나리오 단위 분할 — 같은 시나리오의 인접 시점이 훈련·시험에 섞이지 않는다")
    print("  이미 위반 중인 쌍은 제외 — MBE 는 '지금 괜찮아 보이는 쌍 중")
    print("  무엇이 문제가 되는가'를 답하는 과제다")

    boost = mbe.train_boosting(xtr, ytr, seed=args.seed)
    logit = mbe.train_logistic(xtr, ytr, seed=args.seed)

    results = [
        mbe.evaluate_scores("규칙 — CPA 임계",
                            [mbe.rule_score_cpa(f) for f in xte], yte, args.escalation),
        mbe.evaluate_scores("규칙 — 예지시간 임계",
                            [mbe.rule_score_time(f) for f in xte], yte, args.escalation),
        mbe.evaluate_scores("규칙 — 충돌확률 임계",
                            [mbe.rule_score_probability(f) for f in xte], yte, args.escalation),
        mbe.evaluate_scores("학습 — 로지스틱", logit.score(xte), yte, args.escalation),
        mbe.evaluate_scores("학습 — 부스팅", boost.score(xte), yte, args.escalation),
    ]

    print(f"\n판정 방식 비교 — 목표 상신 부하 {args.escalation:.0%}")
    print(f"{'방식':<22}{'실제 상신':>10}{'미탐률':>9}{'정밀도':>9}{'ROC-AUC':>10}")
    print("-" * 62)
    for r in results:
        flag = " *" if r.escalation_rate > args.escalation * 1.5 else ""
        print(f"{r.name:<22}{r.escalation_rate:10.1%}{r.miss_rate:9.1%}"
              f"{r.precision:9.1%}{r.auc:10.3f}{flag}")
    print("-" * 62)
    if any(r.escalation_rate > args.escalation * 1.5 for r in results):
        print("  * 목표 부하를 크게 초과 — 점수에 동점이 많아 임계로 잘라낼 수 없다.")
        print("    충돌이 예측되지 않는 쌍의 예지시간이 전부 같은 값이라 순위가")
        print("    매겨지지 않는다. 미탐률만 보면 유리해 보이지만, 실제로는 관제사")
        print("    부하가 그만큼 늘어난다 — 이것이 MBE 가 푸는 문제다.")

    scores = boost.score(xte)
    th = mbe.derive_thresholds(scores, yte, escalation_rate=args.escalation,
                               caution_recall=args.caution_recall)
    print("\n4단계 임계 (학습 출력 분포에서 도출)")
    print(f"  위험 ≥ {th.danger:.4f}   상신 부하 {th.escalation_rate:.0%} 목표에서 도출")
    print(f"  주의 ≥ {th.caution:.4f}   목표 재현율 {th.caution_recall:.0%} 에서 도출")
    print("  두 경계 모두 임의 상수가 아니라 운용 목표에서 나온다 —")
    print("  목표가 바뀌면 경계도 따라 바뀐다.")
    print(f"{'단계':<8}{'건수':>8}{'실제 위반율':>12}")
    print("-" * 30)
    for name, n, rate in mbe.level_report(th, scores, yte):
        print(f"{name:<8}{n:8d}{rate:12.1%}")
    print("-" * 30)
    print("  비상 단계는 점수가 아니라 고시 2-1-4(조난 항공기)로 결정된다.")

    print("\n피처 기여도 — 부스팅")
    imps = boost.importances()
    for name, v in imps[:6]:
        print(f"  {name:<22}{v:7.1%}")
    top_name, top_val = imps[0]
    print()
    print(f"  상위 3개 합계 {sum(v for _, v in imps[:3]):.0%}")
    if top_val > 0.5:
        print(f"  [정직성] 기여도의 {top_val:.0%} 가 '{top_name}' 하나에 몰려 있다.")
        print("           '여러 신호를 종합한다'가 아니라 '같은 신호를 비선형으로")
        print("           더 잘 쓴다'가 정확한 표현이다.")
    else:
        print("  기여도가 한 피처에 몰려 있지 않다 — 충돌확률(항적예측의 σ 반영),")
        print("  선후 간격, 예지시간이 함께 쓰인다.")

    import pickle

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "wb") as fh:
        pickle.dump(
            {"boosting": boost.model, "thresholds": th,
             "feature_names": mbe.FEATURE_NAMES,
             "uncertainty": unc, "results": results},
            fh,
        )
    print(f"\n모델 저장 — {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
