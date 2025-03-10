import logging

from typing import List, Optional
from nordigen_account import create_nordigen_client, BankAccountManager, NordigenAPIError, BankAccount

_LOGGER = logging.getLogger(__name__)


class NordigenWrapper:
    """A wrapper around BankAccountManager to manage and update bank accounts."""

    def __init__(
            self,
            secret_id: str,
            secret_key: str,
            requisition_id: str,
            refresh_token: Optional[str] = None
    ) -> None:
        """
        Initialize the NordigenWrapper.

        Args:
            secret_id (str): API secret ID for authentication.
            secret_key (str): API secret key for authentication.
            requisition_id (str): The requisition ID for accessing linked bank accounts.
            refresh_token (Optional[str]): A token used to refresh authentication credentials.
        """
        self._secret_id: str = secret_id
        self._secret_key: str = secret_key
        self._requisition_id: str = requisition_id
        self._refresh_token: Optional[str] = refresh_token

        self.client: Optional[object] = None
        self.manager: Optional[BankAccountManager] = None
        self.accounts: List[BankAccount] = []

        self._initialize_manager()

    def _initialize_manager(self) -> None:
        """
        Initialize the Nordigen API client and bank account manager.

        Raises:
            NordigenAPIError: If the API request fails due to invalid credentials or server errors.
            RuntimeError: If there is an issue initializing the bank account manager.
        """
        try:
            client, new_refresh_token = create_nordigen_client(
                secret_id=self._secret_id,
                secret_key=self._secret_key,
                refresh_token=self._refresh_token
            )
            self.client = client

            # Update the stored refresh token if a new one is returned
            if new_refresh_token:
                self._refresh_token = new_refresh_token

            self.manager = BankAccountManager(
                client=self.client,
                requisition_id=self._requisition_id,
                fetch_data=False
            )
            self.accounts = self.manager.accounts

        except NordigenAPIError as e:
            raise

        except RuntimeError as e:
            raise

    def update_all_accounts(self) -> None:
        """
        Update account and balance data for all linked accounts.

        Raises:
            NordigenAPIError: If the API call to update account data fails.
        """
        if not self.manager:
            self._initialize_manager()

        try:
            for acc in self.manager.accounts:
                _LOGGER.warning("Calling API: GET /api/v2/accounts/%s/", acc._account_id)
                acc.update_account_data()

                _LOGGER.warning("Calling API: GET /api/v2/accounts/%s/balances/", acc._account_id)
                acc.update_balance_data()

                _LOGGER.warning("API Response: Account Data: %s", acc)
                _LOGGER.warning("API Response: Balance Data: %s", acc.balances)

        except NordigenAPIError as e:
            raise

    def refresh_access_token(self) -> None:
        """
        Refresh the access token by re-initializing the Nordigen client.

        This method uses the existing refresh token to obtain a new access token.
        If the refresh token is expired, it generates a new token pair.

        Raises:
            NordigenAPIError: If the token refresh process fails.
        """
        try:
            client, new_refresh_token = create_nordigen_client(
                secret_id=self._secret_id,
                secret_key=self._secret_key,
                refresh_token=self._refresh_token
            )
            self.client = client

            # Update the stored refresh token if a new one is returned
            if new_refresh_token:
                self._refresh_token = new_refresh_token

        except NordigenAPIError as e:
            raise

    @property
    def refresh_token(self) -> Optional[str]:
        """
        Get the current refresh token.
        """
        return self._refresh_token

    @property
    def requisition_id(self) -> str:
        """
        Get the requisition ID.
        """
        return self._requisition_id

    @requisition_id.setter
    def requisition_id(self, new_id: str) -> None:
        """
        Set a new requisition ID and reinitialize the manager.

        Args:
            new_id (str): The new requisition ID to assign.
        """
        self._requisition_id = new_id
        self._initialize_manager()
