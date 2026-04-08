"""Config flow for CANtera integration."""
from __future__ import annotations

from enum import Enum

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_HOST,
    CONF_PORT,
    DEFAULT_PORT,
    DEVICE_ENDPOINT,
    DOMAIN,
    HEALTH_ENDPOINT,
)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Optional(CONF_PORT, default=DEFAULT_PORT): int,
    }
)


class ConnectionResult(Enum):
    """Possible outcomes from a connection test."""

    OK = "ok"
    HOST_UNREACHABLE = "host_unreachable"
    CONNECTION_REFUSED = "connection_refused"
    CANNOT_CONNECT = "cannot_connect"


async def _test_connection(host: str, port: int) -> ConnectionResult:
    """Test connectivity by hitting /api/health (lightweight, immediate response).

    Uses the health endpoint instead of the SSE stream so the test
    completes instantly without opening a long-lived connection.
    """
    url = f"http://{host}:{port}{HEALTH_ENDPOINT}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(connect=5, total=5)
            ) as resp:
                if resp.status == 200:
                    return ConnectionResult.OK
                return ConnectionResult.CANNOT_CONNECT
    except aiohttp.ClientConnectorError as exc:
        os_err = getattr(exc, "os_error", None)
        if os_err is not None:
            errno_val = getattr(os_err, "errno", 0)
            # ECONNREFUSED=111 means the host is up but nothing is listening.
            if errno_val == 111:
                return ConnectionResult.CONNECTION_REFUSED
            # EHOSTUNREACH=113, ENETUNREACH=101 — routing failure (e.g. Tailscale).
            if errno_val in (101, 113):
                return ConnectionResult.HOST_UNREACHABLE
        return ConnectionResult.HOST_UNREACHABLE
    except Exception:
        return ConnectionResult.CANNOT_CONNECT


async def _get_device_info(host: str, port: int) -> dict | None:
    """Fetch /api/device for stable identity. Returns None if not available."""
    url = f"http://{host}:{port}{DEVICE_ENDPOINT}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(connect=5, total=5)
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
    except Exception:
        pass
    return None


class CanteraConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for CANtera."""

    VERSION = 1

    async def async_step_user(self, user_input=None) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            # Strip accidental whitespace around the host value.
            host = user_input[CONF_HOST].strip()
            port = user_input[CONF_PORT]
            user_input = {**user_input, CONF_HOST: host}

            result = await _test_connection(host, port)
            if result == ConnectionResult.OK:
                device_info = await _get_device_info(host, port)
                unique_id = (
                    device_info.get("id")
                    if device_info and device_info.get("id")
                    else f"{host}:{port}"
                )
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured(
                    updates={CONF_HOST: host, CONF_PORT: port}
                )
                return self.async_create_entry(
                    title=f"CANtera ({host})",
                    data=user_input,
                )
            errors["base"] = result.value

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )
