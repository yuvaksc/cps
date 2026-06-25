"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { WS_URL } from "@/lib/config";

const MAX_POINTS = 200;
const FLUSH_MS = 100; // render the chart ~10x/s regardless of message rate

/**
 * WebSocket hook for the replay sensor stream.
 *
 * Readings can arrive far faster than React can render a 200-point chart
 * (especially at 500x), so they're buffered in a ref and flushed to state at a
 * fixed ~10fps. This keeps the chart smooth AND the controls responsive —
 * without it, per-message re-renders starve the UI and buttons feel dead.
 * Status / event messages are infrequent and applied immediately.
 */
export function useSensorStream() {
  const [readings, setReadings] = useState([]);
  const [status, setStatus] = useState(null);
  const [connected, setConnected] = useState(false);
  const [activeEvent, setActiveEvent] = useState(null);
  const [wsEvents, setWsEvents] = useState([]);
  const wsRef = useRef(null);
  const bufRef = useRef([]);

  // Flush buffered readings to state at a steady cadence.
  useEffect(() => {
    const id = setInterval(() => {
      const buf = bufRef.current;
      if (buf.length === 0) return;
      bufRef.current = [];
      setReadings((prev) => {
        const next = prev.length ? prev.concat(buf) : buf;
        return next.length > MAX_POINTS ? next.slice(-MAX_POINTS) : next;
      });
    }, FLUSH_MS);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    let stop = false;
    let retry;

    function connect() {
      let ws;
      try {
        ws = new WebSocket(WS_URL);
      } catch {
        retry = setTimeout(connect, 2000);
        return;
      }
      wsRef.current = ws;

      ws.onopen = () => setConnected(true);
      ws.onclose = () => {
        setConnected(false);
        if (!stop) retry = setTimeout(connect, 2000);
      };
      ws.onerror = () => ws.close();
      ws.onmessage = (e) => {
        let m;
        try {
          m = JSON.parse(e.data);
        } catch {
          return;
        }
        switch (m.type) {
          case "reading":
            bufRef.current.push(m); // buffered; flushed on the interval above
            break;
          case "status":
            setStatus(m);
            break;
          case "event_start":
            setActiveEvent({
              phase: "analyzing",
              idx: m.idx,
              severity: m.severity,
              agent_report: { detector: m.detector },
            });
            break;
          case "event":
            setActiveEvent({
              phase: "done",
              idx: m.idx,
              event_id: m.event_id,
              severity: m.severity,
              agent_report: m.agent_report,
            });
            setWsEvents((prev) =>
              [
                {
                  id: m.event_id || `ws-${m.idx}`,
                  created_at: new Date().toISOString(),
                  severity: m.severity,
                  anomaly_score: m.agent_report?.detector?.anomaly_score,
                  agent_report: m.agent_report,
                  _ws: true,
                },
                ...prev,
              ].slice(0, 50)
            );
            break;
          default:
            break;
        }
      };
    }

    connect();
    return () => {
      stop = true;
      clearTimeout(retry);
      wsRef.current?.close();
    };
  }, []);

  const send = useCallback((obj) => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj));
  }, []);

  return { readings, status, connected, activeEvent, wsEvents, send };
}
