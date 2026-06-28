"""Replay engine tests.

Engine logic tests run against the small sample fixture. The streaming/jump
tests need trained artifacts (the engine scores as it streams) and skip
otherwise.
"""

import asyncio
import os

import pytest

from replay.engine import PRE_CONTEXT, ReplayEngine

ART = os.getenv("ARTIFACTS_DIR", "artifacts")
SAMPLE = "data/sample_readings.json"
HAS_MODELS = os.path.exists(os.path.join(ART, "model_A.pkl"))
HAS_SAMPLE = os.path.exists(SAMPLE)

pytestmark = pytest.mark.skipif(
    not (HAS_MODELS and HAS_SAMPLE), reason="artifacts or sample fixture missing"
)


@pytest.fixture
def engine():
    return ReplayEngine(SAMPLE)


def test_loads_and_finds_attacks(engine):
    assert engine.n > 0
    assert engine.attack_starts, "fixture should contain an attack onset"


def test_jump_lands_before_attack(engine):
    engine.current_idx = 0
    first_attack = engine.attack_starts[0]
    engine._do_jump()
    assert engine.current_idx == max(0, first_attack - PRE_CONTEXT)


def test_full_stream_emits_readings_event_and_complete(engine):
    engine.speed = 1000.0  # fast-forward the fixture for the test
    msgs: list[dict] = []

    async def emit(m):
        msgs.append(m)

    asyncio.run(engine.run(emit))

    types = [m["type"] for m in msgs]
    assert "reading" in types
    assert "event" in types, "the fixture's strong attack should fire one event"
    assert types[-1] == "replay_complete"

    # exactly one event for the single contiguous attack (debounce works)
    assert sum(t == "event" for t in types) == 1
    # the event carries a full 4-block agent report
    event = next(m for m in msgs if m["type"] == "event")
    assert set(event["agent_report"]) == {
        "detector", "classifier", "assessor", "mitigator"
    }


def test_websocket_streams_readings():
    from fastapi.testclient import TestClient

    from api.main import app

    with TestClient(app) as client:
        with client.websocket_connect("/ws/sensor-stream") as ws:
            first = ws.receive_json()
            assert first["type"] == "status"
            got_reading = False
            for _ in range(30):
                m = ws.receive_json()
                if m["type"] == "reading":
                    got_reading = True
                    assert "sensors" in m and "score" in m
                    break
            assert got_reading


def test_jump_endpoint_requests_jump():
    """POST /replay/jump returns engine status and arms the jump flag the run
    loop consumes (the loop then moves the pointer to the next attack)."""
    from fastapi.testclient import TestClient

    from api.main import app
    from replay.engine import get_engine

    with TestClient(app) as client:
        engine = get_engine()
        engine._jump_requested = False
        r = client.post("/replay/jump")
        assert r.status_code == 200
        assert r.json()["type"] == "status"
        assert engine._jump_requested is True
