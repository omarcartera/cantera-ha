# 🚗 CANtera OBD-II — Home Assistant Integration

[![HACS](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz)
[![HA Minimum Version](https://img.shields.io/badge/HA%20minimum-2024.4.0-blue.svg)](https://www.home-assistant.io)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org)

> Live vehicle diagnostics in Home Assistant — stream OBD-II PID readings from
> a Raspberry Pi directly into your dashboard with no MQTT broker required.

---

## ✨ Features

| Feature | Details |
|---------|---------|
| 🚀 **Live OBD sensors** | Auto-created for every PID the ECU supports — RPM, speed, coolant temp, throttle, fuel level, and more |
| 📊 **History backfill** | On reconnect, fetches missed readings from the Pi's Parquet logs and imports them into HA long-term statistics |
| ❤️ **Health heartbeat** | Polls `/api/health` every 5 s — connection sensors go offline within 10 s of the Pi losing power |
| 🔌 **CAN status sensor** | Dedicated binary sensor showing whether the OBD link to the vehicle ECU is active |
| 🔁 **Reconfigure flow** | Update the Pi's IP or port from HA without removing and re-adding the integration |
| 🩺 **Diagnostics** | Built-in diagnostics page in HA with connection state, health data, and config info |
| 🚫 **Zero broker** | Connects directly to CANtera's built-in HTTP/SSE API — no MQTT, no Mosquitto |
| 📦 **HACS compatible** | One-click install from the HACS custom repository list |

---

## 🚀 Quick Start

1. **Deploy** CANtera on a Raspberry Pi with an OBD-II CAN adapter
2. **Start** the logger: `cantera -b 500000 log-obd --api`
3. **Add** the integration in HA → Settings → Devices & Services → CANtera

---

## 📋 Prerequisites

| Component | Requirement |
|-----------|-------------|
| **Raspberry Pi** | Running CANtera with an OBD-II CAN adapter attached |
| **Network** | Pi reachable from the Home Assistant host (same LAN, or VPN with routing) |
| **Home Assistant** | 2024.4.0 or later |
| **HACS** | For one-click installation (manual install also works) |

> **⚠️ Tailscale note**: Tailscale IPs (`100.x.x.x`) are **not** accessible from
> the HA Docker container by default. Use the Pi's **local network IP** (e.g.
> `192.168.x.x`). Tailscale routing requires the Tailscale add-on with subnet
> routing enabled in Home Assistant — otherwise the connection will be refused.

---

## 🔧 Pi Setup

### Run manually

```bash
# Replace 500000 with your adapter's actual bitrate if different.
cantera -b 500000 log-obd --api
```

`--api` starts the built-in HTTP server on port **8088** (default).

### Run as a systemd service (recommended)

Create `/etc/systemd/system/cantera-obd.service`:

```ini
[Unit]
Description=CANtera OBD-II logger
After=network.target

[Service]
ExecStart=/usr/local/bin/cantera -b 500000 log-obd --api
Restart=always
RestartSec=5s
User=pi

[Install]
WantedBy=multi-user.target
```

> `Restart=always` ensures the service restarts if the CAN adapter is
> disconnected or the vehicle is turned off — CANtera will keep retrying.

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now cantera-obd
sudo systemctl status cantera-obd
```

---

## 📦 Installation

### HACS (recommended)

1. Open HACS in Home Assistant
2. Go to **Integrations → ⋮ → Custom repositories**
3. Add this repository URL and select category **Integration**
4. Search for **CANtera OBD-II** and click **Install**
5. Restart Home Assistant

### Manual

```bash
# Run from your HA config directory
cp -r custom_components/cantera/ /config/custom_components/cantera/
```

Restart Home Assistant.

---

## ⚙️ Configuration

1. **Settings → Devices & Services → + Add Integration**
2. Search for **CANtera**
3. Enter the Pi's **local network IP** and port (default: `8088`)
4. Click Submit — the integration tests `/api/health` and creates the config entry

To update the host or port later, click **Configure** on the integration card and use the **Reconfigure** option — no need to remove and re-add the integration.

---

## 📊 Entities

### Binary Sensors

| Entity | Friendly Name | Description |
|--------|---------------|-------------|
| `binary_sensor.cantera_api_connection` | API Connection | `ON` when the Pi's HTTP API responds to health checks |
| `binary_sensor.cantera_can_connection` | CAN Connection | `ON` when the OBD polling loop is actively communicating with the vehicle ECU |

### OBD Sensors (auto-created)

Sensor entities are created automatically as readings arrive from the ECU.
Common examples:

| Entity ID | Friendly Name | Unit | HA Device Class |
|-----------|---------------|------|-----------------|
| `sensor.cantera_engine_rpm` | Engine RPM | rpm | — |
| `sensor.cantera_vehicle_speed` | Vehicle speed | km/h | speed |
| `sensor.cantera_engine_coolant_temperature` | Engine coolant temperature | °C | temperature |
| `sensor.cantera_throttle_position` | Throttle position | % | — |
| `sensor.cantera_fuel_tank_level_input` | Fuel tank level input | % | — |
| `sensor.cantera_control_module_voltage` | Control module voltage | V | voltage |

> Entities appear after the **first reading** from the ECU — start the engine
> or turn the ignition to accessory mode to trigger discovery.

---

## 🏗️ Architecture

```
  Raspberry Pi                          Home Assistant
  ┌──────────────────────────┐          ┌────────────────────────────────┐
  │  cantera -b 500000       │          │  CANtera Integration           │
  │  log-obd --api           │          │                                │
  │                          │  HTTP    │  coordinator.py                │
  │  ┌────────────────────┐  │◄────────►│  ├─ SSE loop (live readings)  │
  │  │  /events  (SSE)    │  │          │  ├─ health poll (5 s)         │
  │  │  /api/health       │  │          │  └─ history backfill          │
  │  │  /api/history      │  │          │                                │
  │  │  /api/device       │  │          │  Sensors / Binary Sensors      │
  │  └────────────────────┘  │          └────────────────────────────────┘
  │                          │
  │  OBD-II CAN adapter      │
  │  ISO-TP ↔ ECU            │
  └──────────────────────────┘
```

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/events` | GET (SSE) | Live OBD readings stream |
| `/api/health` | GET | Service health + `can_connected` flag (polled every 5 s) |
| `/api/history` | GET | Parquet-backed historical readings for backfill |
| `/api/device` | GET | Device identity (used as HA unique ID) |

---

## 🔍 Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| **"host_unreachable"** in config flow | Routing failure | Use the Pi's local IP (`192.168.x.x`). Tailscale IPs require the HA Tailscale add-on with subnet routing |
| **"connection_refused"** in config flow | CANtera not running | SSH to Pi and run `cantera -b 500000 log-obd --api`, or check `systemctl status cantera-obd` |
| **"cannot_connect"** in config flow | API not responding | Verify port — default is 8088. Check firewall. Try `curl http://PI_IP:8088/api/health` |
| **No OBD sensors appear** | ECU not polled yet | Entities are created on first reading. Turn ignition on or start the engine |
| **API Connection sensor goes ON then OFF** | CAN adapter not found | Check `journalctl -u cantera-obd` — adapter may not be detected. Specify `--device` flag if needed |
| **CAN Connection stays OFF** | Vehicle not responding | ECU may be off. The sensor reflects live OBD frame exchange — it goes ON once the ECU starts responding |
| **History not importing** | No Parquet files on Pi | Check that `cantera -b 500000 log-obd --api` ran long enough to write a log segment |
| **Icon not showing in HACS** | Stale cache | Clear browser cache or reload HACS |

---

## 📄 License

MIT
