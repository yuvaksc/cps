"""WebSocket sensor stream + replay control endpoints.

The WebSocket pushes scored readings and anomaly events; controls can be sent
either as WS command messages ({"cmd": ...}) or via the REST endpoints below
(both mutate the same singleton engine).
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from replay.engine import get_engine

router = APIRouter(tags=["replay"])


def _apply_command(engine, data: dict) -> None:
    cmd = (data or {}).get("cmd")
    if cmd == "play":
        engine.play()
    elif cmd == "pause":
        engine.pause()
    elif cmd == "speed":
        engine.set_speed(data.get("speed", engine.speed))
    elif cmd == "jump":
        engine.request_jump()
    elif cmd == "seek":
        engine.seek(int(data.get("idx", 0)))
    elif cmd == "restart":
        engine.seek(0)


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
    # to reconnects / HMR / extra tabs without a stale disconnect killing it.
    session = engine.begin_session()
    engine.play()  # a fresh connection always starts streaming

    async def emit(msg: dict) -> None:
        await ws.send_json(msg)

    stream_task = asyncio.create_task(engine.run(emit, session))
    try:
        while True:
            data = await ws.receive_json()
            if engine._gen == session:
                _apply_command(engine, data)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        if engine._gen == session:  # only stop the engine if we still own it
            engine.stop()
        stream_task.cancel()


# ── REST controls (mirror the WS commands; handy for testing / the spec) ───
class StartBody(BaseModel):
    speed: float | None = None
    start_offset: int | None = None


class SpeedBody(BaseModel):
    speed: float


@router.post("/replay/start")
def replay_start(body: StartBody):
    e = get_engine()
    if body.speed is not None:
        e.set_speed(body.speed)
    if body.start_offset is not None:
        e.seek(body.start_offset)
    e.play()
    return e.status()


@router.post("/replay/jump")
def replay_jump():
    e = get_engine()
    e.request_jump()
    return e.status()


@router.post("/replay/pause")
def replay_pause():
    e = get_engine()
    e.pause()
    return e.status()


@router.post("/replay/speed")
def replay_speed(body: SpeedBody):
    e = get_engine()
    e.set_speed(body.speed)
    return e.status()


@router.get("/replay/status")
def replay_status():
    return get_engine().status()
