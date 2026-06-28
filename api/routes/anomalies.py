"""GET /anomalies and GET /anomalies/{id} — read persisted anomaly events.

Backed by the local SQLite store (api/database.py). Powers the Streamlit
"Anomaly History" panel.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from api import database

router = APIRouter(tags=["anomalies"])


@router.get("/anomalies")
def list_anomalies(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    severity: str | None = Query(None, description="LOW / MEDIUM / HIGH / CRITICAL"),
):
    items = database.list_anomaly_events(limit=limit, offset=offset, severity=severity)
    return {"count": len(items), "limit": limit, "offset": offset, "items": items}


@router.get("/anomalies/{event_id}")
def get_anomaly(event_id: int):
    ev = database.get_anomaly_event(event_id)
    if not ev:
        raise HTTPException(status_code=404, detail="Anomaly event not found")
    return ev
