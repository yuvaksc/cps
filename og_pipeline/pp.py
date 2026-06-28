"""
SWaT Preprocessing — CT-MIF pipeline
Usage:
    python pp.py data/swat_combined.csv
"""

import os
import sys
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
import joblib
import warnings
warnings.filterwarnings("ignore")

SPLIT_DATE = "2015-12-28 00:00:00"
ARTIFACTS  = "artifacts"
os.makedirs(ARTIFACTS, exist_ok=True)

# ── Column definitions ────────────────────────────────────────────────────────
SENSOR_COLS = [
    "FIT101", "LIT101",
    "AIT201", "AIT202", "AIT203", "FIT201",
    "DPIT301", "FIT301", "LIT301",
    "AIT401", "AIT402", "FIT401", "LIT401",
    "AIT501", "AIT502", "AIT503", "AIT504",
    "FIT501", "FIT502", "FIT503", "FIT504",
    "PIT501", "PIT502", "PIT503", "FIT601",
]

ACTUATOR_COLS = [
    "MV101", "P101", "P102",
    "MV201", "P201", "P202", "P203", "P204", "P205", "P206",
    "MV301", "MV302", "MV303", "MV304", "P301", "P302",
    "P401", "P402", "P403", "P404", "UV401",
    "P501", "P502",
    "P601", "P602", "P603",
]


# ─────────────────────────────────────────────────────────────────────────────

def engineer_temporal_features(X: np.ndarray, col_names: list) -> tuple:
    """
    Append per-sensor temporal features to the scaled sensor matrix.
    All operations are causal (forward-only, no future data).

    Added per sensor:
      _deriv — 1st-order difference: spikes when sensor deviates suddenly
      _rstd  — 60-row rolling std:   collapses to 0 under constant spoofing;
               normal cycles have characteristic std signatures
    """
    df = pd.DataFrame(X, columns=col_names)
    new_cols = {}
    for col in col_names:
        s = df[col]
        new_cols[f"{col}_deriv"] = s.diff().fillna(0).values
        new_cols[f"{col}_rstd"]  = s.rolling(60, min_periods=1).std().fillna(0).values

    extra       = np.column_stack(list(new_cols.values()))
    extra_names = list(new_cols.keys())
    return np.hstack([X, extra]), col_names + extra_names


def compute_actuator_scores(df: pd.DataFrame, act_cols: list,
                             ref_freq: dict = None) -> tuple:
    """
    Empirical log-probability of the observed actuator joint state.
    Higher score = rarer combination = more anomalous.
    ref_freq: frozen frequency dict from training (pass None to fit from df).
    Returns (scores_array  shape (n,), freq_dict).
    """
    present = [c for c in act_cols if c in df.columns]
    if not present:
        return np.zeros(len(df)), {}

    cfg = df[present].astype(int).astype(str).agg("_".join, axis=1)
    if ref_freq is None:
        ref_freq = cfg.value_counts(normalize=True).to_dict()

    floor     = 1e-6
    log_probs = cfg.map(ref_freq).fillna(floor).apply(np.log)
    return (-log_probs).values, ref_freq   # higher = more anomalous


# ─────────────────────────────────────────────────────────────────────────────

