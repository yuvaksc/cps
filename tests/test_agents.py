"""Tests for the 4-agent pipeline.

Heuristic-path unit tests run anywhere (no Groq key, no models). The full-graph
test needs trained artifacts and is skipped otherwise. With GROQ_API_KEY set,
agents use Groq; without it they fall back to heuristics — both produce a valid
agent_report, which is what these assert.
"""

import json
import os

import pytest

from agents import assessor, classifier, mitigator
from agents.schemas import AssessorOut, ClassifierOut, MitigatorOut

ART = os.getenv("ARTIFACTS_DIR", "artifacts")
SAMPLE = "data/sample_readings.json"
HAS_MODELS = os.path.exists(os.path.join(ART, "model_A.pkl"))

SYNTH_DET = {
    "anomaly_score": 0.9,
    "is_anomaly": True,
    "flagged_views": ["pca_view", "raw_sensors"],
    "view_scores": {"raw_sensors": 0.7, "pca_view": 0.82, "temporal_diff": 0.2},
    "actuator_surprise": 13.8,
    "score_ratio": 1.6,
    "threshold": 0.667,
    "top_sensors": [
        {"sensor": "P201", "scaled": 3.1, "delta": 2.0},
        {"sensor": "FIT201", "scaled": -2.0, "delta": -1.5},
        {"sensor": "LIT301", "scaled": 1.0, "delta": 0.3},
    ],
}


def test_heuristic_classifier_validates():
    out = classifier._heuristic(SYNTH_DET)
    ClassifierOut(**out)  # raises if invalid
    assert out["attack_type"] == "FDI"  # high actuator surprise + PCA view
    assert 0.0 <= out["confidence"] <= 1.0


def test_heuristic_assessor_validates():
    cls = classifier._heuristic(SYNTH_DET)
    out = assessor._heuristic(SYNTH_DET, cls)
    AssessorOut(**out)
    assert out["severity"] in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
    assert out["affected_subsystems"]  # non-empty
    assert any("Stage 2" in s for s in out["affected_subsystems"])


def test_heuristic_mitigator_validates():
    cls = classifier._heuristic(SYNTH_DET)
    asn = assessor._heuristic(SYNTH_DET, cls)
    out = mitigator._heuristic(cls, asn)
    MitigatorOut(**out)
    assert len(out["actions"]) >= 2
    assert out["priority"] in {"LOW", "MEDIUM", "HIGH", "IMMEDIATE"}


@pytest.mark.skipif(not HAS_MODELS, reason="trained artifacts not present")
def test_full_graph_on_stream():
    """Stream the fixture through the graph; the first anomaly must yield a
    complete 4-block agent_report."""
    from agents.graph import run_pipeline, to_agent_report
    from core.ctmif import get_scorer

    get_scorer().reset()
    with open(SAMPLE) as f:
        rows = json.load(f)["rows"]

    anomaly_report = None
    for r in rows:
        state = run_pipeline(r)
        report = to_agent_report(state)
        assert "detector" in report  # detector always runs
        if report["detector"]["is_anomaly"]:
            anomaly_report = report
            break

    assert anomaly_report is not None, "no anomaly detected in fixture"
    assert set(anomaly_report) == {"detector", "classifier", "assessor", "mitigator"}
    ClassifierOut(**anomaly_report["classifier"])
    AssessorOut(**anomaly_report["assessor"])
    MitigatorOut(**anomaly_report["mitigator"])


@pytest.mark.skipif(not HAS_MODELS, reason="trained artifacts not present")
def test_normal_reading_short_circuits():
    """A cold first reading is below threshold -> only the detector runs."""
    from agents.graph import run_pipeline, to_agent_report
    from core.ctmif import get_scorer

    get_scorer().reset()
    with open(SAMPLE) as f:
        first = json.load(f)["rows"][0]
    report = to_agent_report(run_pipeline(first))
    if not report["detector"]["is_anomaly"]:
        assert set(report) == {"detector"}
