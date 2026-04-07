"""Config flow for CANtera integration."""
import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN, DEFAULT_PORT, CONF_HOST, CONF_PORT, SSE_ENDPOINT

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Optional(CONF_PORT, default=DEFAULT_PORT): int,
    }
)


async def _test_connection(host: str, port: int) -> bool:
    """Try to connect to the SSE endpoint and immediately close."""
    url = f"http://{host}:{port}{SSE_ENDPOINT}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(connect=5)
            ) as resp:
                return resp.status == 200
    except Exception:
        return False


class CanteraConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for CANtera."""

    VERSION = 1

    async def async_step_user(self, user_input=None) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST]
            port = user_input[CONF_PORT]
            if await _test_connection(host, port):
                await self.async_set_unique_id(f"{host}:{port}")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"CANtera ({host})",
                    data=user_input,
                )
            errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )
