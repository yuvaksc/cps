export const API_URL =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export const WS_URL =
  process.env.NEXT_PUBLIC_API_WS_URL || "ws://localhost:8000/ws/sensor-stream";

// Sensors offered in the chart's overlay selector (one+ per SWaT stage).
export const DISPLAY_SENSORS = [
  "FIT101", "LIT101", "AIT201", "DPIT301", "FIT401", "AIT501", "PIT501",
];

export const SEVERITY_COLORS = {
  LOW: "#3b82f6",
  MEDIUM: "#eab308",
  HIGH: "#f97316",
  CRITICAL: "#ef4444",
};
