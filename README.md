# Rack Monitor Simulator

A browser-based simulator that visualises a 19" equipment rack containing 8 network switches. Each switch runs its own independent state machine, generating realistic LED patterns, port activity, and fault events — all viewable at a glance through a web GUI.

---

## Features

| Feature | Detail |
|---|---|
| **Rack view** | 8 × 1U switches stacked in a 19" rack with unit-rail markings |
| **System LEDs** | PWR, SYS, FAN, TEMP, PoE, MGMT — colours match real-world conventions |
| **Port LEDs** | 24 ports per switch (2 × 12 rows); blink during activity, amber on error |
| **State machine** | `OFFLINE → BOOTING → NORMAL ↔ WARNING ↔ FAULT → RESETTING → BOOTING` |
| **Per-device status** | Live CPU %, Memory %, Temperature, port count, all active alarms |
| **Reset button** | Each switch has an individual RST button; re-boots and may re-fault |
| **Master controls** | All Power ON / OFF, Reset All, Inject Fault (random), Toggle Status |
| **Auto simulation** | Random faults injected and auto-recovered over time |

## Switch Models

Three fictional models rotate across the 8 slots:

- **NetCore GS-2400** — 24-port 1G
- **NetCore GS-4824** — 24-port 10G
- **NetCore PoE-2424** — 24-port 1G PoE+

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
| `STP_CHANGE` | STP 拓撲變更 | WARNING |
| `POE_OVERLOAD` | PoE 功率超過預算 | WARNING |
| `HW_FAULT` | 硬體元件故障 | FAULT |
| `PWR_FAULT` | 電源模組故障 | FAULT |

## State Machine

```
OFFLINE
  └─[Power ON]──► BOOTING (3–5 s)
                    └─[Boot complete]──► NORMAL
                                          ├─[Random fault]──► WARNING
                                          │                     ├─[Auto-recover]──► NORMAL
                                          │                     └─[Escalate]──► FAULT
                                          └─[RST / Reset All]──► RESETTING ──► BOOTING
```

## Running

No build step required. Open `index.html` directly in any modern browser:

```bash
open index.html
# or
python3 -m http.server 8080   # then visit http://localhost:8080
```

## Project Structure

```
rack_monitor/
├── index.html      # App shell & rack layout
├── style.css       # Dark rack theme, LED animations
├── simulator.js    # NetworkSwitch class, RackSimulator, UI renderer
└── README.md
```

## Tech Stack

- Plain HTML / CSS / JavaScript — no build tools, no dependencies
- CSS keyframe animations for LED blinking
- `setInterval`-driven tick loop (1 s) for state machine updates
