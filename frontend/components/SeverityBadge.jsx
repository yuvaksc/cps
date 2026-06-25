import { SEVERITY_COLORS } from "@/lib/config";

export default function SeverityBadge({ severity }) {
  const c = SEVERITY_COLORS[severity] || "#64748b";
  return (
    <span className="badge" style={{ color: c, borderColor: c, background: `${c}22` }}>
      {severity || "—"}
    </span>
  );
}
