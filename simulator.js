'use strict';

// ─────────────────────────────────────────────
// Constants
// ─────────────────────────────────────────────

const MODELS = [
    { name: 'NetCore GS-2400',  ports: 24, hasPoe: false, speed: '1G' },
    { name: 'NetCore GS-4824',  ports: 24, hasPoe: false, speed: '10G' },
    { name: 'NetCore PoE-2424', ports: 24, hasPoe: true,  speed: '1G' },
];

const FAULTS = [
    { id: 'FAN_WARN',    name: '風扇轉速異常',         severity: 'WARNING', led: 'FAN',  color: 'amber' },
    { id: 'FAN_FAIL',    name: '風扇故障停止',         severity: 'FAULT',   led: 'FAN',  color: 'blink-red' },
    { id: 'TEMP_WARN',   name: '溫度過高 (>65°C)',     severity: 'WARNING', led: 'TEMP', color: 'amber' },
    { id: 'TEMP_CRIT',   name: '嚴重過熱 (>85°C)',     severity: 'FAULT',   led: 'TEMP', color: 'blink-red' },
    { id: 'CPU_HIGH',    name: 'CPU 使用率過高 (>90%)', severity: 'WARNING', led: 'SYS',  color: 'blink-amber' },
    { id: 'MEM_HIGH',    name: '記憶體使用率過高 (>85%)',severity: 'WARNING', led: 'SYS',  color: 'blink-amber' },
    { id: 'PORT_ERR',    name: '連接埠 CRC 錯誤過多',  severity: 'WARNING', led: 'SYS',  color: 'blink-amber', portEffect: 'error' },
    { id: 'LINK_FLAP',   name: '連接埠 Link Flapping', severity: 'WARNING', led: 'SYS',  color: 'blink-amber', portEffect: 'flap' },
    { id: 'STP_CHANGE',  name: 'STP 拓撲變更',         severity: 'WARNING', led: 'SYS',  color: 'blink-amber' },
    { id: 'POE_OVERLOAD',name: 'PoE 功率超過預算',     severity: 'WARNING', led: 'POE',  color: 'amber', poeOnly: true },
    { id: 'HW_FAULT',    name: '硬體元件故障',         severity: 'FAULT',   led: 'SYS',  color: 'red' },
    { id: 'PWR_FAULT',   name: '電源模組故障',         severity: 'FAULT',   led: 'PWR',  color: 'blink-red' },
];

// ─────────────────────────────────────────────
// NetworkSwitch — state machine + model
// ─────────────────────────────────────────────

class NetworkSwitch {
    constructor(id) {
        this.id    = id;
        this.name  = `SW-${String(id).padStart(2, '0')}`;
        this.model = MODELS[(id - 1) % MODELS.length];
        this.state = 'OFFLINE';  // OFFLINE | BOOTING | NORMAL | WARNING | FAULT | RESETTING

        this.uptime  = 0;
        this.cpu     = 5;
        this.mem     = 30;
        this.temp    = 35;
        this.faults  = [];   // active fault objects
        this.logs    = [];

        this.mgmtActive = false;
        this.mgmtTimer  = 0;

        this._bootTimer = null;

        // 24 ports
        this.ports = Array.from({ length: 24 }, (_, i) => ({
            id:     i + 1,
            state:  'down',   // down | up | error | flap | disabled
            speed:  0,
            active: false,
            activeTimer: 0,
        }));
    }

    // ── Public API ──

    powerOn() {
        if (this.state !== 'OFFLINE') return;
        this._boot();
    }

    powerOff() {
        this._clearBoot();
        this.state  = 'OFFLINE';
        this.uptime = 0;
        this.faults = [];
        this.cpu    = 5;
        this.mem    = 30;
        this.temp   = 35;
        this.ports.forEach(p => { p.state = 'down'; p.active = false; });
        this._log('系統關機');
    }

    reset() {
        if (this.state === 'OFFLINE') return;
        this._clearBoot();
        this.state  = 'RESETTING';
        this.faults = [];
        this.ports.forEach(p => { p.state = 'down'; p.active = false; });
        this._log('使用者手動重置...');
        this._bootTimer = setTimeout(() => this._boot(), 1500);
    }

