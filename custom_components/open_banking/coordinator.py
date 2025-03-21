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
        # Store entry first, before any methods try to use it
        self.entry: ConfigEntry = entry
        self.wrapper: Optional[NordigenWrapper] = None  # Initialize as None
        
        # Get the last update time from config entry data
        last_update_str = entry.data.get("last_update_time")
        
        # Now we can safely call methods that use self.entry
        update_interval = self._calculate_next_update_interval(last_update_str)
        
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=update_interval,
        )
        
        # Store whether we need an immediate refresh
        self._needs_immediate_refresh = self._should_refresh_immediately(last_update_str)
        
        # Debug log to verify the actual type of self.entry
        _LOGGER.warning("Type of self.entry: %s", type(self.entry))
        
        # Get the last update time from config entry data if available
        if last_update_str:
            try:
                self.last_update_time = datetime.fromisoformat(last_update_str)
                _LOGGER.warning("Retrieved last update time from config: %s", self.last_update_time)
            except (ValueError, TypeError):
                self.last_update_time = None
                _LOGGER.warning("Invalid last_update_time format in config entry")
        else:
            self.last_update_time = None
            
        # Track rate limit expiry if set
        rate_limit_reset = entry.data.get("rate_limit_reset")
        if rate_limit_reset:
            try:
                self.rate_limit_reset = datetime.fromisoformat(rate_limit_reset)
                _LOGGER.warning("Rate limit reset time: %s", self.rate_limit_reset)
            except (ValueError, TypeError):
                self.rate_limit_reset = None
        else:
            self.rate_limit_reset = None

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

        try:
            _LOGGER.warning("Calling update_all_accounts()")
            await self.hass.async_add_executor_job(self.wrapper.update_all_accounts)
            _LOGGER.warning("Nordigen retrieved accounts: %s", self.wrapper.accounts)

            if not self.wrapper.accounts:
                _LOGGER.warning("No accounts found in Nordigen API response.")
                raise UpdateFailed("No accounts found. Ensure bank authorization is complete.")

            # Update timestamp on all accounts
            last_updated = datetime.now(timezone.utc).isoformat()
            accounts = self.wrapper.accounts
            
            for account in accounts:
                account._last_updated = last_updated

            _LOGGER.warning("Nordigen updated account data with timestamp: %s", last_updated)
            
            # Always return fresh data, don't trigger another refresh
            self.data = accounts
            
            # Store the update time in the config entry for persistence across restarts
            current_time = datetime.now(timezone.utc)
            self._update_config_entry_timestamp(current_time)
            _LOGGER.warning("Update successful, timestamp: %s", current_time)
            
            return accounts

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

                # Calculate when the rate limit will reset
                reset_time = datetime.now(timezone.utc) + timedelta(seconds=wait_time)
                
                # Store the rate limit reset time in the config entry
                self.hass.config_entries.async_update_entry(
                    self.entry,
                    data={
                        **self.entry.data,
                        "rate_limit_reset": reset_time.isoformat()
                    }
                )
                self.rate_limit_reset = reset_time

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
            
    def _calculate_next_update_interval(self, last_update_str):
        """
        Calculate time until next update based on last update time and rate limits.
        
        If we have a rate limit reset time in the future, use that.
        Otherwise, calculate based on the last update time and normal interval.
        """
        # First check if we're rate limited
        rate_limit_reset = self.entry.data.get("rate_limit_reset") if hasattr(self, 'entry') else None
        if rate_limit_reset:
            try:
                reset_time = datetime.fromisoformat(rate_limit_reset)
                now = datetime.now(timezone.utc)
                
                # If the reset time is in the future, calculate seconds until reset
                if reset_time > now:
                    seconds_until_reset = (reset_time - now).total_seconds()
                    _LOGGER.warning("Rate limit reset in %d seconds", seconds_until_reset)
                    return timedelta(seconds=seconds_until_reset)
            except (ValueError, TypeError):
                pass
        
        # If not rate limited, calculate based on last update time
        if not last_update_str:
            return timedelta(hours=UPDATE_INTERVAL_HOURS)
            
        try:
            last_update = datetime.fromisoformat(last_update_str)
            now = datetime.now(timezone.utc)
            
            # Calculate time since last update
            time_since_update = now - last_update
            
            # Calculate time until next update
            normal_interval = timedelta(hours=UPDATE_INTERVAL_HOURS)
            time_until_next_update = normal_interval - time_since_update
            
            # If we're past due for an update, update soon but not immediately
            if time_until_next_update.total_seconds() <= 0:
                return timedelta(seconds=60)  # Update in 1 minute
                
            # Otherwise, wait until the next scheduled update
            return time_until_next_update
                
        except (ValueError, TypeError):
            # If we can't parse the timestamp, use default interval
            return timedelta(hours=UPDATE_INTERVAL_HOURS)
    
    def _should_refresh_immediately(self, last_update_str):
        """
        Determine if we need an immediate refresh.
        
        We should refresh immediately if:
        1. We have no previous update time
        2. It's been longer than our update interval since the last update
        """
        # Safety check for entry attribute
        if not hasattr(self, 'entry'):
            return False  # Be conservative if we don't have entry yet
            
        if not last_update_str:
            return True  # No previous update, refresh immediately
            
        try:
            last_update = datetime.fromisoformat(last_update_str)
            now = datetime.now(timezone.utc)
            
            # If it's been longer than our update interval, refresh immediately
            if (now - last_update) > timedelta(hours=UPDATE_INTERVAL_HOURS):
                return True
                
            return False  # Within update interval, don't refresh immediately
                
        except (ValueError, TypeError):
            return False  # Can't parse timestamp, don't refresh to avoid rate limits
        
    def _update_config_entry_timestamp(self, timestamp: datetime) -> None:
        """
        Update the config entry with the latest update timestamp.
        
        This ensures the timestamp persists across Home Assistant restarts.
        """
        self.last_update_time = timestamp
        
        # Update the config entry with the new timestamp
        self.hass.config_entries.async_update_entry(
            self.entry,
            data={
                **self.entry.data,
                "last_update_time": timestamp.isoformat()
            }
        )
