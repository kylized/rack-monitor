"""Per-camera MJPEG frame broadcaster: ingester threads push, async HTTP clients subscribe."""

import asyncio
import threading
import time
from collections import deque


class FrameBroadcaster:
    _WINDOW = 3.0  # seconds for rolling fps / kbps average

    def __init__(self):
        self._lock   = threading.Lock()
        self._subs:  list[tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = []
        self._times: deque = deque()
        self._sizes: deque = deque()
        self.fps:    float = 0.0
        self.kbps:   float = 0.0

    def subscribe(self, loop: asyncio.AbstractEventLoop) -> asyncio.Queue:
        """Call from async context. Returns an asyncio.Queue for the caller to await."""
        q: asyncio.Queue = asyncio.Queue(maxsize=2)
        with self._lock:
            self._subs.append((loop, q))
        return q

    def unsubscribe(self, q: asyncio.Queue):
        with self._lock:
            self._subs = [(l, sq) for l, sq in self._subs if sq is not q]

    def publish(self, frame: bytes):
        """Call from ingester thread. Thread-safe; schedules puts on each subscriber's loop."""
        now    = time.monotonic()
        cutoff = now - self._WINDOW
        with self._lock:
            self._times.append(now)
            self._sizes.append((now, len(frame)))
            while self._times and self._times[0] < cutoff:
                self._times.popleft()
            while self._sizes and self._sizes[0][0] < cutoff:
                self._sizes.popleft()
            self.fps  = len(self._times) / self._WINDOW
            self.kbps = sum(s for _, s in self._sizes) / self._WINDOW / 1024

            for loop, q in list(self._subs):
                def _put(q=q, frame=frame):
                    try:
                        q.put_nowait(frame)
                    except asyncio.QueueFull:
                        try:
                            q.get_nowait()       # drop oldest, keep freshest
                            q.put_nowait(frame)
                        except Exception:
                            pass
                loop.call_soon_threadsafe(_put)


broadcasters: list[FrameBroadcaster] = [FrameBroadcaster() for _ in range(5)]
