'use strict';

const NUM_CAMS = 5;
const WS_URL   = `ws://${location.host}/ws`;

// Per-camera device metadata: model name and physical location (datacenter · rack · unit).
const DEVICE_INFO = [
    { name: 'NetCore GS-2424P', location: 'DC-A · Rack-03 · U12' },
    { name: 'NetCore GS-4824',  location: 'DC-A · Rack-03 · U11' },
    { name: 'NetCore PoE-2424', location: 'DC-A · Rack-04 · U08' },
    { name: 'NetCore GS-2424P', location: 'DC-B · Rack-01 · U04' },
    { name: 'NetCore GS-4824',  location: 'DC-B · Rack-01 · U03' },
];

// Runtime state caches (updated on every WS tick; read by popup on open).
let _activeFilter = 'ALL';
let _switches     = [];
let _camStats     = [];

// ── Bootstrap ─────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    buildRows();
    startClock();
    connectWS();
});

// ── Clock ─────────────────────────────────────────────────────────────────────

function startClock() {
    const el = document.getElementById('clock');
    setInterval(() => {
        el.textContent = new Date().toLocaleTimeString('zh-TW', { hour12: false });
    }, 1000);
}

// ── Build initial DOM ─────────────────────────────────────────────────────────

function buildRows() {
    const list = document.getElementById('device-list');
    for (let i = 0; i < NUM_CAMS; i++) {
        const info = DEVICE_INFO[i];
        const row  = document.createElement('div');
        row.className   = 'device-row';
        row.id          = `row-${i}`;
        row.dataset.state = 'UNKNOWN';
        row.innerHTML = `
            <div class="dev-status-col">
                <div class="dev-status-dot" id="sdot-${i}"></div>
            </div>
            <div class="dev-info">
                <div class="dev-name">${info.name}</div>
                <div class="dev-location">${info.location}</div>
                <div class="dev-meta">
                    <span class="state-badge UNKNOWN" id="badge-${i}">UNKNOWN</span>
                    <span class="dev-ts" id="ts-${i}">—</span>
                </div>
            </div>
            <div class="dev-led-section">
                <div class="led-dot-row" id="led-row-${i}">
                    <span class="led-searching">OCR 校準中…</span>
                </div>
            </div>
            <button class="dev-cam-btn" onclick="openCamPopup(${i})" title="查看即時影像">
                <span class="cam-btn-icon">▶</span>
                <span>LIVE</span>
            </button>`;
        list.appendChild(row);
    }
}

// ── Filter ────────────────────────────────────────────────────────────────────

function applyFilter(state) {
    _activeFilter = state;

    document.querySelectorAll('.filter-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.filter === state);
    });

    for (let i = 0; i < NUM_CAMS; i++) {
        const row      = document.getElementById(`row-${i}`);
        if (!row) continue;
        const rowState = row.dataset.state || 'UNKNOWN';
        row.style.display = (state === 'ALL' || rowState === state) ? '' : 'none';
    }
}

// ── Camera popup ──────────────────────────────────────────────────────────────

function openCamPopup(camId) {
    const popup  = document.getElementById('cam-popup');
    const info   = DEVICE_INFO[camId];
    const sw     = _switches[camId];
    const cs     = _camStats[camId] || { fps: 0, kbps: 0 };

    document.getElementById('popup-title').textContent =
        `CAM-${camId}  ·  ${info.name}  ·  ${info.location}`;

    // Setting src triggers the MJPEG connection.
    document.getElementById('popup-stream').src = `/api/stream/${camId}`;

    _updatePopupInfo(sw, cs);

    popup.dataset.camId = camId;
    popup.classList.remove('hidden');
}

function closeCamPopup() {
    const popup  = document.getElementById('cam-popup');
    document.getElementById('popup-stream').src = '';   // stop MJPEG
    popup.classList.add('hidden');
}

