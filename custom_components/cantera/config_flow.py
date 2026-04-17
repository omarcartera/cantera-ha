"""Config flow for CANtera integration."""
from __future__ import annotations

from enum import Enum

import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_CAR_OFF_DEBOUNCE,
    CONF_HEALTH_POLL_INTERVAL,
    CONF_HOST,
    CONF_PORT,
    DEFAULT_PORT,
    DEVICE_ENDPOINT,
    DOMAIN,
    HEALTH_ENDPOINT,
    HEALTH_POLL_INTERVAL_S,
    SYNC_CAR_OFF_DEBOUNCE_S,
)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Optional(CONF_PORT, default=DEFAULT_PORT): vol.All(
            int, vol.Range(min=1, max=65535)
        ),
    }
)


class ConnectionResult(Enum):
    """Possible outcomes from a connection test."""

    OK = "ok"
    HOST_UNREACHABLE = "host_unreachable"
    CONNECTION_REFUSED = "connection_refused"
    CANNOT_CONNECT = "cannot_connect"


async def _test_connection(host: str, port: int, hass) -> ConnectionResult:
    """Test connectivity by hitting /api/health (lightweight, immediate response).

    Uses the health endpoint instead of the SSE stream so the test
    completes instantly without opening a long-lived connection.
    """
    url = f"http://{host}:{port}{HEALTH_ENDPOINT}"
    try:
        session = async_get_clientsession(hass)
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
            # EHOSTUNREACH=113, ENETUNREACH=101 — routing failure.
            if errno_val in (101, 113):
                return ConnectionResult.HOST_UNREACHABLE
        return ConnectionResult.HOST_UNREACHABLE
    except Exception:
        return ConnectionResult.CANNOT_CONNECT


async def _get_device_info(host: str, port: int, hass) -> dict | None:
    """Fetch /api/device for stable identity. Returns None if not available."""
    url = f"http://{host}:{port}{DEVICE_ENDPOINT}"
    try:
        session = async_get_clientsession(hass)
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

    @staticmethod
    @config_entries.callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Return the options flow handler for this config entry."""
        return CanteraOptionsFlowHandler(config_entry)

    async def async_step_user(self, user_input=None) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            # Strip accidental whitespace around the host value.
            host = user_input[CONF_HOST].strip()
            port = user_input[CONF_PORT]
            user_input = {**user_input, CONF_HOST: host}

            result = await _test_connection(host, port, self.hass)
            if result == ConnectionResult.OK:
                device_info = await _get_device_info(host, port, self.hass)
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

    async def async_step_reconfigure(self, user_input=None) -> ConfigFlowResult:
        """Allow the user to update host/port without removing the entry."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            port = user_input[CONF_PORT]
            result = await _test_connection(host, port, self.hass)
            if result == ConnectionResult.OK:
                return self.async_update_reload_and_abort(
                    entry,
                    data={**entry.data, CONF_HOST: host, CONF_PORT: port},
                )
            errors["base"] = result.value

        current_host = entry.data.get(CONF_HOST, "")
        current_port = entry.data.get(CONF_PORT, DEFAULT_PORT)
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST, default=current_host): str,
                    vol.Optional(CONF_PORT, default=current_port): vol.All(
                        int, vol.Range(min=1, max=65535)
                    ),
                }
            ),
            errors=errors,
        )


class CanteraOptionsFlowHandler(config_entries.OptionsFlow):
    """Options flow: lets users tune polling interval and car-off debounce.

    Changes here trigger an integration reload so the coordinator picks up the
    new values without requiring the user to remove and re-add the device.
    """

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Store the config entry for reading current option values."""
        self._config_entry = config_entry

    async def async_step_init(self, user_input=None) -> config_entries.ConfigFlowResult:
        """Show the options form."""
        current_poll = self._config_entry.options.get(
            CONF_HEALTH_POLL_INTERVAL, HEALTH_POLL_INTERVAL_S
        )
        current_debounce = self._config_entry.options.get(
            CONF_CAR_OFF_DEBOUNCE, SYNC_CAR_OFF_DEBOUNCE_S
        )

        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_HEALTH_POLL_INTERVAL, default=current_poll
                    ): vol.All(int, vol.Range(min=1, max=60)),
                    vol.Optional(
                        CONF_CAR_OFF_DEBOUNCE, default=current_debounce
                    ): vol.All(int, vol.Range(min=5, max=300)),
                }
            ),
        )
