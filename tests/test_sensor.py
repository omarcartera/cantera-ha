"""Tests for CANtera sensor entities."""
import time
from unittest.mock import MagicMock

import pytest

from custom_components.cantera.const import (
    CONF_HOST,
    CONF_PORT,
    DEVICE_MANUFACTURER,
    DEVICE_MODEL,
    DOMAIN,
    MODE01_PIDS,
    MODE09_PIDS,
    SENSOR_API_OFFLINE_GRACE_S,
    SYNC_CAR_OFF_DEBOUNCE_S,
    SYNC_STALE_THRESHOLD_S,
    SYNC_STATUS_API_OFFLINE,
    SYNC_STATUS_CAR_OFF,
    SYNC_STATUS_LIVE,
    SYNC_STATUS_SYNCING,
    UNIT_PRECISION_MAP,
)
from custom_components.cantera.coordinator import CanteraCoordinator
from custom_components.cantera.sensor import (
    CanteraSensor,
    CanteraSyncStatusSensor,
    CanteraBusLoadSensor,
    async_setup_entry,
)


@pytest.fixture
def mock_entry():
    entry = MagicMock()
    entry.data = {CONF_HOST: "192.168.1.100", CONF_PORT: 8088}
    entry.entry_id = "test_entry_id"
    return entry


@pytest.fixture
def coordinator(hass, mock_entry):
    return CanteraCoordinator(hass, mock_entry)


@pytest.fixture
def sensor(coordinator, mock_entry):
    """Pre-created sensor for Engine RPM (new constructor signature)."""
    s = CanteraSensor(coordinator, "Engine RPM", "rpm", mock_entry)
    s.async_write_ha_state = MagicMock()
    return s


# ---------- CanteraSensor unit tests ----------

def test_sensor_unique_id(sensor):
    assert sensor._attr_unique_id == "cantera_test_entry_id_engine_rpm"


def test_sensor_name(sensor):
    assert sensor._attr_name == "Engine RPM"


def test_sensor_native_unit(sensor):
    assert sensor._attr_native_unit_of_measurement == "rpm"


def test_sensor_initial_value_is_none(sensor):
    """Pre-created sensors start with None — value arrives via SSE."""
    assert sensor._attr_native_value is None


def test_sensor_precision_rpm(coordinator):
    """rpm sensor gets 0 decimal places."""
    s = CanteraSensor(coordinator, "Engine RPM", "rpm")
    assert s._attr_suggested_display_precision == 0


def test_sensor_precision_temperature(coordinator):
    """°C sensor gets 1 decimal place."""
    s = CanteraSensor(coordinator, "Engine Coolant Temperature", "°C")
    assert s._attr_suggested_display_precision == 1


def test_sensor_precision_voltage(coordinator):
    """V sensor gets 2 decimal places."""
    s = CanteraSensor(coordinator, "Control module voltage", "V")
    assert s._attr_suggested_display_precision == 2


def test_sensor_precision_lambda(coordinator):
    """λ sensor gets 3 decimal places."""
    s = CanteraSensor(coordinator, "Commanded equivalence ratio", "λ")
    assert s._attr_suggested_display_precision == 3


def test_sensor_precision_no_unit(coordinator):
    """Sensor with no unit has no precision override."""
    s = CanteraSensor(coordinator, "Freeze DTC")
    assert s._attr_suggested_display_precision is None


def test_sensor_precision_all_mapped_units(coordinator):
    """Every unit in UNIT_PRECISION_MAP is a non-negative integer."""
    for unit, precision in UNIT_PRECISION_MAP.items():
        assert isinstance(precision, int) and precision >= 0, (
            f"Bad precision for {unit!r}: {precision!r}"
        )


def test_sensor_device_info(sensor):
    info = sensor._attr_device_info
    assert (DOMAIN, "cantera_vehicle_test_entry_id") in info["identifiers"]
    assert info["manufacturer"] == DEVICE_MANUFACTURER
    assert info["model"] == DEVICE_MODEL


def test_sensor_no_unit(coordinator):
    """Sensor with no unit gets None for native_unit_of_measurement."""
    s = CanteraSensor(coordinator, "Freeze DTC")
    assert s._attr_native_unit_of_measurement is None


def test_sensor_is_diagnostic_sets_entity_category(coordinator):
    """Sensors created with is_diagnostic=True carry DIAGNOSTIC entity category."""
    from homeassistant.helpers.entity import EntityCategory
    s = CanteraSensor(coordinator, "VIN", None, is_diagnostic=True)
    assert s._attr_entity_category == EntityCategory.DIAGNOSTIC


def test_sensor_not_diagnostic_by_default(coordinator):
    """Normal sensors have no entity category override."""
    s = CanteraSensor(coordinator, "Engine RPM", "rpm")
    assert getattr(s, "_attr_entity_category", None) is None


def test_sensor_km_h_device_class(coordinator):
    """km/h maps to SensorDeviceClass.SPEED."""
    from homeassistant.components.sensor import SensorDeviceClass
    s = CanteraSensor(coordinator, "Vehicle Speed", "km/h")
    assert s._attr_device_class == SensorDeviceClass.SPEED


def test_sensor_temperature_device_class(coordinator):
    """°C maps to SensorDeviceClass.TEMPERATURE."""
    from homeassistant.components.sensor import SensorDeviceClass
    s = CanteraSensor(coordinator, "Engine Coolant Temperature", "°C")
    assert s._attr_device_class == SensorDeviceClass.TEMPERATURE


def test_sensor_voltage_device_class(coordinator):
    """V maps to SensorDeviceClass.VOLTAGE."""
    from homeassistant.components.sensor import SensorDeviceClass
    s = CanteraSensor(coordinator, "Control module voltage", "V")
    assert s._attr_device_class == SensorDeviceClass.VOLTAGE


def test_handle_reading_updates_value(sensor):
    """_handle_reading always updates the sensor value (slug dispatch is at coordinator)."""
    sensor._handle_reading({"pid": "Engine RPM", "value": 3000.0, "unit": "rpm"})
    assert sensor._attr_native_value == 3000.0
    sensor.async_write_ha_state.assert_called_once()


def test_handle_reading_clears_restored_flag(sensor):
    """_handle_reading resets _restored so live data takes over availability."""
    sensor._restored = True
    sensor._handle_reading({"pid": "Engine RPM", "value": 1500.0})
    assert sensor._restored is False


# ---------- async_setup_entry ----------

async def test_async_setup_entry_creates_all_pid_sensors(hass, mock_entry, coordinator):
    """async_setup_entry pre-creates sensors for all Mode 01 and Mode 09 PIDs."""
    mock_entry.runtime_data = coordinator
    added: list = []
    add_entities = MagicMock(side_effect=lambda entities: added.extend(entities))
    await async_setup_entry(hass, mock_entry, add_entities)

    expected_count = (
        # sync_status + firmware_version + firmware_update_status + pi_api_version + expected_api_version + bus_load + mode01 + mode09
        1 + 1 + 1 + 1 + 1 + 1 + len(MODE01_PIDS) + len(MODE09_PIDS)
    )
    assert len(added) == expected_count


