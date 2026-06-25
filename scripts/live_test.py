"""
Live integration smoke test (requires real .env): exercises the Groq agent
reasoning AND Supabase persistence end-to-end on a synthetic anomaly.

Run:  PYTHONIOENCODING=utf-8 python scripts/live_test.py
"""

from agents.graph import run_reasoning
from api import db
from api.config import settings

SYNTH_DET = {
    "anomaly_score": 0.91,
    "is_anomaly": True,
    "flagged_views": ["pca_view", "raw_sensors"],
    "view_scores": {"raw_sensors": 0.74, "pca_view": 0.86, "temporal_diff": 0.21},
    "actuator_surprise": 13.82,
    "score_ratio": 1.7,
    "threshold": 0.667,
    "top_sensors": [
        {"sensor": "P201", "scaled": 3.2, "delta": 2.1},
        {"sensor": "FIT201", "scaled": -2.1, "delta": -1.6},
        {"sensor": "LIT301", "scaled": 1.1, "delta": 0.4},
    ],
}


def main():
    print(f"supabase_enabled={settings.supabase_enabled}  "
          f"groq_enabled={settings.groq_enabled}  model={settings.groq_model}\n")

    print("── Groq agent reasoning ──")
    report = run_reasoning({}, SYNTH_DET)
    for agent in ("classifier", "assessor", "mitigator"):
        block = report[agent]
        src = block.get("_source", "?")
        err = block.get("_error")
        print(f"[{agent}] source={src}" + (f"  ERROR={err}" if err else ""))
        for k, v in block.items():
            if not k.startswith("_"):
                print(f"    {k}: {v}")
    print()

    print("── Supabase persistence ──")
    reading = db.insert_reading({"FIT101": 2.6, "P201": 1}, None, None)
    print(f"reading id: {reading and reading.get('id')}")
    ev = db.insert_anomaly_event(
        reading_id=reading["id"] if reading else None,
        anomaly_score=SYNTH_DET["anomaly_score"],
        is_anomaly=True,
        severity=report["assessor"]["severity"],
        agent_report=report,
    )
    print(f"event id:   {ev and ev.get('id')}")
    listed = db.list_anomaly_events(limit=3)
    print(f"list_anomaly_events -> {len(listed)} rows")
    if ev:
        fetched = db.get_anomaly_event(ev["id"])
        print(f"get_anomaly_event -> {'OK' if fetched else 'MISSING'}")


if __name__ == "__main__":
    main()
