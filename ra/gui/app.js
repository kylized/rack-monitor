'use strict';

const NUM_CAMS    = 5;
const WS_URL      = `ws://${location.host}/ws`;
const SNAP_PERIOD = 1000;   // ms between snapshot refreshes

const LED_NAMES  = ['PWR','SYS','FAN','TEMP','POE','MGMT'];
const LED_LABELS = { PWR:'電源', SYS:'系統', FAN:'風扇', TEMP:'溫度', POE:'PoE', MGMT:'管理' };

// Chart.js instances per switch (keyed by switch_id 1-5)
const charts = {};

// ── Bootstrap ────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    buildCamGrid();
    buildSwitchCards();
    startClock();
    startSnapshotPolling();
    connectWS();
});

// ── Clock ────────────────────────────────────────────────────────────────────

function startClock() {
    const el = document.getElementById('clock');
    setInterval(() => {
        el.textContent = new Date().toLocaleTimeString('zh-TW', { hour12: false });
    }, 1000);
}

// ── Camera grid ──────────────────────────────────────────────────────────────

function buildCamGrid() {
    const grid = document.getElementById('cam-grid');
    for (let i = 0; i < NUM_CAMS; i++) {
        const wrap = document.createElement('div');
        wrap.className = 'cam-thumb';
        wrap.innerHTML = `
            <img id="snap-${i}" alt="CAM-${i}" title="CAM-${i}">
            <div class="cam-label"><span>CAM-${i}</span> → SW-0${i+1}</div>`;
        grid.appendChild(wrap);
    }
}

function startSnapshotPolling() {
    function refresh() {
        for (let i = 0; i < NUM_CAMS; i++) {
            const img = document.getElementById(`snap-${i}`);
            if (img) img.src = `/api/snapshot/${i}?t=${Date.now()}`;
        }
    }
    refresh();
    setInterval(refresh, SNAP_PERIOD);
}

// ── Switch cards ─────────────────────────────────────────────────────────────

function buildSwitchCards() {
    const col = document.getElementById('switch-col');
    for (let i = 1; i <= NUM_CAMS; i++) {
        const card = document.createElement('div');
        card.className = 'sw-card';
        card.id = `sw-card-${i}`;
        card.innerHTML = `
        <div class="sw-card-header">
            <span class="sw-name-lbl">SW-0${i}</span>
            <span class="sw-cam-lbl">CAM-${i-1}</span>
            <span class="state-badge UNKNOWN" id="badge-${i}">UNKNOWN</span>
            <span class="sw-ts" id="ts-${i}">—</span>
        </div>
        <div class="sw-card-body">
            <div class="led-row" id="leds-${i}">
                ${LED_NAMES.map(n => `
                <div class="led-group">
                    <div class="led-dot off" id="led-${i}-${n}"></div>
                    <div class="led-name">${n}</div>
                </div>`).join('')}
            </div>
            <div class="bar-row">
                <span class="bar-label">Ports up</span>
                <div class="bar-track"><div class="bar-fill green" id="bar-port-${i}" style="width:0%"></div></div>
                <span class="bar-val" id="val-port-${i}">—</span>
            </div>
            <div class="bar-row">
                <span class="bar-label">Port errors</span>
                <div class="bar-track"><div class="bar-fill amber" id="bar-err-${i}" style="width:0%"></div></div>
                <span class="bar-val" id="val-err-${i}">—</span>
            </div>
            <div class="bar-row">
                <span class="bar-label">Anomaly score</span>
                <div class="bar-track"><div class="bar-fill green" id="bar-anom-${i}" style="width:0%"></div></div>
                <span class="bar-val" id="val-anom-${i}">—</span>
            </div>
            <div class="chart-wrap"><canvas id="chart-${i}"></canvas></div>
        </div>`;
        col.appendChild(card);
        initChart(i);
    }
}

