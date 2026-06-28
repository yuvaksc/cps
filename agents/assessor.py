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
    "ROLE: You are an ICS reliability engineer for a 6-stage Secure Water "
    "Treatment (SWaT) plant.\n"
    "TASK: Given a classified attack and the detector's evidence, quantify the "
    "PHYSICAL impact.\n\n"
    f"PROCESS STAGES (the first digit of a tag = its stage, e.g. LIT301 → stage 3):\n"
    f"{PROCESS_CONTEXT}\n\n"
    "METHOD:\n"
    "  1. Map each deviant sensor tag to its stage to get affected_subsystems.\n"
    "  2. The process is sequential (stage N feeds stage N+1), so a compromise at "
    "the earliest affected stage propagates downstream — describe that in "
    "blast_radius.\n"
    "  3. Assign severity using the rubric below and an impact_score in [0,1] "
    "that scales with breadth (number of stages) × intensity (score ratio).\n\n"
    "SEVERITY RUBRIC:\n"
    "  • LOW      — single stage, low score ratio, easily contained.\n"
    "  • MEDIUM   — one stage with some downstream exposure, moderate ratio.\n"
    "  • HIGH     — multiple stages or a high score ratio; operational disruption "
    "likely.\n"
    "  • CRITICAL — wide, confident blast radius threatening plant safety or output "
    "across stages.\n\n"
    "RULES: ground every claim in the provided tags/evidence — do not invent "
    "components. Prefer HIGH over CRITICAL unless the reach is both wide AND the "
    "classification is confident."
)


def _affected_tags(det: dict[str, Any]) -> list[str]:
    return [s["sensor"] for s in det.get("top_sensors", []) if s.get("sensor")]


def _prompt(det: dict[str, Any], cls: dict[str, Any]) -> str:
    return (
        f"Attack type: {cls.get('attack_type')} (confidence {cls.get('confidence')})\n"
        f"Classifier rationale: {cls.get('reasoning')}\n"
        f"anomaly_score: {det.get('anomaly_score')} "
        f"(ratio_over_threshold: {det.get('score_ratio')})\n"
        f"Most-deviant sensors (tag, scaled_value, delta): {det.get('top_sensors')}\n"
        f"Flagged views: {det.get('flagged_views')}\n\n"
        "Assess impact: return affected_subsystems (map each deviant tag to its "
        "stage), blast_radius (downstream propagation from the earliest stage), "
        "severity (per the rubric), and impact_score in [0,1]."
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
