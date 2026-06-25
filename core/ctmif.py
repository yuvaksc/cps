"""
core/ctmif.py — Online inference wrapper for the CT-MIF detector.

The training scripts (pp.py / train.py / test.py) operate on the *whole* test
set at once: temporal features, fusion, smoothing and thresholds are all vector
ops over the full array. A production API instead receives readings **one at a
time**, so this module reproduces the exact training-time pipeline *causally*
using rolling buffers — no future data, no global re-normalization.

What it reproduces, per reading, faithful to pp.py + train.py + test.py:
  1. Scale raw sensors with the frozen StandardScaler.
  2. Temporal features per sensor: `_deriv` (1-step diff) + `_rstd` (trailing
     60-row rolling std)  ->  View A (75-dim, same column order as training).
  3. Actuator joint-state surprise: -log P(config) from the frozen freq table.
  4. View B = PCA(View A) ++ actuator_score ;  View C = View A - prev(View A).
  5. Three Isolation Forests -> raw scores -> min/max normalize (frozen stats).
  6. Multi-view fusion + agreement boost + square amplification.
  7. Rolling-mean smoothing (window from training meta).
  8. Decision = (smoothed >= threshold) OR controlled spike.

The non-causal post-filters in test.py (centered density/baseline/stability
windows, point-adjust-with-grace) exist only to maximize offline F1 — they need
future context and are intentionally omitted from the live detector.
"""

from __future__ import annotations

import math
import os
from collections import deque
from typing import Any

import joblib
import numpy as np
import pandas as pd

# View labels exposed to the agent layer (detector "flagged_views").
VIEW_RAW = "raw_sensors"      # View A — raw + temporal sensor features
VIEW_PCA = "pca_view"         # View B — PCA components + actuator surprise
VIEW_TEMPORAL = "temporal_diff"  # View C — step-over-step change in View A

# A view is "flagged" when its normalized score clears this bar.
_FLAG_CUTOFF = 0.6
# Agreement-boost / strong-view threshold (matches train.py / test.py: > 0.8).
_STRONG = 0.8


def quick_severity(score_ratio: float) -> str:
    """Cheap severity bucket from smoothed/threshold ratio.

    Placeholder used when the LLM ImpactAssessor agent is not in the loop
    (e.g. Phase-1 /analyze, or replay fast-forward). The assessor overrides
    this with a reasoned severity once the agent pipeline runs.
    """
    if score_ratio >= 3.0:
        return "CRITICAL"
    if score_ratio >= 2.0:
        return "HIGH"
    if score_ratio >= 1.0:
        return "MEDIUM"
    return "LOW"


