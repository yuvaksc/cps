"use client";

import { useState } from "react";
import {
  CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from "recharts";
import { DISPLAY_SENSORS } from "@/lib/config";

export default function SensorChart({ readings }) {
  const [sensor, setSensor] = useState(DISPLAY_SENSORS[1]);
  const threshold = readings.length ? readings[readings.length - 1].threshold : null;

  const data = readings.map((r) => ({
    idx: r.idx,
    score: r.score,
    anomaly: r.is_anomaly ? r.score : null,
    sensor: r.sensors?.[sensor],
  }));

  return (
    <div className="card chart-card">
      <div className="card-head">
        <h3>
          Live Sensor Stream <span className="muted">· anomaly score vs threshold</span>
        </h3>
        <select value={sensor} onChange={(e) => setSensor(e.target.value)}>
          {DISPLAY_SENSORS.map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
      </div>
      <ResponsiveContainer width="100%" height={300}>
        <LineChart data={data} margin={{ top: 10, right: 8, left: -12, bottom: 0 }}>
          <CartesianGrid stroke="#1e293b" strokeDasharray="3 3" />
          <XAxis dataKey="idx" tick={{ fill: "#64748b", fontSize: 11 }} minTickGap={40} />
          <YAxis yAxisId="L" tick={{ fill: "#64748b", fontSize: 11 }} domain={[0, "auto"]} />
          <YAxis yAxisId="R" orientation="right" tick={{ fill: "#475569", fontSize: 11 }}
                 domain={["auto", "auto"]} width={48} />
          <Tooltip contentStyle={{ background: "#0f172a", border: "1px solid #1e293b", borderRadius: 8 }}
                   labelStyle={{ color: "#94a3b8" }} />
          {threshold != null && (
            <ReferenceLine yAxisId="L" y={threshold} stroke="#f59e0b" strokeDasharray="5 4"
              label={{ value: "threshold", fill: "#f59e0b", fontSize: 10, position: "insideTopRight" }} />
          )}
          <Line yAxisId="R" type="monotone" dataKey="sensor" name={sensor} stroke="#475569"
                dot={false} strokeWidth={1} isAnimationActive={false} connectNulls />
          <Line yAxisId="L" type="monotone" dataKey="score" name="anomaly score" stroke="#22d3ee"
                dot={false} strokeWidth={2} isAnimationActive={false} />
          <Line yAxisId="L" type="monotone" dataKey="anomaly" name="detected" stroke="#ef4444"
                dot={{ r: 2, fill: "#ef4444", stroke: "none" }} strokeWidth={0}
                isAnimationActive={false} connectNulls={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
