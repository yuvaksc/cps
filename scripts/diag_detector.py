"""Diagnostic: offline point-wise detector behavior over the FULL test set,
plus where attacks live. Tells us whether low live-recall is expected
(point-wise vs point-adjust) or a warm-up/streaming bug."""
import numpy as np
import pandas as pd
import joblib

ART = "artifacts"


def normalize(x, lo, hi):
    return (x - lo) / (hi - lo + 1e-9)


def main():
    mA = joblib.load(f"{ART}/model_A.pkl")
    mB = joblib.load(f"{ART}/model_B.pkl")
    mC = joblib.load(f"{ART}/model_C.pkl")
    pca = joblib.load(f"{ART}/pca.pkl")
    meta = joblib.load(f"{ART}/scoring_meta.pkl")
    X_s = np.load(f"{ART}/X_test_sensors.npy")
    X_a = np.load(f"{ART}/X_test_actuators.npy")
    y = np.load(f"{ART}/y_test.npy")

    X_A = X_s
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

    tp = int(((pred == 1) & (y == 1)).sum())
    fp = int(((pred == 1) & (y == 0)).sum())
    fn = int(((pred == 0) & (y == 1)).sum())
    prec = tp/(tp+fp+1e-9); rec = tp/(tp+fn+1e-9)
    print(f"test rows={len(y)} attack_rows={int(y.sum())} ({y.mean()*100:.1f}%)")
    print(f"[point-wise] TP={tp} FP={fp} FN={fn} P={prec:.3f} R={rec:.3f}")
    print(f"total detections={int(pred.sum())}  fused max={fused.max():.3f} thr={thr:.3f}")

    # attack segments + per-segment point-wise detection
    segs = []
    in_s = False
    for i in range(len(y)):
        if y[i] and not in_s:
            in_s = True; s = i
        elif not y[i] and in_s:
            in_s = False; segs.append((s, i))
    if in_s:
        segs.append((s, len(y)))
    det_segs = sum(1 for a, b in segs if pred[a:b].sum() > 0)
    print(f"attack segments={len(segs)}  detected(point-wise, any hit)={det_segs}")
    print(f"first 5 segments (start,end,len,hits): "
          f"{[(a, b, b-a, int(pred[a:b].sum())) for a, b in segs[:5]]}")
    print(f"first attack starts at test row {segs[0][0] if segs else 'NA'}")
    print(f"detections in rows 0..3000 = {int(pred[:3000].sum())}, "
          f"attacks in 0..3000 = {int(y[:3000].sum())}")


if __name__ == "__main__":
    main()