def main(csv_path: str):
    print(f"[INFO] Loading: {csv_path}")
    df = pd.read_csv(csv_path, parse_dates=["Timestamp"])
    df = df.sort_values("Timestamp").reset_index(drop=True)

    # ── Chronological split ───────────────────────────────────────────────
    split_ts = pd.Timestamp(SPLIT_DATE)
    train_df = df[df["Timestamp"] < split_ts].copy()
    test_df  = df[df["Timestamp"] >= split_ts].copy()

    print(f"[INFO] Train : {len(train_df):,} rows")
    print(f"[INFO] Test  : {len(test_df):,} rows")

    if "label" in train_df.columns:
        assert (train_df["label"] != 0).sum() == 0, "Leakage: attacks in training!"
        print("[CHECK] Zero attack rows in training [OK]")

    # ── Identify columns present in this CSV ──────────────────────────────
    sens_present = [c for c in SENSOR_COLS   if c in df.columns]
    act_present  = [c for c in ACTUATOR_COLS if c in df.columns]
    print(f"[INFO] Sensors   : {len(sens_present)} / {len(SENSOR_COLS)}")
    print(f"[INFO] Actuators : {len(act_present)} / {len(ACTUATOR_COLS)}")

    # ── Scale sensors: fit on training only ───────────────────────────────
    scaler    = StandardScaler()
    X_train_s = scaler.fit_transform(
                    train_df[sens_present].values.astype(np.float64))
    X_test_s  = scaler.transform(
                    test_df[sens_present].values.astype(np.float64))
    print(f"[INFO] Scaler fit on {len(X_train_s):,} training rows")

    # ── Temporal feature engineering ──────────────────────────────────────
    # Computed on each split independently — no cross-contamination.
    # Only causal operations (diff, rolling forward) so no future leakage.
    print("[INFO] Engineering temporal features (deriv + 60-row rolling std) ...")
    X_train_s, aug_names = engineer_temporal_features(X_train_s, sens_present)
    X_test_s,  _         = engineer_temporal_features(X_test_s,  sens_present)
    n_raw = len(sens_present)
    print(f"[INFO] Features: {len(aug_names)}  "
          f"({n_raw} raw + {len(aug_names) - n_raw} temporal)")

    # ── Actuator causal scores (frozen to training distribution) ──────────
    train_act, act_freq = compute_actuator_scores(train_df, act_present)
    test_act,  _        = compute_actuator_scores(test_df,  act_present,
                                                   ref_freq=act_freq)

    train_act = train_act.reshape(-1, 1)
    test_act  = test_act.reshape(-1, 1)

    # ── Labels ────────────────────────────────────────────────────────────
    y_train = np.zeros(len(train_df), dtype=int)
    y_test  = (test_df["label"].values != 0).astype(int) \
              if "label" in test_df.columns \
              else np.zeros(len(test_df), dtype=int)
    print(f"[INFO] Attack rows in test: {y_test.sum():,} "
          f"({y_test.mean()*100:.2f}%)")

    # ── Save ──────────────────────────────────────────────────────────────
    np.save(f"{ARTIFACTS}/X_train_sensors.npy",   X_train_s)
    np.save(f"{ARTIFACTS}/X_train_actuators.npy", train_act)
    np.save(f"{ARTIFACTS}/X_test_sensors.npy",    X_test_s)
    np.save(f"{ARTIFACTS}/X_test_actuators.npy",  test_act)
    np.save(f"{ARTIFACTS}/y_train.npy",            y_train)
    np.save(f"{ARTIFACTS}/y_test.npy",             y_test)

    # ── Persist transformers for ONLINE inference ─────────────────────────
    # The scripts above only need the .npy arrays, but the production API has
    # to transform raw SWaT rows on the fly. Dump the fitted scaler, the frozen
    # actuator-frequency table, and the column layout so core/ctmif.py can
    # reproduce the exact training-time feature pipeline one row at a time.
    joblib.dump(scaler,   f"{ARTIFACTS}/scaler.pkl")
    joblib.dump(act_freq, f"{ARTIFACTS}/actuator_freq.pkl")
    joblib.dump(
        {
            "sensors":   sens_present,   # raw sensor column order
            "actuators": act_present,    # raw actuator column order
            "aug_names": aug_names,      # raw + _deriv + _rstd (View A layout)
            "n_raw":     n_raw,          # number of raw sensors
            "rstd_window": 60,           # rolling-std window used above
        },
        f"{ARTIFACTS}/columns.pkl",
    )

    print(f"\n[DONE] Saved to '{ARTIFACTS}/'")
    print(f"  X_train_sensors  : {X_train_s.shape}")
    print(f"  X_train_actuators: {train_act.shape}")
    print(f"  X_test_sensors   : {X_test_s.shape}")
    print(f"  X_test_actuators : {test_act.shape}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python preprocess.py <path_to_csv>")
        sys.exit(1)
    main(sys.argv[1])


























