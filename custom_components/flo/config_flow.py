"""Config flow for flo integration."""

from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .api import FloAuthError, FloRequestError, async_get_api
from .const import DOMAIN, LOGGER

DATA_SCHEMA = vol.Schema(
    {vol.Required(CONF_USERNAME): str, vol.Required(CONF_PASSWORD): str}
)

REAUTH_SCHEMA = vol.Schema({vol.Required(CONF_PASSWORD): str})


async def _validate_credentials(
    hass: HomeAssistant, username: str, password: str
) -> None:
    """Validate that the credentials authenticate with the Flo API."""
    await async_get_api(hass, username, password)


class FloConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for flo."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_USERNAME])
            self._abort_if_unique_id_configured()
            try:
                await _validate_credentials(
                    self.hass,
                    user_input[CONF_USERNAME],
                    user_input[CONF_PASSWORD],
                )
            except FloAuthError as err:
                LOGGER.error("Authentication failed: %s", err)
                errors["base"] = "invalid_auth"
            except FloRequestError as err:
                LOGGER.error("Error connecting to the Flo API: %s", err)
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(
                    title=user_input[CONF_USERNAME], data=user_input
                )

        return self.async_show_form(
            step_id="user", data_schema=DATA_SCHEMA, errors=errors
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Handle reauthentication."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm reauthentication."""
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            try:
                await _validate_credentials(
                    self.hass,
                    entry.data[CONF_USERNAME],
                    user_input[CONF_PASSWORD],
                )
            except FloAuthError as err:
                LOGGER.error("Authentication failed: %s", err)
                errors["base"] = "invalid_auth"
            except FloRequestError as err:
                LOGGER.error("Error connecting to the Flo API: %s", err)
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]},
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=REAUTH_SCHEMA,
            errors=errors,
            description_placeholders={"username": entry.data[CONF_USERNAME]},
        )
