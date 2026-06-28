"""WebSocket sensor stream + the single replay control (jump-to-next-attack).

The WebSocket is broadcast-only: it pushes scored readings and anomaly events
from the replay engine. The one control — jump — is issued out-of-band via the
REST endpoint below (not over the socket), which mutates the same singleton
engine so the stream reflects the new position on the next tick.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from replay.engine import get_engine

router = APIRouter(tags=["replay"])


@router.websocket("/ws/sensor-stream")
async def sensor_stream(ws: WebSocket):
    await ws.accept()
    try:
        engine = get_engine()
    except FileNotFoundError as e:
        await ws.send_json({"type": "error", "detail": str(e)})
        await ws.close()
        return

    # Begin a new session: any previous run loop sees the generation change and
    # exits, so the newest connection cleanly owns the singleton engine — robust
    # to reconnects / extra tabs without a stale disconnect killing it.
    session = engine.begin_session()

    async def emit(msg: dict) -> None:
        await ws.send_json(msg)

    stream_task = asyncio.create_task(engine.run(emit, session))
    try:
        # The client never sends commands; we still drain the socket so a
        # disconnect is detected promptly and the engine can be released.
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        if engine._gen == session:  # only stop the engine if we still own it
            engine.stop()
        stream_task.cancel()


@router.post("/replay/jump")
def replay_jump():
    """Jump the replay engine to the next detected attack. The WebSocket stream
    reflects the new position on its next tick."""
    e = get_engine()
    e.request_jump()
    return e.status()
