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

    expected_count = 1 + len(MODE01_PIDS) + len(MODE09_PIDS)  # sync + mode01 + mode09
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


def test_sensor_unavailable_when_api_offline(sensor, coordinator):
    """Sensor reports unavailable when sync_status is api_offline."""
    coordinator._first_health_received = True
    coordinator._api_reachable = False
    # No health data → api_offline
    assert coordinator.sync_status == SYNC_STATUS_API_OFFLINE
    assert sensor.available is False


def test_sensor_unavailable_when_car_off(sensor, coordinator):
    """Sensor reports unavailable when car is off (no recent reading, debounce elapsed)."""
    coordinator._first_health_received = True
    coordinator._api_reachable = True
    coordinator._health_data = {"can_connected": False, "last_reading_ms": 0}
    coordinator._car_off_since_mono = time.monotonic() - SYNC_CAR_OFF_DEBOUNCE_S - 1
    assert coordinator.sync_status == SYNC_STATUS_CAR_OFF
    assert sensor.available is False


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


def test_sensor_unavailable_during_syncing(sensor, coordinator):
    """Sensor is unavailable while backfill is in progress (not yet live)."""
    import time as _time
    coordinator._first_health_received = True
    coordinator._api_reachable = True
    coordinator._backfilling = True
    coordinator._health_data = {
        "can_connected": True,
        "last_reading_ms": int(_time.time() * 1000) - 2000,
    }
    # syncing ≠ live
    assert coordinator.sync_status == SYNC_STATUS_SYNCING
    assert sensor.available is False


def test_sensor_health_update_triggers_write(sensor):
    """_handle_health_update calls async_write_ha_state when availability changes."""
    sensor._handle_health_update({"can_connected": True})
    # First call: cache was None, now True (startup grace) → write triggered
    sensor.async_write_ha_state.assert_called_once()


def test_sensor_health_update_no_write_when_unchanged(sensor, coordinator):
    """_handle_health_update skips write when availability has not changed."""
    coordinator._first_health_received = True  # Exit grace period
    coordinator._api_reachable = False  # api_offline → unavailable
    # Prime the cache
    sensor._handle_health_update({})
    sensor.async_write_ha_state.reset_mock()
    # Call again with same availability → no extra write
    sensor._handle_health_update({})
    sensor.async_write_ha_state.assert_not_called()

