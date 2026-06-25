"use client";

import { useEffect, useState } from "react";
import { supabase, supabaseEnabled } from "@/lib/supabase";

/**
 * Supabase Realtime hook for anomaly_events. Loads the latest events, then
 * subscribes to INSERTs. When Supabase isn't configured it returns null so the
 * dashboard falls back to the WebSocket event log.
 */
export function useAnomalyFeed() {
  const [events, setEvents] = useState(supabaseEnabled ? [] : null);

  useEffect(() => {
    if (!supabaseEnabled) return;

    let cancelled = false;
    supabase
      .from("anomaly_events")
      .select("*")
      .order("created_at", { ascending: false })
      .limit(50)
      .then(({ data }) => {
        if (!cancelled && data) setEvents(data);
      });

    const channel = supabase
      .channel("anomaly-feed")
      .on(
        "postgres_changes",
        { event: "INSERT", schema: "public", table: "anomaly_events" },
        (payload) => setEvents((prev) => [payload.new, ...(prev || [])].slice(0, 50))
      )
      .subscribe();

    return () => {
      cancelled = true;
      supabase.removeChannel(channel);
    };
  }, []);

  return events;
}
