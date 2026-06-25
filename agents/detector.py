"""Agent 1 — AnomalyDetector.

Deterministic: wraps the CT-MIF model (no LLM). Produces the anomaly score,
the binary decision, and view-level + sensor-level attribution that the
downstream reasoning agents consume.
"""

from __future__ import annotations

from typing import Any

from core.ctmif import get_scorer


def run_detector(state: dict[str, Any]) -> dict[str, Any]:
    scorer = get_scorer()
    det = scorer.score(state["reading"])
    return {"detector": det}
