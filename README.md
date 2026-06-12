# Rack Monitor

A camera-based rack monitoring system. Physical cameras (or screen-capture overlays) watch rack device LEDs in real time — replacing the need for a human to periodically inspect the rack.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  Rack Simulator (browser)   index.html / simulator.js / style.css│
│  8 virtual switches with animated LEDs, white label text         │
└────────────────────────┬────────────────────────────────────────┘
                         │ screen capture (PyQt6 overlay)
┌────────────────────────▼────────────────────────────────────────┐
│  Native App  native_app/                                         │
│  ├ main.py          — 5 draggable camera overlay windows         │
│  ├ control_panel.py — checkbox per camera, Start/Stop All        │
│  └ capture.py       — screen region → RTSP via FFmpeg @ 24 fps  │
└────────────────────────┬────────────────────────────────────────┘
                         │ RTSP  rtsp://localhost:8554/cam{0..4}
┌────────────────────────▼────────────────────────────────────────┐
│  MediaMTX   mediamtx/mediamtx.yml    (port 8554)                 │
│  RTSP relay / buffer                                             │
└────────────────────────┬────────────────────────────────────────┘
                         │ OpenCV VideoCapture (RTSP)
┌────────────────────────▼────────────────────────────────────────┐
│  Rack Analyzer (RA)  ra/             (port 5001)                 │
│  ├ ingester.py      — per-camera RTSP reader thread @ 5 fps      │
│  ├ led_locator.py   — two-stage OCR: blob detect → PSM-8 label   │
│  ├ analyzer.py      — LED colour detection + blink history        │
│  ├ broadcaster.py   — asyncio MJPEG frame broadcaster             │
│  ├ state_store.py   — switch state + alert ring buffer            │
│  ├ timeseries.py    — rolling time-series analytics               │
│  ├ main.py          — FastAPI: WebSocket + MJPEG + REST           │
│  └ gui/             — dashboard (HTML/CSS/JS)                     │
└─────────────────────────────────────────────────────────────────┘
```

---

## Quick Start

```bash
./start.sh
```

Opens everything:
1. **MediaMTX** — RTSP server on port 8554
2. **RA backend** — FastAPI on port 5001
3. **Native App** — Camera control panel + 5 overlay windows
4. **Browser** — RA dashboard at `http://localhost:5001` and Simulator at `index.html`

Logs are written to `ra.log`, `mediamtx.log`, `native_app.log`.

---

## Components

### Rack Simulator

Browser-based simulator of a 19" rack with 8 network switches.

| Feature | Detail |
|---|---|
| **Rack view** | 8 × 1U switches in a 19" rack with rail markings |
| **System LEDs** | PWR, SYS, FAN, TEMP, PoE, MGMT — white labels for OCR visibility |
| **Port LEDs** | 24 ports per switch; blink during activity, amber on error |
| **State machine** | `OFFLINE → BOOTING → NORMAL ↔ WARNING ↔ FAULT → RESETTING` |
| **Master controls** | All Power ON/OFF, Reset All, Inject Fault, Toggle Status |

```bash
open index.html
# or
python3 -m http.server 8080
```

### Native App (`native_app/`)

PyQt6 application with:
- **5 draggable camera overlay windows** — position each over a switch panel in the simulator
- **Camera Control panel** — checkbox per camera (unchecked by default); Start All only starts checked cameras
- Captures screen region → pushes RTSP stream via FFmpeg @ 24 fps at the overlay's native aspect ratio (no stretching)

### Rack Analyzer (`ra/`)

FastAPI backend at `http://localhost:5001`.

**LED Detection Pipeline:**
1. RTSP frames ingested from mediamtx (5 fps analysis rate)
2. `LedLocator` runs a three-stage pipeline per camera (cached after first calibration):
   - Stage 1: upscale frame, white-pixel threshold, horizontal projection to find label row, dilation to isolate per-label blobs
   - Stage 2: tesseract PSM-8 sanity check — confirms ≥ 2 known labels are present; uses OCR anchor to correct for extra noise blobs
   - Stage 3: positional assignment — blobs sorted left→right map to `PWR SYS FAN TEMP POE MGMT`
