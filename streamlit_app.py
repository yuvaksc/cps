"""
CT-MIF — Streamlit operator dashboard.

A Python-native replacement for the old Next.js frontend. Streamlit reruns its
script top-to-bottom on every interaction, which can't drive a smooth ~60fps
streaming chart — so, exactly like the original React app, the live UI runs in
the *browser*: a self-contained component opens the FastAPI WebSocket directly,
renders a moving canvas chart + an animated 4-agent reasoning flow, and POSTs
the single control (jump-to-attack) straight to the REST endpoint. Streamlit
just hosts the component full-bleed.

  • Live Stream     — browser WebSocket → rolling 200-point canvas chart
                      (anomaly score vs. threshold + a selectable sensor).
  • Control Panel   — "Jump to Attack" → POST /replay/jump (not over the WS).
  • Agent Reasoning — the 4 LangGraph agents reveal step-by-step on each event.
  • Anomaly History — GET /anomalies (SQLite) + the live event log.

Config (browser-reachable):  API_URL, API_WS_URL.
"""

from __future__ import annotations

import json
import os

import streamlit as st
import streamlit.components.v1 as components

API_URL = os.getenv("API_URL", "http://localhost:8000")
WS_URL = os.getenv("API_WS_URL", "ws://localhost:8000/ws/sensor-stream")
# One+ sensor per SWaT stage, offered in the chart's overlay selector.
DISPLAY_SENSORS = ["FIT101", "LIT101", "AIT201", "DPIT301", "FIT401", "AIT501", "PIT501"]

st.set_page_config(page_title="CT-MIF — ICS Anomaly Dashboard", layout="wide")

# Strip Streamlit's default chrome/padding so the component fills the page.
st.markdown(
    """
    <style>
      #MainMenu, header, footer {visibility: hidden;}
      .block-container {padding: 0.4rem 1rem 0 1rem; max-width: 100%;}
    </style>
    """,
    unsafe_allow_html=True,
)