class CTMIFScorer:
    """Stateful, causal CT-MIF scorer. One instance per ordered stream.

    Call :meth:`reset` at the start of a replay session to clear temporal
    state. :meth:`score` consumes a single raw SWaT row (dict keyed by sensor /
    actuator column name) and returns a detector-shaped result dict.
    """

    def __init__(self, artifacts_dir: str | None = None):
        artifacts_dir = artifacts_dir or os.getenv("ARTIFACTS_DIR", "artifacts")
        self.artifacts_dir = artifacts_dir

        def _load(name: str):
            path = os.path.join(artifacts_dir, name)
            if not os.path.exists(path):
                raise FileNotFoundError(
                    f"Missing artifact '{path}'. Run pp.py then train.py first."
                )
            return joblib.load(path)

        self.model_A = _load("model_A.pkl")
        self.model_B = _load("model_B.pkl")
        self.model_C = _load("model_C.pkl")
        self.pca = _load("pca.pkl")
        self.scaler = _load("scaler.pkl")
        self.actuator_freq: dict[str, float] = _load("actuator_freq.pkl")
        cols = _load("columns.pkl")
        self.meta = _load("scoring_meta.pkl")

        self.sensor_cols: list[str] = cols["sensors"]
        self.actuator_cols: list[str] = cols["actuators"]
        self.n_raw: int = cols["n_raw"]
        self.rstd_window: int = cols.get("rstd_window", 60)

        self.threshold: float = float(self.meta["threshold"])
        self.spike_threshold: float = float(self.meta["spike_threshold"])
        self.smooth_window: int = int(self.meta["window"])

        # Frozen Isolation-Forest score normalization ranges (from validation).
        self._minmax = {
            "A": (self.meta["min_A"], self.meta["max_A"]),
            "B": (self.meta["min_B"], self.meta["max_B"]),
            "C": (self.meta["min_C"], self.meta["max_C"]),
        }

        self.reset()

    # ── streaming state ────────────────────────────────────────────────
    def reset(self) -> None:
        """Clear all temporal buffers — call between replay sessions."""
        self._scaled_buf: deque[np.ndarray] = deque(maxlen=self.rstd_window)
        self._prev_view_a: np.ndarray | None = None
        self._fused_buf: deque[float] = deque(maxlen=self.smooth_window)
        self._n_seen = 0

    @property
    def n_seen(self) -> int:
        return self._n_seen

    # ── helpers ────────────────────────────────────────────────────────
    @staticmethod
    def _norm(raw: float, lo: float, hi: float) -> float:
        return (raw - lo) / (hi - lo + 1e-9)

    def _extract(self, row: dict[str, Any], cols: list[str]) -> np.ndarray:
        out = np.empty(len(cols), dtype=np.float64)
        for i, c in enumerate(cols):
            v = row.get(c, 0.0)
            try:
                out[i] = float(v)
            except (TypeError, ValueError):
                out[i] = 0.0
        return out

    def _actuator_score(self, row: dict[str, Any]) -> float:
        """-log P(joint actuator config), frozen to the training distribution.

        Mirrors pp.compute_actuator_scores: int-cast each actuator, join with
        '_', look up empirical frequency, floor unseen configs at 1e-6.
        """
        parts = []
        for c in self.actuator_cols:
            v = row.get(c, 0)
            try:
                parts.append(str(int(float(v))))
            except (TypeError, ValueError):
                parts.append("0")
        cfg = "_".join(parts)
        p = self.actuator_freq.get(cfg, 1e-6)
        return float(-math.log(p))

    # ── main entry point ───────────────────────────────────────────────
    def score(self, row: dict[str, Any]) -> dict[str, Any]:
        """Score one raw reading. Returns the detector result dict."""
        # 1) scale raw sensors -----------------------------------------------
        raw_sensors = self._extract(row, self.sensor_cols).reshape(1, -1)
        scaled = self.scaler.transform(raw_sensors)[0]

        # 2) temporal features (causal): deriv before append, rstd after ------
        prev_scaled = self._scaled_buf[-1] if self._scaled_buf else None
        deriv = (scaled - prev_scaled) if prev_scaled is not None \
            else np.zeros_like(scaled)
        self._scaled_buf.append(scaled)
        window = np.asarray(self._scaled_buf)
        rstd = window.std(axis=0, ddof=1) if len(window) > 1 \
            else np.zeros_like(scaled)

        # View A column order == aug_names: [raw..., (deriv_i, rstd_i) per sensor]
        extras = np.empty(2 * self.n_raw, dtype=np.float64)
        extras[0::2] = deriv
        extras[1::2] = rstd
        view_a = np.concatenate([scaled, extras])

        # 3) actuator surprise ------------------------------------------------
        act_score = self._actuator_score(row)

        # 4) View B (PCA ++ actuator) and View C (temporal diff of View A) ----
        pca_out = self.pca.transform(view_a.reshape(1, -1))[0]
        view_b = np.concatenate([pca_out, [act_score]])
        view_c = view_a - self._prev_view_a if self._prev_view_a is not None \
            else np.zeros_like(view_a)
        self._prev_view_a = view_a

        # 5) Isolation-Forest scores -> normalize -----------------------------
        raw_A = -self.model_A.score_samples(view_a.reshape(1, -1))[0]
        raw_B = -self.model_B.score_samples(view_b.reshape(1, -1))[0]
        raw_C = -self.model_C.score_samples(view_c.reshape(1, -1))[0]

        nA = self._norm(raw_A, *self._minmax["A"])
        nB = self._norm(raw_B, *self._minmax["B"])
        nC = self._norm(raw_C, *self._minmax["C"])

        # 6) fusion (identical weights to train.py / test.py) -----------------
        fused = 0.6 * min(nA, nB) + 0.3 * max(nA, nB) + 0.3 * nC
        if nA > _STRONG and nB > _STRONG:
            fused += 0.3
        fused = fused ** 2

        # 7) rolling-mean smoothing ------------------------------------------
        self._fused_buf.append(fused)
        smoothed = float(np.mean(self._fused_buf))

        # 8) decision: threshold OR controlled spike --------------------------
        smooth_hit = smoothed >= self.threshold
        spike_hit = (fused >= self.spike_threshold) and \
                    (smoothed > 0.6 * self.threshold)
        is_anomaly = bool(smooth_hit or spike_hit)

        self._n_seen += 1

        # view attribution for the detector agent -----------------------------
        view_norms = {VIEW_RAW: nA, VIEW_PCA: nB, VIEW_TEMPORAL: nC}
        flagged = [v for v, s in view_norms.items() if s >= _FLAG_CUTOFF]
        if is_anomaly and not flagged:
            flagged = [max(view_norms, key=view_norms.get)]

        # Most-deviant sensors by absolute step-change — concrete attribution
        # for the classifier/assessor agents and the dashboard.
        dev_idx = np.argsort(-np.abs(deriv))[:3]
        top_sensors = [
            {
                "sensor": self.sensor_cols[j],
                "scaled": round(float(scaled[j]), 3),
                "delta": round(float(deriv[j]), 3),
            }
            for j in dev_idx
        ]

        score_ratio = smoothed / (self.threshold + 1e-12)

        return {
            "anomaly_score": round(smoothed, 6),
            "is_anomaly": is_anomaly,
            "flagged_views": flagged,
            # ── extra context for downstream agents / UI ──
            "fused_score": round(float(fused), 6),
            "score_ratio": round(float(score_ratio), 4),
            "threshold": round(self.threshold, 6),
            "view_scores": {
                VIEW_RAW: round(float(nA), 4),
                VIEW_PCA: round(float(nB), 4),
                VIEW_TEMPORAL: round(float(nC), 4),
            },
            "actuator_surprise": round(act_score, 4),
            "top_sensors": top_sensors,
            "trigger": "spike" if (spike_hit and not smooth_hit)
            else ("threshold" if smooth_hit else "none"),
        }

    # ── batch prediction (offline analysis, e.g. "which attacks fire") ──
    def _actuator_scores_batch(self, df: pd.DataFrame) -> np.ndarray:
        """Vectorized -log P(actuator config) for all rows (mirrors the
        per-row _actuator_score / pp.compute_actuator_scores)."""
        present = [c for c in self.actuator_cols if c in df.columns]
        if not present:
            return np.zeros(len(df))
        sub = df[present].apply(pd.to_numeric, errors="coerce").fillna(0)
        cfg = sub.astype(int).astype(str).agg("_".join, axis=1)
        probs = cfg.map(self.actuator_freq).fillna(1e-6)
        return -np.log(probs.values)

    def predict_dataframe(self, df: pd.DataFrame) -> np.ndarray:
        """Vectorized is_anomaly for every row at once — same fused -> smooth ->
        threshold/spike decision as score(), batched. Lets callers ask which
        attack segments the detector actually fires on without streaming."""
        n = len(df)
        if n == 0:
            return np.zeros(0, dtype=bool)

        raw = np.column_stack([
            pd.to_numeric(df[c], errors="coerce").fillna(0.0).to_numpy()
            if c in df.columns else np.zeros(n)
            for c in self.sensor_cols
        ])
        scaled = self.scaler.transform(raw)

        deriv = np.diff(scaled, axis=0, prepend=scaled[:1])
        rstd = (pd.DataFrame(scaled)
                .rolling(self.rstd_window, min_periods=1).std(ddof=1)
                .fillna(0.0).to_numpy())
        extras = np.empty((n, 2 * self.n_raw))
        extras[:, 0::2] = deriv
        extras[:, 1::2] = rstd
        view_a = np.hstack([scaled, extras])

        act = self._actuator_scores_batch(df)
        view_b = np.column_stack([self.pca.transform(view_a), act])
        view_c = np.diff(view_a, axis=0, prepend=view_a[:1])

        nA = self._norm(-self.model_A.score_samples(view_a), *self._minmax["A"])
        nB = self._norm(-self.model_B.score_samples(view_b), *self._minmax["B"])
        nC = self._norm(-self.model_C.score_samples(view_c), *self._minmax["C"])

        fused = 0.6 * np.minimum(nA, nB) + 0.3 * np.maximum(nA, nB) + 0.3 * nC
        fused += 0.3 * ((nA > _STRONG) & (nB > _STRONG))
        fused = fused ** 2
        smoothed = (pd.Series(fused)
                    .rolling(self.smooth_window, min_periods=1).mean().to_numpy())

        smooth_hit = smoothed >= self.threshold
        spike_hit = (fused >= self.spike_threshold) & (smoothed > 0.6 * self.threshold)
        return smooth_hit | spike_hit


# Lazily-instantiated process-wide singleton (one ordered stream per process).
_scorer: CTMIFScorer | None = None


def get_scorer() -> CTMIFScorer:
    global _scorer
    if _scorer is None:
        _scorer = CTMIFScorer()
    return _scorer
