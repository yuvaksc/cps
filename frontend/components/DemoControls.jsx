"use client";

export default function DemoControls({ status, connected, liveIdx, onCommand }) {
  const speed = status?.speed ?? 50;
  const paused = status?.paused;
  const row = liveIdx ?? status?.idx;

  return (
    <div className="card controls">
      <div className="controls-row">
        <button className="btn primary" onClick={() => onCommand({ cmd: paused ? "play" : "pause" })}>
          {paused ? "▶ Play" : "⏸ Pause"}
        </button>
        <button className="btn" onClick={() => onCommand({ cmd: "jump" })}>
          ⏭ Jump to next attack
        </button>
        <button className="btn" onClick={() => onCommand({ cmd: "restart" })}>
          ⟲ Restart
        </button>
        <div className="speed-group">
          <span className="muted">Speed</span>
          {[1, 50, 500].map((s) => (
            <button
              key={s}
              className={"btn chip" + (speed === s ? " active" : "")}
              onClick={() => onCommand({ cmd: "speed", speed: s })}
            >
              {s}×
            </button>
          ))}
        </div>
      </div>
      <div className="controls-meta">
        <span className={"dot " + (connected ? "on" : "off")} />
        {connected ? "connected" : "disconnected"}
        {status && (
          <span className="muted">
            {" "}· row {row?.toLocaleString()} / {status.total?.toLocaleString()} ·{" "}
            {status.detected_attacks ?? status.attacks}/{status.attacks} attacks detected ·
            supabase {status.supabase ? "on" : "off"}
          </span>
        )}
      </div>
    </div>
  );
}