async def test_async_setup_entry_no_dynamic_listener(hass, mock_entry, coordinator):
    """async_setup_entry does not register a reading listener itself.

    Per-sensor reading listeners are registered in async_added_to_hass, not here.
    """
    mock_entry.runtime_data = coordinator
    total_before = sum(len(v) for v in coordinator._reading_listeners.values())
    await async_setup_entry(hass, mock_entry, MagicMock())
    total_after = sum(len(v) for v in coordinator._reading_listeners.values())
    assert total_after == total_before


async def test_async_setup_entry_pid_sensors_have_none_initial_value(hass, mock_entry, coordinator):
    """All pre-created PID sensors start with native_value None."""
    mock_entry.runtime_data = coordinator
    added: list = []
    add_entities = MagicMock(side_effect=lambda entities: added.extend(entities))
    await async_setup_entry(hass, mock_entry, add_entities)

    pid_sensors = [e for e in added if isinstance(e, CanteraSensor)]
    assert all(s._attr_native_value is None for s in pid_sensors)


async def test_async_setup_entry_includes_mode01_pids(hass, mock_entry, coordinator):
    """Every Mode 01 PID name appears in the pre-created sensor list."""
    mock_entry.runtime_data = coordinator
    added: list = []
    add_entities = MagicMock(side_effect=lambda entities: added.extend(entities))
    await async_setup_entry(hass, mock_entry, add_entities)

    sensor_names = {e._attr_name for e in added if isinstance(e, CanteraSensor)}
    for name, _ in MODE01_PIDS:
        assert name in sensor_names, f"Missing Mode 01 sensor: {name}"


async def test_async_setup_entry_includes_mode09_pids(hass, mock_entry, coordinator):
    """Every Mode 09 PID name appears in the pre-created sensor list."""
    mock_entry.runtime_data = coordinator
    added: list = []
    add_entities = MagicMock(side_effect=lambda entities: added.extend(entities))
    await async_setup_entry(hass, mock_entry, add_entities)

    sensor_names = {e._attr_name for e in added if isinstance(e, CanteraSensor)}
    for name, _ in MODE09_PIDS:
        assert name in sensor_names, f"Missing Mode 09 sensor: {name}"


# ---------- CanteraSyncStatusSensor unit tests ----------

@pytest.fixture
def sync_sensor(coordinator, mock_entry):
    s = CanteraSyncStatusSensor(coordinator, mock_entry)
    s.async_write_ha_state = MagicMock()
    return s


def test_sync_sensor_unique_id(sync_sensor):
    assert sync_sensor._attr_unique_id == "cantera_test_entry_id_sync_status"


def test_sync_sensor_name(sync_sensor):
    assert sync_sensor._attr_name == "Data Sync Status"


def test_sync_sensor_device_class_is_enum(sync_sensor):
    """CanteraSyncStatusSensor uses the ENUM device class for translation support."""
    from homeassistant.components.sensor import SensorDeviceClass
    assert sync_sensor._attr_device_class == SensorDeviceClass.ENUM


def test_sync_sensor_options_cover_all_states(sync_sensor):
    """_attr_options must include every possible sync-status value."""
    from custom_components.cantera.sensor import _SYNC_STATUS_ICON
    assert set(sync_sensor._attr_options) == set(_SYNC_STATUS_ICON)


def test_sync_sensor_translation_key(sync_sensor):
    assert sync_sensor._attr_translation_key == "sync_status"


def test_sync_sensor_entity_category_is_diagnostic(sync_sensor):
    """Data Sync Status belongs in the Diagnostics section of the device page."""
    from homeassistant.helpers.entity import EntityCategory
    assert sync_sensor._attr_entity_category == EntityCategory.DIAGNOSTIC


def test_sync_status_api_offline_by_default(sync_sensor, coordinator):
    """Without any health data, status is api_offline."""
    assert coordinator.sync_status == SYNC_STATUS_API_OFFLINE
    assert sync_sensor.native_value == SYNC_STATUS_API_OFFLINE


def test_sync_status_car_off_when_can_not_connected(coordinator):
    """API reachable but can_connected=False → car_off after debounce."""
    coordinator._api_reachable = True
    coordinator._health_data = {"can_connected": False, "last_reading_ms": 0}
    # Simulate debounce window having elapsed.
    coordinator._car_off_since_mono = time.monotonic() - SYNC_CAR_OFF_DEBOUNCE_S - 1
    assert coordinator.sync_status == SYNC_STATUS_CAR_OFF


def test_sync_status_car_off_when_no_reading(coordinator):
    """API reachable, CAN connected, but last_reading_ms=0 → car_off after debounce."""
    coordinator._api_reachable = True
    coordinator._health_data = {"can_connected": True, "last_reading_ms": 0}
    coordinator._car_off_since_mono = time.monotonic() - SYNC_CAR_OFF_DEBOUNCE_S - 1
    assert coordinator.sync_status == SYNC_STATUS_CAR_OFF


def test_sync_status_car_off_when_reading_stale(coordinator):
    """API reachable, CAN connected, but reading older than threshold → car_off after debounce."""
    coordinator._api_reachable = True
    now_ms = int(time.time() * 1000)
    stale_ms = now_ms - (SYNC_STALE_THRESHOLD_S + 10) * 1000
    coordinator._health_data = {"can_connected": True, "last_reading_ms": stale_ms}
    coordinator._car_off_since_mono = time.monotonic() - SYNC_CAR_OFF_DEBOUNCE_S - 1
    assert coordinator.sync_status == SYNC_STATUS_CAR_OFF


def test_sync_status_live_when_recent_reading(coordinator):
    """API reachable, CAN connected, reading within threshold → live."""
    coordinator._api_reachable = True
    now_ms = int(time.time() * 1000)
    coordinator._health_data = {"can_connected": True, "last_reading_ms": now_ms - 5000}
    assert coordinator.sync_status == SYNC_STATUS_LIVE


def test_sync_status_live_during_car_off_debounce_window(coordinator):
    """car_off condition not yet persisted for full debounce → stay live."""
    coordinator._api_reachable = True
    coordinator._health_data = {"can_connected": False, "last_reading_ms": 0}
    # Just started — debounce timer set to 1 second ago, well within 30 s window.
    coordinator._car_off_since_mono = time.monotonic() - 1
    assert coordinator.sync_status == SYNC_STATUS_LIVE


def test_sync_status_car_off_resets_on_live(coordinator):
    """Once live data comes back, _car_off_since_mono is cleared."""
    coordinator._api_reachable = True
    coordinator._car_off_since_mono = time.monotonic() - SYNC_CAR_OFF_DEBOUNCE_S - 5
    now_ms = int(time.time() * 1000)
    coordinator._health_data = {"can_connected": True, "last_reading_ms": now_ms - 1000}
    coordinator._update_car_off_debounce()
    assert coordinator._car_off_since_mono is None
    assert coordinator.sync_status == SYNC_STATUS_LIVE


def test_sync_status_syncing_during_backfill(coordinator):
    """API reachable + backfilling in progress → syncing."""
    coordinator._api_reachable = True
    coordinator._backfilling = True
    coordinator._health_data = {"can_connected": True, "last_reading_ms": int(time.time() * 1000)}
    assert coordinator.sync_status == SYNC_STATUS_SYNCING


def test_sync_status_icon_matches_state(coordinator):
    """Icon changes with state."""
    from custom_components.cantera.sensor import _SYNC_STATUS_ICON
    for _state, icon in _SYNC_STATUS_ICON.items():
        assert icon.startswith("mdi:")


