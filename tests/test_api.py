"""API smoke tests via FastAPI TestClient.

/health and /anomalies-without-Supabase run anywhere. /analyze needs trained
artifacts and is skipped if they're missing.
"""

import json
import os

import pytest
from fastapi.testclient import TestClient

from api.main import app

ART = os.getenv("ARTIFACTS_DIR", "artifacts")
SAMPLE = "data/sample_readings.json"
HAS_MODELS = os.path.exists(os.path.join(ART, "model_A.pkl"))

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert set(body) >= {"model_ready", "supabase", "groq"}


def test_anomalies_requires_supabase():
    # With no SUPABASE_* configured, these are inherently DB-backed -> 503.
    from api.config import settings

    if settings.supabase_enabled:
        pytest.skip("Supabase configured; 503 path not applicable")
    assert client.get("/anomalies").status_code == 503


@pytest.mark.skipif(not HAS_MODELS, reason="trained artifacts not present")
def test_analyze_returns_detector_report():
    with open(SAMPLE) as f:
        row = json.load(f)["rows"][0]
    r = client.post("/analyze", json={"raw_features": row, "timestamp": row["Timestamp"]})
    assert r.status_code == 200
    body = r.json()
    assert "detector" in body["agent_report"]
    assert isinstance(body["is_anomaly"], bool)
    assert "anomaly_score" in body
