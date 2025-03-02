import logging
from datetime import timedelta, datetime, timezone
from typing import Optional, Dict

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers.event import async_call_later
from homeassistant.components.persistent_notification import async_create
from homeassistant.config_entries import ConfigEntry
from nordigen_account import BankAccount # Can I change this?

from .const import DOMAIN, UPDATE_INTERVAL_HOURS
from .nordigen_wrapper import NordigenWrapper, NordigenAPIError

_LOGGER = logging.getLogger(__name__)


class OpenBankingDataUpdateCoordinator(DataUpdateCoordinator):
    """Coordinator for fetching and managing Open Banking account data in Home Assistant."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """
        Initialize the coordinator and set up defaults.

        Args:
            hass (HomeAssistant): The Home Assistant instance.
            entry (Dict[str, Any]): The configuration entry containing user credentials and requisition data.
        """
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(hours=UPDATE_INTERVAL_HOURS),
        )
        self.entry: ConfigEntry = entry

        # Debug log to verify the actual type of self.entry
        _LOGGER.warning("Type of self.entry: %s", type(self.entry))

        self.wrapper: Optional[NordigenWrapper] = None  # Initialize as None

    async def async_initialize(self, hass: HomeAssistant) -> None:
        """
        Initialize the Nordigen API wrapper asynchronously.

        Args:
            hass (HomeAssistant): The Home Assistant instance.

        Raises:
            NordigenAPIError: If the API authentication or requisition retrieval fails.
        """
        secret_id: str = self.entry.data["secret_id"]
        secret_key: str = self.entry.data["secret_key"]
        requisition_id: str = self.entry.data["requisition_id"]
        refresh_token: Optional[str] = self.entry.data.get("refresh_token")

        _LOGGER.warning("Refresh Token: %s", refresh_token)

        self.wrapper = await hass.async_add_executor_job(
            NordigenWrapper,
            secret_id,
            secret_key,
            requisition_id,
            refresh_token
        )

        # Ensure the refresh token is updated in Home Assistant storage if changed
        new_refresh_token = self.wrapper.refresh_token

        if new_refresh_token and new_refresh_token != refresh_token:
            _LOGGER.warning("Updating stored refresh token.")
            hass.config_entries.async_update_entry(
                self.entry,
                data={**self.entry.data, "refresh_token": new_refresh_token}
            )

    async def _async_update_data(self) -> list[BankAccount] | None:
        """
        Fetch updated account data from Nordigen.

        This method retrieves account balances and handles rate limits, expired requisitions,
        and missing accounts. It schedules retries in case of temporary API failures.

        Returns:
            Optional[Dict[str, Any]]: A dictionary containing updated account data, or None if an error occurs.

        Raises:
            UpdateFailed: If there is an issue retrieving data from the Nordigen API.
        """
        _LOGGER.warning("Nordigen is retrieving accounts!")

        # Debug log for self.entry type
        _LOGGER.warning("Type of self.entry inside _async_update_data: %s", type(self.entry))

        if self.data:
            _LOGGER.debug("Using cached coordinator data.")
            return self.data  # Return cached data

        try:
            _LOGGER.warning("Calling update_all_accounts()")
            await self.hass.async_add_executor_job(self.wrapper.update_all_accounts)
            _LOGGER.warning("Nordigen retrieved accounts: %s", self.wrapper.accounts)

            if not self.wrapper.accounts:
                _LOGGER.warning("No accounts found in Nordigen API response.")
                raise UpdateFailed("No accounts found. Ensure bank authorization is complete.")

            last_updated = datetime.now(timezone.utc).isoformat()
            self.data = self.wrapper.accounts

            for account in self.data:
                account._last_updated = last_updated

            _LOGGER.warning("Nordigen updated coordinator data: %s", self.data)

            return self.data

        except NordigenAPIError as e:
            _LOGGER.warning("Nordigen API issue encountered: %s", e)

            # ✅ Handle Token Expiry (401 Unauthorized)
            if e.status_code == 401:
                _LOGGER.warning("Nordigen access token expired. Attempting refresh...")

                try:
                    await self.hass.async_add_executor_job(self.wrapper.refresh_access_token)
                    new_refresh_token = self.wrapper.refresh_token
                    _LOGGER.warning("New refresh token obtained: %s", new_refresh_token)

                    # Update stored token
                    self.hass.config_entries.async_update_entry(
                        self.entry, data={**self.entry.data, "refresh_token": new_refresh_token}
                    )

                    # Retry the request with the new token
                    await self.hass.async_add_executor_job(self.wrapper.update_all_accounts)
                    self.data = self.wrapper.accounts

                    return self.data

                except NordigenAPIError as refresh_error:
                    _LOGGER.error("Failed to refresh Nordigen token: %s", refresh_error)
                    raise UpdateFailed("Nordigen API authentication failed")

            # Handle Rate Limit (429 Too Many Requests)
            if e.status_code == 429:
                wait_time = int(e.response_body.get("detail", "").split()[-2])  # Extract wait time from API response
                _LOGGER.warning(
                    "Rate limit exceeded. Next update in %d seconds. Error details: 'status_code': %d",
                    wait_time,
                    e.status_code
                )

                # Prevent scheduled updates from triggering before wait_time elapses
                self.update_interval = timedelta(seconds=wait_time)

                async_call_later(
                    self.hass,
                    wait_time,
                    lambda _: self.async_request_refresh()
                )

                return None  # Ensures HA does not retry immediately

            # Handle Expired Requisition
            elif e.status_code == 428:
                message = "Your Nordigen requisition ID has expired. Please update it in the integration settings."

                async_create(
                    self.hass,
                    message,
                    title="Nordigen Integration",
                    notification_id="nordigen_requisition_expired"
                )

                # Debug log before firing the event
                _LOGGER.warning("Checking self.entry before async_fire: %s", self.entry.data)
                _LOGGER.warning("Type of self.entry before async_fire: %s", type(self.entry))

                # Fire an event so Home Assistant automations can use the message
                self.hass.bus.async_fire(
                    "nordigen_requisition_expired",
                    {
                        "entry_id": self.entry.entry_id,
                        "message": message
                    }
                )

            # Handle No Accounts Found
            elif e.status_code == 410:
                _LOGGER.warning("No accounts found for requisition ID. Ensure bank authorization is complete.")

            raise UpdateFailed(f"Nordigen API update failed: {e}")

        except Exception:
            _LOGGER.exception("Unexpected error updating Nordigen data")
            raise UpdateFailed("Error updating from Nordigen")
