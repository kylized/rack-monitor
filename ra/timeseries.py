"""Rule-based time-series analyzer (Phase-1). Phase-2 LSTM slot is here."""

import threading
from state_store import SwitchState, Alert, StateStore
from datetime import datetime

_FAULT_FRAMES   = 3   # consecutive fault frames before alert fires
_WARN_FRAMES    = 5   # consecutive warning frames before alert fires


class TimeSeriesAnalyzer:
    def __init__(self, store: StateStore):
        self.store   = store
        self._lock   = threading.Lock()
        self._consec: list[dict] = [{"fault": 0, "warning": 0} for _ in range(store.num_switches)]
        self._active: list[set]  = [set() for _ in range(store.num_switches)]

    def process(self, state: SwitchState):
        idx = state.switch_id - 1
        with self._lock:
            c, active = self._consec[idx], self._active[idx]

            if state.state == "FAULT":
                c["fault"]   += 1
                c["warning"]  = 0
                if c["fault"] >= _FAULT_FRAMES and "FAULT" not in active:
                    active.add("FAULT")
                    self._alert(state, "FAULT_DETECTED")

            elif state.state == "WARNING":
                c["warning"] += 1
                c["fault"]    = 0
                if "FAULT" in active:
                    active.discard("FAULT")
                    self._alert(state, "FAULT_CLEARED")
                if c["warning"] >= _WARN_FRAMES and "WARNING" not in active:
                    active.add("WARNING")
                    self._alert(state, "WARNING_DETECTED")

            else:  # NORMAL / OFFLINE / UNKNOWN
                if "FAULT" in active:
                    active.discard("FAULT")
                    self._alert(state, "FAULT_CLEARED")
                if "WARNING" in active:
                    active.discard("WARNING")
                    self._alert(state, "WARNING_CLEARED")
                c["fault"] = c["warning"] = 0

    def _alert(self, state: SwitchState, kind: str):
        from dataclasses import asdict
        leds_dict  = asdict(state.leds)
        fault_leds = [
            label for label in state.detected_labels
            if leds_dict.get(label, "off").replace("blink-", "") in ("red", "amber")
        ]
        self.store.add_alert(Alert(
            switch_id  = state.switch_id,
            cam_id     = state.cam_id,
            kind       = kind,
            fault_leds = fault_leds,
            timestamp  = datetime.now().strftime("%H:%M:%S"),
            resolved   = "CLEARED" in kind,
        ))
