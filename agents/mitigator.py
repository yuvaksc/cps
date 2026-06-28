"""Agent 4 — MitigationAdvisor.

Turns the assessment into a prioritized, concrete operator playbook — specific
to the attack type and the affected subsystems, not generic boilerplate.
"""

from __future__ import annotations

from typing import Any

from agents.schemas import MitigatorOut

_SYSTEM = (
    "ROLE: You are an ICS incident-response lead for a 6-stage Secure Water "
    "Treatment (SWaT) plant.\n"
    "TASK: Turn an attack classification and impact assessment into an actionable "
    "operator playbook.\n\n"
    "OUTPUT CONTRACT:\n"
    "  • actions — an ORDERED list of 3-6 concrete steps, most urgent first. Each "
    "is a single imperative instruction.\n"
    "  • priority — overall response priority: LOW | MEDIUM | HIGH | IMMEDIATE "
    "(IMMEDIATE for a CRITICAL assessment).\n\n"
    "GUIDELINES:\n"
    "  1. The FIRST action must contain or isolate the threat (e.g. isolate the "
    "affected stage, switch its actuators to manual).\n"
    "  2. Tailor steps to the attack type — FDI: cross-validate sensors & revert "
    "setpoints; DoS: fail over comms & check flooding; Replay: rotate "
    "credentials/nonces & invalidate the session; Stealth: tighten monitoring & "
    "trend affected tags.\n"
    "  3. Reference the named subsystems / component tags from the assessment — "
    "no generic boilerplate, and do not invent tags.\n"
    "  4. End with notification and forensic-capture steps."
)

_PRIORITY = {"LOW": "LOW", "MEDIUM": "MEDIUM", "HIGH": "HIGH", "CRITICAL": "IMMEDIATE"}


def _prompt(cls: dict[str, Any], asn: dict[str, Any]) -> str:
    return (
        f"Attack type: {cls.get('attack_type')} (confidence {cls.get('confidence')})\n"
        f"Severity: {asn.get('severity')}  impact_score: {asn.get('impact_score')}\n"
        f"Affected subsystems: {asn.get('affected_subsystems')}\n"
        f"Blast radius: {asn.get('blast_radius')}\n\n"
        "Produce the ordered response actions (most urgent first, isolation step "
        "first) and the overall priority."
    )


def _heuristic(cls: dict[str, Any], asn: dict[str, Any]) -> dict[str, Any]:
    atk = cls.get("attack_type", "Unknown")
    subs = asn.get("affected_subsystems", [])
    target = next((s for s in subs if any(c.isdigit() for c in s)), "affected subsystem")
    actions = [f"Isolate {target} and switch its actuators to manual override"]

    if atk == "FDI":
        actions.append("Cross-validate suspect sensors against redundant/physical readings")
        actions.append("Reject injected setpoints; revert PLC to last known-good state")
    elif atk == "DoS":
        actions.append("Fail over the affected PLC comms link; restore polling")
        actions.append("Check for network flooding on the SCADA segment")
    elif atk == "Replay":
        actions.append("Invalidate the current control session; rotate PLC credentials/nonces")
    elif atk == "Stealth":
        actions.append("Widen monitoring thresholds and trend the affected tags closely")

    actions.append("Alert the operations team and on-call engineer")
    actions.append("Capture a forensic snapshot (PLC + historian) for investigation")

    priority = _PRIORITY.get(asn.get("severity", "MEDIUM"), "MEDIUM")
    return {"actions": actions, "priority": priority, "_source": "heuristic"}


def run_mitigator(state: dict[str, Any]) -> dict[str, Any]:
    cls, asn = state["classifier"], state["assessor"]
    try:
        from agents.llm import get_llm

        llm = get_llm(temperature=0.2).with_structured_output(MitigatorOut)
        out = llm.invoke([("system", _SYSTEM), ("human", _prompt(cls, asn))])
        result = out.model_dump()
        result["_source"] = "groq"
        return {"mitigator": result}
    except Exception as e:
        result = _heuristic(cls, asn)
        result["_error"] = str(e)[:160]
        return {"mitigator": result}
