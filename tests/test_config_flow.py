"""Tests for CANtera config flow."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.cantera.config_flow import (
    CanteraConfigFlow,
    ConnectionResult,
    _get_device_info,
    _test_connection,
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


# ---------------------------------------------------------------------------
# Reconfigure flow tests
# ---------------------------------------------------------------------------


@pytest.fixture
def reconfig_flow(hass):
    """Create a reconfigure flow with a mock entry."""
    f = CanteraConfigFlow()
    f.hass = hass
    mock_entry = MagicMock()
    mock_entry.data = {CONF_HOST: "10.0.0.1", CONF_PORT: DEFAULT_PORT}
    f._get_reconfigure_entry = MagicMock(return_value=mock_entry)
    return f, mock_entry


async def test_reconfigure_form_shows(reconfig_flow):
    """Reconfigure step shows form with current values pre-filled."""
    flow, _entry = reconfig_flow
    result = await flow.async_step_reconfigure(user_input=None)
    assert result["type"] == "form"
    assert result["step_id"] == "reconfigure"


@patch(
    "custom_components.cantera.config_flow._test_connection",
    new_callable=AsyncMock,
    return_value=ConnectionResult.OK,
)
async def test_reconfigure_success_updates_and_aborts(mock_conn, reconfig_flow):
    """Successful reconfigure calls async_update_reload_and_abort."""
    flow, entry = reconfig_flow
    flow.async_update_reload_and_abort = MagicMock(
        return_value={"type": "abort", "reason": "reconfigure_successful"}
    )
    result = await flow.async_step_reconfigure(
        user_input={CONF_HOST: "10.0.0.99", CONF_PORT: 8080}
    )
    assert result["type"] == "abort"
    flow.async_update_reload_and_abort.assert_called_once()
    call_kwargs = flow.async_update_reload_and_abort.call_args
    assert call_kwargs[1]["data"][CONF_HOST] == "10.0.0.99"
    assert call_kwargs[1]["data"][CONF_PORT] == 8080


@patch(
    "custom_components.cantera.config_flow._test_connection",
    new_callable=AsyncMock,
    return_value=ConnectionResult.CANNOT_CONNECT,
)
async def test_reconfigure_connection_failure_shows_error(mock_conn, reconfig_flow):
    """Connection failure during reconfigure re-shows the form with an error."""
    flow, _entry = reconfig_flow
    result = await flow.async_step_reconfigure(
        user_input={CONF_HOST: "10.0.0.99", CONF_PORT: DEFAULT_PORT}
    )
    assert result["type"] == "form"
    assert result["errors"]["base"] == ConnectionResult.CANNOT_CONNECT.value


@patch(
    "custom_components.cantera.config_flow._test_connection",
    new_callable=AsyncMock,
    return_value=ConnectionResult.OK,
)
async def test_reconfigure_strips_host_whitespace(mock_conn, reconfig_flow):
    """Whitespace is stripped from host during reconfigure."""
    flow, _entry = reconfig_flow
    flow.async_update_reload_and_abort = MagicMock(
        return_value={"type": "abort", "reason": "reconfigure_successful"}
    )
    await flow.async_step_reconfigure(
        user_input={CONF_HOST: "  10.0.0.99  ", CONF_PORT: DEFAULT_PORT}
    )
    call_kwargs = flow.async_update_reload_and_abort.call_args
    assert call_kwargs[1]["data"][CONF_HOST] == "10.0.0.99"


# ---------------------------------------------------------------------------
# Direct _test_connection unit tests (covers lines 44-65 of config_flow.py)
# ---------------------------------------------------------------------------


def _make_mock_session(resp_status: int = 200):
    mock_resp = AsyncMock()
    mock_resp.status = resp_status
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)
    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=mock_resp)
    return mock_session


def _conn_error(errno_val: int | None):
    """Build a ClientConnectorError whose os_error.errno matches errno_val."""
    import aiohttp
    os_err = OSError(errno_val, "test") if errno_val is not None else OSError("no errno")
    if errno_val is None:
        os_err.errno = None  # type: ignore[assignment]
    return aiohttp.ClientConnectorError(None, os_err)


async def test_test_connection_200_returns_ok(hass):
    """200 response → ConnectionResult.OK."""
    mock_session = _make_mock_session(200)
    with patch(
        "custom_components.cantera.config_flow.async_get_clientsession",
        return_value=mock_session,
    ):
        result = await _test_connection("192.168.1.100", 8080, hass)
    assert result == ConnectionResult.OK


async def test_test_connection_non_200_returns_cannot_connect(hass):
    """Non-200 response → ConnectionResult.CANNOT_CONNECT."""
    mock_session = _make_mock_session(503)
    with patch(
        "custom_components.cantera.config_flow.async_get_clientsession",
        return_value=mock_session,
    ):
        result = await _test_connection("192.168.1.100", 8080, hass)
    assert result == ConnectionResult.CANNOT_CONNECT


async def test_test_connection_econnrefused_returns_connection_refused(hass):
    """ECONNREFUSED (errno 111) → ConnectionResult.CONNECTION_REFUSED."""
    exc = _conn_error(111)
    mock_session = MagicMock()
    mock_session.get.return_value.__aenter__ = AsyncMock(side_effect=exc)
    mock_session.get.return_value.__aexit__ = AsyncMock(return_value=False)
    with patch(
        "custom_components.cantera.config_flow.async_get_clientsession",
        return_value=mock_session,
    ):
        result = await _test_connection("192.168.1.100", 8080, hass)
    assert result == ConnectionResult.CONNECTION_REFUSED


async def test_test_connection_enetunreach_returns_host_unreachable(hass):
    """ENETUNREACH (errno 101) → ConnectionResult.HOST_UNREACHABLE."""
    exc = _conn_error(101)
    mock_session = MagicMock()
    mock_session.get.return_value.__aenter__ = AsyncMock(side_effect=exc)
    mock_session.get.return_value.__aexit__ = AsyncMock(return_value=False)
    with patch(
        "custom_components.cantera.config_flow.async_get_clientsession",
        return_value=mock_session,
    ):
        result = await _test_connection("192.168.1.100", 8080, hass)
    assert result == ConnectionResult.HOST_UNREACHABLE


async def test_test_connection_ehostunreach_returns_host_unreachable(hass):
    """EHOSTUNREACH (errno 113) → ConnectionResult.HOST_UNREACHABLE."""
    exc = _conn_error(113)
    mock_session = MagicMock()
    mock_session.get.return_value.__aenter__ = AsyncMock(side_effect=exc)
    mock_session.get.return_value.__aexit__ = AsyncMock(return_value=False)
    with patch(
        "custom_components.cantera.config_flow.async_get_clientsession",
        return_value=mock_session,
    ):
        result = await _test_connection("192.168.1.100", 8080, hass)
    assert result == ConnectionResult.HOST_UNREACHABLE


async def test_test_connection_no_os_error_returns_host_unreachable(hass):
    """ClientConnectorError with os_error=None → ConnectionResult.HOST_UNREACHABLE."""
    exc = _conn_error(None)
    mock_session = MagicMock()
    mock_session.get.return_value.__aenter__ = AsyncMock(side_effect=exc)
    mock_session.get.return_value.__aexit__ = AsyncMock(return_value=False)
    with patch(
        "custom_components.cantera.config_flow.async_get_clientsession",
        return_value=mock_session,
    ):
        result = await _test_connection("192.168.1.100", 8080, hass)
    assert result == ConnectionResult.HOST_UNREACHABLE


async def test_test_connection_generic_exception_returns_cannot_connect(hass):
    """An unexpected exception → ConnectionResult.CANNOT_CONNECT."""
    mock_session = MagicMock()
    mock_session.get = MagicMock(side_effect=RuntimeError("unexpected"))
    with patch(
        "custom_components.cantera.config_flow.async_get_clientsession",
        return_value=mock_session,
    ):
        result = await _test_connection("192.168.1.100", 8080, hass)
    assert result == ConnectionResult.CANNOT_CONNECT
