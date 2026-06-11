'use strict';

const NUM_CAMS = 5;
const WS_URL   = `ws://${location.host}/ws`;

// ── Bootstrap ─────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    buildRows();
    buildStatusCards();
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
    const col = document.getElementById('cam-led-col');
    for (let i = 0; i < NUM_CAMS; i++) {
        const row = document.createElement('div');
        row.className = 'cam-row';
        row.id = `cam-row-${i}`;
        row.innerHTML = `
            <div class="cam-feed-wrap">
                <img src="/api/stream/${i}" alt="CAM-${i}">
                <div class="cam-feed-label">CAM-${i} → SW-0${i + 1}</div>
                <div class="cam-stats-label" id="cam-stats-${i}">— fps · — KB/s</div>
            </div>
            <div class="led-panel" id="led-panel-${i}">
                <div class="cam-row-header">
                    <span class="cam-sw-label">SW-0${i + 1}</span>
                    <span class="state-badge UNKNOWN" id="badge-${i}">UNKNOWN</span>
                    <span class="cam-ts" id="ts-${i}">—</span>
                </div>
                <div class="led-dot-row" id="led-row-${i}">
                    <span class="led-searching">OCR 校準中…</span>
                </div>
            </div>`;
        col.appendChild(row);
    }
}

function buildStatusCards() {
    const col = document.getElementById('status-col');
    col.innerHTML = `<div class="status-col-title">Analysis Status</div>`;
    for (let i = 0; i < NUM_CAMS; i++) {
        const card = document.createElement('div');
        card.className = 'status-card';
        card.id = `status-card-${i}`;
        card.innerHTML = `
            <div class="status-card-header">
                <div class="status-state-dot UNKNOWN" id="sdot-${i}"></div>
                <span>CAM-${i} · SW-0${i + 1}</span>
            </div>
            <div class="status-ocr" id="socr-${i}">Searching…</div>
            <div class="status-faults" id="sfaults-${i}"></div>
            <div class="status-fps" id="sfps-${i}">— fps · — KB/s</div>
            <div class="status-ts" id="sts-${i}">—</div>`;
        col.appendChild(card);
    }
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
        const raw    = ledsDict[label] || 'off';
        const cls    = ledClass(raw);
        return `
            <div class="led-item">
                <div class="led-dot ${cls}" id="led-${camId}-${label}"></div>
                <div class="led-label">${label}</div>
            </div>`;
    }).join('');
}

function ledClass(color) {
    if (!color || color === 'off') return 'off';
    if (color === 'green') return 'green';
    if (color === 'amber') return 'amber';
    if (color === 'red')   return 'red';
    if (color.startsWith('blink-green')) return 'blink-green';
    if (color.startsWith('blink-amber')) return 'blink-amber';
    if (color.startsWith('blink-red'))   return 'blink-red';
    return 'off';
}

// ── Status card rendering ─────────────────────────────────────────────────────

function renderStatusCard(camId, sw, fps, kbps) {
    const card    = document.getElementById(`status-card-${camId}`);
    const sdot    = document.getElementById(`sdot-${camId}`);
    const socr    = document.getElementById(`socr-${camId}`);
    const sfaults = document.getElementById(`sfaults-${camId}`);
    const sfps    = document.getElementById(`sfps-${camId}`);
    const sts     = document.getElementById(`sts-${camId}`);
    if (!card) return;

    const state  = sw.state || 'UNKNOWN';
    const labels = sw.detected_labels || [];
    const leds   = sw.leds || {};

    // Card background class
    card.className = `status-card state-${state.toLowerCase()}`;

    // State dot
    sdot.className = `status-state-dot ${state}`;

    // OCR status
    const locStatus = sw.locator_status || 'searching';
    if (locStatus === 'calibrated') {
        socr.textContent = `OCR: ${labels.length}/6 labels`;
        socr.className   = 'status-ocr ok';
    } else if (locStatus === 'fallback') {
        socr.textContent = 'Fallback mode (OCR n/a)';
        socr.className   = 'status-ocr';
    } else {
        socr.textContent = 'Searching for labels…';
        socr.className   = 'status-ocr';
    }

    // Fault LEDs
    const faultItems = labels
        .map(label => {
            const raw = (leds[label] || 'off').replace('blink-', '');
            if (raw === 'red' || raw === 'amber') {
                return `<span class="fault-led-tag ${raw}">${label}</span>`;
            }
            return null;
        })
        .filter(Boolean);

    sfaults.innerHTML = faultItems.length
        ? faultItems.join('')
        : (state === 'NORMAL' ? '<span style="color:#1a5a30">All clear</span>' : '');

    // FPS / KB/s
    const rateStr = kbps > 0 ? `${kbps.toFixed(1)} KB/s` : '— KB/s';
    sfps.textContent = `${(fps || 0).toFixed(1)} fps · ${rateStr}`;

    // Timestamp
    sts.textContent = sw.timestamp || '—';
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
        if (msg.cam_stats) updateCamStats(msg.cam_stats);
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
    switches.forEach(sw => {
        if (!sw) return;
        const i = sw.cam_id;

        // Badge + timestamp
        const badge = document.getElementById(`badge-${i}`);
        if (badge) {
            badge.textContent = sw.state || 'UNKNOWN';
            badge.className   = `state-badge ${sw.state || 'UNKNOWN'}`;
        }
        const ts = document.getElementById(`ts-${i}`);
        if (ts) ts.textContent = sw.timestamp || '—';

        // LED row
        renderLedRow(i, sw);

        // Status card
        const cs = camStats[i] || { fps: 0, kbps: 0 };
        renderStatusCard(i, sw, cs.fps, cs.kbps);
    });
}

function updateCamStats(stats) {
    stats.forEach((s, i) => {
        const el = document.getElementById(`cam-stats-${i}`);
        if (el) {
            const rate = s.kbps > 0 ? `${s.kbps.toFixed(1)} KB/s` : '— KB/s';
            el.textContent = `${s.fps.toFixed(1)} fps · ${rate}`;
        }
    });
}
