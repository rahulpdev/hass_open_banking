import logging
from typing import List, Optional

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback, async_get_current_platform
from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN
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
    _LOGGER.warning("Open Banking sensor setup is starting!") # REMOVE THIS LINE
    coordinator: OpenBankingDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    new_sensors: List[OpenBankingBalanceSensor] = []

    @coordinator.async_add_listener
    def _schedule_add_entities() -> None:
        """
        Process and register sensors based on retrieved Open Banking account data.
        """
        _LOGGER.warning("Open Banking coordinator data: %s", coordinator.data) # REMOVE THIS LINE

        if coordinator.data is None:
            _LOGGER.warning("No account data available. Using cached values if available.") # CHANGE TO DEBUG
            return

        if not coordinator.data:  # <-- Prevents execution if no data is available
            _LOGGER.warning("No account data available. Skipping sensor setup.") # CHANGE TO DEBUG
            return

        if not isinstance(coordinator.data, list):
            _LOGGER.error("Unexpected data format: %s", type(coordinator.data))
            return

        entities: List[OpenBankingBalanceSensor] = []
        platform = async_get_current_platform()
        existing_entity_ids = {entity.unique_id for entity in platform.entities.values()}

        for account in coordinator.data:
            _LOGGER.warning("Adding sensor for account: %s", account._account_id)
            acct_id = account._account_id

            for bal in account.balances:
                balance_type: str = bal["balanceType"]
                unique_id: str = f"{acct_id}_{balance_type}"

                if unique_id not in existing_entity_ids:
                    sensor = OpenBankingBalanceSensor(
                        coordinator,
                        entry.entry_id,
                        account,
                        balance_type
                    )
                    entities.append(sensor)
                    new_sensors.append(sensor)
                    existing_entity_ids.add(unique_id)

        if entities:
            _LOGGER.warning("Adding %d new sensors", len(entities))
            async_add_entities(entities)

    # Ensure data is fetched before attempting entity creation
    await coordinator.async_config_entry_first_refresh()
    _schedule_add_entities


class OpenBankingBalanceSensor(SensorEntity):
    """
    Represents an Open Banking bank account balance as a sensor in Home Assistant.

    Attributes:
        coordinator (OpenBankingDataUpdateCoordinator): Data update coordinator instance.
        _config_entry_id (str): The configuration entry ID associated with this sensor.
        _account: The bank account object associated with this sensor.
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
        self.coordinator = coordinator
        self._config_entry_id = config_entry_id
        self._account = account
        self._balance_type = balance_type
        self._last_updated = account._last_updated
        self._attr_unique_id: str = f"{account.name}_{balance_type}_{config_entry_id}"
        self._attr_name: str = f"{account.name}_{balance_type}"
        self._attr_available: bool = True
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
    def native_unit_of_measurement(self) -> Optional[str]:
        """
        Return the currency as the unit of measurement.
        """
        for bal in self._account.balances:
            if bal["balanceType"] == self._balance_type:
                currency = bal["currency"]
                if currency:
                    return currency

        self._attr_available = False
        return None

    @property
    def native_value(self) -> Optional[float]:
        """
        Retrieve the current balance for the associated bank account.

        Returns:
            float: The current balance amount.
        """
        for bal in self._account.balances:
            if bal["balanceType"] == self._balance_type:
                amount = bal.get("amount")

                # Ensure amount is valid
                if amount is None or amount == "":
                    _LOGGER.warning(
                        "Balance amount for %s is None or empty, setting to 0.0",
                        self._attr_unique_id
                    )
                    self._attr_available = False  # Mark entity as unavailable

                    return 0.0  # Prevent TypeError

                try:
                    balance_value = float(amount) # REMOVE THIS LINE
                    _LOGGER.warning(
                        "Sensor updated: entity_id=%s, account_id=%s, balance_type=%s, balance_value=%.2f",
                        self.entity_id,
                        self._account._account_id,
                        self._balance_type,
                        balance_value
                    ) # REMOVE THIS LINE

                    return float(amount)

                except ValueError:
                    _LOGGER.error(
                        "Invalid amount format for %s: %s",
                        self._attr_unique_id,
                        amount
                    )

                    return 0.0

        self._attr_available = False  # Mark entity as unavailable if no valid balance found

        return 0.0

    @property
    def should_poll(self) -> bool:
        return False

    def update(self):
        """
        Polling is disabled; state updates are handled via the coordinator.
        """
        pass

    async def async_added_to_hass(self) -> None:
        """
        Handle actions when the sensor entity is added to Home Assistant.
        """
        self.async_write_ha_state()
        self.async_on_remove(
            self.coordinator.async_add_listener(self.async_write_ha_state)
        )

    @property
    def available(self) -> bool:
        """
        Determine if the entity should be marked as available.

        Returns:
            bool: True if the sensor should be considered available, False otherwise.
        """
        if not self.coordinator.last_update_success:
            return False

        return any(bal["balanceType"] for bal in self._account.balances)
