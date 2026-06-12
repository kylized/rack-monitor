"""
LED locator — two-stage pipeline:

  Stage 1 (Geometry)  : find white-text blobs in the frame, sort left→right
                        to locate each label's pixel position reliably.
  Stage 2 (Identity)  : run tesseract PSM-8 (single-word) on each individual
                        blob crop to read the actual label name dynamically.

Simulator CSS (updated to white #ffffff, 9 px font):
    .led-group { flex-direction:column; align-items:center; gap:4px }
    .led-dot   { width:11px; height:11px; border-radius:50% }
    .led-name  { font-size:9px; color:#ffffff }
"""

import logging
import os
import time
from typing import Optional

import cv2
import numpy as np
import pytesseract

logger = logging.getLogger(__name__)

LED_LABELS   = ["PWR", "SYS", "FAN", "TEMP", "POE", "MGMT"]
_DOT_D_CSS   = 11   # dot diameter  (CSS px)
_GAP_CSS     = 4    # dot-to-label gap (CSS px)
_LABEL_H_CSS = 9    # label font height (CSS px)

_RETRY_INTERVAL = 3.0          # seconds between OCR attempts per camera
_DEBUG_DIR = os.path.join(os.path.dirname(__file__), "debug")
os.makedirs(_DEBUG_DIR, exist_ok=True)


