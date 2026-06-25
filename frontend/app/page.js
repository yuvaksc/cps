"use client";

import { useEffect, useState } from "react";
import AgentPanel from "@/components/AgentPanel";
import AnomalyFeed from "@/components/AnomalyFeed";
import DemoControls from "@/components/DemoControls";
import SensorChart from "@/components/SensorChart";
import { useAnomalyFeed } from "@/hooks/useAnomalyFeed";
import { useSensorStream } from "@/hooks/useSensorStream";

export default function Dashboard() {
  const { readings, status, connected, activeEvent, wsEvents, send } = useSensorStream();
  const supabaseFeed = useAnomalyFeed();
  // Prefer Supabase Realtime when it has rows; otherwise fall back to the
  // WebSocket event log (also covers the case where RLS blocks anon reads).
  const feed = supabaseFeed && supabaseFeed.length ? supabaseFeed : wsEvents;

  const [pinned, setPinned] = useState(null);
  // When a fresh live event arrives, stop pinning so the panel follows it.
  useEffect(() => {
    setPinned(null);
  }, [activeEvent?.idx, activeEvent?.event_id]);

  let displayedEvent = null;
  if (pinned) {
    displayedEvent = {
      phase: "done",
      severity: pinned.severity,
      agent_report: pinned.agent_report,
      event_id: pinned.id,
    };
  } else if (activeEvent) {
    displayedEvent = activeEvent;
  } else if (feed && feed[0]) {
    displayedEvent = {
      phase: "done",
      severity: feed[0].severity,
      agent_report: feed[0].agent_report,
      event_id: feed[0].id,
    };
  }

  return (
    <div className="dashboard">
      <DemoControls
        status={status}
        connected={connected}
        liveIdx={readings.length ? readings[readings.length - 1].idx : null}
        onCommand={send}
      />
      <div className="grid">
        <div className="col-main">
          <SensorChart readings={readings} />
          <AgentPanel event={displayedEvent} />
        </div>
        <div className="col-side">
          <AnomalyFeed events={feed} onSelect={setPinned} selectedId={pinned?.id} />
        </div>
      </div>
    </div>
  );
}