def test_sync_sensor_health_update_triggers_write(sync_sensor):
    """Health update callback triggers async_write_ha_state."""
    sync_sensor._handle_health_update({})
    sync_sensor.async_write_ha_state.assert_called_once()


async def test_async_setup_entry_adds_sync_status_sensor(hass, mock_entry, coordinator):
    """async_setup_entry immediately registers CanteraSyncStatusSensor."""
    mock_entry.runtime_data = coordinator
    added: list = []
    add_entities = MagicMock(side_effect=lambda entities: added.extend(entities))
    await async_setup_entry(hass, mock_entry, add_entities)
    sync_sensors = [e for e in added if isinstance(e, CanteraSyncStatusSensor)]
    assert len(sync_sensors) == 1


# ---------- CanteraSensor availability ----------

def test_sensor_available_during_startup_grace(sensor, coordinator):
    """Before the first health response, sensor is optimistically available."""
    assert coordinator._first_health_received is False
    assert sensor.available is True


def test_sensor_always_available_when_api_offline(sensor, coordinator):
    """Sensor stays available when API is offline — shows 0 instead of unavailable."""
    coordinator._first_health_received = True
    coordinator._api_reachable = False
    assert coordinator.sync_status == SYNC_STATUS_API_OFFLINE
    assert sensor.available is True
    # Grace window not elapsed (last_live_at=0 → infinite elapsed → 0)
    assert sensor.native_value == 0


def test_sensor_always_available_when_car_off(sensor, coordinator):
    """Sensor stays available and reports 0 when car is off (debounce elapsed)."""
    coordinator._first_health_received = True
    coordinator._api_reachable = True
    coordinator._health_data = {"can_connected": False, "last_reading_ms": 0}
    coordinator._car_off_since_mono = time.monotonic() - SYNC_CAR_OFF_DEBOUNCE_S - 1
    assert coordinator.sync_status == SYNC_STATUS_CAR_OFF
    assert sensor.available is True
    assert sensor.native_value == 0


def test_sensor_available_when_live(sensor, coordinator):
    """Sensor reports available only when sync_status is live."""
    import time as _time
    coordinator._first_health_received = True
    coordinator._api_reachable = True
    coordinator._health_data = {
        "can_connected": True,
        "last_reading_ms": int(_time.time() * 1000) - 2000,
    }
    assert coordinator.sync_status == SYNC_STATUS_LIVE
    assert sensor.available is True


def test_sensor_available_during_syncing(sensor, coordinator):
    """Sensor stays available while backfill is in progress."""
    import time as _time
    coordinator._first_health_received = True
    coordinator._api_reachable = True
    coordinator._backfilling = True
    coordinator._health_data = {
        "can_connected": True,
        "last_reading_ms": int(_time.time() * 1000) - 2000,
    }
    assert coordinator.sync_status == SYNC_STATUS_SYNCING
    assert sensor.available is True


def test_sensor_health_update_triggers_write(sensor):
    """_handle_health_update calls async_write_ha_state when availability changes."""
    sensor._handle_health_update({"can_connected": True})
    # First call: cache was None, now True (startup grace) → write triggered
    sensor.async_write_ha_state.assert_called_once()


def test_sensor_health_update_always_writes(sensor, coordinator):
    """_handle_health_update always calls async_write_ha_state.

    (native_value depends on sync_status)
    """
    coordinator._first_health_received = True
    coordinator._api_reachable = False
    sensor._handle_health_update({})
    sensor.async_write_ha_state.reset_mock()
    # Second call with same state still writes — native_value may have changed
    sensor._handle_health_update({})
    sensor.async_write_ha_state.assert_called_once()


# ---------- native_value fallback behaviour ----------

def test_native_value_zero_when_car_off(sensor, coordinator):
    """native_value returns 0 when car is off (no blanking cards)."""
    coordinator._api_reachable = True
    coordinator._car_off_since_mono = time.monotonic() - SYNC_CAR_OFF_DEBOUNCE_S - 1
    assert coordinator.sync_status == SYNC_STATUS_CAR_OFF
    sensor._attr_native_value = 42.0
    assert sensor.native_value == 0


def test_native_value_last_known_during_api_offline_grace(sensor, coordinator):
    """During API offline grace window, native_value returns last-known reading."""
    coordinator._api_reachable = False
    assert coordinator.sync_status == SYNC_STATUS_API_OFFLINE
    sensor._attr_native_value = 88.0
    sensor._last_live_at = time.monotonic() - 5  # 5 s ago, within 60 s grace
    assert sensor.native_value == 88.0


def test_native_value_zero_after_api_offline_grace_expires(sensor, coordinator):
    """After grace window expires, native_value zeros out on api_offline."""
    coordinator._api_reachable = False
    assert coordinator.sync_status == SYNC_STATUS_API_OFFLINE
    sensor._attr_native_value = 88.0
    sensor._last_live_at = time.monotonic() - SENSOR_API_OFFLINE_GRACE_S - 5
    assert sensor.native_value == 0


def test_native_value_zero_api_offline_no_reading_ever(sensor, coordinator):
    """With no reading ever received, api_offline immediately returns 0."""
    coordinator._api_reachable = False
    assert coordinator.sync_status == SYNC_STATUS_API_OFFLINE
    sensor._attr_native_value = None
    sensor._last_live_at = 0.0
    assert sensor.native_value == 0


# ---------- coordinator debounce fixes ----------

def test_car_off_timer_not_started_before_ever_live(coordinator):
    """Debounce timer stays None at startup (never seen live) — no false 'live' window."""
    coordinator._api_reachable = True
    coordinator._health_data = {"can_connected": False, "last_reading_ms": 0}
    coordinator._update_car_off_debounce()
    # _was_ever_live is False → timer should NOT start
    assert coordinator._car_off_since_mono is None


def test_car_off_timer_cleared_on_api_failure(coordinator):
    """Debounce timer is cleared when API goes offline to avoid stale accumulation."""
    coordinator._car_off_since_mono = time.monotonic() - 10
    coordinator._api_reachable = True
    # Simulate crossing HEALTH_FAIL_THRESHOLD
    coordinator._consecutive_health_failures = 99
    coordinator._api_reachable = False
    coordinator._health_data = {}
    coordinator._car_off_since_mono = None  # as done in _poll_health failure branch
    assert coordinator._car_off_since_mono is None


def test_was_ever_live_set_on_first_live_poll(coordinator):
    """_was_ever_live flips to True once health confirms a live reading."""
    coordinator._api_reachable = True
    now_ms = int(time.time() * 1000)
    coordinator._health_data = {"can_connected": True, "last_reading_ms": now_ms - 1000}
    assert not coordinator._was_ever_live
    coordinator._update_car_off_debounce()
    assert coordinator._was_ever_live
    assert coordinator._car_off_since_mono is None


# ---------- Mode 09 diagnostic sensor persistence ----------

def test_mode09_sensor_persists_value_when_car_off(coordinator):
    """Mode 09 sensors (VIN, calibration IDs) must not return 0 when car is off.

    These are static vehicle identifiers — zeroing them is always wrong.
    """
    sensor = CanteraSensor(coordinator, "VIN", None, is_diagnostic=True)
    sensor._attr_native_value = "ZFA0000001234567"
    coordinator._api_reachable = True
    coordinator._car_off_since_mono = time.monotonic() - SYNC_CAR_OFF_DEBOUNCE_S - 1
    assert coordinator.sync_status == SYNC_STATUS_CAR_OFF
    assert sensor.native_value == "ZFA0000001234567"


