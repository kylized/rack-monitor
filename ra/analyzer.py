"""
Per-frame LED analysis pipeline:

  1. LedLocator.get()     — returns {label: (x0,y0,x1,y1)} from cached OCR,
                            or None while still calibrating.
  2. _detect_leds_precise — crops each LED dot box, runs HSV colour detection.
  3. _apply_blink         — promotes solid colours to blink-* when the LED
                            history shows on/off alternation.
  4. _derive_state        — OFFLINE if PWR off; FAULT if any red; WARNING if
                            any amber; otherwise NORMAL.

Fallback: if LedLocator has not yet calibrated, _detect_leds_fallback splits
the frame by fixed percentages so the system still produces output.
"""

from datetime import datetime

import cv2
import numpy as np

from led_locator import LED_LABELS, LedLocator
from state_store import LEDState, StateStore, SwitchState

# ── HSV colour ranges (OpenCV H 0-180, S 0-255, V 0-255) ─────────────────────
# Simulator palette: green #00e676, amber #ffab00, red #ff1744
_HSV: dict[str, tuple[np.ndarray, np.ndarray]] = {
    "green":  (np.array([38,  80,  80]),  np.array([88,  255, 255])),
    "amber":  (np.array([12, 100, 100]),  np.array([32,  255, 255])),
    "red_lo": (np.array([0,  100, 100]),  np.array([10,  255, 255])),
    "red_hi": (np.array([168,100, 100]),  np.array([180, 255, 255])),
}

# Fallback layout (percentage of frame) used when OCR detection fails
_FB_SYS_X = (0.17, 0.42)
_FB_SYS_Y = (0.22, 0.90)

_locator = LedLocator()


# ── colour helpers ────────────────────────────────────────────────────────────

def _dominant_color(region: np.ndarray) -> str:
    """Return dominant colour name ('green'/'amber'/'red'/'off') for a crop."""
    if region.size == 0:
        return "off"
    hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
    counts: dict[str, int] = {}
    for name, (lo, hi) in _HSV.items():
        counts[name] = int(cv2.inRange(hsv, lo, hi).sum() // 255)
    counts["red"] = counts.pop("red_lo", 0) + counts.pop("red_hi", 0)
    total = sum(counts.values())
    if total < 5:
        return "off"
    best = max(counts, key=counts.get)
    return best if counts[best] > 3 else "off"


# ── LED detection ─────────────────────────────────────────────────────────────

def _detect_leds_precise(
    frame: np.ndarray,
    boxes: dict[str, tuple[int, int, int, int]],
) -> dict[str, str]:
    """Crop each LED dot exactly and detect its colour."""
    h, w = frame.shape[:2]
    colours: dict[str, str] = {}
    for label in LED_LABELS:
        if label not in boxes:
            colours[label] = "off"
            continue
        x0, y0, x1, y1 = boxes[label]
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(w, x1), min(h, y1)
        colours[label] = _dominant_color(frame[y0:y1, x0:x1])
    return colours


def _detect_leds_fallback(frame: np.ndarray) -> dict[str, str]:
    """Old percentage-split method — used when OCR localisation fails."""
    h, w = frame.shape[:2]
    x0 = int(w * _FB_SYS_X[0]); x1 = int(w * _FB_SYS_X[1])
    y0 = int(h * _FB_SYS_Y[0]); y1 = int(h * _FB_SYS_Y[1])
    region = frame[y0:y1, x0:x1]
    rh, rw = region.shape[:2]
    slice_w = max(1, rw // 6)
    colours: dict[str, str] = {}
    for i, label in enumerate(LED_LABELS):
        cell = region[:, i * slice_w: (i + 1) * slice_w]
        colours[label] = _dominant_color(cell)
    return colours


def _apply_blink(
    colours: dict[str, str],
    switch_id: int,
    store: StateStore,
) -> dict[str, str]:
    """
    Add a 'blink-' prefix to any LED whose colour history shows alternation
    between a colour and off.
    """
    result = dict(colours)
    for label, colour in colours.items():
        if colour != "off" and store.is_blinking(switch_id, label):
            result[label] = f"blink-{colour}"
    return result


# ── state derivation ──────────────────────────────────────────────────────────

def _derive_state(colours: dict[str, str]) -> str:
    if colours.get("PWR", "off") == "off":
        return "OFFLINE"
    base = {c.replace("blink-", "") for c in colours.values()}
    if "red"   in base: return "FAULT"
    if "amber" in base: return "WARNING"
    return "NORMAL"


# ── public entry point ────────────────────────────────────────────────────────

def analyze_frame(
    frame_bgr: np.ndarray,
    cam_id: int,
    store: StateStore,
) -> SwitchState:
    # ── 1. Locate LEDs via OCR ───────────────────────────────────────────────
    boxes = _locator.get(frame_bgr, cam_id)

    if boxes:
        raw_colours      = _detect_leds_precise(frame_bgr, boxes)
        detected_labels  = list(boxes.keys())          # OCR-found labels, in x-order
        locator_status   = "calibrated"
    else:
        raw_colours      = _detect_leds_fallback(frame_bgr)
        detected_labels  = LED_LABELS[:]               # fallback: use all standard names
        locator_status   = "fallback"

    # ── 2. Record raw colours, then apply blink detection ───────────────────
    raw_leds      = LEDState(**raw_colours)
    store.record_led(cam_id + 1, raw_leds)
    final_colours = _apply_blink(raw_colours, cam_id + 1, store)

    return SwitchState(
        switch_id       = cam_id + 1,
        cam_id          = cam_id,
        state           = _derive_state(final_colours),
        leds            = LEDState(**final_colours),
        port_up_ratio   = 0.0,
        detected_labels = detected_labels,
        locator_status  = locator_status,
        timestamp       = datetime.now().strftime("%H:%M:%S"),
    )