    injectFault(faultId) {
        const def = FAULTS.find(f => f.id === faultId);
        if (!def) return;
        if (def.poeOnly && !this.model.hasPoe) return;
        if (this.faults.find(f => f.id === faultId)) return;
        if (this.state !== 'NORMAL' && this.state !== 'WARNING') return;

        this.faults.push({ ...def, ts: new Date() });
        this._log(`[警報] ${def.name}`);

        if (def.severity === 'FAULT') {
            this.state = 'FAULT';
        } else if (this.state === 'NORMAL') {
            this.state = 'WARNING';
        }

        if (def.portEffect) {
            const up = this.ports.filter(p => p.state === 'up');
            const n  = Math.max(1, Math.floor(up.length * 0.2));
            for (let i = 0; i < n; i++) {
                const p = up[Math.floor(Math.random() * up.length)];
                p.state = def.portEffect;
            }
        }

        if (faultId === 'TEMP_WARN') this.temp = 66 + Math.random() * 8;
        if (faultId === 'TEMP_CRIT') this.temp = 87 + Math.random() * 8;
        if (faultId === 'CPU_HIGH')  this.cpu  = 92 + Math.random() * 7;
        if (faultId === 'MEM_HIGH')  this.mem  = 87 + Math.random() * 10;
    }

    // ── Tick (called every second) ──

    tick() {
        if (this.state === 'OFFLINE' || this.state === 'BOOTING' || this.state === 'RESETTING') return;

        this.uptime++;

        // Drift metrics
        this.cpu  = clamp(this.cpu  + rand(-3, 3),   3,  99);
        this.mem  = clamp(this.mem  + rand(-.5, .6),  15, 99);
        this.temp = clamp(this.temp + rand(-.3, .3),  30, 95);

        // Port simulation
        this.ports.forEach(p => {
            if (p.state === 'up') {
                p.activeTimer--;
                if (p.activeTimer <= 0) {
                    p.active = Math.random() > 0.45;
                    p.activeTimer = 1 + Math.floor(Math.random() * 3);
                }
            } else if (p.state === 'flap') {
                p.state  = Math.random() > 0.5 ? 'up' : 'down';
                p.active = false;
            } else if (p.state === 'down' && Math.random() < 0.003) {
                p.state = 'up';
                p.speed = Math.random() > 0.3 ? 1000 : 100;
            } else if (p.state === 'up' && Math.random() < 0.001) {
                p.state = 'down'; p.active = false;
            }
        });

        // MGMT LED blink simulation
        this.mgmtTimer--;
        if (this.mgmtTimer <= 0) {
            this.mgmtActive  = !this.mgmtActive;
            this.mgmtTimer   = this.mgmtActive ? 1 : 3 + Math.floor(Math.random() * 4);
        }

        // Random fault injection (low probability)
        if (this.state === 'NORMAL' && Math.random() < 0.003) {
            this._injectRandomFault('WARNING');
        }
        if (this.state === 'WARNING' && Math.random() < 0.002) {
            this._injectRandomFault('FAULT');
        }

        // Random fault recovery (warnings only)
        if (Math.random() < 0.004) {
            const warnFaults = this.faults.filter(f => f.severity === 'WARNING');
            if (warnFaults.length > 0) {
                const f = warnFaults[Math.floor(Math.random() * warnFaults.length)];
                this._clearFault(f.id);
            }
        }
    }

    // ── LED state query (deterministic, no side effects) ──

    ledStates() {
        const s = {
            PWR:  'off',
            SYS:  'off',
            FAN:  'off',
            TEMP: 'off',
            POE:  'off',
            MGMT: 'off',
        };

        if (this.state === 'OFFLINE') return s;

        if (this.state === 'BOOTING') {
            s.PWR = 'green';
            s.SYS = 'blink-blue';
            return s;
        }
        if (this.state === 'RESETTING') {
            s.PWR = 'amber';
            s.SYS = 'blink-amber';
            return s;
        }

        // Normal baseline
        s.PWR  = 'green';
        s.SYS  = 'blink-slow-g';
        s.FAN  = 'green';
        s.TEMP = 'green';
        s.MGMT = this.mgmtActive ? 'blink-fast-g' : 'green';
        if (this.model.hasPoe) s.POE = 'green';

        // Overlay faults
        this.faults.forEach(f => {
            s[f.led] = f.color;
        });

        return s;
    }

    // ── Helpers ──

    activePorts() {
        return this.ports.filter(p => p.state === 'up' || p.state === 'error' || p.state === 'flap').length;
    }