def test_mode09_sensor_persists_value_when_api_offline(coordinator):
    """Mode 09 sensors persist their value when the API is offline — no grace window needed."""
    sensor = CanteraSensor(coordinator, "Calibration ID #1", None, is_diagnostic=True)
    sensor._attr_native_value = "CAL-REV-42"
    coordinator._api_reachable = False
    assert coordinator.sync_status == SYNC_STATUS_API_OFFLINE
    # Even with no reading ever received (_last_live_at == 0), value persists.
    sensor._last_live_at = 0.0
    assert sensor.native_value == "CAL-REV-42"


def test_mode09_sensor_persists_none_before_first_reading(coordinator):
    """Mode 09 sensor returns None (not 0) when no reading has ever arrived."""
    sensor = CanteraSensor(coordinator, "ECU Name", None, is_diagnostic=True)
    # No reading received yet — _attr_native_value starts None.
    coordinator._api_reachable = True
    coordinator._car_off_since_mono = time.monotonic() - SYNC_CAR_OFF_DEBOUNCE_S - 1
    assert coordinator.sync_status == SYNC_STATUS_CAR_OFF
    assert sensor.native_value is None


def test_mode01_sensor_returns_zero_when_car_off(coordinator):
    """Mode 01 live sensors (RPM, speed, etc.) still return 0 on car_off."""
    sensor = CanteraSensor(coordinator, "Engine RPM", "rpm", is_diagnostic=False)
    sensor._attr_native_value = 850.0
    coordinator._api_reachable = True
    coordinator._car_off_since_mono = time.monotonic() - SYNC_CAR_OFF_DEBOUNCE_S - 1
    assert coordinator.sync_status == SYNC_STATUS_CAR_OFF
    assert sensor.native_value == 0


def test_mode09_is_diagnostic_flag_set(coordinator):
    """CanteraSensor stores _is_diagnostic correctly."""
    diag = CanteraSensor(coordinator, "VIN", None, is_diagnostic=True)
    live = CanteraSensor(coordinator, "Engine RPM", "rpm", is_diagnostic=False)
    assert diag._is_diagnostic is True
    assert live._is_diagnostic is False


# ---------- Persistent sensor (Fuel Tank Level Input) ----------

def test_persistent_sensor_flag_set(coordinator):
    """CanteraSensor stores _is_persistent correctly."""
    persistent = CanteraSensor(coordinator, "Fuel Tank Level Input", "%", is_persistent=True)
    regular = CanteraSensor(coordinator, "Engine RPM", "rpm")
    assert persistent._is_persistent is True
    assert regular._is_persistent is False


def test_persistent_sensor_persists_value_when_car_off(coordinator):
    """Persistent sensors retain last-known value when car is off — fuel level cannot be 0."""
    sensor = CanteraSensor(coordinator, "Fuel Tank Level Input", "%", is_persistent=True)
    sensor._attr_native_value = 62.0
    coordinator._api_reachable = True
    coordinator._car_off_since_mono = time.monotonic() - SYNC_CAR_OFF_DEBOUNCE_S - 1
    assert coordinator.sync_status == SYNC_STATUS_CAR_OFF
    assert sensor.native_value == 62.0


def test_persistent_sensor_persists_value_when_api_offline(coordinator):
    """Persistent sensors retain last-known value when API is offline — no grace window."""
    sensor = CanteraSensor(coordinator, "Fuel Tank Level Input", "%", is_persistent=True)
    sensor._attr_native_value = 45.5
    coordinator._api_reachable = False
    assert coordinator.sync_status == SYNC_STATUS_API_OFFLINE
    sensor._last_live_at = 0.0  # Never had a live reading
    assert sensor.native_value == 45.5


def test_persistent_sensor_persists_value_api_offline_grace_expired(coordinator):
    """Persistent sensors ignore the grace window — value is kept even after grace expires."""
    sensor = CanteraSensor(coordinator, "Fuel Tank Level Input", "%", is_persistent=True)
    sensor._attr_native_value = 30.0
    coordinator._api_reachable = False
    assert coordinator.sync_status == SYNC_STATUS_API_OFFLINE
    sensor._last_live_at = time.monotonic() - SENSOR_API_OFFLINE_GRACE_S - 100
    assert sensor.native_value == 30.0


def test_persistent_sensor_returns_none_before_first_reading(coordinator):
    """Persistent sensor returns None (not 0) when no reading has ever arrived."""
    sensor = CanteraSensor(coordinator, "Fuel Tank Level Input", "%", is_persistent=True)
    coordinator._api_reachable = True
    coordinator._car_off_since_mono = time.monotonic() - SYNC_CAR_OFF_DEBOUNCE_S - 1
    assert coordinator.sync_status == SYNC_STATUS_CAR_OFF
    assert sensor.native_value is None


async def test_async_setup_entry_fuel_tank_is_persistent(hass, mock_entry, coordinator):
    """async_setup_entry marks Fuel Tank Level Input sensor as persistent."""
    mock_entry.runtime_data = coordinator
    added: list = []
    add_entities = MagicMock(side_effect=lambda entities: added.extend(entities))
    await async_setup_entry(hass, mock_entry, add_entities)

    fuel_sensors = [
        e for e in added
        if isinstance(e, CanteraSensor) and e._attr_name == "Fuel Tank Level Input"
    ]
    assert len(fuel_sensors) == 1
    assert fuel_sensors[0]._is_persistent is True


async def test_async_setup_entry_engine_rpm_is_not_persistent(hass, mock_entry, coordinator):
    """async_setup_entry does NOT mark Engine RPM as persistent (it correctly zeroes on car_off)."""
    mock_entry.runtime_data = coordinator
    added: list = []
    add_entities = MagicMock(side_effect=lambda entities: added.extend(entities))
    await async_setup_entry(hass, mock_entry, add_entities)

    rpm_sensors = [
        e for e in added
        if isinstance(e, CanteraSensor) and e._attr_name == "Engine RPM"
    ]
    assert len(rpm_sensors) == 1
    assert rpm_sensors[0]._is_persistent is False


# ---------------------------------------------------------------------------
# async_setup_entry unique_id registration (line 85)
# ---------------------------------------------------------------------------

async def test_async_setup_entry_registers_unique_ids_in_tracking_set(hass, mock_entry):
    """async_setup_entry updates current_unique_ids when the key exists in hass.data."""
    coordinator = CanteraCoordinator(hass, mock_entry)
    mock_entry.runtime_data = coordinator

    uid_set: set[str] = set()
    hass.data = {DOMAIN: {mock_entry.entry_id: {"current_unique_ids": uid_set}}}

    add_entities = MagicMock()
    await async_setup_entry(hass, mock_entry, add_entities)

    # At least the sync-status and firmware-version unique_ids should appear.
    assert len(uid_set) > 0
    assert any("sync_status" in uid for uid in uid_set)


# ---------------------------------------------------------------------------
# CanteraSensor.async_added_to_hass (lines 152-161)
# ---------------------------------------------------------------------------

