"""Screen-region capture → FFmpeg → RTSP push (one instance per camera)."""

import subprocess
import threading
import time
import logging

import mss
import numpy as np

logger = logging.getLogger(__name__)


class CameraCapture:
    def __init__(self, cam_id: int, rtsp_url: str, fps: int = 10):
        self.cam_id = cam_id
        self.rtsp_url = rtsp_url
        self.fps = fps
        self.region: dict | None = None   # {left, top, width, height}
        self.running = False
        self.actual_fps = 0.0
        self._proc: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    # ── public API ─────────────────────────────────────────────────────────

    def set_region(self, left: int, top: int, width: int, height: int):
        self.region = dict(left=left, top=top, width=max(2, width), height=max(2, height))

    def start(self) -> bool:
        if self.running or self.region is None:
            return False
        self.running = True
        self.actual_fps = 0.0
        self._thread = threading.Thread(
            target=self._run, daemon=True, name=f"cap-{self.cam_id}"
        )
        self._thread.start()
        return True

    def stop(self):
        self.running = False
        with self._lock:
            if self._proc:
                try:
                    self._proc.stdin.close()
                    self._proc.wait(timeout=3)
                except Exception:
                    self._proc.kill()
                self._proc = None

    def update_region(self, left: int, top: int, width: int, height: int):
        """Move/resize; restart FFmpeg only when dimensions change."""
        new = dict(left=left, top=top, width=max(2, width), height=max(2, height))
        size_changed = (
            self.region is None
            or new["width"] != self.region["width"]
            or new["height"] != self.region["height"]
        )
        if size_changed and self.running:
            self.stop()
            self.region = new
            self.start()
        else:
            self.region = new

    # ── internal ───────────────────────────────────────────────────────────

    def _ffmpeg_cmd(self, w: int, h: int) -> list[str]:
        return [
            "ffmpeg", "-y",
            "-f", "rawvideo", "-vcodec", "rawvideo",
            "-s", f"{w}x{h}", "-pix_fmt", "bgr24",
            "-r", str(self.fps),
            "-i", "pipe:0",
            "-vf", f"scale=1920:1080,format=yuv420p",
            "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency",
            "-g", str(self.fps * 2),
            "-f", "rtsp", "-rtsp_transport", "tcp",
            self.rtsp_url,
        ]

    def _run(self):
        r = self.region
        w, h = r["width"], r["height"]
        cmd = self._ffmpeg_cmd(w, h)

        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            logger.error("ffmpeg not found — install FFmpeg and add it to PATH")
            self.running = False
            return

        with self._lock:
            self._proc = proc

        sct = mss.mss()
        interval = 1.0 / self.fps
        frame_count = 0
        t_start = time.monotonic()

        while self.running:
            t0 = time.monotonic()
            try:
                shot = sct.grab(self.region)
                frame = np.asarray(shot)[:, :, :3]          # BGRA → BGR
                proc.stdin.write(frame.tobytes())
                frame_count += 1
                dt = time.monotonic() - t_start
                self.actual_fps = frame_count / dt if dt > 0 else 0.0
            except (BrokenPipeError, OSError):
                break
            except Exception as exc:
                logger.warning("CAM-%d capture: %s", self.cam_id, exc)
                break

            sleep_t = interval - (time.monotonic() - t0)
            if sleep_t > 0:
                time.sleep(sleep_t)

        sct.close()
        self.running = False
        self.actual_fps = 0.0
        with self._lock:
            if self._proc is proc:
                try:
                    proc.stdin.close()
                except Exception:
                    pass
                self._proc = None
