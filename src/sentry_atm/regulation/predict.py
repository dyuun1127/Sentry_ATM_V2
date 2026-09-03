"""항적예측 — 물리 기준선 + 학습 잔차보정.

궤적 전체를 신경망이 생성하지 않는다. 물리 예측을 기준선으로 두고 **그 차이만**
학습하므로 물리적으로 타당한 해가 보장되고, 학습이 실패해도 기준선 성능은 남는다.

이전 구현이 개선 0.7% 로 실패했던 원인 두 가지를 구조로 막는다.

1. **자기기 기준 좌표계** — 잔차를 동/북이 아니라 전방/좌측으로 예측한다.
   전역 좌표로 하면 "선회 중이라 예측보다 안쪽으로 온다"는 같은 상황이
   방위마다 완전히 다른 목표값이 되어 학습이 되지 않는다.

2. **필수 특성** — 공항 상대 방위와 3° 활공로 대비 고도 여유.
   접근 항적의 잔차는 대부분 "공항 쪽으로 선회한다"와 "활공로를 향해 강하한다"에서
   나온다. 이 둘이 입력에 없으면 신경망이 볼 수 있는 신호가 없다.

정규화도 **지평별로** 한다. 60초와 600초의 잔차는 크기가 두 자릿수 다르므로
공통 스케일을 쓰면 단기 구간이 수치적으로 뭉개진다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .geo import (
    M_PER_NM,
    angular_diff,
    bearing_true,
    enu_offset_nm,
    separation_distance_nm,
    vincenty_direct,
)
from .state import AircraftState

FT_PER_NM = 6076.11548556

DEFAULT_HORIZONS_S = (60.0, 180.0, 300.0, 600.0)
DEFAULT_HISTORY = 15
"""입력 시퀀스 길이. 4초 간격 15개 = 60초 이력."""


# ----------------------------------------------------------------------
# 물리 기준선
# ----------------------------------------------------------------------


@dataclass
class PhysicsBaseline:
    """등속·등침로 외삽에 활공로 하한을 씌운 물리 예측.

    학습이 줄여야 할 기준이자, 학습이 실패해도 남는 성능의 바닥이다.
    수직은 상승률을 그대로 외삽하되 3° 활공로 아래로는 내려가지 않게 한다 —
    강하 중인 도착기가 지평 끝에서 지면 아래로 내려가는 것을 막는다.
    """

    thr: tuple[float, float]
    thr_elev_ft: float
    gs_angle_deg: float = 3.0
    tch_ft: float = 59.0

    def glidepath_alt_ft(self, dist_nm: float) -> float:
        return (
            dist_nm * FT_PER_NM * math.tan(math.radians(self.gs_angle_deg))
            + self.tch_ft
            + self.thr_elev_ft
        )

    def predict(self, ac: AircraftState, horizon_s: float) -> AircraftState:
        """지평 뒤 상태."""
        out = ac.advance(horizon_s)
        floor = self.glidepath_alt_ft(
            separation_distance_nm(out.lat, out.lon, *self.thr)
        )
        if out.alt_ft < floor:
            from dataclasses import replace

            out = replace(out, alt_ft=floor)
        return out

    @classmethod
    def from_dataset(cls, ds, runway: str = "24R", approach: str = "RNP_24R"):
        rwy = ds.procedures.runways[runway]
        iap = ds.procedures.iap(approach)
        return cls(
            thr=(rwy.thr_lat, rwy.thr_lon),
            thr_elev_ft=rwy.thr_elev_ft,
            gs_angle_deg=iap["gs_angle_deg"],
            tch_ft=iap["tch_ft"],
        )


# ----------------------------------------------------------------------
# 특성
# ----------------------------------------------------------------------

FEATURE_NAMES = (
    "dist_thr",          # 시단까지 거리 (정규화)
    "rel_brg_sin",       # 공항 상대 방위 — 필수
    "rel_brg_cos",       # 공항 상대 방위 — 필수
    "gp_margin",         # 3° 활공로 대비 고도 여유 — 필수
    "alt",               # 고도
    "gs",                # 대지속도
    "vs",                # 상승률
    "gs_rate",           # 속도 변화율
    "track_rate",        # 선회율
    "vs_rate",           # 상승률 변화율
)


def features(
    ac: AircraftState,
    prev: AircraftState | None,
    baseline: PhysicsBaseline,
    dt_s: float,
) -> list[float]:
    """한 시점의 특성 벡터.

    공항 상대 방위와 활공로 여유가 핵심이다. 이 둘이 빠지면 접근 항적의 잔차를
    설명할 신호가 사라져 학습이 사실상 실패한다.
    """
    dist = separation_distance_nm(ac.lat, ac.lon, *baseline.thr)
    brg = bearing_true(ac.lat, ac.lon, *baseline.thr)
    rel = math.radians(angular_diff(brg, ac.track_deg))

    gp = baseline.glidepath_alt_ft(dist)
    gp_margin = (ac.alt_ft - gp) / 3000.0

    if prev is None:
        gs_rate = track_rate = vs_rate = 0.0
    else:
        gs_rate = (ac.gs_kt - prev.gs_kt) / dt_s
        track_rate = angular_diff(ac.track_deg, prev.track_deg) / dt_s
        vs_rate = (ac.vs_fpm - prev.vs_fpm) / dt_s

    return [
        dist / 30.0,
        math.sin(rel),
        math.cos(rel),
        gp_margin,
        ac.alt_ft / 10000.0,
        ac.gs_kt / 250.0,
        ac.vs_fpm / 2000.0,
        gs_rate / 2.0,
        track_rate / 3.0,
        vs_rate / 50.0,
    ]


def own_frame_residual(
    origin: AircraftState, predicted: AircraftState, truth: AircraftState
) -> tuple[float, float]:
    """자기기 기준 좌표계의 잔차 (전방 NM, 좌측 NM).

    `origin` 의 현재 침로를 전방으로 삼는다. 전역 동/북으로 두면 같은 기동이
    방위마다 다른 목표값이 되어 학습이 회전 불변성을 갖지 못한다.
    """
    east, north = enu_offset_nm(predicted.lat, predicted.lon, truth.lat, truth.lon)
    c = math.radians(origin.track_deg)
    forward = east * math.sin(c) + north * math.cos(c)
    left = -(east * math.cos(c) - north * math.sin(c))
    return forward, left


def apply_residual(
    origin: AircraftState, predicted: AircraftState, forward_nm: float, left_nm: float
) -> tuple[float, float]:
    """자기기 기준 잔차를 물리 예측 위치에 더해 위경도로 되돌린다."""
    c = math.radians(origin.track_deg)
    east = forward_nm * math.sin(c) - left_nm * math.cos(c)
    north = forward_nm * math.cos(c) + left_nm * math.sin(c)
    dist = math.hypot(east, north)
    if dist == 0.0:
        return predicted.lat, predicted.lon
    brg = math.degrees(math.atan2(east, north)) % 360.0
    return vincenty_direct(predicted.lat, predicted.lon, brg, dist * M_PER_NM)


# ----------------------------------------------------------------------
# 데이터셋
# ----------------------------------------------------------------------


@dataclass
class Sample:
    """학습 표본 하나."""

    history: list[list[float]]
    """길이 DEFAULT_HISTORY 의 특성 시퀀스."""

    targets: list[tuple[float, float]]
    """지평별 (전방, 좌측) 잔차 NM."""

    baseline_error_nm: list[float]
    """지평별 물리 기준선 오차 — 개선율 계산용."""

    callsign: str = ""
    t_s: float = 0.0


@dataclass
class DatasetBuilder:
    """Trajectory 목록에서 학습 표본을 만든다."""

    baseline: PhysicsBaseline
    horizons_s: tuple[float, ...] = DEFAULT_HORIZONS_S
    history: int = DEFAULT_HISTORY

    def build(self, trajectories, stride: int = 2) -> list[Sample]:
        out: list[Sample] = []
        for tr in trajectories:
            dt = tr.dt_s
            steps = [int(round(h / dt)) for h in self.horizons_s]
            need = max(steps)
            n = len(tr.samples)

            feats: list[list[float]] = []
            for i, s in enumerate(tr.samples):
                feats.append(features(s, tr.samples[i - 1] if i else None, self.baseline, dt))

            for i in range(self.history - 1, n - need, stride):
                origin = tr.samples[i]
                targets: list[tuple[float, float]] = []
                errors: list[float] = []
                for h, k in zip(self.horizons_s, steps, strict=False):
                    truth = tr.samples[i + k]
                    pred = self.baseline.predict(origin, h)
                    targets.append(own_frame_residual(origin, pred, truth))
                    errors.append(
                        separation_distance_nm(pred.lat, pred.lon, truth.lat, truth.lon)
                    )
                out.append(
                    Sample(
                        history=feats[i - self.history + 1: i + 1],
                        targets=targets,
                        baseline_error_nm=errors,
                        callsign=tr.callsign,
                        t_s=origin.t_s,
                    )
                )
        return out


@dataclass
class Normalizer:
    """지평별 잔차 정규화.

    60초와 600초의 잔차는 크기가 두 자릿수 다르다. 공통 스케일로 정규화하면
    단기 구간의 목표값이 0 근처로 뭉개져 학습이 장기 구간만 맞추게 된다.
    """

    scales: list[float] = field(default_factory=list)

    @classmethod
    def fit(cls, samples: list[Sample], n_horizons: int) -> Normalizer:
        scales = []
        for h in range(n_horizons):
            vals = [abs(v) for s in samples for v in s.targets[h]]
            vals.sort()
            # 이상치에 끌려가지 않도록 90분위를 스케일로 쓴다
            scale = vals[int(len(vals) * 0.9)] if vals else 1.0
            scales.append(max(scale, 1e-3))
        return cls(scales=scales)

    def encode(self, targets: list[tuple[float, float]]) -> list[tuple[float, float]]:
        return [
            (fwd / s, lat / s)
            for (fwd, lat), s in zip(targets, self.scales, strict=False)
        ]

    def decode(self, values: list[tuple[float, float]]) -> list[tuple[float, float]]:
        return [
            (fwd * s, lat * s)
            for (fwd, lat), s in zip(values, self.scales, strict=False)
        ]

    def decode_sigma(self, sigmas: list[float]) -> list[float]:
        return [g * s for g, s in zip(sigmas, self.scales, strict=False)]


# ----------------------------------------------------------------------
# 잔차 LSTM
# ----------------------------------------------------------------------


def _require_torch():
    try:
        import torch
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "항적예측 학습에는 torch 가 필요하다: "
            'python -m pip install torch --index-url https://download.pytorch.org/whl/cpu'
        ) from exc
    return torch


def build_model(n_features: int, n_horizons: int, hidden: int = 64, layers: int = 1,
                dropout: float = 0.2):
    """이력 시퀀스 → 지평별 (전방, 좌측) 잔차 + log σ².

    σ 를 함께 출력해 이분산(heteroscedastic) 가우시안 우도로 학습한다.
    모델이 자기 오차를 스스로 추정하게 되며, 그 σ 가 CD&R 충돌확률의 입력이 된다.
    """
    torch = _require_torch()
    nn = torch.nn

    class ResidualLSTM(nn.Module):
        def __init__(self):
            super().__init__()
            self.lstm = nn.LSTM(n_features, hidden, num_layers=layers, batch_first=True)
            self.drop = nn.Dropout(dropout)
            self.head = nn.Sequential(
                nn.Linear(hidden, hidden), nn.ReLU(), nn.Dropout(dropout),
                nn.Linear(hidden, n_horizons * 3),
            )
            self.n_horizons = n_horizons

        def forward(self, x):
            out, _ = self.lstm(x)
            y = self.head(self.drop(out[:, -1, :]))
            y = y.view(-1, self.n_horizons, 3)
            mu = y[..., :2]
            logvar = y[..., 2].clamp(-8.0, 4.0)
            return mu, logvar

    return ResidualLSTM()


def gaussian_nll(mu, logvar, target):
    """이분산 가우시안 음의 로그우도.

    등방 σ 를 지평마다 하나씩 둔다 — 전방·좌측 두 성분이 같은 σ 를 공유한다.
    성분별로 σ 를 두면 표현력은 늘지만 CD&R 이 쓰는 '위치 불확실성 반지름'이
    모호해진다.
    """
    torch = _require_torch()
    sq = ((target - mu) ** 2).sum(dim=-1)
    return (0.5 * torch.exp(-logvar) * sq + logvar).mean()


@dataclass
class TrainReport:
    epochs: int
    train_loss: list[float]
    val_loss: list[float]
    n_train: int
    n_val: int
    best_epoch: int = 0
    best_val_loss: float = 0.0
    val_position: list[float] = field(default_factory=list)


def train(
    model,
    train_samples: list[Sample],
    val_samples: list[Sample],
    normalizer: Normalizer,
    *,
    epochs: int = 60,
    batch_size: int = 64,
    lr: float = 2e-3,
    weight_decay: float = 1e-4,
    patience: int = 12,
    seed: int = 20260903,
    verbose: bool = False,
) -> TrainReport:
    """검증 손실이 가장 낮았던 가중치를 되돌린다.

    이분산 우도는 과적합하면 σ 를 극단적으로 줄이는 쪽으로 폭주한다.
    검증 손실 기준 조기 종료가 없으면 훈련 손실만 내려가고 σ 가 무너져
    CD&R 이 위험을 과소평가하게 된다.
    """
    torch = _require_torch()
    torch.manual_seed(seed)

    def to_tensors(samples):
        x = torch.tensor([s.history for s in samples], dtype=torch.float32)
        y = torch.tensor(
            [normalizer.encode(s.targets) for s in samples], dtype=torch.float32
        )
        return x, y

    xtr, ytr = to_tensors(train_samples)
    xva, yva = to_tensors(val_samples)

    opt = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=weight_decay)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=epochs)
    n = len(train_samples)
    tr_hist, va_hist = [], []
    pos_hist: list[float] = []
    best_loss, best_state, best_epoch, stale = float("inf"), None, 0, 0

    for ep in range(epochs):
        model.train()
        perm = torch.randperm(n)
        total = 0.0
        for i in range(0, n, batch_size):
            idx = perm[i: i + batch_size]
            opt.zero_grad()
            mu, logvar = model(xtr[idx])
            loss = gaussian_nll(mu, logvar, ytr[idx])
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            total += loss.item() * len(idx)
        sched.step()
        tr_hist.append(total / n)

        model.eval()
        with torch.no_grad():
            mu, logvar = model(xva)
            va_hist.append(gaussian_nll(mu, logvar, yva).item())
            # 조기 종료는 **위치 오차**로 판단한다. 이분산 NLL 은 σ 가 조금만
            # 작아도 폭증해서, 위치 정확도가 계속 좋아지는 중에도 손실이
            # 나빠진다. 두 지표를 분리하고 σ 는 별도 보정한다.
            pos_hist.append(
                ((mu - yva) ** 2).sum(dim=-1).sqrt().mean().item()
            )
        if pos_hist[-1] < best_loss - 1e-5:
            best_loss, best_epoch, stale = pos_hist[-1], ep, 0
            best_state = {k: v.detach().clone() for k, v in model.state_dict().items()}
        else:
            stale += 1

        if verbose and (ep % 10 == 0 or ep == epochs - 1):
            print(f"  epoch {ep:3d}  train NLL {tr_hist[-1]:7.3f}  "
                  f"val NLL {va_hist[-1]:7.3f}  val 위치오차 {pos_hist[-1]:.4f}")
        if stale >= patience:
            if verbose:
                print(f"  조기 종료 — 검증 손실이 {patience}에폭 개선 없음")
            break

    if best_state is not None:
        model.load_state_dict(best_state)
    if verbose:
        print(f"  최적 에폭 {best_epoch} (검증 위치오차 {best_loss:.4f}) 가중치 복원")

    return TrainReport(
        len(tr_hist), tr_hist, va_hist, len(train_samples), len(val_samples),
        best_epoch=best_epoch, best_val_loss=best_loss, val_position=pos_hist,
    )


# ----------------------------------------------------------------------
# 평가
# ----------------------------------------------------------------------


@dataclass
class HorizonResult:
    horizon_s: float
    baseline_nm: float
    model_nm: float
    sigma_mean_nm: float
    coverage_1sigma: float
    """성분별 1σ 포함률. 이론값 68.3% (1차원 가우시안)."""

    coverage_radial_1sigma: float
    """반경 1σ 포함률. 등방 2차원이면 이론값 39.3% (레일리 분포)."""

    @property
    def improvement(self) -> float:
        if self.baseline_nm == 0.0:
            return 0.0
        return (self.baseline_nm - self.model_nm) / self.baseline_nm


def evaluate(model, samples: list[Sample], normalizer: Normalizer,
             horizons_s=DEFAULT_HORIZONS_S,
             sigma_calibration: list[float] | None = None) -> list[HorizonResult]:
    """지평별 물리 대비 개선율과 σ 보정 상태."""
    torch = _require_torch()
    model.eval()
    x = torch.tensor([s.history for s in samples], dtype=torch.float32)
    with torch.no_grad():
        mu, logvar = model(x)
    mu = mu.numpy()
    sigma = torch.exp(0.5 * logvar).numpy()

    out: list[HorizonResult] = []
    for h_idx, h in enumerate(horizons_s):
        scale = normalizer.scales[h_idx]
        base_err, model_err, sig, cov_c, cov_r = [], [], [], [], []
        for i, s in enumerate(samples):
            tf, tl = s.targets[h_idx]
            pf = mu[i, h_idx, 0] * scale
            pl = mu[i, h_idx, 1] * scale
            sg = float(sigma[i, h_idx]) * scale
            if sigma_calibration is not None:
                sg *= sigma_calibration[h_idx]

            base_err.append(s.baseline_error_nm[h_idx])
            model_err.append(math.hypot(tf - pf, tl - pl))
            sig.append(sg)
            if sg > 0:
                cov_c.append(abs(tf - pf) <= sg)
                cov_c.append(abs(tl - pl) <= sg)
                cov_r.append(math.hypot(tf - pf, tl - pl) <= sg)

        out.append(
            HorizonResult(
                horizon_s=h,
                baseline_nm=sum(base_err) / len(base_err),
                model_nm=sum(model_err) / len(model_err),
                sigma_mean_nm=sum(sig) / len(sig),
                coverage_1sigma=sum(cov_c) / len(cov_c) if cov_c else 0.0,
                coverage_radial_1sigma=sum(cov_r) / len(cov_r) if cov_r else 0.0,
            )
        )
    return out


# ----------------------------------------------------------------------
# 추론기
# ----------------------------------------------------------------------


@dataclass
class Prediction:
    """한 지평의 예측."""

    horizon_s: float
    lat: float
    lon: float
    alt_ft: float
    sigma_nm: float


@dataclass
class Predictor:
    """물리 기준선 + 학습 잔차 = 최종 예측. σ 를 함께 낸다."""

    baseline: PhysicsBaseline
    model: object
    normalizer: Normalizer
    horizons_s: tuple[float, ...] = DEFAULT_HORIZONS_S
    history: int = DEFAULT_HISTORY

    def predict(self, track: list[AircraftState], dt_s: float = 4.0) -> list[Prediction]:
        """최근 이력으로 지평별 위치와 불확실성을 낸다."""
        torch = _require_torch()
        if len(track) < self.history:
            track = [track[0]] * (self.history - len(track)) + list(track)
        window = track[-self.history:]

        feats = [
            features(s, window[i - 1] if i else None, self.baseline, dt_s)
            for i, s in enumerate(window)
        ]
        self.model.eval()
        with torch.no_grad():
            mu, logvar = self.model(torch.tensor([feats], dtype=torch.float32))
        mu = mu[0].numpy()
        sigma = torch.exp(0.5 * logvar)[0].numpy()

        origin = window[-1]
        out: list[Prediction] = []
        for i, h in enumerate(self.horizons_s):
            scale = self.normalizer.scales[i]
            phys = self.baseline.predict(origin, h)
            lat, lon = apply_residual(
                origin, phys, float(mu[i, 0]) * scale, float(mu[i, 1]) * scale
            )
            out.append(
                Prediction(h, lat, lon, phys.alt_ft, float(sigma[i]) * scale)
            )
        return out

    def uncertainty_model(self, results: list[HorizonResult]):
        """평가 결과의 σ 로 CD&R 이 쓰는 불확실성 모델을 만든다.

        Phase 4 가 기본값 0(결정론)으로 두었던 자리를 학습 결과로 채운다.
        지평에 대한 σ 증가를 원점을 지나는 직선으로 근사한다.
        """
        from .resolution import UncertaintyModel

        num = sum(r.horizon_s * r.sigma_mean_nm for r in results)
        den = sum(r.horizon_s ** 2 for r in results)
        slope = num / den if den else 0.0
        return UncertaintyModel(horizontal_nm_per_s=slope)


def calibrate_sigma(model, samples: list[Sample], normalizer: Normalizer,
                    n_horizons: int) -> list[float]:
    """검증 집합에서 지평별 σ 보정 계수를 구한다.

    이분산 우도로 학습한 σ 는 훈련 분포에 맞춰져 있어 미지의 항적에서는
    대체로 과소평가된다. 표준화 잔차 z = 오차/σ 의 제곱평균이 1 이 되도록
    지평마다 스칼라 배율을 맞춘다.

    **불확실성을 줄이는 보정이 아니라 늘리는 보정**이며, 시험 집합이 아니라
    검증 집합에서만 구한다.
    """
    torch = _require_torch()
    model.eval()
    x = torch.tensor([s.history for s in samples], dtype=torch.float32)
    with torch.no_grad():
        mu, logvar = model(x)
    mu = mu.numpy()
    sigma = torch.exp(0.5 * logvar).numpy()

    out: list[float] = []
    for h in range(n_horizons):
        zs = []
        for i, s in enumerate(samples):
            sg = float(sigma[i, h])
            if sg <= 0:
                continue
            for j in (0, 1):
                zs.append((s.targets[h][j] / normalizer.scales[h] - mu[i, h, j]) / sg)
        rms = math.sqrt(sum(z * z for z in zs) / len(zs)) if zs else 1.0
        out.append(max(rms, 1e-3))
    return out