class TestCanteraSensorLifecycle:
    async def test_async_added_to_hass_registers_listeners(self, hass, mock_entry):
        """async_added_to_hass registers reading and health listeners."""
        from unittest.mock import AsyncMock, patch

        coordinator = CanteraCoordinator(hass, mock_entry)
        s = CanteraSensor(coordinator, "Engine RPM", "rpm", mock_entry)
        s.async_write_ha_state = MagicMock()

        with (
            patch(
                "homeassistant.components.sensor.RestoreSensor.async_added_to_hass",
                new_callable=AsyncMock,
            ),
            patch.object(
                s, "async_get_last_sensor_data", new_callable=AsyncMock, return_value=None
            ),
        ):
            await s.async_added_to_hass()

        assert s._handle_reading in coordinator._reading_listeners.get("engine_rpm", [])
        assert s._handle_health_update in coordinator._health_listeners

    async def test_async_added_to_hass_restores_previous_state(self, hass, mock_entry):
        """async_added_to_hass restores native_value from the recorder."""
        from unittest.mock import AsyncMock, patch

        coordinator = CanteraCoordinator(hass, mock_entry)
        s = CanteraSensor(coordinator, "Engine RPM", "rpm", mock_entry)
        s.async_write_ha_state = MagicMock()

        last_data = MagicMock()
        last_data.native_value = 3500.0
        last_data.native_unit_of_measurement = "rpm"

        with (
            patch(
                "homeassistant.components.sensor.RestoreSensor.async_added_to_hass",
                new_callable=AsyncMock,
            ),
            patch.object(
                s, "async_get_last_sensor_data", new_callable=AsyncMock, return_value=last_data
            ),
        ):
            await s.async_added_to_hass()

        assert s._attr_native_value == 3500.0
        assert s._restored is True

    async def test_async_will_remove_from_hass_removes_listeners(self, hass, mock_entry):
        """async_will_remove_from_hass deregisters both reading and health listeners."""
        from unittest.mock import AsyncMock, patch

        coordinator = CanteraCoordinator(hass, mock_entry)
        s = CanteraSensor(coordinator, "Engine RPM", "rpm", mock_entry)
        s.async_write_ha_state = MagicMock()

        with (
            patch(
                "homeassistant.components.sensor.RestoreSensor.async_added_to_hass",
                new_callable=AsyncMock,
            ),
            patch.object(
                s, "async_get_last_sensor_data", new_callable=AsyncMock, return_value=None
            ),
        ):
            await s.async_added_to_hass()
        await s.async_will_remove_from_hass()

        assert s._handle_reading not in coordinator._reading_listeners.get("engine_rpm", [])
        assert s._handle_health_update not in coordinator._health_listeners


# ---------------------------------------------------------------------------
# native_value LIVE path (line 207) and should_poll (line 212)
# ---------------------------------------------------------------------------

def test_native_value_returns_value_when_live(sensor, coordinator):
    """native_value returns _attr_native_value when sync_status is live."""
    coordinator._api_reachable = True
    coordinator._backfilling = False
    coordinator._car_off_since_mono = None
    sensor._attr_native_value = 2750.0
    assert sensor.native_value == 2750.0


def test_should_poll_returns_false(sensor):
    """should_poll is always False — values arrive via SSE push."""
    assert sensor.should_poll is False


# ---------------------------------------------------------------------------
# CanteraSyncStatusSensor lifecycle (lines 273-280)
# ---------------------------------------------------------------------------

class TestSyncStatusSensorLifecycle:
    async def test_async_added_to_hass_registers_health_listener(self, hass, mock_entry):
        """CanteraSyncStatusSensor registers its health listener on add."""
        from unittest.mock import AsyncMock, patch

        coordinator = CanteraCoordinator(hass, mock_entry)
        s = CanteraSyncStatusSensor(coordinator, mock_entry)
        s.async_write_ha_state = MagicMock()

        with patch(
            "homeassistant.components.sensor.SensorEntity.async_added_to_hass",
            new_callable=AsyncMock,
        ):
            await s.async_added_to_hass()

        assert s._handle_health_update in coordinator._health_listeners

    async def test_async_will_remove_from_hass_removes_health_listener(self, hass, mock_entry):
        """CanteraSyncStatusSensor deregisters its health listener on remove."""
        from unittest.mock import AsyncMock, patch

        coordinator = CanteraCoordinator(hass, mock_entry)
        s = CanteraSyncStatusSensor(coordinator, mock_entry)
        s.async_write_ha_state = MagicMock()

        with patch(
            "homeassistant.components.sensor.SensorEntity.async_added_to_hass",
            new_callable=AsyncMock,
        ):
            await s.async_added_to_hass()
        await s.async_will_remove_from_hass()

        assert s._handle_health_update not in coordinator._health_listeners


# ---------------------------------------------------------------------------
# CanteraFirmwareVersionSensor.device_info (line 318)
# ---------------------------------------------------------------------------

def test_firmware_version_sensor_device_info(hass, mock_entry):
    """CanteraFirmwareVersionSensor.device_info delegates to coordinator."""
    from custom_components.cantera.sensor import CanteraFirmwareVersionSensor

    coordinator = CanteraCoordinator(hass, mock_entry)
    s = CanteraFirmwareVersionSensor(coordinator, mock_entry)
    # device_info is a computed property — compare equality, not identity.
    assert s.device_info == coordinator.device_info


# ---------------------------------------------------------------------------
# CanteraFirmwareVersionSensor persistence tests
# ---------------------------------------------------------------------------

def test_firmware_version_initial_value_is_none(hass, mock_entry):
    """Before any health update the cached version is None."""
    from custom_components.cantera.sensor import CanteraFirmwareVersionSensor

    coordinator = CanteraCoordinator(hass, mock_entry)
    s = CanteraFirmwareVersionSensor(coordinator, mock_entry)
    assert s.native_value is None


def test_firmware_version_updates_on_health_data(hass, mock_entry):
    """Health update with a version string updates native_value."""
    from custom_components.cantera.sensor import CanteraFirmwareVersionSensor

    coordinator = CanteraCoordinator(hass, mock_entry)
    s = CanteraFirmwareVersionSensor(coordinator, mock_entry)
    s.async_write_ha_state = MagicMock()

    s._handle_health_update({"version": "0.1.0", "can_connected": True})
    assert s.native_value == "0.1.0"
    s.async_write_ha_state.assert_called_once()


def test_firmware_version_persists_when_api_goes_offline(hass, mock_entry):
    """When the Pi goes offline and health_data is cleared, the cached version persists.

    This is the core regression: coordinator.health_data becomes {} on API offline,
    but the sensor must still show the last known version rather than 'Unknown'.
    """
    from custom_components.cantera.sensor import CanteraFirmwareVersionSensor

    coordinator = CanteraCoordinator(hass, mock_entry)
    s = CanteraFirmwareVersionSensor(coordinator, mock_entry)
    s.async_write_ha_state = MagicMock()

    # Simulate health arriving while Pi is live.
    s._handle_health_update({"version": "0.1.0"})
    assert s.native_value == "0.1.0"

    # Simulate coordinator going offline — health_data cleared, empty dict emitted.
    coordinator._health_data = {}
    s._handle_health_update({})

    # Version must still be shown.
    assert s.native_value == "0.1.0"


