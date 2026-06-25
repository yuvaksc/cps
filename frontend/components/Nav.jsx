"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  ["/", "Live Dashboard"],
  ["/anomalies", "Anomaly History"],
];

export default function Nav() {
  const path = usePathname();
  return (
    <nav className="nav">
      <div className="brand">
        CT-MIF <span>Monitor</span>
      </div>
      <div className="nav-links">
        {LINKS.map(([href, label]) => (
          <Link key={href} href={href} className={path === href ? "active" : ""}>
            {label}
          </Link>
        ))}
      </div>
    </nav>
  );
}
