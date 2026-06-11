"""RTSP stream ingestion: one thread per camera, feeds analyzer + snapshot store."""

import logging
import threading
import time

import cv2
import numpy as np

from analyzer import analyze_frame
from broadcaster import broadcasters
from state_store import StateStore
from timeseries import TimeSeriesAnalyzer

logger = logging.getLogger(__name__)

RTSP_URLS     = [f"rtsp://localhost:8554/cam{i}" for i in range(5)]
ANALYSIS_FPS  = 5    # frames sent to CV analyzer per second (≥4 needed for blink detection)
SNAPSHOT_FPS  = 10   # thumbnail refresh rate


def _jpeg(frame: np.ndarray) -> bytes:
    thumb = cv2.resize(frame, (320, 180))
    ok, buf = cv2.imencode(".jpg", thumb, [cv2.IMWRITE_JPEG_QUALITY, 72])
    return buf.tobytes() if ok else b""


class CameraIngester:
    def __init__(self, cam_id: int, store: StateStore, ts: TimeSeriesAnalyzer):
        self.cam_id  = cam_id
        self.url     = RTSP_URLS[cam_id]
        self.store   = store
        self.ts      = ts
        self.running = False
        self._thread: threading.Thread | None = None

    def start(self):
        self.running = True
        self._thread = threading.Thread(
            target=self._run, daemon=True, name=f"ingest-{self.cam_id}"
        )
        self._thread.start()

    def stop(self):
        self.running = False

    def _run(self):
        while self.running:
            cap = self._connect()
            if cap is None:
                time.sleep(3)
                continue

            logger.info("CAM-%d connected", self.cam_id)
            t_analysis = t_snapshot = 0.0

            while self.running:
                ok, frame = cap.read()
                if not ok:
                    logger.warning("CAM-%d lost, reconnecting…", self.cam_id)
                    break

                now = time.monotonic()

                if now - t_snapshot >= 1.0 / SNAPSHOT_FPS:
                    jpeg = _jpeg(frame)
                    self.store.set_snapshot(self.cam_id, jpeg)  # kept for REST /api/snapshot
                    broadcasters[self.cam_id].publish(jpeg)
                    t_snapshot = now

                if now - t_analysis >= 1.0 / ANALYSIS_FPS:
                    try:
                        state = analyze_frame(frame, self.cam_id, self.store)
                        self.store.update(state)
                        self.ts.process(state)
                    except Exception as exc:
                        logger.error("CAM-%d analysis: %s", self.cam_id, exc)
                    t_analysis = now

            cap.release()

    def _connect(self) -> cv2.VideoCapture | None:
        cap = cv2.VideoCapture(self.url, cv2.CAP_FFMPEG)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        if cap.isOpened():
            return cap
        cap.release()
        logger.debug("CAM-%d stream not available, retrying…", self.cam_id)
        return None


def start_all(store: StateStore, ts: TimeSeriesAnalyzer) -> list[CameraIngester]:
    ingesters = [CameraIngester(i, store, ts) for i in range(5)]
    for ing in ingesters:
        ing.start()
    return ingesters
