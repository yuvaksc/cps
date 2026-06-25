"use client";

import { useCallback, useEffect, useState } from "react";
import AgentPanel from "@/components/AgentPanel";
import SeverityBadge from "@/components/SeverityBadge";
import { API_URL } from "@/lib/config";
import { supabase, supabaseEnabled } from "@/lib/supabase";

const SEVERITIES = ["", "LOW", "MEDIUM", "HIGH", "CRITICAL"];

function fmt(t) {
  try {
    return new Date(t).toLocaleString();
  } catch {
    return "";
  }
}

export default function AnomaliesPage() {
  const [rows, setRows] = useState([]);
  const [severity, setSeverity] = useState("");
  const [selected, setSelected] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      if (supabaseEnabled) {
        let q = supabase
          .from("anomaly_events")
          .select("*")
          .order("created_at", { ascending: false })
          .limit(100);
        if (severity) q = q.eq("severity", severity);
        const { data } = await q;
        setRows(data || []);
      } else {
        const url = new URL(`${API_URL}/anomalies`);
        url.searchParams.set("limit", "100");
        if (severity) url.searchParams.set("severity", severity);
        const res = await fetch(url);
        const j = await res.json();
        setRows(j.items || []);
      }
    } catch {
      setRows([]);
    }
    setLoading(false);
  }, [severity]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="history">
      <div className="card-head history-head">
        <h2>Anomaly History</h2>
        <select value={severity} onChange={(e) => setSeverity(e.target.value)}>
          {SEVERITIES.map((s) => (
            <option key={s} value={s}>{s || "All severities"}</option>
          ))}
        </select>
      </div>

      <div className="history-grid">
        <div className="card table-card">
          {loading ? (
            <p className="muted">Loading…</p>
          ) : rows.length === 0 ? (
            <p className="muted">No events {severity && `with severity ${severity}`}.</p>
          ) : (
            <table className="tbl">
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Severity</th>
                  <th>Attack</th>
                  <th>Score</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => {
                  const cls = r.agent_report?.classifier;
                  return (
                    <tr
                      key={r.id}
                      className={selected?.id === r.id ? "sel" : ""}
                      onClick={() => setSelected(r)}
                    >
                      <td>{fmt(r.created_at)}</td>
                      <td><SeverityBadge severity={r.severity} /></td>
                      <td>{cls?.attack_type || "—"}</td>
                      <td>{Number(r.anomaly_score ?? 0).toFixed(3)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>

        <div className="card detail-card">
          {selected ? (
            <AgentPanel
              event={{
                phase: "done",
                severity: selected.severity,
                agent_report: selected.agent_report,
                event_id: selected.id,
              }}
            />
          ) : (
            <p className="muted">Select an event to see the full 4-agent report.</p>
          )}
        </div>
      </div>
    </div>
  );
}
