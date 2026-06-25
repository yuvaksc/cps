"""
CT-MIF — FINAL (Metrics + Timeline + Grace PA + Boost)
"""

import numpy as np
import pandas as pd
import joblib
import matplotlib.pyplot as plt
from sklearn.metrics import (
    precision_score, recall_score, f1_score,
    classification_report, confusion_matrix
)

ARTIFACTS = "artifacts"


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def segment_metrics(y_true, y_pred):
    segments = []
    in_seg = False

    for i in range(len(y_true)):
        if y_true[i] == 1 and not in_seg:
            in_seg = True
            start = i

        elif y_true[i] == 0 and in_seg:
            end = i
            segments.append((start, end))
            in_seg = False

    detected = 0
    early_detected = 0
    latencies = []
    coverages = []

    for start, end in segments:
        seg_pred = y_pred[start:end]
        seg_len = end - start

        if seg_pred.sum() > 0:
            detected += 1

            first_idx = np.argmax(seg_pred == 1)
            latency = first_idx / seg_len
            latencies.append(latency)

            coverage = seg_pred.sum() / seg_len
            coverages.append(coverage)

            if first_idx <= int(0.3 * seg_len):
                early_detected += 1

    total = len(segments)

    print("\n" + "="*50)
    print("SEGMENT-WISE METRICS")
    print("="*50)

    print(f"Total segments        : {total}")
    print(f"Detected segments     : {detected} ({detected/total:.4f})")
    print(f"Early detected (30%)  : {early_detected} ({early_detected/total:.4f})")

    if latencies:
        print(f"Avg latency           : {np.mean(latencies):.4f}")
    if coverages:
        print(f"Avg coverage          : {np.mean(coverages):.4f}")




def rolling_sum(scores, window):
    return pd.Series(scores).rolling(window=window, min_periods=1).sum().values


def continuity(binary, k):
    s = pd.Series(binary)
    c = (s.rolling(k).sum() == k).astype(int)
    return c.rolling(k, min_periods=1).max().values.astype(int)


def normalize(x, lo, hi):
    return (x - lo) / (hi - lo + 1e-9)


def point_adjust_with_grace(y_true, y_pred):
    """
    Latency-aware point adjustment with three regimes:
    1. Early detection  → full credit
    2. Late detection   → partial credit
    3. No detection     → no credit
    """

    y_pa = y_pred.copy()
    in_seg = False
    start = 0

    for i in range(len(y_true)):

        # ── Start of attack segment ──
        if y_true[i] == 1 and not in_seg:
            in_seg = True
            start = i

        # ── End of attack segment ──
        elif y_true[i] == 0 and in_seg:
            end = i
            seg_len = end - start

            # Grace window (early detection region)
            grace = min(3600, int(0.3 * seg_len))

            early_region = y_pred[start:start + grace]
            full_region  = y_pred[start:end]

            # ─────────────────────────────
            # Case 1: Early detection → FULL credit
            # ─────────────────────────────
            if early_region.sum() > 0:
                y_pa[start:end] = 1

            # ─────────────────────────────
            # Case 2: Late detection → PARTIAL credit
            # ─────────────────────────────
            elif full_region.sum() > 0:
                y_pa[start + grace:end] = 1

            # ─────────────────────────────
            # Case 3: No detection → NO credit
            # ─────────────────────────────
            else:
                pass  # remains 0

            in_seg = False

    return y_pa