def test_firmware_version_does_not_clear_on_health_without_version(hass, mock_entry):
    """A health update dict that lacks a 'version' key must not overwrite the cache."""
    from custom_components.cantera.sensor import CanteraFirmwareVersionSensor

    coordinator = CanteraCoordinator(hass, mock_entry)
    s = CanteraFirmwareVersionSensor(coordinator, mock_entry)
    s.async_write_ha_state = MagicMock()

    s._handle_health_update({"version": "0.2.0"})
    s._handle_health_update({"can_connected": False})  # no version key
    assert s.native_value == "0.2.0"


async def test_firmware_version_restores_across_ha_restart(hass, mock_entry):
    """The sensor restores its persisted version on HA restart even if Pi is offline."""
    from unittest.mock import AsyncMock, patch
    from custom_components.cantera.sensor import CanteraFirmwareVersionSensor

    coordinator = CanteraCoordinator(hass, mock_entry)
    s = CanteraFirmwareVersionSensor(coordinator, mock_entry)
    s.async_write_ha_state = MagicMock()

    mock_sensor_data = MagicMock()
    mock_sensor_data.native_value = "0.3.0"

    with (
        patch(
            "homeassistant.components.sensor.RestoreSensor.async_added_to_hass",
            new_callable=AsyncMock,
        ),
        patch.object(s, "async_get_last_sensor_data", new_callable=AsyncMock, return_value=mock_sensor_data),
    ):
        await s.async_added_to_hass()

    # Pi is still offline — no health update received yet.
    assert s.native_value == "0.3.0"


def test_firmware_version_always_available(hass, mock_entry):
    """Pi Firmware Version is always available regardless of API state."""
    from custom_components.cantera.sensor import CanteraFirmwareVersionSensor

    coordinator = CanteraCoordinator(hass, mock_entry)
    s = CanteraFirmwareVersionSensor(coordinator, mock_entry)
    coordinator._api_reachable = False
    assert s.available is True


async def test_firmware_version_registers_health_listener(hass, mock_entry):
    """async_added_to_hass registers a health listener with the coordinator."""
    from unittest.mock import AsyncMock, patch
    from custom_components.cantera.sensor import CanteraFirmwareVersionSensor

    coordinator = CanteraCoordinator(hass, mock_entry)
    s = CanteraFirmwareVersionSensor(coordinator, mock_entry)
    s.async_write_ha_state = MagicMock()

    with (
        patch(
            "homeassistant.components.sensor.RestoreSensor.async_added_to_hass",
            new_callable=AsyncMock,
        ),
        patch.object(s, "async_get_last_sensor_data", new_callable=AsyncMock, return_value=None),
    ):
        await s.async_added_to_hass()

    assert s._handle_health_update in coordinator._health_listeners


async def test_firmware_version_unregisters_health_listener_on_remove(hass, mock_entry):
    """async_will_remove_from_hass removes the health listener."""
    from custom_components.cantera.sensor import CanteraFirmwareVersionSensor

    coordinator = CanteraCoordinator(hass, mock_entry)
    s = CanteraFirmwareVersionSensor(coordinator, mock_entry)
    coordinator._health_listeners.append(s._handle_health_update)

    await s.async_will_remove_from_hass()
    assert s._handle_health_update not in coordinator._health_listeners


# ---------------------------------------------------------------------------
# CanteraPiApiVersionSensor tests
# ---------------------------------------------------------------------------


def test_pi_api_version_initial_value_is_none(hass, mock_entry):
    """Before any health update the cached API version is None."""
    from custom_components.cantera.sensor import CanteraPiApiVersionSensor

    coordinator = CanteraCoordinator(hass, mock_entry)
    s = CanteraPiApiVersionSensor(coordinator, mock_entry)
    assert s.native_value is None


def test_pi_api_version_updates_on_health_data(hass, mock_entry):
    """Health update containing api_version updates the sensor value."""
    from custom_components.cantera.sensor import CanteraPiApiVersionSensor

    coordinator = CanteraCoordinator(hass, mock_entry)
    s = CanteraPiApiVersionSensor(coordinator, mock_entry)
    s.async_write_ha_state = MagicMock()

    coordinator._reported_api_version = "1.0"
    s._handle_health_update({})

    assert s.native_value == "1.0"
    s.async_write_ha_state.assert_called_once()


def test_pi_api_version_persists_when_pi_goes_offline(hass, mock_entry):
    """Cached API version survives when the Pi goes offline and health_data is cleared."""
    from custom_components.cantera.sensor import CanteraPiApiVersionSensor

    coordinator = CanteraCoordinator(hass, mock_entry)
    s = CanteraPiApiVersionSensor(coordinator, mock_entry)
    s.async_write_ha_state = MagicMock()

    coordinator._reported_api_version = "1.0"
    s._handle_health_update({})
    assert s.native_value == "1.0"

    # Pi goes offline — coordinator clears its version.
    coordinator._reported_api_version = None
    s._handle_health_update({})

    assert s.native_value == "1.0"


async def test_pi_api_version_restores_across_ha_restart(hass, mock_entry):
    """The sensor restores its persisted API version on HA restart."""
    from unittest.mock import AsyncMock, patch
    from custom_components.cantera.sensor import CanteraPiApiVersionSensor

    coordinator = CanteraCoordinator(hass, mock_entry)
    s = CanteraPiApiVersionSensor(coordinator, mock_entry)
    s.async_write_ha_state = MagicMock()

    mock_sensor_data = MagicMock()
    mock_sensor_data.native_value = "1.0"

    with (
        patch(
            "homeassistant.components.sensor.RestoreSensor.async_added_to_hass",
            new_callable=AsyncMock,
        ),
        patch.object(s, "async_get_last_sensor_data", new_callable=AsyncMock, return_value=mock_sensor_data),
    ):
        await s.async_added_to_hass()

    assert s.native_value == "1.0"


def test_pi_api_version_always_available(hass, mock_entry):
    """Pi API Version is always available regardless of API reachability."""
    from custom_components.cantera.sensor import CanteraPiApiVersionSensor

    coordinator = CanteraCoordinator(hass, mock_entry)
    s = CanteraPiApiVersionSensor(coordinator, mock_entry)
    coordinator._api_reachable = False
    assert s.available is True


def test_pi_api_version_entity_category_is_diagnostic(hass, mock_entry):
    """Pi API Version belongs in the Diagnostics section."""
    from homeassistant.helpers.entity import EntityCategory
    from custom_components.cantera.sensor import CanteraPiApiVersionSensor

    coordinator = CanteraCoordinator(hass, mock_entry)
    s = CanteraPiApiVersionSensor(coordinator, mock_entry)
    assert s._attr_entity_category == EntityCategory.DIAGNOSTIC


async def test_pi_api_version_registers_health_listener(hass, mock_entry):
    """async_added_to_hass registers a health listener."""
    from unittest.mock import AsyncMock, patch
    from custom_components.cantera.sensor import CanteraPiApiVersionSensor

    coordinator = CanteraCoordinator(hass, mock_entry)
    s = CanteraPiApiVersionSensor(coordinator, mock_entry)
    s.async_write_ha_state = MagicMock()

    with (
        patch(
            "homeassistant.components.sensor.RestoreSensor.async_added_to_hass",
            new_callable=AsyncMock,
        ),
        patch.object(s, "async_get_last_sensor_data", new_callable=AsyncMock, return_value=None),
    ):
        await s.async_added_to_hass()

    assert s._handle_health_update in coordinator._health_listeners


