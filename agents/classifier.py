"""Agent 2 — AttackClassifier.

Distinguishes the ICS attack class from the detector's evidence:
  DoS     — comms flooding/blocking: sensors freeze or jump abruptly
  FDI     — false data injection: sensor values contradict actuator state
            (high actuator surprise, PCA view fires)
  Replay  — recorded-traffic playback: values look plausible but temporal
            correlations break
  Stealth — slow, small manipulation hugging the normal band
"""

from __future__ import annotations

from typing import Any

from agents.domain import PROCESS_CONTEXT
from agents.schemas import ClassifierOut

_SYSTEM = (
    "You are an ICS/SCADA security analyst for a 6-stage water-treatment plant "
    "(SWaT). Classify the cyber-attack type from multi-view anomaly-detector "
    "evidence. Attack types: DoS, FDI (false data injection), Replay, Stealth. "
    "If evidence is weak, use Unknown. Be precise and cite the specific signal.\n"
    f"Process stages:\n{PROCESS_CONTEXT}"
)


def _prompt(det: dict[str, Any]) -> str:
    return (
        "Detector evidence:\n"
        f"- anomaly_score: {det.get('anomaly_score')} "
        f"(threshold {det.get('threshold')}, ratio {det.get('score_ratio')})\n"
        f"- flagged_views: {det.get('flagged_views')}\n"
        f"- view_scores: {det.get('view_scores')}\n"
        f"- actuator_surprise: {det.get('actuator_surprise')} "
        "(>=13.8 means an actuator state combination never seen in training)\n"
        f"- most-deviant sensors: {det.get('top_sensors')}\n\n"
        "Classify the attack type, give confidence 0-1, and a one-sentence "
        "rationale grounded in the evidence above."
    )


def _heuristic(det: dict[str, Any]) -> dict[str, Any]:
    views = det.get("view_scores", {})
    flagged = set(det.get("flagged_views", []))
    act = det.get("actuator_surprise", 0.0)
    temporal = views.get("temporal_diff", 0.0)
    raw = views.get("raw_sensors", 0.0)
    pca = views.get("pca_view", 0.0)

    if act >= 10.0 and ("pca_view" in flagged or pca > 0.6):
        atk, conf = "FDI", 0.7
        why = ("Actuator state is inconsistent with sensor readings "
               f"(actuator_surprise={act}); classic false-data-injection signature.")
    elif temporal >= 0.6 and temporal >= raw:
        atk, conf = "DoS", 0.6
        why = (f"Dominant temporal-difference view ({temporal}) indicates an "
               "abrupt freeze/jump consistent with a denial-of-service disruption.")
    elif raw >= 0.6 and temporal < 0.4:
        atk, conf = "Stealth", 0.55
        why = (f"Elevated raw-sensor view ({raw}) with low temporal change "
               "suggests slow, low-and-slow manipulation staying near normal.")
    elif raw >= 0.5 and pca >= 0.5:
        atk, conf = "Replay", 0.5
        why = ("Plausible-looking values across views with broken cross-correlation "
               "are consistent with replayed traffic.")
    else:
        atk, conf = "Unknown", 0.4
        why = "Evidence is mixed; attack class cannot be determined confidently."
    return {"attack_type": atk, "confidence": conf, "reasoning": why,
            "_source": "heuristic"}


def run_classifier(state: dict[str, Any]) -> dict[str, Any]:
    det = state["detector"]
    try:
        from agents.llm import get_llm

        llm = get_llm(temperature=0.1).with_structured_output(ClassifierOut)
        out = llm.invoke(
            [("system", _SYSTEM), ("human", _prompt(det))]
        )
        result = out.model_dump()
        result["_source"] = "groq"
        return {"classifier": result}
    except Exception as e:  # no key / API error / parse error -> heuristic
        result = _heuristic(det)
        result["_error"] = str(e)[:160]
        return {"classifier": result}