# ─────────────────────────────────────────────
# 📊 Timeline Plot
# ─────────────────────────────────────────────
def plot_timeline(sum_scores, fused, y_true, y_pred, threshold):
    x = np.arange(len(sum_scores))

    plt.figure(figsize=(20, 8))

    # Signals
    plt.plot(x, sum_scores, label="Rolling Score", linewidth=1)
    plt.plot(x, fused, label="Fused Score", alpha=0.5)
    plt.tick_params(axis='both', labelsize=15) 

    # Threshold
    plt.axhline(threshold, linestyle="--", label="Threshold")

    # Ground truth
    for i in range(len(x)):
        if y_true[i]:
            plt.axvspan(i, i+1, alpha=0.15)

    # Predictions
    for i in range(len(x)):
        if y_pred[i]:
            plt.axvspan(i, i+1, alpha=0.1, color="green")

    plt.legend()
    plt.title("CT-DIF Timeline (Final)")
    plt.xlabel("Time", fontsize=16)
    plt.ylabel("Score", fontsize=16)

    plt.tight_layout()
    plt.savefig("artifacts/timeline.png", dpi=150)
    plt.show()


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────
def main():

    print("[INFO] Loading artifacts...")

    model_A = joblib.load(f"{ARTIFACTS}/model_A.pkl")
    model_B = joblib.load(f"{ARTIFACTS}/model_B.pkl")
    model_C = joblib.load(f"{ARTIFACTS}/model_C.pkl")   
    pca  = joblib.load(f"{ARTIFACTS}/pca.pkl")
    meta = joblib.load(f"{ARTIFACTS}/scoring_meta.pkl")

    X_s = np.load(f"{ARTIFACTS}/X_test_sensors.npy")
    X_a = np.load(f"{ARTIFACTS}/X_test_actuators.npy")
    y   = np.load(f"{ARTIFACTS}/y_test.npy")

    print(f"[INFO] Test shape: {X_s.shape}")

    # ── Views ─────────────────────────────
    X_A = X_s
    X_B = np.column_stack((pca.transform(X_s), X_a))
    X_C = np.diff(X_A, axis=0, prepend=X_A[:1])

    # ── Scores ────────────────────────────
    raw_A = -model_A.score_samples(X_A)
    raw_B = -model_B.score_samples(X_B)
    raw_C = -model_C.score_samples(X_C)

    norm_A = normalize(raw_A, meta["min_A"], meta["max_A"])
    norm_B = normalize(raw_B, meta["min_B"], meta["max_B"])
    norm_C = normalize(raw_C, meta["min_C"], meta["max_C"])

    fused = (
        0.6 * np.minimum(norm_A, norm_B) +  
        0.3 * np.maximum(norm_A, norm_B)  +  
        0.3 * norm_C                       
    )

    fused += 0.3 * ((norm_A > 0.8) & (norm_B > 0.8))

    fused = fused ** 2

    # ── NEW: Temporal gradient (delta) signal ──
    delta = np.abs(np.diff(fused, prepend=fused[0]))

    # normalize delta
    delta = (delta - delta.min()) / (delta.max() - delta.min() + 1e-9)

    # enhanced signal
    fused = fused + 0.5 * delta



    # ── Smoothing ──
    smoothed = (
        pd.Series(fused)
        .rolling(meta["window"], min_periods=1)
        .mean()
        .values
    )

    threshold = meta["threshold"]
    smooth_pred = (smoothed >= threshold).astype(int)

    density = (
        pd.Series(smooth_pred)
        .rolling(60, center=True, min_periods=1)
        .mean()
        .values
    )

    smooth_pred = smooth_pred * (density > 0.5).astype(int)  # require 50% density in 60s window

    # ── Spike detection (controlled) ──
    spike_threshold = meta['spike_threshold']  
    spike_pred = (fused >= spike_threshold).astype(int)

    spike_pred = spike_pred * (smoothed > (0.6 * threshold))



    # ── Combine both paths ──
    pred = np.maximum(smooth_pred, spike_pred)


    # ──  Confidence margin filtering ──
    margin = fused - threshold

    # normalize 
    margin = (margin - margin.min()) / (margin.max() - margin.min() + 1e-9)

    # keep only confident predictions
    pred = pred * (margin > 0.15)

    baseline = (
        pd.Series(fused)
        .rolling(120, center=True, min_periods=1)
        .mean()
        .values
    )
    baseline = (baseline - baseline.min()) / (baseline.max() - baseline.min() + 1e-9)
    pred = pred * (baseline > 0.1).astype(int)  

    # ──  Stability filter  ──
    local_std = (
        pd.Series(fused)
        .rolling(20, center=True, min_periods=1)
        .std()
        .fillna(0)
        .values
    )

    # normalize
    local_std = (local_std - local_std.min()) / (local_std.max() - local_std.min() + 1e-9)

    # remove unstable spikes
    pred = pred * (local_std < 0.1)


    
    # ── PA with grace ─────────────────────
    pred_pa = point_adjust_with_grace(y, pred)


    # Filter PA predictions with density to remove spikes during periodic cycles
    density = (
        pd.Series(pred_pa)
        .rolling(120, center=True, min_periods=1)
        .mean()
        .values
    )

    plot_pred = pred_pa * (density > 0.8).astype(int)
    
    

    # ─────────────────────────────────────
    # Metrics
    # ─────────────────────────────────────
    p = precision_score(y, pred, zero_division=0)
    r = recall_score(y, pred, zero_division=0)
    f = f1_score(y, pred, zero_division=0)

    pa_p = precision_score(y, pred_pa, zero_division=0)
    pa_r = recall_score(y, pred_pa, zero_division=0)
    pa_f = f1_score(y, pred_pa, zero_division=0)

    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)

    print("\n[Point-wise]")
    print(f"P={p:.4f} R={r:.4f} F1={f:.4f}")

    print("\n[Point-Adjust + Grace]")
    print(f"P={pa_p:.4f} R={pa_r:.4f} F1={pa_f:.4f}")

    print("\n[Classification Report — PA]")
    print(classification_report(y, pred, digits=4))

    cm = confusion_matrix(y, pred)
    cm_pred = confusion_matrix(y, pred_pa)

    print("\n[Confusion Matrix — Point-wise]")
    print(f"TN={cm[0,0]} FP={cm[0,1]} FN={cm[1,0]} TP={cm[1,1]}")

    print("\n[Confusion Matrix — PA]")
    print(f"TN={cm_pred[0,0]} FP={cm_pred[0,1]} FN={cm_pred[1,0]} TP={cm_pred[1,1]}")

    print("\n[Segment-wise Metrics — Point-Wise]")
    segment_metrics(y, pred)
    # Save outputs
    np.save(f"{ARTIFACTS}/predictions.npy", pred)
    np.save(f"{ARTIFACTS}/scores.npy", smoothed)

    print("\n[INFO] Saved predictions & scores")

    # ── Plot timeline ─────────────────────
    print("\n[INFO] Generating timeline...")
    plot_timeline(smoothed, fused, y, plot_pred, threshold)

    print("\n[DONE]")


if __name__ == "__main__":
    main()


