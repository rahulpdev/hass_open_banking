import logging
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback

from .const import (
    DOMAIN,
    CONF_SECRET_ID,
    CONF_SECRET_KEY,
    CONF_REQUISITION_ID,
    CONF_REFRESH_TOKEN,
    ERROR_INVALID_CREDENTIALS,
    ERROR_INVALID_REQUISITION,
    ERROR_API_FAILURE,
    ERROR_EXPIRED_REQUISITION,
    ERROR_NO_LINKED_ACCOUNTS
)
from .nordigen_wrapper import NordigenAPIError, NordigenWrapper

_LOGGER = logging.getLogger(__name__)


class OpenBankingConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Open Banking."""

    VERSION: int = 1

    async def async_step_user(self, user_input: dict | None = None) -> config_entries.FlowResult:
        """Handle the user input step in the configuration flow.

        Args:
            user_input (dict, optional): Dictionary containing user-provided configuration data.
                Expected keys are CONF_SECRET_ID, CONF_SECRET_KEY, CONF_REQUISITION_ID, and CONF_REFRESH_TOKEN.

        Returns:
            Config entry or an error message prompting the user to correct input issues.
        """
        errors: dict[str, str] = {}

        if user_input is not None:
            secret_id = user_input[CONF_SECRET_ID].strip()
            secret_key = user_input[CONF_SECRET_KEY].strip()
            requisition_id = user_input[CONF_REQUISITION_ID].strip()
            refresh_token = user_input.get(CONF_REFRESH_TOKEN)
            refresh_token = refresh_token.strip() if refresh_token else None

            try:
                new_refresh_token = refresh_token

                # Validate requisition ID before creating the entry
                wrapper = await self.hass.async_add_executor_job(
                    NordigenWrapper,
                    secret_id,
                    secret_key,
                    requisition_id,
                    new_refresh_token
                )

                data = {
                    CONF_SECRET_ID: secret_id,
                    CONF_SECRET_KEY: secret_key,
                    CONF_REQUISITION_ID: requisition_id,
                    CONF_REFRESH_TOKEN: new_refresh_token
                }

                await self.async_set_unique_id(secret_id)
                self._abort_if_unique_id_configured()

                institution_id = wrapper.manager.institution_id
                reference = wrapper.manager.reference

                return self.async_create_entry(
                    title=f"{institution_id} - {reference}",
                    data=data
                )

            except NordigenAPIError as e:
                _LOGGER.error("Nordigen API error: %s", e)
                if e.status_code == 401:
                    errors["base"] = ERROR_INVALID_CREDENTIALS
                elif e.status_code == 400:
                    errors["base"] = ERROR_INVALID_REQUISITION
                elif e.status_code == 410:
                    errors["base"] = ERROR_NO_LINKED_ACCOUNTS
                elif e.status_code == 428:
                    errors["base"] = ERROR_EXPIRED_REQUISITION
                else:
                    errors["base"] = ERROR_API_FAILURE
            except Exception as e:
                _LOGGER.exception("Unexpected error during setup: %s", str(e))
                errors["base"] = "unknown_error"

        schema = vol.Schema(
            {
                vol.Required(CONF_SECRET_ID): str,
                vol.Required(CONF_SECRET_KEY): str,
                vol.Required(CONF_REQUISITION_ID): str,
                vol.Optional(CONF_REFRESH_TOKEN): str,
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> config_entries.OptionsFlow:
        """Return the options flow handler for updating integration settings.

        Args:
            config_entry (ConfigEntry): The configuration entry for this integration.

        Returns:
            OpenBankingOptionsFlow: The handler for managing configuration updates.
        """
        return OpenBankingOptionsFlow(
            config_entry
        )


class OpenBankingOptionsFlow(config_entries.OptionsFlow):
    """Manage the options flow for updating Open Banking configuration"""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry: config_entries.ConfigEntry = config_entry

    async def async_step_init(self, user_input: dict | None = None) -> config_entries.FlowResult:
        """Handle the initialization step of the options flow.

        Args:
            user_input (dict, optional): Dictionary containing updated configuration settings.
                Expected keys are CONF_REQUISITION_ID and CONF_REFRESH_TOKEN.

        Returns:
            Config entry update or a form prompting the user for correct input.
        """
        if user_input is not None:
            data = dict(self.config_entry.data)
            data[CONF_REQUISITION_ID] = user_input[CONF_REQUISITION_ID].strip()
            data[CONF_REFRESH_TOKEN] = user_input.get(CONF_REFRESH_TOKEN, "").strip()

            self.hass.config_entries.async_update_entry(self.config_entry, data=data)

            return self.async_create_entry(
                title="",
                data={}
            )

        current_requisition_id = self.config_entry.data.get(CONF_REQUISITION_ID, "")
        current_refresh_token = self.config_entry.data.get(CONF_REFRESH_TOKEN, "")

        schema = vol.Schema(
            {
                vol.Required(CONF_REQUISITION_ID, default=current_requisition_id): str,
                vol.Optional(CONF_REFRESH_TOKEN, default=current_refresh_token): str,
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=schema
        )
