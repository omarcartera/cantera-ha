"""Tests for CANtera config flow."""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from custom_components.cantera.config_flow import CanteraConfigFlow, ConnectionResult
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


@patch(
    "custom_components.cantera.config_flow._test_connection",
    new_callable=AsyncMock,
    return_value=ConnectionResult.CANNOT_CONNECT,
)
async def test_connection_error(mock_conn, flow):
    """Connection failure shows cannot_connect error."""
    result = await flow.async_step_user(
        user_input={CONF_HOST: "192.168.1.100", CONF_PORT: DEFAULT_PORT}
    )
    assert result["type"] == "form"
    assert result["errors"]["base"] == "cannot_connect"


@patch(
    "custom_components.cantera.config_flow._test_connection",
    new_callable=AsyncMock,
    return_value=ConnectionResult.HOST_UNREACHABLE,
)
async def test_host_unreachable_error(mock_conn, flow):
    """Unreachable host shows host_unreachable error."""
    result = await flow.async_step_user(
        user_input={CONF_HOST: "100.64.0.1", CONF_PORT: DEFAULT_PORT}
    )
    assert result["type"] == "form"
    assert result["errors"]["base"] == "host_unreachable"


@patch(
    "custom_components.cantera.config_flow._test_connection",
    new_callable=AsyncMock,
    return_value=ConnectionResult.CONNECTION_REFUSED,
)
async def test_connection_refused_error(mock_conn, flow):
    """Connection refused shows connection_refused error."""
    result = await flow.async_step_user(
        user_input={CONF_HOST: "192.168.1.100", CONF_PORT: DEFAULT_PORT}
    )
    assert result["type"] == "form"
    assert result["errors"]["base"] == "connection_refused"


@patch(
    "custom_components.cantera.config_flow._test_connection",
    new_callable=AsyncMock,
    return_value=ConnectionResult.OK,
)
@patch(
    "custom_components.cantera.config_flow._get_device_info",
    new_callable=AsyncMock,
    return_value=None,
)
async def test_successful_setup(mock_device, mock_conn, flow):
    """Successful connection creates config entry."""
    flow.async_set_unique_id = AsyncMock()
    flow._abort_if_unique_id_configured = MagicMock()
    result = await flow.async_step_user(
        user_input={CONF_HOST: "192.168.1.100", CONF_PORT: DEFAULT_PORT}
    )
    assert result["type"] == "create_entry"
    assert result["title"] == "CANtera (192.168.1.100)"
    assert result["data"][CONF_HOST] == "192.168.1.100"


@patch(
    "custom_components.cantera.config_flow._test_connection",
    new_callable=AsyncMock,
    return_value=ConnectionResult.OK,
)
@patch(
    "custom_components.cantera.config_flow._get_device_info",
    new_callable=AsyncMock,
    return_value=None,
)
async def test_host_whitespace_stripped(mock_device, mock_conn, flow):
    """Whitespace around host is stripped before storing."""
    flow.async_set_unique_id = AsyncMock()
    flow._abort_if_unique_id_configured = MagicMock()
    result = await flow.async_step_user(
        user_input={CONF_HOST: "  192.168.1.100  ", CONF_PORT: DEFAULT_PORT}
    )
    assert result["type"] == "create_entry"
    assert result["data"][CONF_HOST] == "192.168.1.100"
