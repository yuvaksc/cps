"""Structured output schemas for the reasoning agents (used by Groq's
structured-output / tool-calling interface and for validation)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

AttackType = Literal["Normal", "DoS", "FDI", "Replay", "Stealth", "Unknown"]
Severity = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
Priority = Literal["LOW", "MEDIUM", "HIGH", "IMMEDIATE"]


class ClassifierOut(BaseModel):
    attack_type: AttackType = Field(description="ICS attack category")
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str = Field(description="One or two sentences citing the evidence")


class AssessorOut(BaseModel):
    severity: Severity
    affected_subsystems: list[str] = Field(description="Component tags and/or process stages impacted")
    blast_radius: str = Field(description="Downstream physical impact")
    impact_score: float = Field(ge=0.0, le=1.0)


class MitigatorOut(BaseModel):
    actions: list[str] = Field(description="Ordered, concrete operator actions")
    priority: Priority
