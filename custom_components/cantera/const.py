"""Constants for the CANtera integration."""

DOMAIN = "cantera"

# GitHub repository used for release discovery and self-update.
GITHUB_REPO = "omarcartera/cantera-ha"
GITHUB_RELEASES_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases"
GITHUB_TAGS_URL = f"https://api.github.com/repos/{GITHUB_REPO}/tags"
GITHUB_API_HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

# Network defaults — must match constants.rs in the cantera Rust codebase
DEFAULT_PORT = 8088
DEFAULT_HOST = ""  # user must provide

# API endpoints — must match api_server/constants.rs
SSE_ENDPOINT = "/events"
HEALTH_ENDPOINT = "/api/health"
HISTORY_ENDPOINT = "/api/history"
DEVICE_ENDPOINT = "/api/device"
FIRMWARE_UPDATE_ENDPOINT = "/api/update"
FIRMWARE_INSTALL_ENDPOINT = "/api/update/install"

# Health polling
HEALTH_POLL_INTERVAL_S = 5
HEALTH_FAIL_THRESHOLD = 2  # consecutive failures before marking unreachable

# SSE behaviour
# Initial reconnect delay; grows exponentially up to SSE_MAX_RECONNECT_DELAY_S.
# These are intentionally short because the Pi is a local device — long
# backoffs would leave HA dark for minutes after a Pi restart.  A health-poll
# wake event cuts the backoff short the moment the Pi comes back online.
SSE_RECONNECT_DELAY_S = 3
SSE_MAX_RECONNECT_DELAY_S = 10
SSE_EVENT_TYPE_OBD = "obd_reading"
SSE_EVENT_TYPE_BUS_STATS = "bus_stats"
# Read timeout for the SSE connection.  The Pi firmware sends an SSE keepalive
# comment every 15 s, so 45 s (3×) gives comfortable headroom for normal
# quiet periods while still detecting a power-killed Pi within one keepalive
# period after the timeout fires.  Set to None only with Pi firmware >= 0.54
# that ships the keepalive; older firmware will not produce any bytes when the
# vehicle CAN bus is silent and a timeout would cause spurious reconnects.
SSE_READ_TIMEOUT_S = 45

# Statistics behaviour
HISTORY_BUCKET_MINUTES = 5  # HA statistics minimum bucket size

# HA config entry keys
CONF_HOST = "host"
CONF_PORT = "port"
# Options flow keys — stored in config_entry.options, not config_entry.data.
CONF_HEALTH_POLL_INTERVAL = "health_poll_interval"
CONF_CAR_OFF_DEBOUNCE = "car_off_debounce"

# Device info
DEVICE_MANUFACTURER = "CANtera"
DEVICE_MODEL = "OBD-II Logger"
DEVICE_IDENTIFIER = "cantera_vehicle"

# Sync status sensor states.
# A reading is considered stale when last_reading_ms is older than this.
SYNC_STATUS_LIVE = "live"
SYNC_STATUS_CAR_OFF = "car_off"
SYNC_STATUS_SYNCING = "syncing"
SYNC_STATUS_API_OFFLINE = "api_offline"
SYNC_STATUS_INCOMPATIBLE = "incompatible"

# API contract version this integration was built against.
# EXPECTED_API_VERSION_MAJOR must match the `api_version.major` field returned
# by the Pi's /api/health endpoint.  A mismatch blocks the SSE stream and
# shows SYNC_STATUS_INCOMPATIBLE in the Data Sync Status sensor.
EXPECTED_API_VERSION_MAJOR = 1
# Minimum acceptable minor version from the Pi (informational; minor mismatches
# only produce a log entry, not a hard block).
# History:
#   minor 2 — bus_load_pct in obd_reading events (spec 053)
#   minor 3 — can_signal SSE event, mode field in /api/health, /api/logs
#             endpoints (spec 054 Android target). HA integration does not
#             consume these additions.
#   minor 4 — vin, calibration_id, cvn optional fields in /api/health;
#             Mode 09 sensors now populated via health poll.
#   minor 5 — wifi_ssid, wifi_rssi_dbm, local_ip optional fields in /api/health.
#   minor 6 — sync_status field in /api/health; RPi owns live/car_off/syncing.
#   minor 7 — limit/offset pagination on /api/history; capped page sizes;
#             HTTP gzip compression support.
#   minor 8 — cpu_temp_c, disk_usage_pct, throttled_flags optional fields
#             in /api/health; new /metrics Prometheus endpoint.
MIN_API_VERSION_MINOR = 8
#   minor 5 — wifi_ssid, wifi_rssi_dbm, local_ip optional fields in /api/health.
#   minor 6 — sync_status field in /api/health; RPi owns live/car_off/syncing.
SYNC_STALE_THRESHOLD_S = 30  # seconds before a reading timestamp is considered stale
# How long car-off condition must persist before sync_status flips to "car_off".
# This prevents rapid oscillation when the ECU briefly stops responding between
# successful OBD poll cycles (e.g. during ECU keep-alive retries).
SYNC_CAR_OFF_DEBOUNCE_S = 30
# How long to show last-known values during an API outage before zeroing sensors.
# A brief Pi reboot (~30-60 s) should not cause cards to blank out.
SENSOR_API_OFFLINE_GRACE_S = 60

