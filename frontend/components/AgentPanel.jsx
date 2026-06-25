"use client";

import { useEffect, useState } from "react";
import SeverityBadge from "./SeverityBadge";

const STEPS = [
  { key: "detector", num: "①", name: "AnomalyDetector" },
  { key: "classifier", num: "②", name: "AttackClassifier" },
  { key: "assessor", num: "③", name: "ImpactAssessor" },
  { key: "mitigator", num: "④", name: "MitigationAdvisor" },
];

function renderBlock(key, d) {
  if (key === "detector")
    return (
      <>
        score <b>{Number(d.anomaly_score).toFixed(3)}</b> · views{" "}
        {(d.flagged_views || []).join(", ") || "—"}
      </>
    );
  if (key === "classifier")
    return (
      <>
        <b>{d.attack_type}</b> · conf {Math.round((d.confidence ?? 0) * 100)}%
        <div className="reason">{d.reasoning}</div>
      </>
    );
  if (key === "assessor")
    return (
      <>
        <b>{d.severity}</b> · {(d.affected_subsystems || []).slice(0, 3).join(", ")} ·
        impact {d.impact_score}
        <div className="reason">{d.blast_radius}</div>
      </>
    );
  if (key === "mitigator")
    return (
      <>
        priority <b>{d.priority}</b>
        <ul>
          {(d.actions || []).map((a, i) => (
            <li key={i}>{a}</li>
          ))}
        </ul>
      </>
    );
  return null;
}

export default function AgentPanel({ event }) {
  const report = event?.agent_report || {};
  const present = STEPS.filter((s) => report[s.key]).length;
  const [revealed, setRevealed] = useState(present);

  // Staggered "sequential reveal" each time a new event/report arrives.
  useEffect(() => {
    setRevealed(0);
    const timers = [];
    for (let i = 0; i < present; i++) {
      timers.push(setTimeout(() => setRevealed((v) => Math.max(v, i + 1)), i * 350));
    }
    return () => timers.forEach(clearTimeout);
  }, [present, event?.idx, event?.event_id]);

  if (!event) {
    return (
      <div className="card agent-panel">
        <div className="card-head"><h3>Agent Reasoning</h3></div>
        <p className="muted">
          Awaiting an anomaly — the 4-agent pipeline appears here step by step.
        </p>
      </div>
    );
  }

  return (
    <div className="card agent-panel">
      <div className="card-head">
        <h3>Agent Reasoning {event.phase === "analyzing" && <span className="muted">· analyzing…</span>}</h3>
        {event.severity && <SeverityBadge severity={event.severity} />}
      </div>
      <div className="agent-steps">
        {STEPS.map((s, i) => {
          const data = report[s.key];
          const shown = i < revealed && data;
          const analyzing = !data && event.phase === "analyzing" && i > 0;
          return (
            <div
              key={s.key}
              className={"agent-step" + (shown ? " in" : "") + (data ? "" : " pending")}
            >
              <div className="agent-step-head">
                <span className="num">{s.num}</span>
                <span className="aname">{s.name}</span>
                <span className="check">{data ? "✓" : analyzing ? "…" : ""}</span>
              </div>
              {shown && <div className="agent-step-body">{renderBlock(s.key, data)}</div>}
            </div>
          );
        })}
      </div>
    </div>
  );
}