    formatUptime() {
        const h = Math.floor(this.uptime / 3600);
        const m = Math.floor((this.uptime % 3600) / 60);
        const s = this.uptime % 60;
        return `${pad(h)}:${pad(m)}:${pad(s)}`;
    }

    stateClass() {
        switch (this.state) {
            case 'WARNING':   return 'state-warning';
            case 'FAULT':     return 'state-fault';
            case 'OFFLINE':   return 'state-offline';
            default:          return '';
        }
    }

    // ── Private ──

    _boot() {
        this.state = 'BOOTING';
        this._log('系統啟動中...');
        const delay = 3000 + Math.random() * 2000;
        this._bootTimer = setTimeout(() => this._booted(), delay);
    }

    _booted() {
        this.state  = 'NORMAL';
        this.uptime = 0;
        this.faults = [];
        this.cpu    = 5  + Math.random() * 15;
        this.mem    = 25 + Math.random() * 20;
        this.temp   = 35 + Math.random() * 10;
        this.mgmtActive = false;
        this.mgmtTimer  = 5;

        this.ports.forEach(p => {
            p.state  = Math.random() > 0.25 ? 'up' : 'down';
            p.speed  = p.state === 'up' ? (Math.random() > 0.3 ? 1000 : 100) : 0;
            p.active = false;
            p.activeTimer = 0;
        });

        this._log('系統啟動完成，所有服務正常運行');
        this._bootTimer = null;
    }

    _clearBoot() {
        if (this._bootTimer) { clearTimeout(this._bootTimer); this._bootTimer = null; }
    }

    _injectRandomFault(severity) {
        const available = FAULTS.filter(f =>
            f.severity === severity &&
            !this.faults.find(af => af.id === f.id) &&
            !(f.poeOnly && !this.model.hasPoe)
        );
        if (available.length === 0) return;
        const f = available[Math.floor(Math.random() * available.length)];
        this.injectFault(f.id);
    }

    _clearFault(faultId) {
        const idx = this.faults.findIndex(f => f.id === faultId);
        if (idx === -1) return;
        const f = this.faults.splice(idx, 1)[0];
        this._log(`[恢復] ${f.name} 已恢復正常`);

        // Restore port effects
        this.ports.forEach(p => {
            if (p.state === 'error' || p.state === 'flap') p.state = 'up';
        });

        // Restore metrics
        if (!this.faults.find(f2 => f2.id === 'TEMP_WARN' || f2.id === 'TEMP_CRIT'))
            this.temp = 35 + Math.random() * 15;
        if (!this.faults.find(f2 => f2.id === 'CPU_HIGH'))
            this.cpu = 5 + Math.random() * 20;
        if (!this.faults.find(f2 => f2.id === 'MEM_HIGH'))
            this.mem = 25 + Math.random() * 20;

        // Re-evaluate state
        if (this.faults.length === 0) {
            this.state = 'NORMAL';
        } else if (this.faults.every(f2 => f2.severity === 'WARNING')) {
            this.state = 'WARNING';
        }
    }

    _log(msg) {
        const t = new Date().toLocaleTimeString('zh-TW', { hour12: false });
        this.logs.unshift(`[${t}] ${msg}`);
        if (this.logs.length > 60) this.logs.pop();
    }
}

// ─────────────────────────────────────────────
// RackSimulator — owns all switches
// ─────────────────────────────────────────────

class RackSimulator {
    constructor(count = 8) {
        this.switches   = Array.from({ length: count }, (_, i) => new NetworkSwitch(i + 1));
        this.showStatus = true;
        this._interval  = null;
    }

    start() {
        this._interval = setInterval(() => {
            this.switches.forEach(sw => sw.tick());
            ui.render(this);
        }, 1000);
        ui.render(this);
    }

    allOn()     { this.switches.forEach(sw => sw.powerOn()); }
    allOff()    { this.switches.forEach(sw => sw.powerOff()); }
    resetAll()  { this.switches.forEach(sw => sw.reset()); }

    injectFault() {
        const candidates = this.switches.filter(sw =>
            sw.state === 'NORMAL' || sw.state === 'WARNING'
        );
        if (candidates.length === 0) return;
        const sw  = candidates[Math.floor(Math.random() * candidates.length)];
        const all = FAULTS.filter(f =>
            !sw.faults.find(af => af.id === f.id) &&
            !(f.poeOnly && !sw.model.hasPoe)
        );
        if (all.length === 0) return;
        sw.injectFault(all[Math.floor(Math.random() * all.length)].id);
    }

