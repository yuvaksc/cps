"""LangGraph 4-agent pipeline.

    detect ──(anomaly?)──> classify ──> assess ──> mitigate ──> END
       └────────────(normal)───────────────────────────────────> END

Downstream reasoning agents run only when the detector flags an anomaly, so
normal readings cost one cheap model call and zero LLM calls.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from agents.assessor import run_assessor
from agents.classifier import run_classifier
from agents.detector import run_detector
from agents.mitigator import run_mitigator


class AgentState(TypedDict, total=False):
    reading: dict[str, Any]
    detector: dict[str, Any]
    classifier: dict[str, Any]
    assessor: dict[str, Any]
    mitigator: dict[str, Any]


def _should_continue(state: AgentState) -> str:
    return "classify" if state.get("detector", {}).get("is_anomaly") else "end"


def build_graph():
    g = StateGraph(AgentState)
    g.add_node("detect", run_detector)
    g.add_node("classify", run_classifier)
    g.add_node("assess", run_assessor)
    g.add_node("mitigate", run_mitigator)

    g.set_entry_point("detect")
    g.add_conditional_edges("detect", _should_continue,
                            {"classify": "classify", "end": END})
    g.add_edge("classify", "assess")
    g.add_edge("assess", "mitigate")
    g.add_edge("mitigate", END)
    return g.compile()


@lru_cache(maxsize=1)
def get_pipeline():
    return build_graph()


def to_agent_report(state: AgentState) -> dict[str, Any]:
    """Strip the input reading; keep the agent blocks that ran."""
    return {
        k: state[k]
        for k in ("detector", "classifier", "assessor", "mitigator")
        if state.get(k)
    }


def run_pipeline(reading: dict[str, Any]) -> AgentState:
    """Run the full graph on one raw reading and return the final state."""
    return get_pipeline().invoke({"reading": reading})


def run_reasoning(reading: dict[str, Any], detector: dict[str, Any]) -> dict[str, Any]:
    """Run ONLY the downstream agents from an already-computed detector result.

    Used by the replay engine, which scores with its own scorer and must not
    re-run the detector (that would advance a different scorer's state). Returns
    a full agent_report (detector + classifier + assessor + mitigator).
    """
    state: AgentState = {"reading": reading, "detector": detector}
    state.update(run_classifier(state))
    state.update(run_assessor(state))
    state.update(run_mitigator(state))
    return to_agent_report(state)