COMPONENT = r"""
<!doctype html>
<html>
<head>
<meta charset="utf-8" />
<style>
  :root {
    --bg:#0b1220; --card:#0f172a; --line:#1e293b; --muted:#64748b;
    --text:#e2e8f0; --cyan:#22d3ee; --amber:#f59e0b; --red:#ef4444;
  }
  * { box-sizing: border-box; }
  body {
    margin:0; background:var(--bg); color:var(--text);
    font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  }
  .topbar {
    display:flex; align-items:center; gap:16px; padding:12px 16px;
    background:var(--card); border:1px solid var(--line); border-radius:12px;
  }
  .topbar h1 { font-size:1.05rem; margin:0; font-weight:700; letter-spacing:.2px;}
  .topbar .sub { color:var(--muted); font-size:.8rem; margin-top:2px; }
  .spacer { flex:1; }
  .status { color:var(--muted); font-size:.82rem; }
  .dot { display:inline-block; width:9px; height:9px; border-radius:50%; margin-right:6px;
         background:var(--red); vertical-align:middle; }
  .dot.on { background:#22c55e; box-shadow:0 0 8px #22c55e88; }
  .btn {
    background:var(--cyan); color:#04222b; border:none; border-radius:9px;
    padding:9px 16px; font-weight:700; font-size:.86rem; cursor:pointer;
    transition:filter .15s, transform .05s;
  }
  .btn:hover { filter:brightness(1.08); }
  .btn:active { transform:translateY(1px); }
  .btn:disabled { opacity:.6; cursor:default; }
  .grid { display:grid; grid-template-columns: 2fr 1fr; gap:14px; margin-top:14px; }
  @media (max-width: 980px) { .grid { grid-template-columns: 1fr; } }
  .col-main { display:flex; flex-direction:column; gap:14px; }
  .card {
    background:var(--card); border:1px solid var(--line); border-radius:12px; padding:14px;
  }
  .card-head { display:flex; align-items:center; justify-content:space-between; margin-bottom:8px; }
  .card-head h3 { margin:0; font-size:.92rem; font-weight:650; }
  .card-head .muted { color:var(--muted); font-weight:400; font-size:.78rem; }
  select {
    background:#0b1220; color:var(--text); border:1px solid var(--line);
    border-radius:7px; padding:4px 8px; font-size:.8rem;
  }
  canvas { width:100%; height:300px; display:block; }

  /* ── Agent panel ── */
  .agent-steps { display:flex; flex-direction:column; gap:8px; }
  .agent-step {
    border:1px solid var(--line); border-left:3px solid #334155; border-radius:9px;
    padding:9px 12px; background:#0b1220;
    opacity:0; transform:translateY(6px); transition:opacity .35s ease, transform .35s ease;
  }
  .agent-step.in { opacity:1; transform:none; }
  .agent-step.pending { opacity:.4; }
  .agent-step.detector { border-left-color:var(--cyan); }
  .agent-step.classifier { border-left-color:#a78bfa; }
  .agent-step.assessor { border-left-color:var(--amber); }
  .agent-step.mitigator { border-left-color:#34d399; }
  .agent-step-head { display:flex; align-items:center; gap:8px; font-size:.82rem; }
  .agent-step-head .num { color:var(--muted); font-weight:700; }
  .agent-step-head .aname { font-weight:650; }
  .agent-step-head .check { margin-left:auto; color:#34d399; }
  .agent-step-body { margin-top:6px; font-size:.82rem; color:#cbd5e1; line-height:1.45; }
  .agent-step-body b { color:var(--text); }
  .agent-step-body .reason { color:var(--muted); margin-top:3px; font-size:.78rem; }
  .agent-step-body ul { margin:6px 0 0; padding-left:18px; }
  .agent-step-body li { margin:2px 0; }
  .pill {
    padding:2px 9px; border-radius:7px; font-size:.72rem; font-weight:700; color:#fff;
  }
  .empty { color:var(--muted); font-size:.84rem; padding:6px 2px; }

  /* ── Feed ── */
  .feed-list { display:flex; flex-direction:column; gap:8px; max-height:560px; overflow:auto; }
  .event-card {
    text-align:left; width:100%; background:#0b1220; border:1px solid var(--line);
    border-radius:9px; padding:9px 11px; cursor:pointer; color:var(--text);
    transition:border-color .15s;
  }
  .event-card:hover { border-color:#334155; }
  .event-card.sel { border-color:var(--cyan); }
  .event-card-top { display:flex; align-items:center; gap:8px; font-size:.8rem; }
  .event-card-top .atk { font-weight:650; }
  .event-card-top .time { margin-left:auto; color:var(--muted); font-size:.72rem; }
  .event-card-mid { color:var(--muted); font-size:.76rem; margin-top:4px; }
</style>
</head>
<body>
  <div class="topbar">
    <div>
      <h1 style="color: var(--cyan);">CT-MIF — ICS Anomaly Detection</h1>
      <div class="sub">Multi-view Isolation-Forest + 4-agent LangGraph reasoning · live SWaT replay</div>
    </div>
    <div class="spacer"></div>
    <div class="status"><span id="dot" class="dot"></span><span id="connText">connecting…</span><span id="statusText"></span></div>
    <button id="jumpBtn" class="btn">⏭ Jump to Attack</button>
  </div>

  <div class="grid">
    <div class="col-main">
      <div class="card">
        <div class="card-head">
          <h3>Live Stream <span class="muted">· CT-MIF anomaly score · red = detected</span></h3>
          <select id="sensorSel"></select>
        </div>
        <canvas id="chart"></canvas>
      </div>
      <div class="card">
        <div class="card-head">
          <h3 id="agentHead">Agent Reasoning</h3>
          <span id="agentBadge"></span>
        </div>
        <div id="agentBody"><div class="empty">Awaiting an anomaly — the 4-agent pipeline appears here step by step.</div></div>
      </div>
    </div>
    <div class="card">
      <div class="card-head">
        <h3>Anomaly Feed <span class="muted">· realtime</span></h3>
        <span id="feedCount" class="muted" style="color:var(--muted);font-size:.78rem"></span>
      </div>
      <div id="feedList" class="feed-list"><div class="empty">Connecting to the live event stream…</div></div>
    </div>
  </div>

<script>
const API_URL = "__API_URL__";
const WS_URL = "__WS_URL__";
const SENSORS = __SENSORS__;
const MAX_POINTS = 200;
const SEV_COLORS = { LOW:"#3b82f6", MEDIUM:"#eab308", HIGH:"#f97316", CRITICAL:"#ef4444" };

const STEPS = [
  { key:"detector",   num:"①", name:"AnomalyDetector" },
  { key:"classifier", num:"②", name:"AttackClassifier" },
  { key:"assessor",   num:"③", name:"ImpactAssessor" },
  { key:"mitigator",  num:"④", name:"MitigationAdvisor" },
];

let readings = [];          // rolling window of reading msgs
let threshold = null;
let status = null;
let activeEvent = null;
let events = [];            // newest first
let selectedSensor = SENSORS[1];

// ── sensor selector ──
const sel = document.getElementById("sensorSel");
SENSORS.forEach(s => { const o=document.createElement("option"); o.value=s; o.textContent=s; sel.appendChild(o); });
sel.value = selectedSensor;
sel.onchange = () => { selectedSensor = sel.value; };

// ── auto-resize the embedded iframe to fit its content, so a long agent
//    report is fully visible and the Streamlit page scrolls naturally
//    (components.html otherwise locks the iframe at a fixed height) ──
function fitHeight() {
  try {
    const h = Math.max(document.body.scrollHeight, 320);
    if (window.frameElement) window.frameElement.style.height = (h + 6) + "px";
  } catch (e) { /* cross-origin: fall back to the iframe's own scrollbar */ }
}

// ── severity badge ──
function badge(sev) {
  if (!sev) return "";
  const c = SEV_COLORS[(sev||"").toUpperCase()] || "#64748b";
  return `<span class="pill" style="background:${c}">${sev}</span>`;
}

// ── status line ──
function renderStatus() {
  const liveIdx = readings.length ? readings[readings.length-1].idx : (status ? status.idx : 0);
  if (!status) { document.getElementById("statusText").textContent = ""; return; }
  const det = (status.detected_attacks != null ? status.detected_attacks : status.attacks);
  document.getElementById("statusText").textContent =
    ` · row ${liveIdx.toLocaleString()} / ${status.total.toLocaleString()} · ${det}/${status.attacks} attacks detected`;
}

// ── agent panel ──
function renderBlock(key, d) {
  if (key === "detector")
    return `score <b>${Number(d.anomaly_score).toFixed(3)}</b> · views ${ (d.flagged_views||[]).join(", ") || "—" }`;
  if (key === "classifier")
    return `<b>${d.attack_type}</b> · conf ${Math.round((d.confidence??0)*100)}%`
         + (d.reasoning ? `<div class="reason">${d.reasoning}</div>` : "");
  if (key === "assessor")
    return `<b>${d.severity}</b> · ${(d.affected_subsystems||[]).slice(0,3).join(", ")} · impact ${d.impact_score}`
         + (d.blast_radius ? `<div class="reason">${d.blast_radius}</div>` : "");
  if (key === "mitigator")
    return `priority <b>${d.priority}</b><ul>` + (d.actions||[]).map(a=>`<li>${a}</li>`).join("") + `</ul>`;
  return "";
}

function renderAgents() {
  const head = document.getElementById("agentHead");
  const badgeEl = document.getElementById("agentBadge");
  const body = document.getElementById("agentBody");
  if (!activeEvent) {
    head.textContent = "Agent Reasoning";
    badgeEl.innerHTML = "";
    body.innerHTML = `<div class="empty">Awaiting an anomaly — the 4-agent pipeline appears here step by step.</div>`;
    return;
  }
  const report = activeEvent.agent_report || {};
  head.innerHTML = "Agent Reasoning" + (activeEvent.phase === "analyzing" ? ` <span class="muted" style="color:var(--muted);font-weight:400;font-size:.78rem">· analyzing…</span>` : "");
  badgeEl.innerHTML = badge(activeEvent.severity);

  let html = `<div class="agent-steps">`;
  STEPS.forEach((s) => {
    const d = report[s.key];
    const analyzing = !d && activeEvent.phase === "analyzing";
    html += `<div class="agent-step ${s.key} ${d ? "" : "pending"}" data-key="${s.key}">
      <div class="agent-step-head">
        <span class="num">${s.num}</span>
        <span class="aname">${s.name}</span>
        <span class="check">${d ? "✓" : (analyzing ? "…" : "")}</span>
      </div>
      ${ d ? `<div class="agent-step-body">${renderBlock(s.key, d)}</div>` : "" }
    </div>`;
  });
  html += `</div>`;
  body.innerHTML = html;

  // staggered reveal
  const nodes = body.querySelectorAll(".agent-step");
  nodes.forEach((node, i) => {
    if (node.classList.contains("pending")) { node.classList.add("in"); return; }
    setTimeout(() => node.classList.add("in"), i * 280);
  });
  fitHeight();
}

// ── feed ──
function fmtTime(t) { try { return new Date(t).toLocaleTimeString(); } catch { return ""; } }
function renderFeed() {
  const list = document.getElementById("feedList");
  document.getElementById("feedCount").textContent = events.length ? `${events.length}` : "";
  if (!events.length) { list.innerHTML = `<div class="empty">No anomalies yet — hit “Jump to Attack”.</div>`; return; }
  list.innerHTML = events.map(ev => {
    const cls = (ev.agent_report||{}).classifier || {};
    const asn = (ev.agent_report||{}).assessor || {};
    const subs = (asn.affected_subsystems||[]).slice(0,2).join(", ");
    const atk = ev.attack_type || cls.attack_type || "anomaly";
    return `<button class="event-card" data-id="${ev.id}">
      <div class="event-card-top">${badge(ev.severity)}<span class="atk">${atk}</span><span class="time">${fmtTime(ev.created_at)}</span></div>
      <div class="event-card-mid">score ${Number(ev.anomaly_score??0).toFixed(3)}${subs ? " · "+subs : ""}</div>
    </button>`;
  }).join("");
  list.querySelectorAll(".event-card").forEach(card => {
    card.onclick = () => {
      const ev = events.find(e => String(e.id) === card.dataset.id);
      if (ev && ev.agent_report) {
        activeEvent = { phase:"done", severity:ev.severity, agent_report:ev.agent_report };
        renderAgents();
      }
    };
  });
  fitHeight();
}

// ── canvas chart ──
const canvas = document.getElementById("chart");
const ctx = canvas.getContext("2d");
function resize() {
  const dpr = window.devicePixelRatio || 1;
  canvas.width = canvas.clientWidth * dpr;
  canvas.height = canvas.clientHeight * dpr;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
}
window.addEventListener("resize", resize);

function draw() {
  const W = canvas.clientWidth, H = canvas.clientHeight;
  ctx.clearRect(0, 0, W, H);
  const padL = 38, padR = 14, padT = 12, padB = 22;
  const pW = W - padL - padR, pH = H - padT - padB;

  // grid
  ctx.strokeStyle = "#1e293b"; ctx.lineWidth = 1; ctx.font = "10px ui-sans-serif";
  ctx.fillStyle = "#475569"; ctx.textAlign = "left";
  const data = readings;
  const n = data.length;
  const scores = data.map(r => r.score);
  let sMax = Math.max(threshold || 0, ...(scores.length ? scores : [1])) * 1.15;
  if (!isFinite(sMax) || sMax <= 0) sMax = 1;
  const yScore = v => padT + pH * (1 - v / sMax);
  const xAt = i => padL + (n <= 1 ? 0 : (i / (n - 1)) * pW);

  for (let g = 0; g <= 4; g++) {
    const yv = (sMax) * (g / 4);
    const y = yScore(yv);
    ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(W - padR, y); ctx.stroke();
    ctx.fillText(yv.toFixed(1), 4, y + 3);
  }

  if (n === 0) {
    ctx.fillStyle = "#475569"; ctx.font = "12px ui-sans-serif";
    ctx.fillText("Waiting for the sensor stream…", padL + 8, padT + pH / 2);
    return;
  }

  // x-axis tick labels — the reading index (r.idx), like the original chart
  ctx.fillStyle = "#475569"; ctx.font = "10px ui-sans-serif"; ctx.textAlign = "center";
  const xTicks = Math.min(6, n);
  for (let k = 0; k < xTicks; k++) {
    const i = xTicks === 1 ? 0 : Math.round((n - 1) * k / (xTicks - 1));
    const x = Math.max(padL + 10, Math.min(W - padR - 10, xAt(i)));
    ctx.fillText(String(data[i].idx), x, H - 6);
  }
  ctx.textAlign = "left";

  // sensor overlay (secondary scale)
  const svals = data.map(r => (r.sensors || {})[selectedSensor]).filter(v => v != null);
  if (svals.length) {
    let vMin = Math.min(...svals), vMax = Math.max(...svals);
    if (vMin === vMax) { vMin -= 1; vMax += 1; }
    const ySensor = v => padT + pH * (1 - (v - vMin) / (vMax - vMin));
    ctx.strokeStyle = "#475569"; ctx.lineWidth = 1; ctx.beginPath();
    let started = false;
    data.forEach((r, i) => {
      const v = (r.sensors || {})[selectedSensor];
      if (v == null) { started = false; return; }
      const x = xAt(i), y = ySensor(v);
      if (!started) { ctx.moveTo(x, y); started = true; } else ctx.lineTo(x, y);
    });
    ctx.stroke();
  }

  // (No threshold line: the detector's verdict comes from smoothing + spike +
  // debounce post-processing, not a hard score >= threshold cut — the red
  // "detected" points below convey the actual decision. `threshold` is still
  // used as an invisible y-scale floor so the axis stays stable.)

  // score line
  ctx.strokeStyle = "#22d3ee"; ctx.lineWidth = 2; ctx.beginPath();
  data.forEach((r, i) => {
    const x = xAt(i), y = yScore(r.score);
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  });
  ctx.stroke();

  // anomaly points
  ctx.fillStyle = "#ef4444";
  data.forEach((r, i) => {
    if (r.is_anomaly) {
      ctx.beginPath(); ctx.arc(xAt(i), yScore(r.score), 2.6, 0, Math.PI * 2); ctx.fill();
    }
  });
}

function loop() { draw(); requestAnimationFrame(loop); }
resize(); requestAnimationFrame(loop);

// ── jump control (REST, not over the WS) ──
const jumpBtn = document.getElementById("jumpBtn");
jumpBtn.onclick = async () => {
  jumpBtn.disabled = true;
  const prev = jumpBtn.textContent; jumpBtn.textContent = "Jumping…";
  try { await fetch(`${API_URL}/replay/jump`, { method: "POST" }); }
  catch (e) { /* ignore */ }
  setTimeout(() => { jumpBtn.disabled = false; jumpBtn.textContent = prev; }, 700);
};

// ── seed the feed from SQLite history ──
fetch(`${API_URL}/anomalies?limit=50`).then(r => r.json()).then(d => {
  if (d && d.items && d.items.length) { events = d.items; renderFeed(); }
  else renderFeed();
}).catch(() => renderFeed());

// ── live WebSocket ──
function connect() {
  let ws;
  try { ws = new WebSocket(WS_URL); }
  catch { setTimeout(connect, 2000); return; }

  ws.onopen = () => {
    document.getElementById("dot").classList.add("on");
    document.getElementById("connText").textContent = "connected";
  };
  ws.onclose = () => {
    document.getElementById("dot").classList.remove("on");
    document.getElementById("connText").textContent = "disconnected";
    setTimeout(connect, 2000);
  };
  ws.onerror = () => ws.close();
  ws.onmessage = (e) => {
    let m; try { m = JSON.parse(e.data); } catch { return; }
    if (m.type === "reading") {
      readings.push(m);
      if (readings.length > MAX_POINTS) readings = readings.slice(-MAX_POINTS);
      threshold = m.threshold;
    } else if (m.type === "status") {
      status = m; renderStatus();
    } else if (m.type === "event_start") {
      activeEvent = { phase:"analyzing", idx:m.idx, severity:m.severity, agent_report:{ detector:m.detector } };
      renderAgents();
    } else if (m.type === "event") {
      activeEvent = { phase:"done", idx:m.idx, event_id:m.event_id, severity:m.severity, agent_report:m.agent_report };
      renderAgents();
      events.unshift({
        id: m.event_id || ("ws-" + m.idx),
        created_at: new Date().toISOString(),
        severity: m.severity,
        attack_type: (m.agent_report||{}).classifier?.attack_type,
        anomaly_score: (m.agent_report||{}).detector?.anomaly_score,
        agent_report: m.agent_report,
      });
      events = events.slice(0, 50);
      renderFeed();
    }
  };
}
connect();

// keep the status row's live index advancing between status messages
setInterval(renderStatus, 500);

// keep the embedded iframe sized to its content (covers dynamic growth such as
// a long Groq mitigation list and the staggered agent reveal)
try { new ResizeObserver(() => fitHeight()).observe(document.body); } catch (e) {}
window.addEventListener("load", fitHeight);
window.addEventListener("resize", fitHeight);
setInterval(fitHeight, 400);
fitHeight();
</script>
</body>
</html>
"""

COMPONENT = (
    COMPONENT.replace("__API_URL__", API_URL)
    .replace("__WS_URL__", WS_URL)
    .replace("__SENSORS__", json.dumps(DISPLAY_SENSORS))
)

# Initial height; the component's fitHeight() auto-grows the iframe to its
# content (scrolling=True is a fallback if iframe self-resize is blocked).
components.html(COMPONENT, height=760, scrolling=True)
