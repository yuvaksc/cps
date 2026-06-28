"""API smoke tests via FastAPI TestClient.

/health and /anomalies run anywhere (SQLite needs no configuration). The
end-to-end persistence check writes a row through the ORM and reads it back via
the REST endpoint.
"""

from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert set(body) >= {"model_ready", "groq"}


def test_anomalies_returns_list():
    # SQLite-backed: always 200 with a paginated envelope (possibly empty).
    r = client.get("/anomalies")
    assert r.status_code == 200
    body = r.json()
    assert set(body) >= {"count", "limit", "offset", "items"}
    assert isinstance(body["items"], list)


def test_persisted_event_is_listed_and_fetchable():
    from api import database

    database.init_db()
    ev = database.save_anomaly_event(
        anomaly_score=0.91,
        severity="HIGH",
        agent_report={"classifier": {"attack_type": "FDI"}},
        idx=123,
        raw_features={"FIT101": 2.6},
    )
    assert ev and ev["id"]

    listed = client.get("/anomalies").json()
    assert listed["count"] >= 1
    assert any(item["id"] == ev["id"] for item in listed["items"])

    one = client.get(f"/anomalies/{ev['id']}")
    assert one.status_code == 200
    assert one.json()["attack_type"] == "FDI"

    assert client.get("/anomalies/99999999").status_code == 404
