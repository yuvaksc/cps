"""Pydantic request/response models for the API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AnalyzeRequest(BaseModel):
    raw_features: dict[str, Any] = Field(
        ..., description="Raw SWaT reading keyed by sensor/actuator column name."
    )
    sensor_id: str | None = Field(
        None, description="Optional sensors.id; defaults to the SWaT-System sensor."
    )
    timestamp: str | None = Field(
        None, description="ISO-8601 timestamp; defaults to server time (UTC)."
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "raw_features": {"FIT101": 2.6, "LIT101": 523.8, "MV101": 2, "P101": 2},
                "timestamp": "2015-12-28T10:23:45Z",
            }
        }
    }


class AnalyzeResponse(BaseModel):
    event_id: str | None = None
    is_anomaly: bool
    severity: str | None = None
    anomaly_score: float
    agent_report: dict[str, Any]
    persisted: bool = False
