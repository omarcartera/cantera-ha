"""Tests for the config flow."""
import pytest
from unittest.mock import AsyncMock, patch
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType

from custom_components.cantera.const import DOMAIN, DEFAULT_PORT, CONF_HOST, CONF_PORT


@pytest.fixture
def config_entry_data():
    return {CONF_HOST: "192.168.1.100", CONF_PORT: DEFAULT_PORT}


async def test_form_shows(hass):
    """Test that the config form is shown."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {}


async def test_connection_error(hass):
    """Test error shown when connection fails."""
    with patch(
        "custom_components.cantera.config_flow._test_connection",
        return_value=False,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_HOST: "192.168.1.100", CONF_PORT: DEFAULT_PORT},
        )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_successful_setup(hass):
    """Test successful config entry creation."""
    with patch(
        "custom_components.cantera.config_flow._test_connection",
        return_value=True,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_HOST: "192.168.1.100", CONF_PORT: DEFAULT_PORT},
        )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "CANtera (192.168.1.100)"
    assert result["data"][CONF_HOST] == "192.168.1.100"
    assert result["data"][CONF_PORT] == DEFAULT_PORT
