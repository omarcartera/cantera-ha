"""Tests for CANtera config flow."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.cantera.config_flow import (
    CanteraConfigFlow,
    ConnectionResult,
    _get_device_info,
)
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


# ---------------------------------------------------------------------------
# Direct tests for _get_device_info (covers lines 70-80)
# ---------------------------------------------------------------------------

def _make_session_mock(status: int, json_return=None):
    """Build a minimal aiohttp session mock."""
    mock_resp = AsyncMock()
    mock_resp.status = status
    if json_return is not None:
        mock_resp.json = AsyncMock(return_value=json_return)
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=mock_resp)
    return mock_session


async def test_get_device_info_returns_json_on_200(hass):
    """_get_device_info returns parsed JSON when status is 200."""
    mock_session = _make_session_mock(200, json_return={"id": "device-xyz", "name": "CANtera"})
    with patch("custom_components.cantera.config_flow.async_get_clientsession", return_value=mock_session):
        result = await _get_device_info("192.168.1.100", 8088, hass)
    assert result == {"id": "device-xyz", "name": "CANtera"}


async def test_get_device_info_non_200_returns_none(hass):
    """_get_device_info returns None when the server returns a non-200 status."""
    mock_session = _make_session_mock(404)
    with patch("custom_components.cantera.config_flow.async_get_clientsession", return_value=mock_session):
        result = await _get_device_info("192.168.1.100", 8088, hass)
    assert result is None


async def test_get_device_info_exception_returns_none(hass):
    """_get_device_info swallows exceptions and returns None."""
    mock_session = MagicMock()
    mock_session.get = MagicMock(side_effect=Exception("network error"))
    with patch("custom_components.cantera.config_flow.async_get_clientsession", return_value=mock_session):
        result = await _get_device_info("192.168.1.100", 8088, hass)
    assert result is None


# ---------------------------------------------------------------------------
# async_step_user: unique_id selection
# ---------------------------------------------------------------------------

@patch(
    "custom_components.cantera.config_flow._test_connection",
    new_callable=AsyncMock,
    return_value=ConnectionResult.OK,
)
@patch(
    "custom_components.cantera.config_flow._get_device_info",
    new_callable=AsyncMock,
    return_value={"id": "device-abc"},
)
async def test_device_id_used_as_unique_id(mock_device, mock_conn, flow):
    """When _get_device_info returns a dict with 'id', that ID is the unique_id."""
    flow.async_set_unique_id = AsyncMock()
    flow._abort_if_unique_id_configured = MagicMock()
    await flow.async_step_user(
        user_input={CONF_HOST: "192.168.1.100", CONF_PORT: DEFAULT_PORT}
    )
    flow.async_set_unique_id.assert_awaited_once_with("device-abc")


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
async def test_host_port_used_as_unique_id_when_no_device_info(mock_device, mock_conn, flow):
    """When _get_device_info returns None, unique_id falls back to 'host:port'."""
    flow.async_set_unique_id = AsyncMock()
    flow._abort_if_unique_id_configured = MagicMock()
    await flow.async_step_user(
        user_input={CONF_HOST: "192.168.1.100", CONF_PORT: DEFAULT_PORT}
    )
    flow.async_set_unique_id.assert_awaited_once_with(f"192.168.1.100:{DEFAULT_PORT}")


# ---------------------------------------------------------------------------
# already_configured abort path
# ---------------------------------------------------------------------------

@patch(
    "custom_components.cantera.config_flow._test_connection",
    new_callable=AsyncMock,
    return_value=ConnectionResult.OK,
)
@patch(
    "custom_components.cantera.config_flow._get_device_info",
    new_callable=AsyncMock,
    return_value={"id": "device-abc"},
)
async def test_already_configured_aborts(mock_device, mock_conn, flow):
    """_abort_if_unique_id_configured raises AbortFlow when already configured."""
    from homeassistant.data_entry_flow import AbortFlow

    flow.async_set_unique_id = AsyncMock()
    flow._abort_if_unique_id_configured = MagicMock(side_effect=AbortFlow("already_configured"))
    with pytest.raises(AbortFlow, match="already_configured"):
        await flow.async_step_user(
            user_input={CONF_HOST: "192.168.1.100", CONF_PORT: DEFAULT_PORT}
        )
