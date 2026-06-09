"""Rack Analyzer — FastAPI backend (port 5000)."""

import asyncio
import json
import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

from ingester import start_all
from state_store import StateStore
from timeseries import TimeSeriesAnalyzer

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")

store    = StateStore(num_switches=5, window=60)
ts       = TimeSeriesAnalyzer(store)
_clients: set[WebSocket] = set()


async def _broadcast():
    while True:
        await asyncio.sleep(1)
        if not _clients:
            continue
        payload = json.dumps({
            "switches": store.get_all_states(),
            "summary":  store.get_summary(),
            "alerts":   store.get_alerts(limit=10),
            "history":  {str(i + 1): store.get_history(i + 1) for i in range(5)},
        }, default=str)
        dead = set()
        for ws in list(_clients):
            try:
                await ws.send_text(payload)
            except Exception:
                dead.add(ws)
        _clients -= dead


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


# ── WebSocket ─────────────────────────────────────────────────────────────────

@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    _clients.add(ws)
    try:
        while True:
            await ws.receive_text()       # keep-alive pings from client
    except WebSocketDisconnect:
        _clients.discard(ws)


# ── Static GUI — must be mounted last ─────────────────────────────────────────

app.mount("/", StaticFiles(directory="gui", html=True), name="gui")


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=5000, reload=False)