function initChart(switchId) {
    const ctx = document.getElementById(`chart-${switchId}`).getContext('2d');
    charts[switchId] = new Chart(ctx, {
        type: 'line',
        data: {
            labels: Array(60).fill(''),
            datasets: [{
                data: Array(60).fill(0),
                borderColor: '#00e676',
                borderWidth: 1.5,
                fill: true,
                backgroundColor: 'rgba(0,230,118,0.08)',
                pointRadius: 0,
                tension: 0.3,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: false,
            plugins: { legend: { display: false } },
            scales: {
                x: { display: false },
                y: { display: false, min: 0, max: 1 },
            }
        }
    });
}

// ── WebSocket ─────────────────────────────────────────────────────────────────

function connectWS() {
    const dot = document.getElementById('ws-dot');
    const ws  = new WebSocket(WS_URL);

    ws.onopen = () => {
        dot.className = 'ws-dot ok';
        // keep-alive ping every 10s
        setInterval(() => { if (ws.readyState === WebSocket.OPEN) ws.send('ping'); }, 10000);
    };

    ws.onmessage = ({ data }) => {
        const msg = JSON.parse(data);
        updateSummary(msg.summary);
        if (msg.switches) msg.switches.forEach(sw => sw && updateSwCard(sw));
        if (msg.alerts)   updateAlerts(msg.alerts);
        if (msg.history)  updateCharts(msg.history);
    };

    ws.onclose = () => {
        dot.className = 'ws-dot err';
        setTimeout(connectWS, 3000);
    };

    ws.onerror = () => ws.close();
}

// ── Update helpers ────────────────────────────────────────────────────────────

function updateSummary(s) {
    if (!s) return;
    document.getElementById('cnt-n').textContent = s.normal  ?? '—';
    document.getElementById('cnt-w').textContent = s.warning ?? '—';
    document.getElementById('cnt-f').textContent = s.fault   ?? '—';
    document.getElementById('cnt-u').textContent = s.unknown ?? '—';
}

function updateSwCard(sw) {
    const id = sw.switch_id;
    if (!id) return;

    // Card border
    const card = document.getElementById(`sw-card-${id}`);
    if (!card) return;
    card.className = `sw-card state-${(sw.state || 'unknown').toLowerCase()}`;

    // Badge
    const badge = document.getElementById(`badge-${id}`);
    badge.textContent = sw.state || 'UNKNOWN';
    badge.className   = `state-badge ${sw.state || 'UNKNOWN'}`;

    // Timestamp
    const ts = document.getElementById(`ts-${id}`);
    if (ts) ts.textContent = sw.timestamp || '';

    // LEDs
    const leds = sw.leds || {};
    LED_NAMES.forEach(n => {
        const el = document.getElementById(`led-${id}-${n}`);
        if (!el) return;
        const color = leds[n] || 'off';
        el.className = `led-dot ${ledClass(color)}`;
    });

    // Bars
    const up   = sw.port_up_ratio  ?? 0;
    const err  = sw.port_err_ratio ?? 0;
    const anom = sw.anomaly_score  ?? 0;

    setBar(`bar-port-${id}`, `val-port-${id}`, up,   anomColor(0),      `${(up  *100).toFixed(0)}%`);
    setBar(`bar-err-${id}`,  `val-err-${id}`,  err,  anomColor(err),    `${(err *100).toFixed(0)}%`);
    setBar(`bar-anom-${id}`, `val-anom-${id}`, anom, anomColor(anom),   anom.toFixed(2));
}

function setBar(barId, valId, ratio, colorClass, label) {
    const bar = document.getElementById(barId);
    const val = document.getElementById(valId);
    if (bar) { bar.style.width = `${(ratio * 100).toFixed(1)}%`; bar.className = `bar-fill ${colorClass}`; }
    if (val) val.textContent = label;
}

function anomColor(v) {
    if (v >= 0.7) return 'red';
    if (v >= 0.4) return 'amber';
    return 'green';
}

function ledClass(color) {
    if (color === 'off')   return 'off';
    if (color === 'green') return 'green';
    if (color === 'amber') return 'amber';
    if (color === 'red')   return 'red';
    // blink variants from simulator (treated as the base color for RA display)
    if (color.includes('green')) return 'blink-green';
    if (color.includes('amber')) return 'blink-amber';
    if (color.includes('red'))   return 'blink-red';
    return 'off';
}

function updateCharts(history) {
    for (const [switchId, data] of Object.entries(history)) {
        const chart = charts[parseInt(switchId)];
        if (!chart || !Array.isArray(data)) continue;
        const len  = chart.data.datasets[0].data.length;
        const vals = Array(len).fill(0);
        data.slice(-len).forEach((v, i) => { vals[len - data.slice(-len).length + i] = v; });
        chart.data.datasets[0].data = vals;
        // Color sparkline by max anomaly
        const maxV = Math.max(...vals);
        chart.data.datasets[0].borderColor = maxV >= 0.7 ? '#ff1744' : maxV >= 0.4 ? '#ffab00' : '#00e676';
        chart.update('none');
    }
}

function updateAlerts(alerts) {
    if (!alerts || alerts.length === 0) return;
    const list = document.getElementById('alert-list');
    list.innerHTML = '';
    alerts.forEach(a => {
        const div = document.createElement('div');
        const isResolved = a.resolved || a.kind?.includes('CLEARED');
        const isFault    = a.kind?.includes('FAULT') && !isResolved;
        div.className = `alert-item ${isResolved ? 'resolved' : isFault ? 'fault' : 'warning'}`;
        div.innerHTML =
            `<span class="alert-ts">${a.timestamp}</span>  ` +
            `<span class="alert-sw">SW-0${a.switch_id}</span>  ` +
            `<span class="alert-kind">${a.kind}</span>  ` +
            `<span style="color:#555">score=${(a.score ?? 0).toFixed(2)}</span>`;
        list.appendChild(div);
    });
}
