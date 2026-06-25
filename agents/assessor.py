"""Agent 3 — ImpactAssessor.

Quantifies blast radius: which physical subsystems are affected, how far the
damage propagates downstream, and an overall severity + impact score.
"""

from __future__ import annotations

from typing import Any

from agents.domain import PROCESS_CONTEXT, blast_radius_for, subsystems_for
from agents.schemas import AssessorOut
from core.ctmif import quick_severity

_SYSTEM = (
    "You are an ICS reliability engineer for a 6-stage water-treatment plant "
    "(SWaT). Given a detected/classified attack, assess physical impact: which "
    "subsystems are affected, the downstream blast radius (the process is "
    "sequential, stage N feeds stage N+1), a severity (LOW/MEDIUM/HIGH/CRITICAL) "
    "and an impact_score 0-1.\n"
    f"Process stages:\n{PROCESS_CONTEXT}"
)


def _affected_tags(det: dict[str, Any]) -> list[str]:
    return [s["sensor"] for s in det.get("top_sensors", []) if s.get("sensor")]


def _prompt(det: dict[str, Any], cls: dict[str, Any]) -> str:
    return (
        f"Attack type: {cls.get('attack_type')} "
        f"(confidence {cls.get('confidence')})\n"
        f"Classifier rationale: {cls.get('reasoning')}\n"
        f"anomaly_score: {det.get('anomaly_score')} "
        f"(ratio over threshold: {det.get('score_ratio')})\n"
        f"Most-deviant sensors (tag, scaled value, delta): {det.get('top_sensors')}\n"
        f"Flagged views: {det.get('flagged_views')}\n\n"
        "Determine affected_subsystems (use the stage of each tag), the "
        "downstream blast_radius, a severity, and an impact_score 0-1."
    )


def _heuristic(det: dict[str, Any], cls: dict[str, Any]) -> dict[str, Any]:
    tags = _affected_tags(det)
    subsystems = subsystems_for(tags) or ["Unknown"]
    ratio = det.get("score_ratio", 0.0)
    severity = quick_severity(ratio)
    # CRITICAL only if a confident attack also has wide reach.
    if severity == "CRITICAL" and len(subsystems) < 2 and cls.get("confidence", 0) < 0.7:
        severity = "HIGH"
    impact = max(0.0, min(1.0, 0.5 * min(ratio, 3.0) / 3.0 + 0.15 * len(subsystems)))
    print("hi")
    return {
        "severity": severity,
        "affected_subsystems": tags + subsystems,
        "blast_radius": blast_radius_for(tags),
        "impact_score": round(impact, 3),
        "_source": "heuristic",
    }


def run_assessor(state: dict[str, Any]) -> dict[str, Any]:
    det, cls = state["detector"], state["classifier"]
    try:
        from agents.llm import get_llm

        llm = get_llm(temperature=0.1).with_structured_output(AssessorOut)
        out = llm.invoke([("system", _SYSTEM), ("human", _prompt(det, cls))])
        result = out.model_dump()
        result["_source"] = "groq"
        return {"assessor": result}
    except Exception as e:
        result = _heuristic(det, cls)
        result["_error"] = str(e)[:160]
        return {"assessor": result}
