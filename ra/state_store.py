"""In-memory state store: latest switch states + alert queue + snapshots."""

import threading
from collections import deque
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class LEDState:
    PWR:  str = "off"
    SYS:  str = "off"
    FAN:  str = "off"
    TEMP: str = "off"
    POE:  str = "off"
    MGMT: str = "off"


@dataclass
class SwitchState:
    switch_id:        int       = 0
    cam_id:           int       = 0
    state:            str       = "UNKNOWN"   # NORMAL | WARNING | FAULT | OFFLINE | UNKNOWN
    leds:             LEDState  = field(default_factory=LEDState)
    port_up_ratio:    float     = 0.0
    detected_labels:  list      = field(default_factory=list)  # OCR-found label names, in order
    locator_status:   str       = "searching"                  # calibrated | fallback | searching
    timestamp:        str       = ""


@dataclass
class Alert:
    switch_id:  int
    cam_id:     int
    kind:       str   # FAULT_DETECTED | FAULT_CLEARED | WARNING_DETECTED | WARNING_CLEARED
    fault_leds: list  # which LED labels triggered this alert, e.g. ["FAN", "TEMP"]
    timestamp:  str
    resolved:   bool = False


_LED_NAMES    = list(LEDState.__dataclass_fields__)
_BLINK_WINDOW = 10


class StateStore:
    def __init__(self, num_switches: int = 5, window: int = 60):
        self._lock        = threading.Lock()
        self.num_switches = num_switches
        self.latest:   list[Optional[SwitchState]] = [None] * num_switches
        self.history:  list[deque]                 = [deque(maxlen=window) for _ in range(num_switches)]
        self.alerts:   deque[Alert]                = deque(maxlen=100)
        self.snapshots: list[Optional[bytes]]      = [None] * num_switches
        self._led_history: list[dict[str, deque]]  = [
            {label: deque(maxlen=_BLINK_WINDOW) for label in _LED_NAMES}
            for _ in range(num_switches)
        ]

    def update(self, state: SwitchState):
        with self._lock:
            idx = state.switch_id - 1
            self.latest[idx] = state
            self.history[idx].append(state)

    def add_alert(self, alert: Alert):
        with self._lock:
            self.alerts.appendleft(alert)

    def record_led(self, switch_id: int, leds: LEDState):
        with self._lock:
            hist = self._led_history[switch_id - 1]
            for label in _LED_NAMES:
                hist[label].append(getattr(leds, label))

    def is_blinking(self, switch_id: int, label: str) -> bool:
        with self._lock:
            hist = self._led_history[switch_id - 1][label]
            if len(hist) < 3:
                return False
            colours = set(hist)
            return "off" in colours and len(colours) >= 2

    def set_snapshot(self, cam_id: int, jpeg: bytes):
        with self._lock:
            self.snapshots[cam_id] = jpeg

    def get_snapshot(self, cam_id: int) -> Optional[bytes]:
        with self._lock:
            return self.snapshots[cam_id]

    def get_all_states(self) -> list:
        with self._lock:
            return [asdict(s) if s else None for s in self.latest]

    def get_alerts(self, limit: int = 30) -> list:
        with self._lock:
            return [asdict(a) for a in list(self.alerts)[:limit]]

    def get_summary(self) -> dict:
        with self._lock:
            c = dict(normal=0, warning=0, fault=0, unknown=0)
            for s in self.latest:
                if   s is None:            c["unknown"] += 1
                elif s.state == "NORMAL":  c["normal"]  += 1
                elif s.state == "WARNING": c["warning"] += 1
                elif s.state == "FAULT":   c["fault"]   += 1
                else:                      c["unknown"]  += 1
            return c