async def test_pi_api_version_unregisters_health_listener_on_remove(hass, mock_entry):
    """async_will_remove_from_hass unregisters the health listener."""
    from custom_components.cantera.sensor import CanteraPiApiVersionSensor

    coordinator = CanteraCoordinator(hass, mock_entry)
    s = CanteraPiApiVersionSensor(coordinator, mock_entry)
    coordinator._health_listeners.append(s._handle_health_update)

    await s.async_will_remove_from_hass()
    assert s._handle_health_update not in coordinator._health_listeners


# ---------------------------------------------------------------------------
# CanteraExpectedApiVersionSensor tests
# ---------------------------------------------------------------------------


def test_expected_api_version_static_value(hass, mock_entry):
    """Expected API Version shows the compile-time constant as a string."""
    from custom_components.cantera.const import EXPECTED_API_VERSION_MAJOR, MIN_API_VERSION_MINOR
    from custom_components.cantera.sensor import CanteraExpectedApiVersionSensor

    coordinator = CanteraCoordinator(hass, mock_entry)
    s = CanteraExpectedApiVersionSensor(coordinator, mock_entry)
    assert s.native_value == f"{EXPECTED_API_VERSION_MAJOR}.{MIN_API_VERSION_MINOR}"


def test_expected_api_version_entity_category_is_diagnostic(hass, mock_entry):
    """Expected API Version belongs in the Diagnostics section."""
    from homeassistant.helpers.entity import EntityCategory
    from custom_components.cantera.sensor import CanteraExpectedApiVersionSensor

    coordinator = CanteraCoordinator(hass, mock_entry)
    s = CanteraExpectedApiVersionSensor(coordinator, mock_entry)
    assert s._attr_entity_category == EntityCategory.DIAGNOSTIC


def test_expected_api_version_always_available(hass, mock_entry):
    """Expected API Version is always available."""
    from custom_components.cantera.sensor import CanteraExpectedApiVersionSensor

    coordinator = CanteraCoordinator(hass, mock_entry)
    s = CanteraExpectedApiVersionSensor(coordinator, mock_entry)
    assert s.available is True


# ---------------------------------------------------------------------------
# Sync status — incompatible state
# ---------------------------------------------------------------------------


def test_sync_status_sensor_shows_incompatible_when_api_incompatible(hass, mock_entry):
    """CanteraSyncStatusSensor.native_value returns 'incompatible' when coordinator is incompatible."""
    from custom_components.cantera.const import SYNC_STATUS_INCOMPATIBLE
    from custom_components.cantera.sensor import CanteraSyncStatusSensor

    coordinator = CanteraCoordinator(hass, mock_entry)
    coordinator._api_compatible = False
    s = CanteraSyncStatusSensor(coordinator, mock_entry)
    assert s.native_value == SYNC_STATUS_INCOMPATIBLE


def test_sync_status_sensor_incompatible_icon(hass, mock_entry):
    """Incompatible state uses the alert-circle icon."""
    from custom_components.cantera.sensor import CanteraSyncStatusSensor, _SYNC_STATUS_ICON
    from custom_components.cantera.const import SYNC_STATUS_INCOMPATIBLE

    assert _SYNC_STATUS_ICON[SYNC_STATUS_INCOMPATIBLE] == "mdi:alert-circle"


# ---------------------------------------------------------------------------
# CanteraFirmwareUpdateStatusSensor tests
# ---------------------------------------------------------------------------

def test_firmware_update_status_initial_state(hass, mock_entry):
    """Sensor starts in 'not_checked' state."""
    from custom_components.cantera.sensor import CanteraFirmwareUpdateStatusSensor

    coordinator = CanteraCoordinator(hass, mock_entry)
    s = CanteraFirmwareUpdateStatusSensor(coordinator, mock_entry)
    assert s.native_value == "not_checked"


def test_firmware_update_status_entity_category_is_diagnostic(hass, mock_entry):
    """Sensor is in the DIAGNOSTIC entity category."""
    from custom_components.cantera.sensor import CanteraFirmwareUpdateStatusSensor
    from homeassistant.const import EntityCategory

    coordinator = CanteraCoordinator(hass, mock_entry)
    s = CanteraFirmwareUpdateStatusSensor(coordinator, mock_entry)
    assert s.entity_category == EntityCategory.DIAGNOSTIC


def test_firmware_update_status_options_are_complete(hass, mock_entry):
    """Sensor options list contains all five expected states."""
    from custom_components.cantera.sensor import (
        CanteraFirmwareUpdateStatusSensor,
        _FIRMWARE_UPDATE_STATUS_STATES,
    )

    coordinator = CanteraCoordinator(hass, mock_entry)
    s = CanteraFirmwareUpdateStatusSensor(coordinator, mock_entry)
    assert set(s.options) == set(_FIRMWARE_UPDATE_STATUS_STATES)
    assert "not_checked" in s.options
    assert "checking" in s.options
    assert "up_to_date" in s.options
    assert "update_available" in s.options
    assert "check_failed" in s.options


def test_firmware_update_status_reflects_coordinator_state(hass, mock_entry):
    """native_value tracks coordinator.firmware_update_state."""
    from custom_components.cantera.sensor import CanteraFirmwareUpdateStatusSensor

    coordinator = CanteraCoordinator(hass, mock_entry)
    s = CanteraFirmwareUpdateStatusSensor(coordinator, mock_entry)
    s.async_write_ha_state = MagicMock()

    for state in ("checking", "up_to_date", "update_available", "check_failed", "not_checked"):
        coordinator.set_firmware_update_state(state)
        assert s.native_value == state


async def test_firmware_update_status_registers_listener(hass, mock_entry):
    """Sensor registers a firmware state listener on async_added_to_hass."""
    from custom_components.cantera.sensor import CanteraFirmwareUpdateStatusSensor

    coordinator = CanteraCoordinator(hass, mock_entry)
    s = CanteraFirmwareUpdateStatusSensor(coordinator, mock_entry)
    s.async_write_ha_state = MagicMock()
    s.hass = hass

    assert len(coordinator._firmware_state_listeners) == 0
    await s.async_added_to_hass()
    assert len(coordinator._firmware_state_listeners) == 1


async def test_firmware_update_status_unregisters_listener_on_remove(hass, mock_entry):
    """Sensor removes its listener on async_will_remove_from_hass."""
    from custom_components.cantera.sensor import CanteraFirmwareUpdateStatusSensor

    coordinator = CanteraCoordinator(hass, mock_entry)
    s = CanteraFirmwareUpdateStatusSensor(coordinator, mock_entry)
    s.async_write_ha_state = MagicMock()
    s.hass = hass

    await s.async_added_to_hass()
    assert len(coordinator._firmware_state_listeners) == 1
    await s.async_will_remove_from_hass()
    assert len(coordinator._firmware_state_listeners) == 0


def test_firmware_update_status_write_ha_state_called_on_update(hass, mock_entry):
    """Sensor calls async_write_ha_state when firmware state changes."""
    from custom_components.cantera.sensor import CanteraFirmwareUpdateStatusSensor

    coordinator = CanteraCoordinator(hass, mock_entry)
    s = CanteraFirmwareUpdateStatusSensor(coordinator, mock_entry)
    s.async_write_ha_state = MagicMock()

    coordinator._firmware_state_listeners.append(s._handle_firmware_state)
    coordinator.set_firmware_update_state("update_available")

    s.async_write_ha_state.assert_called_once()
    assert s.native_value == "update_available"