3. Each LED dot box is derived from its label's text bounding box + CSS geometry constants
4. HSV colour detection per dot + rolling blink history → `NORMAL / WARNING / FAULT / OFFLINE`
5. Results broadcast via WebSocket to dashboard every 1 s

**API endpoints:**

| Endpoint | Description |
|---|---|
| `GET /` | RA dashboard |
| `WS /ws` | Live switch states + LED colours + cam stats (1 s tick) |
| `GET /api/stream/{cam_id}` | MJPEG stream (multipart/x-mixed-replace) |
| `GET /api/debug/ocr/{cam_id}/roi` | Label-strip ROI debug image |
| `GET /api/debug/ocr/{cam_id}/thresh` | Dilated blob mask debug image |
| `GET /api/switches` | Current switch states (JSON) |
| `GET /api/alerts` | Recent alert ring buffer |
| `GET /api/history/{switch_id}` | Rolling LED history |

**RA Dashboard layout (per camera row):**
```
[MJPEG feed]  |  [SW-0X  STATE  timestamp  ·  LED dots]  |  [OCR N/6  fault tags  fps · KB/s]
```
- LED labels rendered dynamically from `detected_labels` (OCR results) — never hardcoded
- Shows "OCR 校準中…" until ≥ 4 labels are detected; updates live as OCR calibrates
- After RA restart, open a fresh tab or press **Cmd+Shift+R** to clear the browser cache

### MediaMTX (`mediamtx/`)

RTSP relay server. Native app pushes `rtsp://localhost:8554/cam{0..4}`; RA ingester reads from the same URLs.

---

## Project Structure

```
rack_monitor/
├── index.html           # Rack Simulator shell
├── simulator.js         # Switch state machine + UI renderer
├── style.css            # Simulator dark theme (white LED labels for OCR)
├── start.sh             # One-click startup script
│
├── native_app/
│   ├── main.py          # Camera overlay windows (PyQt6), vertical layout
│   ├── control_panel.py # Camera control panel with per-camera checkboxes
│   └── capture.py       # Screen-region capture → FFmpeg RTSP push
│
├── ra/
│   ├── main.py          # FastAPI app (port 5001)
│   ├── ingester.py      # Per-camera RTSP reader threads
│   ├── led_locator.py   # Two-stage OCR LED locator
│   ├── analyzer.py      # LED colour detection + blink detection
│   ├── broadcaster.py   # asyncio MJPEG frame broadcaster
│   ├── state_store.py   # Switch state + alert storage
│   ├── timeseries.py    # Rolling analytics
│   ├── requirements.txt
│   └── gui/
│       ├── index.html   # Dashboard shell
│       ├── app.js       # WebSocket client + dynamic LED rendering
│       └── style.css    # Dashboard styles
│
└── mediamtx/
    └── mediamtx.yml     # RTSP server config
```

---

## Simulated Fault Types

| ID | Description | Severity |
|---|---|---|
| `FAN_WARN` | 風扇轉速異常 | WARNING |
| `FAN_FAIL` | 風扇故障停止 | FAULT |
| `TEMP_WARN` | 溫度過高 (>65°C) | WARNING |
| `TEMP_CRIT` | 嚴重過熱 (>85°C) | FAULT |
| `CPU_HIGH` | CPU 使用率過高 (>90%) | WARNING |
| `MEM_HIGH` | 記憶體使用率過高 (>85%) | WARNING |
| `PORT_ERR` | 連接埠 CRC 錯誤過多 | WARNING |
| `LINK_FLAP` | 連接埠 Link Flapping | WARNING |
| `POE_OVERLOAD` | PoE 功率超過預算 | WARNING |
| `HW_FAULT` | 硬體元件故障 | FAULT |
| `PWR_FAULT` | 電源模組故障 | FAULT |

---

## Requirements

- Python 3.11+, pip packages in `ra/requirements.txt`
- PyQt6 (`pip install PyQt6`)
- tesseract-ocr (`brew install tesseract`)
- FFmpeg (`brew install ffmpeg`)
- mediamtx binary in `mediamtx/`
