import logging
from typing import List, Optional
from datetime import datetime, timezone, timedelta

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback, async_get_current_platform
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, UPDATE_INTERVAL_HOURS
from .coordinator import OpenBankingDataUpdateCoordinator
from .nordigen_wrapper import BankAccount

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
        hass: HomeAssistant,
        entry: ConfigEntry,
        async_add_entities: AddEntitiesCallback
) -> None:
    """
    Set up Open Banking sensors from a config entry.

    Args:
        hass (HomeAssistant): The Home Assistant instance.
        entry (ConfigEntry): The configuration entry for the integration.
        async_add_entities (AddEntitiesCallback): Callback function to add entities to Home Assistant.
    """
    _LOGGER.warning("Open Banking sensor setup is starting!")
    coordinator: OpenBankingDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    # Check if we have data in the coordinator
    _LOGGER.warning("Sensor setup - coordinator data available: %s", bool(coordinator.data))
    
    # Create entities from the data
    entities: List[OpenBankingBalanceSensor] = []
    platform = async_get_current_platform()
    existing_entity_ids = {entity.unique_id for entity in platform.entities.values()}

    # If we have data in the coordinator, use it to create entities
    if coordinator.data:
        _LOGGER.warning("Creating sensors from coordinator data")
        for account in coordinator.data:
            _LOGGER.warning("Creating sensors for account: %s", account._account_id)
            
            # Store this account ID in the config entry for future reference
            known_accounts = entry.data.get("known_accounts", [])
            if account._account_id not in known_accounts:
                known_accounts.append(account._account_id)
                hass.config_entries.async_update_entry(
                    entry,
                    data={
                        **entry.data,
                        "known_accounts": known_accounts
                    }
                )
            
            for bal in account.balances:
                balance_type: str = bal["balanceType"]
                unique_id: str = f"{account.name}_{balance_type}_{entry.entry_id}"

                if unique_id not in existing_entity_ids:
                    sensor = OpenBankingBalanceSensor(
                        coordinator,
                        entry.entry_id,
                        account,
                        balance_type
                    )
                    entities.append(sensor)
                    existing_entity_ids.add(unique_id)
    else:
        _LOGGER.warning("No coordinator data available")
        _LOGGER.warning("Home Assistant will restore entities from registry")

    if entities:
        _LOGGER.warning("Adding %d new sensors", len(entities))
        async_add_entities(entities)


class OpenBankingBalanceSensor(CoordinatorEntity, SensorEntity):
    """
    Represents an Open Banking bank account balance as a sensor in Home Assistant.

    Attributes:
        coordinator (OpenBankingDataUpdateCoordinator): Data update coordinator instance.
        _config_entry_id (str): The configuration entry ID associated with this sensor.
        _account_id (str): The ID of the bank account associated with this sensor.
        _balance_type (str): The type of balance being tracked (e.g., 'closingBooked').
    """

    _attr_device_class = "monetary"
    _attr_state_class = "total"

    def __init__(
            self,
            coordinator: OpenBankingDataUpdateCoordinator,
            config_entry_id: str,
            account: BankAccount,
            balance_type: str
    ) -> None:
        """Initialize the sensor."""
        # Initialize the CoordinatorEntity first
        super().__init__(coordinator)
        
        # Store account ID instead of object reference
        self._config_entry_id = config_entry_id
        self._account_id = account._account_id
        self._balance_type = balance_type
        self._account_name = account.name
        
        self._attr_unique_id: str = f"{account.name}_{balance_type}_{config_entry_id}"
        self._attr_name: str = f"{account.name}_{balance_type}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, config_entry_id, account.name)},
            name=account.name,
            manufacturer="GoCardless",
            model=f"Status: {account.status}",
            configuration_url="https://bankaccountdata.gocardless.com/",
        )

        self._attr_extra_state_attributes = {
            "last_updated": account._last_updated,
            "account_name": account.name,
            "balance_type": balance_type,
            "account_status": account.status
        }

    @property
    def _account(self) -> Optional[BankAccount]:
        """Get the current account object from coordinator data."""
        if not self.coordinator.data:
            return None
            
        for account in self.coordinator.data:
            if account._account_id == self._account_id:
                # Update extra state attributes with latest data
                self._attr_extra_state_attributes["last_updated"] = account._last_updated
                self._attr_extra_state_attributes["account_status"] = account.status
                return account
                
        return None
        
    @property
    def native_unit_of_measurement(self) -> Optional[str]:
        """
        Return the currency as the unit of measurement.
        """
        account = self._account
        if not account:
            return None
            
        for bal in account.balances:
            if bal["balanceType"] == self._balance_type:
                currency = bal["currency"]
                if currency:
                    return currency

        return None

    @property
    def native_value(self) -> Optional[float]:
        """
        Retrieve the current balance for the associated bank account.

        Returns:
            float: The current balance amount.
        """
        account = self._account
        if not account:
            _LOGGER.warning(
                "No account data found for entity: %s | Account ID: %s",
                self.entity_id, self._account_id
            )
            return None
            
        _LOGGER.warning(
            "Fetching native_value for entity: %s | Account: %s",
            self.entity_id, account._account_id
        )
        
        for bal in account.balances:
            if bal["balanceType"] == self._balance_type:
                amount = bal.get("amount")

                # Ensure amount is valid
                if amount is None or amount == "":
                    _LOGGER.warning(
                        "Balance amount for %s is None or empty, setting to 0.0",
                        self._attr_unique_id
                    )
                    return 0.0

                try:
                    value = float(amount)
                    _LOGGER.warning(
                        "Sensor value: entity_id=%s, balance_type=%s, value=%.2f",
                        self.entity_id,
                        self._balance_type,
                        value
                    )
                    return value

                except ValueError:
                    _LOGGER.error(
                        "Invalid amount format for %s: %s",
                        self._attr_unique_id,
                        amount
                    )
                    return 0.0

        # No matching balance found
        return 0.0


    @property
    def available(self) -> bool:
        """
        Determine if the entity should be marked as available.

        Returns:
            bool: True if the sensor should be considered available, False otherwise.
        """
        account = self._account
        if not self.coordinator.last_update_success or not account:
            return False

        return any(bal["balanceType"] for bal in account.balances)
