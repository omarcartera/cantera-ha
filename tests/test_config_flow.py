"""Tests for CANtera config flow."""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from custom_components.cantera.config_flow import CanteraConfigFlow
from custom_components.cantera.const import CONF_HOST, CONF_PORT, DEFAULT_PORT


@pytest.fixture
def flow(hass):
    """Create a config flow instance with mocked hass."""
    f = CanteraConfigFlow()
    f.hass = hass
    return f


async def test_form_shows(flow):
    """Show user form when no input provided."""
    result = await flow.async_step_user(user_input=None)
    assert result["type"] == "form"
    assert result["step_id"] == "user"


@patch("custom_components.cantera.config_flow._test_connection", return_value=False)
async def test_connection_error(mock_conn, flow):
    """Connection failure shows error."""
    result = await flow.async_step_user(
        user_input={CONF_HOST: "192.168.1.100", CONF_PORT: DEFAULT_PORT}
    )
    assert result["type"] == "form"
    assert result["errors"] == {"base": "cannot_connect"}


@patch("custom_components.cantera.config_flow._test_connection", return_value=True)
async def test_successful_setup(mock_conn, flow):
    """Successful connection creates config entry."""
    flow.async_set_unique_id = AsyncMock()
    flow._abort_if_unique_id_configured = MagicMock()
    result = await flow.async_step_user(
        user_input={CONF_HOST: "192.168.1.100", CONF_PORT: DEFAULT_PORT}
    )
    assert result["type"] == "create_entry"
    assert result["title"] == "CANtera (192.168.1.100)"
    assert result["data"][CONF_HOST] == "192.168.1.100"