# Page size for history backfill pagination.
# Must be ≤ the Rust server's HISTORY_MAX_ROWS (currently 50_000).
HISTORY_PAGE_SIZE = 10_000

# Unit -> HA device_class mapping
UNIT_DEVICE_CLASS_MAP = {
    "km/h": "speed",
    "mph": "speed",
    "°C": "temperature",
    "℃": "temperature",
    "V": "voltage",
    "kPa": "pressure",
    "Pa": "pressure",
    "%": None,
    "rpm": None,
    "g/s": None,
    "km": "distance",
    "L": "volume",
    "L/h": None,
    # Additional units from OBD PID registry
    "s": None,
    "min": None,
    "Nm": None,
    "ppm": None,
    "λ": None,
    "°BTDC": None,
    "°": None,
}

# Unit -> HA state_class mapping
UNIT_STATE_CLASS_MAP = {
    "km/h": "measurement",
    "mph": "measurement",
    "°C": "measurement",
    "℃": "measurement",
    "V": "measurement",
    "kPa": "measurement",
    "Pa": "measurement",
    "%": "measurement",
    "rpm": "measurement",
    "g/s": "measurement",
    "km": "total_increasing",
    "L": "total_increasing",
    "L/h": "measurement",
    # Additional units from OBD PID registry
    "s": "measurement",
    "min": "measurement",
    "Nm": "measurement",
    "ppm": "measurement",
    "λ": "measurement",
    "°BTDC": "measurement",
    "°": "measurement",
}

# Unit -> suggested display precision (decimal places shown in HA UI).
# Units absent from this map get no override (HA auto-selects).
UNIT_PRECISION_MAP: dict[str, int] = {
    "rpm":   0,  # 2400, not 2400.12
    "km/h":  0,  # 60, not 60.3
    "mph":   0,
    "°C":    1,  # 90.5
    "℃":     1,
    "%":     1,  # 42.3 %
    "kPa":   1,  # 101.3 kPa
    "Pa":    0,  # integer pascals
    "V":     2,  # 14.23 V
    "km":    0,  # 12345 km
    "g/s":   2,  # 5.42 g/s
    "L/h":   1,  # 8.5 L/h
    "L":     1,
    "s":     0,  # integer seconds
    "min":   0,  # integer minutes
    "Nm":    0,  # integer newton-metres
    "ppm":   0,  # integer parts-per-million
    "λ":     3,  # 0.998 lambda ratio
    "°BTDC": 1,  # 12.5 °BTDC
    "°":     1,  # generic degrees
}

# ---------------------------------------------------------------------------
# OBD PID registries — sourced from src-tauri/src/db/mode01.rs and mode09.rs.
# Each entry is (human-readable name, native unit or None).
# Units that describe data types (bitmap, bitmask, DTC, enum, count) are
# represented as None since they carry no physical measurement unit.
# ---------------------------------------------------------------------------

