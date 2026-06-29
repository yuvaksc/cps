"""Agent 2 — AttackClassifier.

Distinguishes the ICS attack class from the detector's evidence, using the two
CLEAN sensor-space views (raw_sensors, temporal_diff) as the primary signal —
pca_view embeds actuator_surprise, which saturates on every attack, so it can't
discriminate type:
  DoS     — comms flooding/blocking: temporal_diff high (sensors freeze/jump)
  Stealth — slow drift: raw_sensors elevated, temporal_diff low
  FDI     — actuator state impossible behind normal-looking sensors (sensor
            views quiet, actuator_surprise saturated, pca_view high)
  Replay  — both sensor views moderately elevated/plausible, correlation broken
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
    "CRITICAL — pca_view is NOT a reliable TYPE discriminator. It is built from "
    "the sensor PCA PLUS actuator_surprise, and actuator_surprise saturates "
    "(~13.82, the floor probability for an actuator combination never seen in "
    "training) on ESSENTIALLY EVERY attack here. So pca_view runs high regardless "
    "of attack type. Determine the type PRIMARILY from the two CLEAN sensor-space "
    "views — raw_sensors and temporal_diff — and never classify FDI merely "
    "because pca_view or actuator_surprise is high.\n\n"
    "DECISION GUIDE (raw_sensors & temporal_diff are the primary signals):\n"
    "  • DoS     — temporal_diff is high / dominant: values freeze or jump "
    "abruptly.\n"
    "  • Stealth — raw_sensors elevated while temporal_diff stays low: slow drift "
    "hugging the normal band.\n"
    "  • FDI     — the sensor-space views are UNREMARKABLE (raw_sensors and "
    "temporal_diff both modest) yet actuator_surprise is saturated and pca_view "
    "is high: the actuator STATE is impossible given the normal-looking sensors.\n"
    "  • Replay  — raw_sensors and temporal_diff are both moderately elevated and "
    "individually plausible, with no single clean signature: replayed traffic, "
    "broken cross-correlation.\n"
    "  • Unknown — nothing clears ~0.6, or the evidence is contradictory.\n\n"
    "RULES:\n"
    "  1. Reason ONLY from the evidence — never invent sensor tags or values.\n"
    "  2. Base the class on raw_sensors / temporal_diff; treat pca_view & "
    "actuator_surprise as FDI-confirming only when the sensor views are quiet.\n"
    "  3. Calibrate `confidence` to the clarity of the signal; cite the deciding "
    "view(s) in `reasoning` (one or two sentences)."
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
    """Classify on the CLEAN sensor-space views (raw_sensors, temporal_diff).

    pca_view embeds actuator_surprise, which saturates (~13.82) on almost every
    attack, so pca_view is high regardless of type and is NOT used as a primary
    discriminator. It only confirms FDI when the sensor-space views are quiet
    (an impossible actuator state behind normal-looking sensors)."""
    views = det.get("view_scores", {})
    raw = views.get("raw_sensors", 0.0)
    pca = views.get("pca_view", 0.0)
    temporal = views.get("temporal_diff", 0.0)
    act = det.get("actuator_surprise", 0.0)
    clean = max(raw, temporal)  # strongest CLEAN (uncontaminated) signal

    if max(raw, pca, temporal) < 0.6:
        atk, conf = "Unknown", 0.4
        why = "No view clears the detection band; attack class can't be determined confidently."
    elif temporal >= 0.6 and temporal >= raw:
        atk, conf = "DoS", 0.6
        why = (f"Temporal-difference view is high ({temporal}); an abrupt "
               "freeze/jump consistent with a denial-of-service disruption.")
    elif raw >= 0.6 and temporal <= 0.4:
        atk, conf = "Stealth", 0.55
        why = (f"Sustained raw-sensor deviation ({raw}) with low temporal change "
               f"({temporal}); slow, low-and-slow manipulation near the normal band.")
    elif clean < 0.5 and act >= 12.0 and pca >= 0.6:
        atk, conf = "FDI", 0.6
        why = (f"Sensor views are unremarkable (raw={raw}, temporal={temporal}) "
               f"yet the actuator state is impossible (actuator_surprise={act}); "
               "false-data-injection signature.")
    else:
        atk, conf = "Replay", 0.5
        why = (f"Both sensor views are moderately elevated and plausible "
               f"(raw={raw}, temporal={temporal}) with no single clean signature; "
               "consistent with replayed traffic.")
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
