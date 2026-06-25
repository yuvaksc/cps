-- ════════════════════════════════════════════════════════════════════
--  CT-MIF — Supabase setup
--  Run in the Supabase SQL editor. Schema is idempotent; policies are
--  re-runnable. The backend writes with the SERVICE-ROLE key (bypasses RLS);
--  the browser reads with the ANON key (needs the SELECT policies below).
-- ════════════════════════════════════════════════════════════════════

-- ── Schema ──────────────────────────────────────────────────────────
create table if not exists sensors (
  id          uuid primary key default gen_random_uuid(),
  name        text not null,
  system_id   text not null,
  sensor_type text,
  created_at  timestamptz default now()
);

create table if not exists readings (
  id           uuid primary key default gen_random_uuid(),
  sensor_id    uuid references sensors(id),
  timestamp    timestamptz not null,
  raw_features jsonb not null
);

create table if not exists anomaly_events (
  id            uuid primary key default gen_random_uuid(),
  reading_id    uuid references readings(id),
  anomaly_score float not null,
  is_anomaly    boolean not null,
  severity      text,
  agent_report  jsonb,
  created_at    timestamptz default now()
);

-- ── Realtime (so the dashboard feed updates live) ───────────────────
alter publication supabase_realtime add table anomaly_events;

-- ── Row-Level Security ──────────────────────────────────────────────
-- The dashboard reads anomaly_events with the ANON key. Without a SELECT
-- policy, anon reads return [] (200) AND Realtime delivers nothing, because
-- Supabase Realtime is gated by RLS. Allow read-only anon access; all writes
-- still flow through the backend's service-role key.
alter table anomaly_events enable row level security;
drop policy if exists "anon read anomaly_events" on anomaly_events;
create policy "anon read anomaly_events"
  on anomaly_events for select to anon using (true);

-- Optional: only needed if the frontend ever reads these directly.
alter table readings enable row level security;
drop policy if exists "anon read readings" on readings;
create policy "anon read readings" on readings for select to anon using (true);

alter table sensors enable row level security;
drop policy if exists "anon read sensors" on sensors;
create policy "anon read sensors" on sensors for select to anon using (true);