MODE01_PIDS: list[tuple[str, str | None]] = [
    ("PIDs supported", "bitmap"),
    ("Monitor status since DTCs cleared", "bitmask"),
    ("Freeze DTC", "DTC"),
    ("Fuel system status", "enum"),
    ("Calculated engine load", "%"),
    ("Engine Coolant Temperature", "°C"),
    ("Short term fuel trim (STFT)—Bank 1", "%"),
    ("Long-term fuel trim bank 1", "%"),
    ("Short-term fuel trim bank 2", "%"),
    ("Long-term fuel trim bank 2", "%"),
    ("Fuel pressure", "kPa"),
    ("Intake manifold absolute pressure", "kPa"),
    ("Engine RPM", "rpm"),
    ("Vehicle Speed", "km/h"),
    ("Ignition Timing Advance", "°BTDC"),
    ("Intake Air Temperature", "°C"),
    ("Mass Air Flow Rate", "g/s"),
    ("Throttle Position", "%"),
    ("Commanded secondary air status", None),
    ("Oxygen sensors present (in 2 banks)", None),
    ("O2 sensor 1 — bank 1", "V"),
    ("O2 sensor 2 — bank 1", "V"),
    ("O2 sensor 3 — bank 1", "V"),
    ("O2 sensor 4 — bank 1", "V"),
    ("O2 sensor 1 — bank 2", "V"),
    ("O2 sensor 2 — bank 2", "V"),
    ("O2 sensor 3 — bank 2", "V"),
    ("O2 sensor 4 — bank 2", "V"),
    ("OBD standards this vehicle conforms to", None),
    ("Oxygen sensors present (in 4 banks)", None),
    ("Auxiliary input status", None),
    ("Run time since engine start", "s"),
    ("PIDs supported", "bitmap"),
    ("Distance traveled with malfunction indicator lamp (MIL) on", "km"),
    ("Fuel Rail Pressure (relative to manifold vacuum)", "kPa"),
    ("Fuel Rail Gauge Pressure (diesel, or gasoline direct injection)", "kPa"),
    ("O2 sensor 1 — λ/voltage", "ratioV"),
    ("O2 sensor 2 — λ/voltage", None),
    ("O2 sensor 3 — λ/voltage", None),
    ("O2 sensor 4 — λ/voltage", None),
    ("O2 sensor 5 — λ/voltage", None),
    ("O2 sensor 6 — λ/voltage", None),
    ("O2 sensor 7 — λ/voltage", None),
    ("O2 sensor 8 — λ/voltage", None),
    ("Commanded EGR", "%"),
    ("EGR Error", "%"),
    ("Commanded evaporative purge", "%"),
    ("Fuel Tank Level Input", "%"),
    ("Warm-ups since DTC clear", "count"),
    ("Distance since DTC clear", "km"),
    ("Evap system vapor pressure", "Pa"),
    ("Barometric pressure", "kPa"),
    ("O2 sensor 1 — λ/current", "ratiomA"),
    ("O2 sensor 2 — λ/current", None),
    ("O2 sensor 3 — λ/current", None),
    ("O2 sensor 4 — λ/current", None),
    ("O2 sensor 5 — λ/current", None),
    ("O2 sensor 6 — λ/current", None),
    ("O2 sensor 7 — λ/current", None),
    ("O2 sensor 8 — λ/current", None),
    ("Catalyst temperature B1S1", "°C"),
    ("Catalyst temperature B2S1", "°C"),
    ("Catalyst temperature B1S2", "°C"),
    ("Catalyst temperature B2S2", "°C"),
    ("PIDs supported", "bitmap"),
    ("Monitor status this drive cycle", "bitmask"),
    ("Control module voltage", "V"),
    ("Absolute load value", "%"),
    ("Commanded equivalence ratio", "λ"),
    ("Relative throttle position", "%"),
    ("Ambient air temperature", "°C"),
    ("Absolute throttle position B", "%"),
    ("Absolute throttle position C", "%"),
    ("Accelerator pedal position D", "%"),
    ("Accelerator pedal position E", "%"),
    ("Accelerator pedal position F", "%"),
    ("Commanded throttle actuator", "%"),
    ("Time run with MIL on", "min"),
    ("Time since DTC clear", "min"),
    ("Maximum values (various)", "ratio, V, mA, kPa"),
    ("Maximum MAF flow rate", "g/s"),
    ("Fuel type", "enum"),
    ("Ethanol fuel %", "%"),
    ("Absolute evap vapor pressure", "kPa"),
    ("Evap vapor pressure (signed)", "Pa"),
    ("Short-term O2 trim — bank 1 & 3", "%"),
    ("Long-term O2 trim — bank 1 & 3", "%"),
    ("Short-term O2 trim — bank 2 & 4", "%"),
    ("Long-term O2 trim — bank 2 & 4", "%"),
    ("Fuel rail absolute pressure", "kPa"),
    ("Relative accelerator pedal position", "%"),
    ("Hybrid battery pack remaining life", "%"),
    ("Engine oil temperature", "°C"),
    ("Fuel injection timing", "°"),
    ("Engine fuel rate", "L/h"),
    ("Emission requirements", None),
    ("PIDs supported", "bitmap"),
    ("Driver's demand engine torque", "%"),
    ("Actual engine torque", "%"),
    ("Engine reference torque", "Nm"),
    ("Engine percent torque data", "%"),
    ("Auxiliary I/O supported", None),
    ("MAF sensor (dual)", "g/s"),
    ("Engine coolant temperature (dual)", "°C"),
    ("Intake air temperature (multi)", "°C"),
    ("Commanded EGR and EGR error", "%"),
    ("Commanded Diesel intake air flow control and relative intake air flow position", None),
    ("EGR temperature", "°C"),
    ("Commanded throttle actuator control and relative throttle position", None),
    ("Fuel pressure control", "kPa"),
    ("Injection pressure control", "kPa"),
    ("Turbocharger compressor inlet pressure", None),
    ("Boost pressure control", "kPa"),
    ("Variable Geometry turbo (VGT) control", None),
    ("Wastegate control", None),
    ("Exhaust pressure", "kPa"),
    ("Turbocharger RPM", "rpm"),
    ("Turbocharger temperature", None),
    ("Turbocharger temperature", None),
    ("Charge air cooler temperature (CACT)", "°C"),
    ("Exhaust Gas temperature (EGT) Bank 1", "°C"),
    ("Exhaust Gas temperature (EGT) Bank 2", "°C"),
    ("Diesel particulate filter (DPF) differential pressure", "°C"),
    ("Diesel particulate filter (DPF)", "°C"),
    ("DPF temperature", "°C"),
    ("NOx NTE control area status", "°C"),
    ("PM NTE control area status", None),
    ("Engine run time [b]", "s"),
    ("PIDs supported", "bitmap"),
    ("Engine run time for Auxiliary Emissions Control Device(AECD)", None),
    ("Engine run time for Auxiliary Emissions Control Device(AECD)", None),
    ("NOx sensor", "ppm"),
    ("Manifold surface temperature", "°C"),
    ("NOx reagent system", "%"),
    ("PM sensor — bank 1", None),
    ("Intake manifold absolute pressure", None),
    ("SCR Induce System", None),
    ("Run Time for AECD #11-#15", None),
    ("Run Time for AECD #16-#20", None),
    ("Diesel Aftertreatment", None),
    ("O2 Sensor (Wide Range)", None),
    ("Throttle Position G", "%"),
    ("Engine Friction - Percent Torque", "%"),
    ("PM Sensor Bank 1 & 2", None),
    ("WWH-OBD Vehicle OBD System Information", "h"),
    ("WWH-OBD Vehicle OBD System Information", "h"),
    ("Fuel System Control", None),
    ("WWH-OBD Vehicle OBD Counters support", "h"),
    ("NOx Warning And Inducement System", None),
    ("Exhaust Gas Temperature Sensor", None),
    ("Exhaust Gas Temperature Sensor", None),
    ("Hybrid/EV Vehicle System Data, Battery, Voltage", None),
    ("Diesel Exhaust Fluid Sensor Data", "%"),
    ("O2 Sensor Data", None),
    ("Engine Fuel Rate", "g/s"),
    ("Engine Exhaust Flow Rate", "kg/h"),
    ("Fuel System Percentage Use", None),
    ("PIDs supported", "bitmap"),
    ("NOx Sensor Corrected Data", "ppm"),
    ("Cylinder Fuel Rate", "mg/stroke"),
    ("Evap System Vapor Pressure", "Pa"),
    ("Transmission Actual Gear", "ratio"),
    ("Commanded Diesel Exhaust Fluid Dosing", "%"),
    ("Odometer [c]", "km"),
    ("NOx Sensor Concentration Sensors 3 and 4", None),
    ("NOx Sensor Corrected Concentration Sensors 3 and 4", None),
    ("ABS Disable Switch State", None),
    ("PIDs supported", "bitmap"),
    ("Fuel Level Input A/B", "%"),
    ("Exhaust Particulate Control System Diagnostic Time/Count", None),
    ("Fuel Pressure A and B", "kPa"),
    ("Particulate control system status", None),
    ("Distance Since Reflash or Module Replacement", "km"),
    ("NOx Control Diagnostic and Particulate Control Diagnostic Warning Lamp status", None),
]