    toggleStatus() { this.showStatus = !this.showStatus; }

    summary() {
        const c = { normal: 0, warning: 0, fault: 0, offline: 0 };
        this.switches.forEach(sw => {
            if      (sw.state === 'NORMAL')  c.normal++;
            else if (sw.state === 'WARNING') c.warning++;
            else if (sw.state === 'FAULT')   c.fault++;
            else                             c.offline++;
        });
        return c;
    }
}

// ─────────────────────────────────────────────
// UI — DOM creation & updates
// ─────────────────────────────────────────────

class UI {
    constructor() {
        this._ready = false;
    }

    build(sim) {
        const body = document.getElementById('rack-body');
        body.innerHTML = '';
        sim.switches.forEach(sw => body.appendChild(this._makeSwitchEl(sw)));
        this._ready = true;
    }

    render(sim) {
        if (!this._ready) this.build(sim);
        sim.switches.forEach(sw => this._updateSwitch(sw, sim.showStatus));
        this._updateSummary(sim.summary());
    }

    _makeSwitchEl(sw) {
        const div = document.createElement('div');
        div.className = 'switch-unit';
        div.id = `sw-${sw.id}`;

        const poeRow = sw.model.hasPoe ? `
            <div class="led-row">
                <span class="led-tag">PoE</span>
                <div class="led" id="l-${sw.id}-POE"></div>
            </div>` : '';

        const ports = (start, end) => Array.from(
            { length: end - start + 1 },
            (_, i) => `<div class="port" id="p-${sw.id}-${start + i}" title="Port ${start + i}"></div>`
        ).join('');

        div.innerHTML = `
        <div class="switch-front">
            <div class="sw-label">
                <div class="sw-name">${sw.name}</div>
                <div class="sw-model">${sw.model.name}</div>
            </div>

            <div class="sys-leds">
                <div class="led-row">
                    <span class="led-tag">PWR</span>
                    <div class="led" id="l-${sw.id}-PWR"></div>
                </div>
                <div class="led-row">
                    <span class="led-tag">SYS</span>
                    <div class="led" id="l-${sw.id}-SYS"></div>
                </div>
                <div class="led-row">
                    <span class="led-tag">FAN</span>
                    <div class="led" id="l-${sw.id}-FAN"></div>
                </div>
                <div class="led-row">
                    <span class="led-tag">TEMP</span>
                    <div class="led" id="l-${sw.id}-TEMP"></div>
                </div>
                ${poeRow}
            </div>

            <div class="port-section">
                <div class="port-row">${ports(1, 12)}</div>
                <div class="port-row">${ports(13, 24)}</div>
            </div>

            <div class="mgmt-section">
                <div class="mgmt-jack" title="Management Port">
                    <div class="led" id="l-${sw.id}-MGMT"></div>
                </div>
                <span class="mgmt-tag">MGMT</span>
            </div>

            <button class="reset-btn" id="rst-${sw.id}"
                    onclick="sim.switches[${sw.id - 1}].reset(); ui.render(sim);">
                RST
            </button>
        </div>

        <div class="sw-status" id="sts-${sw.id}">
            <div class="st-state">
                <div class="st-dot offline" id="dot-${sw.id}"></div>
                <span id="stlabel-${sw.id}">OFFLINE</span>
            </div>
            <div class="st-info" id="stinfo-${sw.id}">—</div>
            <div class="st-uptime" id="stup-${sw.id}"></div>
        </div>`;

        return div;
    }