function _updatePopupInfo(sw, cs) {
    const locStatus = sw ? (sw.locator_status || 'searching') : 'searching';
    const ocrEl     = document.getElementById('popup-ocr');

    if (locStatus === 'calibrated') {
        ocrEl.textContent = `OCR ${(sw.detected_labels || []).length}/6 ✓`;
        ocrEl.className   = 'ok';
    } else {
        ocrEl.textContent = 'OCR 校準中…';
        ocrEl.className   = '';
    }

    document.getElementById('popup-fps').textContent =
        `${(cs.fps || 0).toFixed(1)} fps · ${cs.kbps > 0 ? cs.kbps.toFixed(1) + ' KB/s' : '—'}`;
    document.getElementById('popup-ts').textContent =
        sw ? (sw.timestamp || '—') : '—';
}

// ── LED row rendering ─────────────────────────────────────────────────────────

function renderLedRow(camId, sw) {
    const row = document.getElementById(`led-row-${camId}`);
    if (!row) return;

    const labels   = sw.detected_labels || [];
    const ledsDict = sw.leds || {};

    if (labels.length === 0) {
        row.innerHTML = `<span class="led-searching">OCR 校準中…</span>`;
        return;
    }

    row.innerHTML = labels.map(label => {
        const raw = ledsDict[label] || 'off';
        const cls = ledClass(raw);
        return `<div class="led-item">
            <div class="led-dot ${cls}"></div>
            <div class="led-label">${label}</div>
        </div>`;
    }).join('');
}

function ledClass(color) {
    if (!color || color === 'off')             return 'off';
    if (color === 'green')                     return 'green';
    if (color === 'amber')                     return 'amber';
    if (color === 'red')                       return 'red';
    if (color.startsWith('blink-green'))       return 'blink-green';
    if (color.startsWith('blink-amber'))       return 'blink-amber';
    if (color.startsWith('blink-red'))         return 'blink-red';
    return 'off';
}

// ── WebSocket ─────────────────────────────────────────────────────────────────

function connectWS() {
    const dot = document.getElementById('ws-dot');
    const ws  = new WebSocket(WS_URL);

    ws.onopen = () => {
        dot.className = 'ws-dot ok';
        setInterval(() => { if (ws.readyState === WebSocket.OPEN) ws.send('ping'); }, 10000);
    };

    ws.onmessage = ({ data }) => {
        const msg = JSON.parse(data);
        if (msg.summary)   updateSummary(msg.summary);
        if (msg.switches)  updateSwitches(msg.switches, msg.cam_stats || []);
        if (msg.cam_stats) _camStats = msg.cam_stats;
    };

    ws.onclose = () => { dot.className = 'ws-dot err'; setTimeout(connectWS, 3000); };
    ws.onerror = () => ws.close();
}

function updateSummary(s) {
    document.getElementById('cnt-n').textContent = s.normal  ?? '—';
    document.getElementById('cnt-w').textContent = s.warning ?? '—';
    document.getElementById('cnt-f').textContent = s.fault   ?? '—';
    document.getElementById('cnt-u').textContent = s.unknown ?? '—';
}

function updateSwitches(switches, camStats) {
    _switches = switches;

    switches.forEach(sw => {
        if (!sw) return;
        const i     = sw.cam_id;
        const state = sw.state || 'UNKNOWN';

        // Row: state class + filter visibility
        const row = document.getElementById(`row-${i}`);
        if (row) {
            row.dataset.state = state;
            row.className     = `device-row state-${state}`;
            row.style.display = (_activeFilter === 'ALL' || _activeFilter === state) ? '' : 'none';
        }

        // Status dot
        const sdot = document.getElementById(`sdot-${i}`);
        if (sdot) sdot.className = `dev-status-dot ${state}`;

        // State badge + timestamp
        const badge = document.getElementById(`badge-${i}`);
        if (badge) { badge.textContent = state; badge.className = `state-badge ${state}`; }
        const ts = document.getElementById(`ts-${i}`);
        if (ts) ts.textContent = sw.timestamp || '—';

        // LED dots
        renderLedRow(i, sw);

        // Keep popup live if it's open for this camera
        const popup = document.getElementById('cam-popup');
        if (!popup.classList.contains('hidden') && Number(popup.dataset.camId) === i) {
            _updatePopupInfo(sw, camStats[i] || { fps: 0, kbps: 0 });
        }
    });
}
