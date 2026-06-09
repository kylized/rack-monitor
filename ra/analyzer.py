"""CV frame analysis: HSV LED color detection → SwitchState."""

from datetime import datetime

import cv2
import numpy as np

from state_store import LEDState, SwitchState

# ── HSV color ranges (OpenCV: H 0-180, S 0-255, V 0-255) ─────────────────────
# Simulator colors: green #00e676, amber #ffab00, red #ff1744
_HSV = {
    "green": (np.array([38,  80,  80]),  np.array([88,  255, 255])),
    "amber": (np.array([12, 100, 100]),  np.array([32,  255, 255])),
    "red_lo":(np.array([0,  100, 100]),  np.array([10,  255, 255])),
    "red_hi":(np.array([168,100, 100]),  np.array([180, 255, 255])),
}

LED_NAMES = ["PWR", "SYS", "FAN", "TEMP", "POE", "MGMT"]

# ROI layout as fractions of frame dimensions
# Simulator front-panel zones (approximate, accounts for title-bar offset):
#   sw-label  : x  0%–17%
#   sys-leds  : x 17%–42%   ← 6 LEDs, equally spaced
#   port-sect : x 42%–88%
#   (title bar from native overlay: top ~20% of frame height)
_SYS_X  = (0.17, 0.42)
_SYS_Y  = (0.22, 0.90)   # start below overlay title bar (~22% of frame)
_PORT_X = (0.42, 0.88)
_PORT_Y = (0.22, 0.90)


def _dominant_color(region: np.ndarray) -> str:
    if region.size == 0:
        return "off"
    hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
    counts: dict[str, int] = {}
    for name, (lo, hi) in _HSV.items():
        mask = cv2.inRange(hsv, lo, hi)
        counts[name] = int(mask.sum() // 255)
    counts["red"] = counts.pop("red_lo", 0) + counts.pop("red_hi", 0)
    total = sum(counts.values())
    if total < 15:
        return "off"
    best = max(counts, key=counts.get)
    return best if counts[best] > 8 else "off"


def _detect_leds(region: np.ndarray) -> LEDState:
    """Split sys-led region into 6 horizontal slices → detect each LED color."""
    if region.size == 0:
        return LEDState()
    h, w = region.shape[:2]
    slice_w = max(1, w // 6)
    colors = []
    for i in range(6):
        x0 = i * slice_w
        cell = region[:, x0: x0 + slice_w]
        colors.append(_dominant_color(cell))
    return LEDState(**dict(zip(LED_NAMES, colors)))


def _detect_ports(region: np.ndarray) -> tuple[float, float]:
    """Return (up_ratio, err_ratio) from port section frame."""
    if region.size == 0:
        return 0.0, 0.0
    hsv   = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
    total = region.shape[0] * region.shape[1]
    green = int(cv2.inRange(hsv, *_HSV["green"]).sum() // 255)
    amber = int(cv2.inRange(hsv, *_HSV["amber"]).sum() // 255)
    ref   = max(1, total * 0.08)
    return round(min(1.0, green / ref), 3), round(min(1.0, amber / ref), 3)


def _derive_state(led: LEDState, err_ratio: float) -> str:
    if led.PWR == "off":
        return "OFFLINE"
    if any(getattr(led, n) == "red" for n in LED_NAMES):
        return "FAULT"
    if any(getattr(led, n) == "amber" for n in LED_NAMES) or err_ratio > 0.25:
        return "WARNING"
    return "NORMAL"


def _anomaly_score(led: LEDState, err_ratio: float) -> float:
    weights = {"PWR": 0.25, "SYS": 0.25, "FAN": 0.20, "TEMP": 0.15, "POE": 0.10, "MGMT": 0.05}
    cv_map  = {"off": 0.0, "green": 0.0, "amber": 0.5, "red": 1.0}
    score   = sum(weights[n] * cv_map.get(getattr(led, n), 0.3) for n in LED_NAMES)
    score  += err_ratio * 0.25
    return round(min(1.0, score), 3)


def analyze_frame(frame_bgr: np.ndarray, cam_id: int) -> SwitchState:
    h, w = frame_bgr.shape[:2]

    def crop(xr, yr):
        return frame_bgr[int(h * yr[0]): int(h * yr[1]),
                         int(w * xr[0]): int(w * xr[1])]

    led  = _detect_leds(crop(_SYS_X, _SYS_Y))
    up_r, err_r = _detect_ports(crop(_PORT_X, _PORT_Y))

    return SwitchState(
        switch_id     = cam_id + 1,
        cam_id        = cam_id,
        state         = _derive_state(led, err_r),
        leds          = led,
        port_up_ratio = up_r,
        port_err_ratio= err_r,
        anomaly_score = _anomaly_score(led, err_r),
        timestamp     = datetime.now().strftime("%H:%M:%S"),
    )