    _updateSwitch(sw, showStatus) {
        const unit = document.getElementById(`sw-${sw.id}`);
        if (!unit) return;

        // Border color by state
        unit.className = `switch-unit ${sw.stateClass()}`;

        // System LEDs
        const leds = sw.ledStates();
        ['PWR', 'SYS', 'FAN', 'TEMP', 'POE', 'MGMT'].forEach(name => {
            const el = document.getElementById(`l-${sw.id}-${name}`);
            if (el) el.className = `led ${leds[name] || 'off'}`;
        });

        // Port LEDs
        sw.ports.forEach(p => {
            const el = document.getElementById(`p-${sw.id}-${p.id}`);
            if (!el) return;
            if (sw.state === 'OFFLINE' || sw.state === 'BOOTING') {
                el.className = 'port';
            } else {
                el.className = `port ${p.state === 'up' ? (p.active ? 'active' : 'up') : p.state}`;
            }
            el.title = `Port ${p.id}: ${p.state}${p.state === 'up' ? ` (${p.speed}M)` : ''}`;
        });

        // Status bar visibility
        const stsEl = document.getElementById(`sts-${sw.id}`);
        if (stsEl) stsEl.className = `sw-status${showStatus ? '' : ' hidden'}`;

        // State dot + label
        const dotEl    = document.getElementById(`dot-${sw.id}`);
        const labelEl  = document.getElementById(`stlabel-${sw.id}`);
        const stateKey = sw.state.toLowerCase();
        if (dotEl)   dotEl.className   = `st-dot ${stateKey}`;
        if (labelEl) labelEl.textContent = sw.state;

        // Info text
        const infoEl = document.getElementById(`stinfo-${sw.id}`);
        if (infoEl) infoEl.innerHTML = this._buildInfo(sw);

        // Uptime
        const upEl = document.getElementById(`stup-${sw.id}`);
        if (upEl) {
            upEl.textContent = (sw.state !== 'OFFLINE' && sw.state !== 'BOOTING')
                ? `運行時間: ${sw.formatUptime()}`
                : '';
        }

        // Reset button
        const rstEl = document.getElementById(`rst-${sw.id}`);
        if (rstEl) {
            rstEl.disabled = ['OFFLINE', 'BOOTING', 'RESETTING'].includes(sw.state);
        }
    }

    _buildInfo(sw) {
        if (sw.state === 'OFFLINE')    return '<span style="color:#2e3540">設備已關機</span>';
        if (sw.state === 'BOOTING')    return '<span style="color:#2979ff">系統啟動中，執行 POST 與服務初始化...</span>';
        if (sw.state === 'RESETTING')  return '<span style="color:#ffab00">重置中，準備重新啟動...</span>';

        const ap  = sw.activePorts();
        let text  = `CPU: ${sw.cpu.toFixed(0)}%  Mem: ${sw.mem.toFixed(0)}%  Temp: ${sw.temp.toFixed(0)}°C  Ports: ${ap}/24`;

        if (sw.faults.length > 0) {
            const parts = sw.faults.map(f =>
                `<span class="${f.severity === 'FAULT' ? 'alarm' : 'warn-t'}">[${f.severity}] ${f.name}</span>`
            );
            text += '  |  ' + parts.join('  ');
        } else {
            text += '  |  <span class="ok">所有系統正常</span>';
        }

        return text;
    }

    _updateSummary(s) {
        const el = document.getElementById('global-summary');
        if (!el) return;
        el.innerHTML = `
            <div class="summary-item"><div class="s-dot green"></div>正常: ${s.normal}</div>
            <div class="summary-item"><div class="s-dot amber"></div>警告: ${s.warning}</div>
            <div class="summary-item"><div class="s-dot red"></div>故障: ${s.fault}</div>
            <div class="summary-item"><div class="s-dot gray"></div>離線: ${s.offline}</div>`;
    }
}

// ─────────────────────────────────────────────
// Utilities
// ─────────────────────────────────────────────

function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }
function rand(lo, hi)     { return lo + Math.random() * (hi - lo); }
function pad(n)           { return String(n).padStart(2, '0'); }

// ─────────────────────────────────────────────
// Bootstrap
// ─────────────────────────────────────────────

const sim = new RackSimulator(8);
const ui  = new UI();

document.addEventListener('DOMContentLoaded', () => {
    ui.build(sim);
    ui.render(sim);

    document.getElementById('btn-all-on').addEventListener('click',      () => { sim.allOn();       ui.render(sim); });
    document.getElementById('btn-all-off').addEventListener('click',     () => { sim.allOff();      ui.render(sim); });
    document.getElementById('btn-reset-all').addEventListener('click',   () => { sim.resetAll();    ui.render(sim); });
    document.getElementById('btn-sim-fault').addEventListener('click',   () => { sim.injectFault(); ui.render(sim); });
    document.getElementById('btn-toggle-status').addEventListener('click', () => { sim.toggleStatus(); ui.render(sim); });

    sim.start();
});