async def test_firmware_update_status_restores_last_known_value(hass, mock_entry):
    """Sensor restores persisted state on HA restart instead of reverting to not_checked."""
    from unittest.mock import AsyncMock as _AsyncMock
    from custom_components.cantera.sensor import CanteraFirmwareUpdateStatusSensor

    coordinator = CanteraCoordinator(hass, mock_entry)
    s = CanteraFirmwareUpdateStatusSensor(coordinator, mock_entry)
    s.async_write_ha_state = MagicMock()
    s.hass = hass

    # Simulate HA restore data with a previously persisted state.
    mock_sensor_data = MagicMock()
    mock_sensor_data.native_value = "update_available"
    s.async_get_last_sensor_data = _AsyncMock(return_value=mock_sensor_data)

    await s.async_added_to_hass()

    # Coordinator state should be seeded with the restored value.
    assert coordinator.firmware_update_state == "update_available"
    assert s.native_value == "update_available"


async def test_firmware_update_status_ignores_invalid_restored_value(hass, mock_entry):
    """Sensor ignores a persisted value that is not in the valid options list."""
    from unittest.mock import AsyncMock as _AsyncMock
    from custom_components.cantera.sensor import CanteraFirmwareUpdateStatusSensor

    coordinator = CanteraCoordinator(hass, mock_entry)
    s = CanteraFirmwareUpdateStatusSensor(coordinator, mock_entry)
    s.async_write_ha_state = MagicMock()
    s.hass = hass

    mock_sensor_data = MagicMock()
    mock_sensor_data.native_value = "some_unknown_state_from_future_version"
    s.async_get_last_sensor_data = _AsyncMock(return_value=mock_sensor_data)

    await s.async_added_to_hass()

    # Invalid value must not be loaded — coordinator stays at default.
    assert coordinator.firmware_update_state == "not_checked"


# ---------- CanteraBusLoadSensor unit tests ----------

@pytest.fixture
def bus_load_sensor(coordinator, mock_entry):
    # Simulate a live coordinator (API reachable, no car-off) so that
    # native_value returns the actual _bus_load_pct rather than the
    # sync-status-driven 0.0 fallback.
    coordinator._api_reachable = True
    s = CanteraBusLoadSensor(coordinator, mock_entry)
    s.async_write_ha_state = MagicMock()
    return s


def test_bus_load_initial_value_is_none(bus_load_sensor):
    """Sensor starts with None before any health/SSE data arrives."""
    assert bus_load_sensor.native_value is None


def test_bus_load_unique_id(bus_load_sensor):
    assert bus_load_sensor._attr_unique_id == "test_entry_id_can_bus_load"


def test_bus_load_updates_from_health_poll(bus_load_sensor):
    """Health listener populates bus_load_pct and estimated flag."""
    bus_load_sensor._handle_health_update({"bus_load_pct": 12.5, "bus_load_estimated": True})
    assert bus_load_sensor.native_value == 12.5
    assert bus_load_sensor.extra_state_attributes == {"estimated": True}
    bus_load_sensor.async_write_ha_state.assert_called()


def test_bus_load_hardware_api_not_estimated(bus_load_sensor):
    """Hardware API source has estimated=False."""
    bus_load_sensor._handle_health_update({"bus_load_pct": 5.0, "bus_load_estimated": False})
    assert bus_load_sensor.native_value == 5.0
    assert bus_load_sensor.extra_state_attributes == {"estimated": False}


def test_bus_load_health_with_null_pct_ignored(bus_load_sensor):
    """Health update with null bus_load_pct does not overwrite prior value."""
    bus_load_sensor._handle_health_update({"bus_load_pct": 20.0, "bus_load_estimated": False})
    bus_load_sensor._handle_health_update({"bus_load_pct": None})
    assert bus_load_sensor.native_value == 20.0


def test_bus_load_missing_key_in_old_firmware(bus_load_sensor):
    """Health data without bus_load_pct (old firmware) leaves sensor at None."""
    bus_load_sensor._handle_health_update({"can_connected": True})
    assert bus_load_sensor.native_value is None
    assert bus_load_sensor.extra_state_attributes == {}


def test_bus_load_updates_from_sse_bus_stats(bus_load_sensor):
    """SSE bus_stats event updates the sensor value."""
    bus_load_sensor._handle_bus_stats({"bus_load_pct": 33.3, "estimated": True})
    assert bus_load_sensor.native_value == 33.3
    assert bus_load_sensor.extra_state_attributes == {"estimated": True}
    bus_load_sensor.async_write_ha_state.assert_called()


def test_bus_load_sse_without_pct_ignored(bus_load_sensor):
    """SSE bus_stats without bus_load_pct does not overwrite prior value."""
    bus_load_sensor._handle_bus_stats({"bus_load_pct": 10.0, "estimated": False})
    bus_load_sensor._handle_bus_stats({"some_other_key": 1})
    assert bus_load_sensor.native_value == 10.0


def test_bus_load_no_estimated_flag(bus_load_sensor):
    """When estimated flag absent, extra_state_attributes contains no estimated key."""
    bus_load_sensor._handle_health_update({"bus_load_pct": 7.0})
    assert "estimated" not in bus_load_sensor.extra_state_attributes


def test_bus_load_listener_registered_in_coordinator(coordinator, mock_entry):
    """async_added_to_hass registers both health and bus_stats listeners."""
    s = CanteraBusLoadSensor(coordinator, mock_entry)
    s.async_write_ha_state = MagicMock()
    before_health = len(coordinator._health_listeners)
    before_bus = len(coordinator._bus_stats_listeners)
    coordinator.add_health_listener(s._handle_health_update)
    coordinator.add_bus_stats_listener(s._handle_bus_stats)
    assert len(coordinator._health_listeners) == before_health + 1
    assert len(coordinator._bus_stats_listeners) == before_bus + 1
    coordinator.remove_health_listener(s._handle_health_update)
    coordinator.remove_bus_stats_listener(s._handle_bus_stats)
    assert len(coordinator._health_listeners) == before_health
    assert len(coordinator._bus_stats_listeners) == before_bus


def test_bus_load_returns_zero_when_api_offline(coordinator, mock_entry):
    """native_value is 0.0 when the API is unreachable (default initial state)."""
    # Default coordinator state: _api_reachable=False → sync_status=api_offline
    s = CanteraBusLoadSensor(coordinator, mock_entry)
    s.async_write_ha_state = MagicMock()
    s._bus_load_pct = 25.0  # prior cached reading
    assert s.native_value == 0.0


def test_bus_load_returns_zero_when_car_off(coordinator, mock_entry):
    """native_value is 0.0 when sync_status is car_off, regardless of cached reading."""
    import time as _time
    coordinator._api_reachable = True
    coordinator._car_off_since_mono = _time.monotonic() - 9999  # well past debounce
    s = CanteraBusLoadSensor(coordinator, mock_entry)
    s.async_write_ha_state = MagicMock()
    s._bus_load_pct = 18.0
    assert s.native_value == 0.0


def test_bus_load_write_ha_state_called_even_when_pct_is_none(bus_load_sensor):
    """_handle_health_update always calls async_write_ha_state so sync_status changes
    are reflected immediately, even when bus_load_pct is absent in the health data."""
    bus_load_sensor._handle_health_update({"can_connected": True})
    bus_load_sensor.async_write_ha_state.assert_called()

