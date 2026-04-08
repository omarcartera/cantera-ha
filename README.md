# CANtera OBD-II — Home Assistant Integration

A custom Home Assistant integration that connects to a
[CANtera](https://github.com/your-org/cantera) OBD-II logger running on a
Raspberry Pi and streams live vehicle data into HA sensor entities.

---

## Features

- **Live OBD sensors** — auto-created for every PID the ECU supports
  (RPM, speed, coolant temp, throttle, fuel level, …)
- **History backfill** — on reconnect, imports any missed readings into HA
  long-term statistics so your graphs stay complete
- **Zero broker** — connects directly to CANtera's built-in HTTP API; no
  Mosquitto or MQTT setup required
- **HACS compatible** — install from the HACS custom repository list

---

## Prerequisites

| Component | Notes |
|-----------|-------|
| **Raspberry Pi** | Running CANtera with an OBD-II CAN adapter |
| **Tailscale** (recommended) | Gives the Pi a stable IP reachable from your HA instance |
| **Home Assistant** | 2023.6.0 or later |
| **HACS** | For one-click installation (optional — manual install also works) |

---

## Pi Setup

SSH into the Pi and start CANtera with the API server enabled:

```bash
cantera log-obd --api
```

> `--api` enables the built-in HTTP API server on port 8088 (default), exposing
> three endpoints: `/events` (SSE), `/api/history`, and `/api/last-sync`.
> To use a different port: `cantera log-obd --api --api-port 9000`.

To run as a systemd service, create `/etc/systemd/system/cantera-obd.service`:

```ini
[Unit]
Description=CANtera OBD-II logger
After=network.target

[Service]
ExecStart=/usr/local/bin/cantera log-obd --api
Restart=on-failure
RestartSec=10s
User=pi

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now cantera-obd
```

---

## Installation

### Option A: HACS (recommended)

1. Open HACS in Home Assistant
2. Go to **Integrations → ⋮ → Custom repositories**
3. Add this repository URL and select category **Integration**
4. Search for **CANtera OBD-II** and click **Install**
5. Restart Home Assistant

### Option B: Manual

Copy the `custom_components/cantera/` directory into your HA config directory:

```bash
cp -r custom_components/cantera/ /config/custom_components/cantera/
```

Restart Home Assistant.

---

## Configuration

1. Go to **Settings → Devices & Services → + Add Integration**
2. Search for **CANtera**
3. Enter the Pi's IP address (Tailscale IP recommended) and port (default 8088)
4. The integration validates the connection and creates a config entry

---

## What to Expect

After setup, sensor entities are **created automatically** as readings arrive:

| Entity ID | Friendly Name | Unit |
|-----------|---------------|------|
| `sensor.cantera_engine_rpm` | Engine RPM | rpm |
| `sensor.cantera_vehicle_speed` | Vehicle speed | km/h |
| `sensor.cantera_engine_coolant_temperature` | Engine coolant temperature | °C |
| `sensor.cantera_throttle_position` | Throttle position | % |
| `sensor.cantera_fuel_tank_level_input` | Fuel tank level input | % |

Device classes (temperature, speed, voltage, pressure) are assigned
automatically, enabling HA unit conversion and long-term statistics.

On every reconnect, the integration fetches historical readings from the
Pi's Parquet log files and imports them as HA statistics — so your
history graphs stay complete even if HA was offline.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| **"cannot_connect" error** | Verify the Pi is reachable: `curl http://PI_IP:8088/events` should stream SSE data |
| **No entities appear** | Entities are created on the first reading. Start the engine or turn the ignition on. |
| **Connection drops frequently** | Check network stability between HA and the Pi. Tailscale is recommended for reliable connectivity. |
| **Wrong port** | Use `--api-port <N>` when starting CANtera and enter the same port in the HA config flow (default: 8088) |
| **History not importing** | Check HA logs for "History backfill failed". The Pi must have Parquet files in the log directory. |

---

## License

MIT