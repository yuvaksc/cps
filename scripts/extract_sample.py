"""
Extract a small, self-contained slice of real SWaT readings for tests, replay
smoke-checks, and demo seeding — so none of those need the full 290 MB CSV.

Picks the attack segment the point-wise detector handles BEST (highest hit
coverage) and wraps it with warm-up context, so streaming the fixture visibly
fires the pipeline (normal -> detected attack -> recovery).

Output: data/sample_readings.json
Run:    python scripts/extract_sample.py
"""

import json
import os

import joblib
import numpy as np
import pandas as pd

CSV = "data/swat_combined.csv"
ART = "artifacts"
SPLIT = "2015-12-28 00:00:00"
OUT = "data/sample_readings.json"
PRE, POST = 300, 150  # warm-up rows before onset / rows after segment end


def normalize(x, lo, hi):
    return (x - lo) / (hi - lo + 1e-9)


def offline_pred():
    mA = joblib.load(f"{ART}/model_A.pkl")
    mB = joblib.load(f"{ART}/model_B.pkl")
    mC = joblib.load(f"{ART}/model_C.pkl")
    pca = joblib.load(f"{ART}/pca.pkl")
    meta = joblib.load(f"{ART}/scoring_meta.pkl")
    X_A = np.load(f"{ART}/X_test_sensors.npy")
    X_a = np.load(f"{ART}/X_test_actuators.npy")
    y = np.load(f"{ART}/y_test.npy")
    X_B = np.column_stack((pca.transform(X_A), X_a))
    X_C = np.diff(X_A, axis=0, prepend=X_A[:1])
    nA = normalize(-mA.score_samples(X_A), meta["min_A"], meta["max_A"])
    nB = normalize(-mB.score_samples(X_B), meta["min_B"], meta["max_B"])
    nC = normalize(-mC.score_samples(X_C), meta["min_C"], meta["max_C"])
    fused = 0.6*np.minimum(nA, nB) + 0.3*np.maximum(nA, nB) + 0.3*nC
    fused += 0.3*((nA > 0.8) & (nB > 0.8))
    fused = fused**2
    sm = pd.Series(fused).rolling(meta["window"], min_periods=1).mean().values
    thr, sthr = meta["threshold"], meta["spike_threshold"]
    pred = ((sm >= thr) | ((fused >= sthr) & (sm > 0.6*thr))).astype(int)
    return pred, y


def best_segment(pred, y):
    segs, in_s, s = [], False, 0
    for i in range(len(y)):
        if y[i] and not in_s:
            in_s, s = True, i
        elif not y[i] and in_s:
            in_s = False
            segs.append((s, i))
    if in_s:
        segs.append((s, len(y)))
    # rank by hit coverage, require a usable length
    scored = [
        (a, b, pred[a:b].sum() / (b - a))
        for a, b in segs if (b - a) >= 150 and pred[a:b].sum() >= 20
    ]
    scored.sort(key=lambda t: t[2], reverse=True)
    return scored[0]  # (start, end, coverage)


def main():
    print("[sample] computing offline detections to pick best attack segment ...")
    pred, y = offline_pred()
    a, b, cov = best_segment(pred, y)
    print(f"[sample] chosen segment: rows {a}..{b} (len {b-a}, coverage {cov:.2f})")

    print("[sample] reading CSV (one pass) ...")
    df = pd.read_csv(CSV, parse_dates=["Timestamp"])
    df = df.sort_values("Timestamp").reset_index(drop=True)
    test = df[df["Timestamp"] >= pd.Timestamp(SPLIT)].reset_index(drop=True)

    start = max(0, a - PRE)
    end = min(len(test), b + POST)
    window = test.iloc[start:end].copy()
    window["Timestamp"] = window["Timestamp"].astype(str)
    rows = window.to_dict(orient="records")

    payload = {
        "meta": {
            "source": "SWaT swat_combined.csv (test split)",
            "test_rows": [int(start), int(end)],
            "attack_onset_in_window": int(a - start),
            "attack_end_in_window": int(b - start),
            "n_rows": len(rows),
            "n_attack_rows": int((window["label"].values != 0).sum()),
            "offline_segment_coverage": round(float(cov), 3),
        },
        "rows": rows,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(payload, f)
    print(f"[sample] wrote {len(rows)} rows -> {OUT}")
    print(f"[sample] meta: {payload['meta']}")


if __name__ == "__main__":
    main()
