"""Tests verifying binary_sensor platform is not registered in CANtera integration."""
from custom_components.cantera import PLATFORMS


def test_binary_sensor_platform_not_registered():
    """The binary_sensor platform must NOT be in PLATFORMS after removal."""
    assert "binary_sensor" not in PLATFORMS


def test_only_sensor_platform_registered():
    """Only the sensor platform should be registered."""
    assert PLATFORMS == ["sensor"]
