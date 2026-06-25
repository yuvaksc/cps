"""
Supabase data-access layer.

Designed to degrade gracefully: when SUPABASE_URL/KEY are absent the client is
None and every write becomes a no-op (returns None) while reads raise a clear
503 upstream. This lets the scorer, agents, and replay engine be developed and
tested with zero database configuration.
"""

from __future__ import annotations

import datetime as dt
from functools import lru_cache
from typing import Any

from api.config import settings

try:  # supabase is optional at import time
    from supabase import Client, create_client
except Exception:  # pragma: no cover
    Client = Any  # type: ignore
    create_client = None  # type: ignore


@lru_cache(maxsize=1)
def get_client():
    """Return a cached Supabase client, or None if not configured."""
    if not settings.supabase_enabled or create_client is None:
        return None
    return create_client(settings.supabase_url, settings.supabase_key)


# Cache the synthetic "whole SWaT system" sensor id (one reading == full vector).
_default_sensor_id: str | None = None


def ensure_default_sensor() -> str | None:
    """Get (or create) the default system sensor row; cache its id."""
    global _default_sensor_id
    if _default_sensor_id:
        return _default_sensor_id
    client = get_client()
    if client is None:
        return None
    try:
        res = (
            client.table("sensors")
            .select("id")
            .eq("name", "SWaT-System")
            .limit(1)
            .execute()
        )
        if res.data:
            _default_sensor_id = res.data[0]["id"]
        else:
            ins = (
                client.table("sensors")
                .insert(
                    {
                        "name": "SWaT-System",
                        "system_id": "SWaT",
                        "sensor_type": "system",
                    }
                )
                .execute()
            )
            _default_sensor_id = ins.data[0]["id"] if ins.data else None
    except Exception as e:  # pragma: no cover
        print(f"[db] ensure_default_sensor failed: {e}")
    return _default_sensor_id


def insert_reading(
    raw_features: dict[str, Any],
    timestamp: str | None = None,
    sensor_id: str | None = None,
) -> dict | None:
    """Insert a row into `readings`. Returns the inserted row (with id) or None."""
    client = get_client()
    if client is None:
        return None
    ts = timestamp or dt.datetime.now(dt.timezone.utc).isoformat()
    payload = {
        "sensor_id": sensor_id or ensure_default_sensor(),
        "timestamp": ts,
        "raw_features": raw_features,
    }
    try:
        res = client.table("readings").insert(payload).execute()
        return res.data[0] if res.data else None
    except Exception as e:  # pragma: no cover
        print(f"[db] insert_reading failed: {e}")
        return None


def insert_anomaly_event(
    reading_id: str | None,
    anomaly_score: float,
    is_anomaly: bool,
    severity: str | None,
    agent_report: dict[str, Any],
) -> dict | None:
    """Insert into `anomaly_events` (triggers Supabase Realtime). Returns row/None."""
    client = get_client()
    if client is None:
        return None
    payload = {
        "reading_id": reading_id,
        "anomaly_score": anomaly_score,
        "is_anomaly": is_anomaly,
        "severity": severity,
        "agent_report": agent_report,
    }
    try:
        res = client.table("anomaly_events").insert(payload).execute()
        return res.data[0] if res.data else None
    except Exception as e:  # pragma: no cover
        print(f"[db] insert_anomaly_event failed: {e}")
        return None


def list_anomaly_events(
    limit: int = 50, offset: int = 0, severity: str | None = None
) -> list[dict]:
    """Paginated anomaly events, newest first; optional severity filter."""
    client = get_client()
    if client is None:
        return []
    try:
        q = client.table("anomaly_events").select("*")
        if severity:
            q = q.eq("severity", severity.upper())
        res = (
            q.order("created_at", desc=True)
            .range(offset, offset + max(limit, 1) - 1)
            .execute()
        )
        return res.data or []
    except Exception as e:  # pragma: no cover
        print(f"[db] list_anomaly_events failed: {e}")
        return []


def get_anomaly_event(event_id: str) -> dict | None:
    """Fetch a single anomaly event (full agent_report) by id."""
    client = get_client()
    if client is None:
        return None
    try:
        res = (
            client.table("anomaly_events")
            .select("*")
            .eq("id", event_id)
            .limit(1)
            .execute()
        )
        return res.data[0] if res.data else None
    except Exception as e:  # pragma: no cover
        print(f"[db] get_anomaly_event failed: {e}")
        return None
