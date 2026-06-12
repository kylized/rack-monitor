"""Rack Analyzer — FastAPI backend (port 5001)."""

import asyncio
import json
import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from broadcaster import broadcasters
from ingester import start_all
from state_store import StateStore
from timeseries import TimeSeriesAnalyzer

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
logger = logging.getLogger(__name__)

store    = StateStore(num_switches=5, window=60)
ts       = TimeSeriesAnalyzer(store)
# Per-client outbound queues — _broadcast puts here; ws_endpoint drains
_client_queues: set[asyncio.Queue] = set()


async def _broadcast():
    while True:
        await asyncio.sleep(1)
        if not _client_queues:
            continue
        payload = json.dumps({
            "cam_stats": [{"fps": round(b.fps, 1), "kbps": round(b.kbps, 1)}
                          for b in broadcasters],
            "switches":  store.get_all_states(),
            "summary":   store.get_summary(),
            "alerts":    store.get_alerts(limit=20),
        }, default=str)
        for q in list(_client_queues):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                pass  # slow client — skip this tick


@asynccontextmanager
async def lifespan(_app: FastAPI):
    ingesters = start_all(store, ts)
    task = asyncio.create_task(_broadcast())
    yield
    task.cancel()
    for ing in ingesters:
        ing.stop()


app = FastAPI(lifespan=lifespan)


# ── REST ──────────────────────────────────────────────────────────────────────

@app.get("/api/switches")
def get_switches():
    return store.get_all_states()


@app.get("/api/summary")
def get_summary():
    return store.get_summary()


@app.get("/api/alerts")
def get_alerts():
    return store.get_alerts()


@app.get("/api/history/{switch_id}")
def get_history(switch_id: int):
    return store.get_history(switch_id)


@app.get("/api/snapshot/{cam_id}")
def get_snapshot(cam_id: int):
    data = store.get_snapshot(cam_id)
    if data is None:
        return Response(status_code=204)
    return Response(content=data, media_type="image/jpeg")


# ── OCR debug ────────────────────────────────────────────────────────────────

@app.get("/api/debug/ocr/{cam_id}/{kind}")
def debug_ocr_image(cam_id: int, kind: str):
    """Return ROI or threshold debug image saved by LedLocator.
    kind: 'roi' | 'thresh'
    """
    import os
    debug_dir = os.path.join(os.path.dirname(__file__), "debug")
    path = os.path.join(debug_dir, f"{kind}_{cam_id}.jpg")
    if not os.path.exists(path):
        return Response(status_code=404)
    with open(path, "rb") as f:
        return Response(content=f.read(), media_type="image/jpeg")


# ── MJPEG stream ──────────────────────────────────────────────────────────────

@app.get("/api/stream/{cam_id}")
async def mjpeg_stream(cam_id: int):
    if not 0 <= cam_id < 5:
        return Response(status_code=404)
    loop = asyncio.get_event_loop()
    q    = broadcasters[cam_id].subscribe(loop)

    async def generate():
        try:
            while True:
                frame = await q.get()   # pure async wait — no thread consumed
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n"
                    + frame +
                    b"\r\n"
                )
        finally:
            broadcasters[cam_id].unsubscribe(q)

    return StreamingResponse(
        generate(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-cache"},
    )


# ── WebSocket ─────────────────────────────────────────────────────────────────

@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    q: asyncio.Queue = asyncio.Queue(maxsize=4)
    _client_queues.add(q)
    try:
        async def sender():
            while True:
                msg = await q.get()
                await ws.send_text(msg)

        async def receiver():
            while True:
                await ws.receive()   # absorb any message type (text or binary pings)

        await asyncio.gather(sender(), receiver())
    except (WebSocketDisconnect, Exception) as e:
        logger.warning("WS closed: %s %s", type(e).__name__, e)
    finally:
        _client_queues.discard(q)


# ── Static GUI — must be mounted last ─────────────────────────────────────────

app.mount("/", StaticFiles(directory="gui", html=True), name="gui")


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=5001, reload=False)
