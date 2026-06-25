"""
CT-MIF
"""

import os
import numpy as np
import pandas as pd
import joblib
from sklearn.ensemble import IsolationForest
from sklearn.decomposition import PCA
import warnings
warnings.filterwarnings("ignore")

ARTIFACTS_DIR = "artifacts"
os.makedirs(ARTIFACTS_DIR, exist_ok=True)

WINDOW_S        = 5
TIME_AWARE_SEC  = 8
VAL_SPLIT       = 0.20
IF_N_EST        = 300
PCA_VAR         = 0.95


def normalize(x, lo, hi):
    return (x - lo) / (hi - lo + 1e-9)


def main():
    print("[INFO] Loading data...")

    X_s = np.load(f"{ARTIFACTS_DIR}/X_train_sensors.npy")
    X_a = np.load(f"{ARTIFACTS_DIR}/X_train_actuators.npy")

    df = pd.DataFrame(X_s)

    split = int(len(df) * (1 - VAL_SPLIT))
    df_fit, df_val = df.iloc[:split], df.iloc[split:]
    X_fit_a, X_val_a = X_a[:split], X_a[split:]

    # ─────────────────────────────
    # PCA
    # ─────────────────────────────
    pca = PCA(n_components=PCA_VAR, random_state=42)
    X_fit_pca = pca.fit_transform(df_fit.values)
    X_val_pca = pca.transform(df_val.values)
    joblib.dump(pca, f"{ARTIFACTS_DIR}/pca.pkl")

    # ─────────────────────────────
    # Views
    # ─────────────────────────────
    # View A (raw sensors)
    X_fit_A = df_fit.values
    X_val_A = df_val.values

    # View B (PCA + actuators)
    X_fit_B = np.column_stack((X_fit_pca, X_fit_a))
    X_val_B = np.column_stack((X_val_pca, X_val_a))

    # View C (temporal differences)
    X_fit_C = np.diff(X_fit_A, axis=0, prepend=X_fit_A[:1])
    X_val_C = np.diff(X_val_A, axis=0, prepend=X_val_A[:1])

    # ─────────────────────────────
    # Models
    # ─────────────────────────────
    print("[MODEL A] Training IF...")
    model_A = IsolationForest(n_estimators=IF_N_EST, random_state=42)
    model_A.fit(X_fit_A)

    print("[MODEL B] Training IF...")
    model_B = IsolationForest(n_estimators=IF_N_EST, random_state=42)
    model_B.fit(X_fit_B)

    print("[MODEL C] Training IF (temporal)...")
    model_C = IsolationForest(n_estimators=IF_N_EST, random_state=42)
    model_C.fit(X_fit_C)

    # ─────────────────────────────
    # Validation scores
    # ─────────────────────────────
    raw_A = -model_A.score_samples(X_val_A)
    raw_B = -model_B.score_samples(X_val_B)
    raw_C = -model_C.score_samples(X_val_C)

    min_A, max_A = raw_A.min(), raw_A.max()
    min_B, max_B = raw_B.min(), raw_B.max()
    min_C, max_C = raw_C.min(), raw_C.max()

    norm_A = normalize(raw_A, min_A, max_A)
    norm_B = normalize(raw_B, min_B, max_B)
    norm_C = normalize(raw_C, min_C, max_C)

    # ─────────────────────────────
    # FUSION (3-view)
    # ─────────────────────────────
    fused = (
        0.6 * np.minimum(norm_A, norm_B) +   # agreement
        0.3 * np.maximum(norm_A, norm_B) +   # sensitivity
        0.3 * norm_C                        # temporal anomalies
    )

    # boost when A & B agree strongly
    fused += 0.3 * ((norm_A > 0.8) & (norm_B > 0.8))

    fused = fused ** 2 # amplify high scores

    # ─────────────────────────────
    # Smoothing
    # ─────────────────────────────
    smoothed = pd.Series(fused).rolling(window=WINDOW_S, min_periods=1).mean().values

    # ─────────────────────────────
    # Thresholds (VAL ONLY)
    # ─────────────────────────────
    main_threshold  = float(np.percentile(smoothed, 99.9))
    spike_threshold = np.percentile(fused, 91)

    print(f"[MAIN THRESHOLD]  {main_threshold:.6f}")
    print(f"[SPIKE THRESHOLD] {spike_threshold:.6f}")

    # ─────────────────────────────
    # Save everything
    # ─────────────────────────────
    joblib.dump(model_A, f"{ARTIFACTS_DIR}/model_A.pkl")
    joblib.dump(model_B, f"{ARTIFACTS_DIR}/model_B.pkl")
    joblib.dump(model_C, f"{ARTIFACTS_DIR}/model_C.pkl")   

    joblib.dump({
        "min_A": min_A, "max_A": max_A,
        "min_B": min_B, "max_B": max_B,
        "min_C": min_C, "max_C": max_C,  
        "threshold": main_threshold,
        "spike_threshold": spike_threshold,
        "window": WINDOW_S,
        "time_sec": TIME_AWARE_SEC
    }, f"{ARTIFACTS_DIR}/scoring_meta.pkl")

    print("[DONE]")


if __name__ == "__main__":
    main()

