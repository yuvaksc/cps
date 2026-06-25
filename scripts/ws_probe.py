"""Throwaway: drive the WS stream like the UI would and print every status
message, to confirm the backend emits status after each control command."""
import asyncio
import json

import websockets

URL = "ws://127.0.0.1:8000/ws/sensor-stream"


async def collect(ws, seconds, tag):
    """Drain messages for `seconds`; return (status_msgs, reading_count)."""
    statuses, readings = [], 0
    end = asyncio.get_event_loop().time() + seconds
    while asyncio.get_event_loop().time() < end:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=seconds)
        except asyncio.TimeoutError:
            break
        m = json.loads(raw)
        if m.get("type") == "status":
            statuses.append({"paused": m["paused"], "speed": m["speed"], "idx": m["idx"]})
        elif m.get("type") == "reading":
            readings += 1
    print(f"[{tag}] readings={readings} statuses={statuses}")
    return statuses, readings


async def main():
    async with websockets.connect(URL) as ws:
        await collect(ws, 1.0, "initial")
        await ws.send(json.dumps({"cmd": "pause"}))
        await collect(ws, 1.2, "after pause (expect paused=True, readings~0)")
        await ws.send(json.dumps({"cmd": "play"}))
        await collect(ws, 1.0, "after play  (expect paused=False, readings>0)")
        await ws.send(json.dumps({"cmd": "speed", "speed": 500}))
        await collect(ws, 1.0, "after speed=500 (expect speed=500)")
        await ws.send(json.dumps({"cmd": "jump"}))
        await collect(ws, 1.5, "after jump  (expect idx jumps to an attack)")
        await ws.send(json.dumps({"cmd": "restart"}))
        await collect(ws, 1.0, "after restart (expect idx -> ~0)")


if __name__ == "__main__":
    asyncio.run(main())
