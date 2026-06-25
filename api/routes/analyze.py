"""POST /analyze — score a reading, run the agent pipeline, persist, respond.

Runs the full 4-agent LangGraph graph: the detector always runs; the
classifier/assessor/mitigator run only when an anomaly is flagged. Severity
comes from the ImpactAssessor (falling back to a score-ratio bucket).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from agents.graph import run_pipeline, to_agent_report
from api import db
from api.schemas import AnalyzeRequest, AnalyzeResponse
from core.ctmif import quick_severity

router = APIRouter(tags=["analyze"])


def _run_pipeline(raw_features: dict) -> tuple[dict, str | None]:
    """Return (agent_report, severity) from the LangGraph pipeline."""
    state = run_pipeline(raw_features)
    agent_report = to_agent_report(state)
    det = agent_report["detector"]
    if not det["is_anomaly"]:
        return agent_report, None
    severity = (agent_report.get("assessor") or {}).get("severity")
    return agent_report, severity or quick_severity(det["score_ratio"])


@router.post("/analyze", response_model=AnalyzeResponse)
def analyze(req: AnalyzeRequest):
    try:
        agent_report, severity = _run_pipeline(req.raw_features)
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))

    det = agent_report["detector"]
    is_anomaly = det["is_anomaly"]
    score = det["anomaly_score"]

    # Persist: always store the reading; store an anomaly_event only on a hit
    # (keeps the Supabase Realtime feed meaningful instead of flooding it).
    reading = db.insert_reading(req.raw_features, req.timestamp, req.sensor_id)
    event_id, persisted = None, False
    if is_anomaly:
        ev = db.insert_anomaly_event(
            reading_id=reading["id"] if reading else None,
            anomaly_score=score,
            is_anomaly=True,
            severity=severity,
            agent_report=agent_report,
        )
        if ev:
            event_id, persisted = ev["id"], True

    return AnalyzeResponse(
        event_id=event_id,
        is_anomaly=is_anomaly,
        severity=severity,
        anomaly_score=score,
        agent_report=agent_report,
        persisted=persisted,
    )
