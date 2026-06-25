import { createClient } from "@supabase/supabase-js";

const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

export const supabaseEnabled = Boolean(url && key);

// Null when not configured — callers fall back to the WebSocket event stream.
export const supabase = supabaseEnabled ? createClient(url, key) : null;
