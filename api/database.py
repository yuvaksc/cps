"""
Local SQLite persistence via SQLAlchemy ORM.

The whole anomaly-detection demo runs on a single node, so the heavyweight
Supabase/Postgres + Realtime stack was replaced by an embedded SQLite file and
a single `AnomalyEvent` table. The LangGraph pipeline writes one row per
*confirmed* anomaly (after the MitigationAdvisor produces its report); the
Streamlit "Anomaly History" panel reads them back through GET /anomalies.

Everything degrades gracefully: a write failure is logged and swallowed so a DB
hiccup never takes down the live sensor stream.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    Integer,
    String,
    create_engine,
    desc,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from api.config import settings

# SQLite needs check_same_thread=False because the replay engine persists from a
# worker thread (run_in_executor) while FastAPI reads on the event-loop thread.
engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False}
    if settings.database_url.startswith("sqlite")
    else {},
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class AnomalyEvent(Base):
    """One confirmed anomaly: the detector verdict plus the full 4-agent report."""

    __tablename__ = "anomaly_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime, default=lambda: dt.datetime.now(dt.timezone.utc), index=True
    )
    # Replay row index the event fired on (handy for jumping back to it).
    idx: Mapped[int | None] = mapped_column(Integer, nullable=True)
    anomaly_score: Mapped[float] = mapped_column(Float, nullable=False)
    is_anomaly: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    severity: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    # Denormalized from agent_report["classifier"] so the feed can show it cheaply.
    attack_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    raw_features: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    agent_report: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "idx": self.idx,
            "anomaly_score": self.anomaly_score,
            "is_anomaly": self.is_anomaly,
            "severity": self.severity,
            "attack_type": self.attack_type,
            "raw_features": self.raw_features,
            "agent_report": self.agent_report,
        }


def init_db() -> None:
    """Create tables if they don't exist (idempotent; called at startup)."""
    Base.metadata.create_all(bind=engine)


def save_anomaly_event(
    anomaly_score: float,
    severity: str | None,
    agent_report: dict[str, Any],
    idx: int | None = None,
    raw_features: dict[str, Any] | None = None,
    is_anomaly: bool = True,
) -> dict[str, Any] | None:
    """Persist one anomaly event; return the stored row as a dict (or None)."""
    attack_type = (agent_report.get("classifier") or {}).get("attack_type")
    event = AnomalyEvent(
        idx=idx,
        anomaly_score=anomaly_score,
        is_anomaly=is_anomaly,
        severity=severity,
        attack_type=attack_type,
        raw_features=raw_features,
        agent_report=agent_report,
    )
    try:
        with SessionLocal() as session:
            session.add(event)
            session.commit()
            session.refresh(event)
            return event.to_dict()
    except Exception as e:  # pragma: no cover - a DB error must not kill the stream
        print(f"[db] save_anomaly_event failed: {e}")
        return None


def list_anomaly_events(
    limit: int = 50, offset: int = 0, severity: str | None = None
) -> list[dict[str, Any]]:
    """Paginated anomaly events, newest first; optional severity filter."""
    try:
        with SessionLocal() as session:
            q = session.query(AnomalyEvent)
            if severity:
                q = q.filter(AnomalyEvent.severity == severity.upper())
            rows = (
                q.order_by(desc(AnomalyEvent.created_at))
                .offset(offset)
                .limit(max(limit, 1))
                .all()
            )
            return [r.to_dict() for r in rows]
    except Exception as e:  # pragma: no cover
        print(f"[db] list_anomaly_events failed: {e}")
        return []


def get_anomaly_event(event_id: int) -> dict[str, Any] | None:
    """Fetch a single anomaly event (full agent_report) by id."""
    try:
        with SessionLocal() as session:
            row = session.get(AnomalyEvent, event_id)
            return row.to_dict() if row else None
    except Exception as e:  # pragma: no cover
        print(f"[db] get_anomaly_event failed: {e}")
        return None