# Mode 01 PIDs that must retain their last-known value when the car is off or
# the API is offline.  Add PIDs here when their physical property cannot be 0
# while the engine is stopped (e.g. fuel level does not drain to 0 at key-off).
PERSISTENT_MODE01_PIDS: frozenset[str] = frozenset(
    [
        "Fuel Tank Level Input",
    ]
)

MODE09_PIDS: list[tuple[str, str | None]] = [
    ("Supported InfoType PIDs (00-1F)", None),         # 0x00
    ("VIN - Message Count", None),                     # 0x01 (non-CAN only)
    ("Vehicle Identification Number (VIN)", None),     # 0x02
    ("Calibration ID Number - Message Count", None),   # 0x03 (non-CAN only)
    ("Calibration ID (CalID)", None),                  # 0x04
    ("CVN - Message Count", None),                     # 0x05 (non-CAN only)
    ("Calibration Verification Number (CVN)", None),   # 0x06
    ("IUPR Message Count", None),                      # 0x07 (non-CAN only)
    ("In-use Performance Tracking (Spark Ignition)", None),         # 0x08
    ("ECU Name Message Count", None),                  # 0x09
    ("ECU Name", None),                                # 0x0A
    ("In-use Performance Tracking (Compression Ignition)", None),   # 0x0B
]
