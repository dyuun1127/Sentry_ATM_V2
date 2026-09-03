"""예외 기반 관리(MBE) — 무엇을 관제사에게 상신할 것인가.

고시 2-1-2 는 *"모든 상황에 통일적으로 적용되는 업무 우선순위의 표준 목록을
설정하는 것은 불가능"* 하며 관제사가 자신의 기량으로 판단해야 한다고 명시한다.
즉 **상신 임계치의 근거가 규정에 없다.** 그래서 이 부분만 학습으로 채운다.

두 가지를 지킨다.

1. **라벨은 임계치가 아니라 결과다.** 개입 없이 두었을 때 실제로 분리위반이
   발생했는가를 정답으로 쓴다(synth.rollout_labels). 관제사 개인의 습관이 아니라
   "결과가 좋았던 판단"을 학습하므로 편향이 전이되지 않는다.

2. **설명가능성.** 심층 신경망 대신 부스팅을 쓰고 피처 기여도를 함께 낸다.
   관제사에게 "왜 이걸 올렸는가"를 답할 수 없으면 상신은 소음이 된다.

4단계 임계는 임의로 정하지 않고 학습 출력 분포와 운용 목표(상신 부하)에서 도출한다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .geometry import cpa as cpa_of
from .geometry import detect_conflict
from .resolution import UncertaintyModel, analytic_collision_probability
from .state import AircraftState, relative_state

FEATURE_NAMES = (
    "collision_prob",     # 예측 불확실성 반영 충돌확률 — Phase 5a 의 σ 가 들어온다
    "cpa_horizontal_nm",
    "cpa_vertical_ft",
    "t_cpa_s",
    "sep_horizontal_nm",
    "sep_vertical_ft",
    "closing_speed_kt",
    "time_to_violation_s",
    "convergence_deg",    # 두 항적의 침로차
    "speed_diff_kt",
    "dist_thr_min_nm",    # 둘 중 활주로에 가까운 쪽
    "dist_thr_diff_nm",
    "wake_pair_rank",     # 후류 등급 조합 (선행 무거움 → 큼)
    "both_on_final",
)

_WAKE_RANK = {"소형": 0, "중형": 1, "대형": 2, "초대형": 3}
_CAP_S = 1e4


@dataclass
class FeatureBuilder:
    """항적 쌍 → 특성 벡터."""

    detector: object
    uncertainty: UncertaintyModel
    horizon_s: float = 600.0

    def build(self, a: AircraftState, b: AircraftState) -> list[float]:
        from .geo import separation_distance_nm

        rel = relative_state(a, b)
        c = cpa_of(rel)
        std = self.detector.rules.separation_standard(a, b)

        window = detect_conflict(rel, std.horizontal_nm, std.vertical_ft, self.horizon_s)
        ttv = window.time_to_violation_s if window else _CAP_S

        p = analytic_collision_probability(
            a, b, std.horizontal_nm, std.vertical_ft, self.uncertainty, self.horizon_s
        )

        thr = self.detector.threshold
        da = separation_distance_nm(a.lat, a.lon, *thr) if thr else 0.0
        db = separation_distance_nm(b.lat, b.lon, *thr) if thr else 0.0

        from .geo import angular_diff

        lead, follow = (a, b) if da <= db else (b, a)

        return [
            p,
            c.horizontal_nm,
            c.vertical_ft,
            min(max(c.t_s, -_CAP_S), _CAP_S),
            rel.horizontal_nm,
            rel.vertical_ft,
            rel.closing_speed_kt,
            min(ttv, _CAP_S),
            abs(angular_diff(a.track_deg, b.track_deg)),
            abs(a.gs_kt - b.gs_kt),
            min(da, db),
            abs(da - db),
            float(_WAKE_RANK.get(lead.wake_cat, 1) - _WAKE_RANK.get(follow.wake_cat, 1)),
            float(self.detector.is_on_final(a) and self.detector.is_on_final(b)),
        ]


# ----------------------------------------------------------------------
# 규칙 기준선
# ----------------------------------------------------------------------


def rule_score_cpa(features: list[float]) -> float:
    """규칙 — 최근접거리 임계. 가까울수록 위험."""
    return -features[FEATURE_NAMES.index("cpa_horizontal_nm")]


def rule_score_probability(features: list[float]) -> float:
    """규칙 — 충돌확률 임계."""
    return features[FEATURE_NAMES.index("collision_prob")]


def rule_score_time(features: list[float]) -> float:
    """규칙 — 예지시간 임계. 임박할수록 위험."""
    return -features[FEATURE_NAMES.index("time_to_violation_s")]


# ----------------------------------------------------------------------
# 평가
# ----------------------------------------------------------------------


@dataclass
class ScoreResult:
    """한 판정 방식의 성능."""

    name: str
    miss_rate: float
    """상신 부하를 고정했을 때 놓치는 실제 위반의 비율."""

    escalation_rate: float
    """**실제** 상신 비율. 동점이 많으면 목표 부하를 초과한다."""

    target_rate: float
    auc: float
    n_positive: int
    n_total: int

    @property
    def recall(self) -> float:
        return 1.0 - self.miss_rate

    @property
    def precision(self) -> float:
        n_escalated = self.escalation_rate * self.n_total
        return (self.recall * self.n_positive / n_escalated) if n_escalated else 0.0


def roc_auc(scores: list[float], labels: list[bool]) -> float:
    """순위 기반 AUC (동점은 평균 순위로 처리)."""
    pairs = sorted(zip(scores, labels))
    ranks: list[float] = [0.0] * len(pairs)
    i = 0
    while i < len(pairs):
        j = i
        while j + 1 < len(pairs) and pairs[j + 1][0] == pairs[i][0]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[k] = avg
        i = j + 1

    pos = sum(1 for _, y in pairs if y)
    neg = len(pairs) - pos
    if pos == 0 or neg == 0:
        return 0.5
    rank_sum = sum(r for r, (_, y) in zip(ranks, pairs) if y)
    return (rank_sum - pos * (pos + 1) / 2.0) / (pos * neg)


def evaluate_scores(
    name: str, scores: list[float], labels: list[bool], escalation_rate: float = 0.20
) -> ScoreResult:
    """**상신 부하를 고정하고** 미탐률을 잰다.

    임계치를 각자 유리하게 잡으면 비교가 되지 않는다. 관제사가 감당할 수 있는
    상신 건수는 정해져 있으므로, 같은 상신 비율에서 무엇을 더 놓치는지를 본다.

    **실제 상신 비율을 함께 돌려준다.** 점수에 동점이 많으면(예: 충돌이 없는 쌍의
    예지시간이 전부 같은 값으로 잘린 경우) 목표 부하를 크게 초과하므로,
    미탐률만 보면 그 방식이 부당하게 좋아 보인다.
    """
    n = len(scores)
    k = max(1, int(round(n * escalation_rate)))
    cutoff = sorted(scores, reverse=True)[k - 1]
    escalated = [s >= cutoff for s in scores]

    pos = sum(labels)
    missed = sum(1 for s, y in zip(escalated, labels) if y and not s)
    return ScoreResult(
        name=name,
        miss_rate=missed / pos if pos else 0.0,
        escalation_rate=sum(escalated) / n,
        target_rate=escalation_rate,
        auc=roc_auc(scores, labels),
        n_positive=pos,
        n_total=n,
    )


# ----------------------------------------------------------------------
# 학습
# ----------------------------------------------------------------------


@dataclass
class Scorer:
    """학습된 위험 스코어러."""

    model: object
    kind: str

    def score(self, features: list[list[float]]) -> list[float]:
        return [float(p) for p in self.model.predict_proba(features)[:, 1]]

    def importances(self) -> list[tuple[str, float]]:
        """피처 기여도 — 큰 순으로."""
        if hasattr(self.model, "feature_importances_"):
            vals = list(self.model.feature_importances_)
        else:
            coefs = [abs(c) for c in self.model.coef_[0]]
            total = sum(coefs) or 1.0
            vals = [c / total for c in coefs]
        return sorted(zip(FEATURE_NAMES, vals), key=lambda kv: -kv[1])


def train_boosting(x: list[list[float]], y: list[bool], seed: int = 20260903) -> Scorer:
    """부스팅 분류기. 심층 신경망 대신 쓰는 이유는 설명가능성이다."""
    from sklearn.ensemble import GradientBoostingClassifier

    m = GradientBoostingClassifier(
        n_estimators=200, max_depth=3, learning_rate=0.05,
        subsample=0.9, random_state=seed,
    )
    m.fit(x, y)
    return Scorer(m, "부스팅")


def train_logistic(x: list[list[float]], y: list[bool], seed: int = 20260903) -> Scorer:
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    m = make_pipeline(
        StandardScaler(),
        LogisticRegression(max_iter=2000, random_state=seed),
    )
    m.fit(x, y)
    scorer = Scorer(m, "로지스틱")
    scorer.model.coef_ = m[-1].coef_
    return scorer


# ----------------------------------------------------------------------
# 4단계 임계
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class Thresholds:
    """정상 / 주의 / 위험 / 비상 경계.

    임의 지정이 아니라 학습 출력 분포와 운용 목표에서 도출한다.
    비상은 점수가 아니라 고시 2-1-4 의 조난 항공기 여부로 결정된다.
    """

    caution: float
    danger: float
    escalation_rate: float
    caution_recall: float

    def level(self, score: float, emergency: bool = False) -> str:
        if emergency:
            return "비상"
        if score >= self.danger:
            return "위험"
        if score >= self.caution:
            return "주의"
        return "정상"


def derive_thresholds(
    scores: list[float],
    labels: list[bool],
    *,
    escalation_rate: float = 0.20,
    caution_recall: float = 0.95,
) -> Thresholds:
    """학습 출력 분포에서 4단계 경계를 도출한다.

    - **위험**: 관제사에게 상신할 상위 구간. 감당 가능한 상신 부하로 정한다.
    - **주의**: 상신하지 않고 화면에만 강조할 구간. 이 아래로는 실제 위반이
      거의 없도록, 목표 재현율을 만족하는 가장 높은 점수로 잡는다.
    - **정상**: 그 아래. 자율 유지 대상이며 관제사 화면에 강조하지 않는다.

    두 경계 모두 임의 상수가 아니라 (상신 부하, 목표 재현율) 이라는 운용 목표에서
    나온다. 목표가 바뀌면 경계도 따라 바뀐다.
    """
    n = len(scores)
    k = max(1, int(round(n * escalation_rate)))
    danger = sorted(scores, reverse=True)[k - 1]

    order = sorted(zip(scores, labels), key=lambda sl: -sl[0])
    pos = sum(labels)
    caution = min(scores) if scores else 0.0
    if pos:
        seen = 0
        for s, y in order:
            if y:
                seen += 1
            if seen / pos >= caution_recall:
                caution = s
                break
    return Thresholds(
        caution=min(caution, danger),
        danger=danger,
        escalation_rate=escalation_rate,
        caution_recall=caution_recall,
    )


def level_report(
    thresholds: Thresholds, scores: list[float], labels: list[bool]
) -> list[tuple[str, int, float]]:
    """단계별 건수와 실제 위반율 — 임계가 타당한지 보는 표."""
    buckets: dict[str, list[bool]] = {"위험": [], "주의": [], "정상": []}
    for s, y in zip(scores, labels):
        buckets[thresholds.level(s)].append(y)
    out = []
    for name in ("위험", "주의", "정상"):
        ys = buckets[name]
        out.append((name, len(ys), sum(ys) / len(ys) if ys else 0.0))
    return out


def build_uncertainty_from_checkpoint(path) -> UncertaintyModel:
    """학습된 항적예측 체크포인트에서 σ 증가율을 읽어 온다.

    없으면 결정론(σ=0)으로 돌아간다 — 근거 없는 σ 를 지어내지 않는다.
    """
    import os

    if not os.path.exists(path):
        return UncertaintyModel()
    import torch

    ck = torch.load(path, map_location="cpu", weights_only=False)
    slope = ck.get("sigma_slope_nm_per_s")
    if slope is None:
        return UncertaintyModel()
    return UncertaintyModel(
        horizontal_nm_per_s=slope,
        vertical_ft_per_s=ck.get("sigma_slope_ft_per_s", 0.0),
    )
