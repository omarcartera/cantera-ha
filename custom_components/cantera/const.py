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
SSE_RECONNECT_DELAY_S = 5
SSE_EVENT_TYPE_OBD = "obd_reading"
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
MIN_API_VERSION_MINOR = 0
SYNC_STALE_THRESHOLD_S = 30  # seconds before a reading timestamp is considered stale
# How long car-off condition must persist before sync_status flips to "car_off".
# This prevents rapid oscillation when the ECU briefly stops responding between
# successful OBD poll cycles (e.g. during ECU keep-alive retries).
SYNC_CAR_OFF_DEBOUNCE_S = 30
# How long to show last-known values during an API outage before zeroing sensors.
# A brief Pi reboot (~30-60 s) should not cause cards to blank out.
SENSOR_API_OFFLINE_GRACE_S = 60

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
    ("Supported PIDs (00-1F)", None),
    ("Monitor status since DTCs cleared", None),
    ("Freeze DTC", None),
    ("Fuel system status", None),
    ("Calculated engine load", "%"),
    ("Engine Coolant Temperature", "°C"),
    ("Short-term fuel trim bank 1", "%"),
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
    ("Run time since engine start", "s"),
    ("Fuel Tank Level Input", "%"),
    ("Distance traveled with MIL on", "km"),
    ("Fuel rail pressure (relative)", "kPa"),
    ("Fuel rail gauge pressure", "kPa"),
    ("Commanded EGR", "%"),
    ("EGR error", "%"),
    ("Commanded evaporative purge", "%"),
    ("Warm-ups since DTC clear", None),
    ("Distance since DTC clear", "km"),
    ("Barometric pressure", "kPa"),
    ("Catalyst temperature B1S1", "°C"),
    ("Catalyst temperature B2S1", "°C"),
    ("Catalyst temperature B1S2", "°C"),
    ("Catalyst temperature B2S2", "°C"),
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
    ("Fuel type", None),
    ("Ethanol fuel %", "%"),
    ("Engine oil temperature", "°C"),
    ("Engine fuel rate", "L/h"),
    ("Commanded secondary air status", None),
    ("Oxygen sensors present (2-bank)", None),
    ("O2 sensor 1 \u2014 bank 1", "V"),
    ("O2 sensor 2 \u2014 bank 1", "V"),
    ("O2 sensor 3 \u2014 bank 1", "V"),
    ("O2 sensor 4 \u2014 bank 1", "V"),
    ("O2 sensor 1 \u2014 bank 2", "V"),
    ("O2 sensor 2 \u2014 bank 2", "V"),
    ("O2 sensor 3 \u2014 bank 2", "V"),
    ("O2 sensor 4 \u2014 bank 2", "V"),
    ("OBD standards compliance", None),
    ("Oxygen sensors present (4-bank)", None),
    ("Auxiliary input status", None),
    ("PIDs supported [21-40]", None),
    ("O2 sensor 1 \u2014 \u03bb/voltage", None),
    ("O2 sensor 2 \u2014 \u03bb/voltage", None),
    ("O2 sensor 3 \u2014 \u03bb/voltage", None),
    ("O2 sensor 4 \u2014 \u03bb/voltage", None),
    ("O2 sensor 5 \u2014 \u03bb/voltage", None),
    ("O2 sensor 6 \u2014 \u03bb/voltage", None),
    ("O2 sensor 7 \u2014 \u03bb/voltage", None),
    ("O2 sensor 8 \u2014 \u03bb/voltage", None),
    ("Evap system vapor pressure", "Pa"),
    ("O2 sensor 1 \u2014 \u03bb/current", None),
    ("O2 sensor 2 \u2014 \u03bb/current", None),
    ("O2 sensor 3 \u2014 \u03bb/current", None),
    ("O2 sensor 4 \u2014 \u03bb/current", None),
    ("O2 sensor 5 \u2014 \u03bb/current", None),
    ("O2 sensor 6 \u2014 \u03bb/current", None),
    ("O2 sensor 7 \u2014 \u03bb/current", None),
    ("O2 sensor 8 \u2014 \u03bb/current", None),
    ("PIDs supported [41-60]", None),
    ("Monitor status this drive cycle", None),
    ("Maximum values (various)", None),
    ("Maximum MAF flow rate", "g/s"),
    ("Absolute evap vapor pressure", "kPa"),
    ("Evap vapor pressure (signed)", "Pa"),
    ("Short-term O2 trim \u2014 bank 1 & 3", "%"),
    ("Long-term O2 trim \u2014 bank 1 & 3", "%"),
    ("Short-term O2 trim \u2014 bank 2 & 4", "%"),
    ("Long-term O2 trim \u2014 bank 2 & 4", "%"),
    ("Fuel rail absolute pressure", "kPa"),
    ("Relative accelerator pedal position", "%"),
    ("Hybrid battery pack remaining life", "%"),
    ("Fuel injection timing", "\u00b0"),
    ("Emission requirements", None),
    ("PIDs supported [61-80]", None),
    ("Driver's demand engine torque", "%"),
    ("Actual engine torque", "%"),
    ("Engine reference torque", "Nm"),
    ("Engine percent torque data", "%"),
    ("Auxiliary I/O supported", None),
    ("MAF sensor (dual)", "g/s"),
    ("Engine coolant temperature (dual)", "°C"),
    ("Intake air temperature (multi)", "°C"),
    ("Commanded EGR and EGR error", "%"),
    ("EGR temperature", "°C"),
    ("Fuel pressure control", "kPa"),
    ("Injection pressure control", "kPa"),
    ("Boost pressure control", "kPa"),
    ("Exhaust pressure", "kPa"),
    ("Turbocharger RPM", "rpm"),
    ("Charge air cooler temperature (CACT)", "°C"),
    ("EGT \u2014 bank 1", "°C"),
    ("EGT \u2014 bank 2", "°C"),
    ("EGT \u2014 bank 3", "°C"),
    ("EGT \u2014 bank 4", "°C"),
    ("DPF", None),
    ("DPF temperature", "°C"),
    ("PM sensor", None),
    ("PIDs supported [81-A0]", None),
    ("NOx sensor", "ppm"),
    ("Manifold surface temperature", "°C"),
    ("NOx reagent system", None),
    ("PM sensor \u2014 bank 1", None),
    ("Engine friction \u2014 percent torque", "%"),
    ("PIDs supported [A1-C0]", None),
    ("PIDs supported [C1-E0]", None),
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
