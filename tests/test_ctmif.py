"""Tests for the online CT-MIF scorer.

These are integration tests: they need the trained artifacts/ and the sample
fixture. They skip cleanly (not fail) when those aren't present, so CI without
models stays green while local runs get full coverage.
"""

import json
import os

import pytest

ART = os.getenv("ARTIFACTS_DIR", "artifacts")
SAMPLE = "data/sample_readings.json"

pytestmark = pytest.mark.skipif(
    not os.path.exists(os.path.join(ART, "model_A.pkl")),
    reason="trained artifacts not present (run pp.py + train.py)",
)


@pytest.fixture(scope="module")
def scorer():
    from core.ctmif import CTMIFScorer

    return CTMIFScorer(ART)


@pytest.fixture(scope="module")
def sample():
    if not os.path.exists(SAMPLE):
        pytest.skip("sample fixture missing (run scripts/extract_sample.py)")
    with open(SAMPLE) as f:
        return json.load(f)


def test_single_reading_shape(scorer, sample):
    scorer.reset()
    out = scorer.score(sample["rows"][0])
    assert set(out) >= {"anomaly_score", "is_anomaly", "flagged_views"}
    assert isinstance(out["is_anomaly"], bool)
    assert 0.0 <= out["anomaly_score"]
    assert isinstance(out["flagged_views"], list)


def test_stream_detects_known_attack(scorer, sample):
    """Streaming the fixture must catch the (well-detected) attack segment."""
    scorer.reset()
    rows = sample["rows"]
    tp = fn = 0
    for r in rows:
        pred = scorer.score(r)["is_anomaly"]
        truth = r["label"] != 0
        if truth and pred:
            tp += 1
        elif truth and not pred:
            fn += 1
    recall = tp / max(tp + fn, 1)
    assert recall > 0.8, f"attack recall too low: {recall:.3f}"


def test_reset_clears_state(scorer, sample):
    scorer.reset()
    a = scorer.score(sample["rows"][0])
    scorer.reset()
    b = scorer.score(sample["rows"][0])
    assert a == b  # identical first-reading output after reset
