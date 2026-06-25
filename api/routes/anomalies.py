"""GET /anomalies and GET /anomalies/{id} — read persisted anomaly events."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from api import db
from api.config import settings

router = APIRouter(tags=["anomalies"])


def _require_db() -> None:
    if not settings.supabase_enabled:
        raise HTTPException(
            status_code=503,
            detail="Supabase not configured (set SUPABASE_URL / SUPABASE_KEY).",
        )


@router.get("/anomalies")
def list_anomalies(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    severity: str | None = Query(None, description="LOW / MEDIUM / HIGH / CRITICAL"),
):
    _require_db()
    items = db.list_anomaly_events(limit=limit, offset=offset, severity=severity)
    return {"count": len(items), "limit": limit, "offset": offset, "items": items}


@router.get("/anomalies/{event_id}")
def get_anomaly(event_id: str):
    _require_db()
    ev = db.get_anomaly_event(event_id)
    if not ev:
        raise HTTPException(status_code=404, detail="Anomaly event not found")
    return ev
