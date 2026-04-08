"""Constants for the CANtera integration."""

DOMAIN = "cantera"

# Network defaults — must match constants.rs in the cantera Rust codebase
DEFAULT_PORT = 8088
DEFAULT_HOST = ""  # user must provide

# API endpoints — must match api_server/constants.rs
SSE_ENDPOINT = "/events"
HISTORY_ENDPOINT = "/api/history"

# SSE behaviour
SSE_RECONNECT_DELAY_S = 5
SSE_EVENT_TYPE_OBD = "obd_reading"

# Statistics behaviour
HISTORY_BUCKET_MINUTES = 5  # HA statistics minimum bucket size

# HA config entry keys
CONF_HOST = "host"
CONF_PORT = "port"

# Device info
DEVICE_MANUFACTURER = "CANtera"
DEVICE_MODEL = "OBD-II Logger"
DEVICE_IDENTIFIER = "cantera_vehicle"

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
}
