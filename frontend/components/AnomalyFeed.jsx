"use client";

import SeverityBadge from "./SeverityBadge";

function fmtTime(t) {
  try {
    return new Date(t).toLocaleTimeString();
  } catch {
    return "";
  }
}

export default function AnomalyFeed({ events, onSelect, selectedId }) {
  if (events == null) {
    return (
      <div className="card feed">
        <div className="card-head"><h3>Anomaly Feed</h3></div>
        <p className="muted">Connecting to the live event stream…</p>
      </div>
    );
  }

  return (
    <div className="card feed">
      <div className="card-head">
        <h3>Anomaly Feed <span className="muted">· realtime</span></h3>
        <span className="muted">{events.length}</span>
      </div>
      <div className="feed-list">
        {events.length === 0 && (
          <p className="muted">No anomalies yet — hit “Jump to next attack”.</p>
        )}
        {events.map((ev) => {
          const cls = ev.agent_report?.classifier;
          const asn = ev.agent_report?.assessor;
          const subs = (asn?.affected_subsystems || []).slice(0, 2).join(", ");
          return (
            <button
              key={ev.id}
              className={"event-card" + (selectedId === ev.id ? " sel" : "")}
              onClick={() => onSelect?.(ev)}
            >
              <div className="event-card-top">
                <SeverityBadge severity={ev.severity} />
                <span className="atk">{cls?.attack_type || "anomaly"}</span>
                <span className="time">{fmtTime(ev.created_at)}</span>
              </div>
              <div className="event-card-mid">
                score {Number(ev.anomaly_score ?? 0).toFixed(3)}
                {subs ? ` · ${subs}` : ""}
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}