class LedLocator:
    def __init__(self):
        self._cache:        dict[int, dict[str, tuple]] = {}
        self._last_attempt: dict[int, float]            = {}

    def get(self, frame: np.ndarray, cam_id: int
            ) -> Optional[dict[str, tuple[int, int, int, int]]]:
        if cam_id in self._cache:
            return self._cache[cam_id]
        now = time.monotonic()
        if now - self._last_attempt.get(cam_id, 0) < _RETRY_INTERVAL:
            return None
        self._last_attempt[cam_id] = now
        boxes = self._detect(frame, cam_id)
        if boxes and len(boxes) >= 4:
            self._cache[cam_id] = boxes
            logger.info("CAM-%d OCR calibrated (%d/6 labels): %s",
                        cam_id, len(boxes), list(boxes.keys()))
        else:
            logger.info("CAM-%d OCR attempt: %d labels found %s",
                        cam_id, len(boxes), list(boxes.keys()) if boxes else "[]")
        return self._cache.get(cam_id)

    def invalidate(self, cam_id: int):
        self._cache.pop(cam_id, None)
        self._last_attempt.pop(cam_id, None)

    # ── main detection ─────────────────────────────────────────────────────────

    def _detect(self, frame: np.ndarray, cam_id: int
                ) -> dict[str, tuple[int, int, int, int]]:
        h, w = frame.shape[:2]
        roi_y0 = int(h * 0.20)
        roi_y1 = int(h * 0.98)
        roi    = frame[roi_y0:roi_y1]

        # ── upscale + extract white text ──────────────────────────────────────
        SCALE = 3
        big   = cv2.resize(roi, None, fx=SCALE, fy=SCALE,
                           interpolation=cv2.INTER_CUBIC)
        gray  = cv2.cvtColor(big, cv2.COLOR_BGR2GRAY)

        # White text on dark background → simple threshold keeps white pixels
        _, white_mask = cv2.threshold(gray, 180, 255, cv2.THRESH_BINARY)

        # ── Stage 1: find label row by horizontal projection ──────────────────
        row_sums = np.sum(white_mask > 0, axis=1).astype(float)
        # Smooth over a window = ~2× label height to find the dense row band
        win = max(1, int(SCALE * _LABEL_H_CSS * 2))
        kernel = np.ones(win) / win
        smoothed = np.convolve(row_sums, kernel, mode='same')

        peak = smoothed.max()
        if peak < 10:
            logger.info("CAM-%d no white text found in ROI", cam_id)
            _save_debug(big, white_mask, cam_id)
            return {}

        # Keep the y-band that contains the label row
        threshold = peak * 0.35
        in_band   = smoothed > threshold
        band_rows = np.where(in_band)[0]
        y0b = max(0,          band_rows[0]  - SCALE * 4)
        y1b = min(big.shape[0], band_rows[-1] + SCALE * 10)

        label_strip = white_mask[y0b:y1b, :]   # narrow horizontal band

        # ── Stage 1b: isolate label blobs via horizontal dilation ─────────────
        # Kernel width merges characters within one label but (hopefully) not
        # across adjacent labels. Labels are ~3-4 chars × ~7px = ~21-28px CSS
        # → at SCALE=3: ~63-84px per label; inter-label gap ~10-20px × SCALE.
        # Use kernel = 12 × SCALE to bridge intra-label gaps but leave
        # inter-label gaps intact.
        kern_w  = int(SCALE * 12)
        kernel  = cv2.getStructuringElement(cv2.MORPH_RECT, (kern_w, 1))
        dilated = cv2.dilate(label_strip, kernel)

        n, _, stats, centroids = cv2.connectedComponentsWithStats(
            dilated, connectivity=8)

        blobs = []
        for i in range(1, n):
            bw   = stats[i, cv2.CC_STAT_WIDTH]
            bh   = stats[i, cv2.CC_STAT_HEIGHT]
            area = stats[i, cv2.CC_STAT_AREA]
            bx   = stats[i, cv2.CC_STAT_LEFT]
            by   = stats[i, cv2.CC_STAT_TOP] + y0b   # back to big-frame coords
            # Filter noise: must be wide enough to be ≥1 label word
            if bw > SCALE * 8 and area > SCALE * SCALE * 5:
                blobs.append({
                    'bx': bx, 'by': by, 'bw': bw, 'bh': bh,
                    'cx': int(centroids[i][0]),
                    'cy': int(centroids[i][1]) + y0b,
                })

        # Sort left → right
        blobs.sort(key=lambda b: b['bx'])

        if len(blobs) == 0:
            logger.info("CAM-%d no label blobs found", cam_id)
            _save_debug(big, dilated, cam_id)
            return {}

        # Save debug images
        _save_debug(roi, dilated, cam_id)

        # ── Stage 2: OCR sanity check + anchor detection ──────────────────────
        # OCR is unreliable at small font sizes; use it to:
        #   a) confirm this is actually the LED label strip (≥ 2 matches)
        #   b) find an anchor blob when blob count ≠ 6 (extra/missing blobs)
        ocr_confirmed = 0
        ocr_matched: list[Optional[str]] = []   # matched label or None per blob

        for blob in blobs[:8]:
            pad = SCALE * 4
            cx0 = max(0,            blob['bx'] - pad)
            cx1 = min(big.shape[1], blob['bx'] + blob['bw'] + pad)
            cy0 = max(0,            blob['by'] - pad)
            cy1 = min(big.shape[0], blob['by'] + blob['bh'] + pad)
            crop_gray = gray[cy0:cy1, cx0:cx1]
            if crop_gray.size == 0:
                ocr_matched.append(None)
                continue
            _, crop_thresh = cv2.threshold(
                crop_gray, 140, 255, cv2.THRESH_BINARY_INV)
            raw = pytesseract.image_to_string(
                crop_thresh,
                config="--psm 8 --oem 3 "
                       "-c tessedit_char_whitelist=PWRSYFANTEMPOEMG"
            ).strip().upper()
            label = _best_match(raw)
            ocr_matched.append(label)
            if label:
                ocr_confirmed += 1

        logger.info("CAM-%d OCR sanity (%d/6 confirmed): %s",
                    cam_id, ocr_confirmed, ocr_matched)

        if ocr_confirmed < 2:
            logger.info("CAM-%d OCR sanity check failed — not the LED strip", cam_id)
            return {}

        # ── Stage 3: Positional assignment with anchor correction ─────────────
        # Label order is fixed: PWR SYS FAN TEMP POE MGMT (left→right).
        # When blob count == 6, assign directly by index.
        # When count > 6 (extra noise blobs), use OCR anchor to find the true
        # start index: if blob[bidx] OCR-matched LED_LABELS[lidx], then
        # the PWR blob is at start = bidx - lidx.
        start_idx = 0
        n_blobs   = len(blobs)

        if n_blobs != len(LED_LABELS):
            for bidx, matched in enumerate(ocr_matched):
                if matched is None:
                    continue
                lidx = LED_LABELS.index(matched)
                candidate = bidx - lidx
                if 0 <= candidate <= n_blobs - len(LED_LABELS):
                    start_idx = candidate
                    logger.info("CAM-%d %d blobs detected, anchor '%s' at blob %d "
                                "→ start_idx=%d",
                                cam_id, n_blobs, matched, bidx, start_idx)
                    break

        n     = min(n_blobs - start_idx, len(LED_LABELS))
        found: dict[str, tuple[int, int, int, int]] = {}

        for idx in range(n):
            blob  = blobs[start_idx + idx]
            label = LED_LABELS[idx]

            orig_cx = blob['cx'] // SCALE
            orig_cy = blob['cy'] // SCALE + roi_y0
            orig_h  = max(1, blob['bh'] // SCALE)

            px_per_css = orig_h / _LABEL_H_CSS
            dot_r  = max(5, int(_DOT_D_CSS * px_per_css / 2))
            gap_px = max(2, int(_GAP_CSS   * px_per_css))
            pad_r  = max(4, dot_r // 2)

            dot_cx = orig_cx
            dot_cy = orig_cy - gap_px - dot_r

            if dot_cy >= 0:
                found[label] = (
                    dot_cx - dot_r - pad_r, dot_cy - dot_r - pad_r,
                    dot_cx + dot_r + pad_r, dot_cy + dot_r + pad_r,
                )

        return found


# ── helpers ───────────────────────────────────────────────────────────────────

def _best_match(raw: str) -> Optional[str]:
    """Return the LED label that best matches the raw OCR string."""
    if raw in LED_LABELS:
        return raw
    # Allow single char substitutions for short labels
    for label in LED_LABELS:
        if raw == label:
            return label
        # Accept if ≥ half the characters match in order
        overlap = sum(1 for a, b in zip(raw, label) if a == b)
        if overlap >= max(2, len(label) - 1):
            return label
    return None


def _save_debug(roi: np.ndarray, processed: np.ndarray, cam_id: int):
    cv2.imwrite(os.path.join(_DEBUG_DIR, f"roi_{cam_id}.jpg"),
                cv2.resize(roi, None, fx=2, fy=2,
                           interpolation=cv2.INTER_NEAREST))
    cv2.imwrite(os.path.join(_DEBUG_DIR, f"thresh_{cam_id}.jpg"), processed)
