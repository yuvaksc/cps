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

from agents.schemas import ClassifierOut

_SYSTEM = (
    "ROLE: You are a senior ICS/SCADA security analyst for a 6-stage Secure "
    "Water Treatment (SWaT) plant.\n"
    "TASK: Classify the cyber-attack class behind one flagged reading, using only "
    "the multi-view anomaly detector's evidence.\n\n"
    "The detector reports three normalized VIEW SCORES (higher = more anomalous):\n"
    "  • raw_sensors   — raw + temporal sensor features (levels, flows, pressures)\n"
    "  • pca_view      — PCA of the sensor space + actuator-state surprise\n"
    "  • temporal_diff — step-over-step change (captures freezes and abrupt jumps)\n"
    "plus actuator_surprise = -log P(actuator configuration).\n\n"
    "CRITICAL — do NOT over-weight actuator_surprise. It saturates at its ceiling "
    "(~13.82, the floor probability for an actuator-state combination never seen "
    "in training) during ESSENTIALLY EVERY attack in this plant. So a value near "
    "13.82 confirms 'an attack is happening' but does NOT identify the class on "
    "its own — never default to FDI just because actuator_surprise is high.\n\n"
    "DISCRIMINATE by WHICH VIEW DOMINATES and the temporal behavior:\n"
    "  • DoS     — temporal_diff is the dominant view (abrupt freeze/jump).\n"
    "  • Stealth — raw_sensors elevated while temporal_diff stays low (slow drift "
    "hugging the normal band).\n"
    "  • FDI     — pca_view clearly dominates with low/moderate temporal change "
    "(sensor values inconsistent with actuator state); the saturated "
    "actuator_surprise reinforces this ONLY when pca_view leads.\n"
    "  • Replay  — no single view dominates (raw ≈ pca, moderate scores); values "
    "look individually plausible but cross-correlation is broken.\n"
    "  • Unknown — evidence is weak (no view clears ~0.6) or contradictory.\n\n"
    "RULES:\n"
    "  1. Reason ONLY from the evidence — never invent sensor tags or values.\n"
    "  2. Calibrate `confidence` to how clearly one view dominates (clean → high; "
    "mixed → low; nothing clears ~0.6 → Unknown).\n"
    "  3. In `reasoning`, cite the deciding view(s) in one or two sentences."
)


def _prompt(det: dict[str, Any]) -> str:
    return (
        "Detector evidence for this reading:\n"
        f"- anomaly_score: {det.get('anomaly_score')} "
        f"(threshold {det.get('threshold')}, ratio_over_threshold {det.get('score_ratio')})\n"
        f"- flagged_views: {det.get('flagged_views')}\n"
        f"- view_scores: {det.get('view_scores')}\n"
        f"- actuator_surprise: {det.get('actuator_surprise')} "
        "(~13.82 = saturated ceiling; elevated in most attacks, so weak on its own)\n"
        f"- most-deviant sensors (tag, scaled_value, delta): {det.get('top_sensors')}\n\n"
        "Classify the attack: return attack_type (DoS | FDI | Replay | Stealth | "
        "Unknown), a calibrated confidence in [0,1], and a one-to-two sentence "
        "reasoning that cites the specific signal(s)."
    )


def _heuristic(det: dict[str, Any]) -> dict[str, Any]:
    """Classify by which detector VIEW dominates. actuator_surprise is NOT used
    as a primary signal: it saturates (~13.82) during almost every attack, so it
    can't distinguish the class — only the relative view scores can."""
    views = det.get("view_scores", {})
    raw = views.get("raw_sensors", 0.0)
    pca = views.get("pca_view", 0.0)
    temporal = views.get("temporal_diff", 0.0)
    act = det.get("actuator_surprise", 0.0)

    if max(raw, pca, temporal) < 0.6:
        atk, conf = "Unknown", 0.4
        why = "No view clears the detection band; attack class can't be determined confidently."
    elif temporal >= raw and temporal >= pca:
        atk, conf = "DoS", 0.6
        why = (f"Temporal-difference view dominates ({temporal}); an abrupt "
               "freeze/jump consistent with a denial-of-service disruption.")
    elif raw >= pca and temporal < 0.4:
        atk, conf = "Stealth", 0.55
        why = (f"Raw-sensor view leads ({raw}) with low temporal change "
               f"({temporal}); slow, low-and-slow manipulation near the normal band.")
    elif pca >= raw and pca >= temporal:
        atk, conf = "FDI", 0.65
        why = (f"PCA view dominates ({pca}) with saturated actuator_surprise "
               f"({act}); sensor values inconsistent with actuator state.")
    else:
        atk, conf = "Replay", 0.5
        why = ("No single view dominates (raw≈pca, moderate scores); plausible "
               "values with broken cross-correlation, consistent with replay.")
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
