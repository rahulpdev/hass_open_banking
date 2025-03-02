# Open Banking Integration for Home Assistant

## Overview
This custom integration connects Home Assistant with the **Nordigen Open Banking API**, allowing you to retrieve and display **bank account balances** as sensors.

### Features
- **Secure authentication** using Nordigen API credentials.
- **Scheduled updates every 6 hours** (configurable in `const.py`).
- **Rate limit handling:** If Nordigen returns a `429 Too Many Requests`, the integration dynamically **delays the next update** to match the wait time.
- **Automatic token refresh** to maintain seamless authentication.
- **Bank account balance tracking** with entity attributes that include:
  - `account_name`
  - `balance_type`
  - `account_status`
  - `institution_id`
  - `last_updated` (timestamp of the last successful API update)

## Installation
### **Prerequisites**
Before adding the integration, you need:
1. **Nordigen API Credentials**: Register for an account at [Nordigen](https://bankaccountdata.gocardless.com/overview/).
2. **Bank Account Requisition ID**: Generated after linking your bank account via Nordigen.

### **Manual Installation**
1. Download this repository.
2. Copy the `custom_components/open_banking` folder to your Home Assistant `custom_components` directory.
3. Restart Home Assistant.

### **Adding the Integration**
1. In Home Assistant, go to **Settings > Devices & Services**.
2. Click **Add Integration** and search for **Open Banking**.
3. Enter your **Nordigen API credentials** and **Requisition ID**.
4. The integration will fetch and create sensors for your linked bank accounts.

## Configuration
### **Required Fields:**
- **Secret ID**: From your Nordigen API dashboard.
- **Secret Key**: From your Nordigen API dashboard.
- **Requisition ID**: Obtained after linking your bank.

### **Optional Fields:**
- **Refresh Token**:
  - If not provided, the integration **will generate a refresh token automatically** during setup.
  - Once generated, it is **stored in Home Assistant’s config entries** for seamless authentication.
  - **Stored refresh tokens are automatically updated** whenever a new token is issued.

## How It Works
### **Data Updates and `last_updated` Attribute**
- Each sensor includes a `last_updated` attribute that **tracks the last successful data refresh**.
- The update schedule remains **every 6 hours**, unless dynamically delayed due to rate limits.

### **Automatic Token Refresh in `_async_update_data()`**
- **Access tokens expire every 24 hours**, and **refresh tokens expire every 30 days**.
- If a `401 Unauthorized` error occurs:
  - `_async_update_data()` in `coordinator.py` **calls `refresh_access_token()` in `nordigen_wrapper.py`** to obtain a new access token.
  - If the access token is expired, the intgeration **retrieves a new access token**
  - If the refresh token is **expired**, the integration **retrieves a new refresh token and access token pair** automatically.
- This ensures **seamless authentication** without user intervention.

### **Entity Attributes**
Each bank account balance sensor includes the following attributes:
```yaml
account_name: "personalChecking"
balance_type: "closingBooked"
account_status: "active"
institution_id: "STARLING_STRL"
last_updated: "2025-02-28T07:07:28.302832"
```

## Logging and Debugging
To enable detailed logging for troubleshooting, add the following to your `configuration.yaml`:

```yaml
logger:
  default: warning
  logs:
    custom_components.open_banking: debug
    nordigen_account: debug  # Logs API responses and balance updates
```

### **What This Logs:**
- **`custom_components.open_banking: debug`**
  - Sensor creation and updates.
  - Token refresh handling.
- **`nordigen_account: debug`**
  - API requests and responses.
  - Retrieved bank account and balance data.

## FAQ
### **1. How often does the integration update?**
- By default, the integration **refreshes every 6 hours**.
- If Nordigen’s API returns a `429 Too Many Requests`, the update is **delayed automatically** to comply with rate limits.

### **2. What happens if my access token expires?**
- The integration **automatically refreshes the token** using `_async_update_data()` in `coordinator.py`.
- If the refresh token is also expired, the integration **retrieves a new one** without user intervention.

### **3. Why do my sensors show an old `last_updated` value?**
- Ensure that `_async_update_data()` is **being called every 6 hours**.
- If `last_updated` is not changing, check logs for any rate-limit warnings or authentication failures.

## Contributing
If you would like to contribute, submit a pull request or open an issue on GitHub.

## License
This project is licensed under the MIT License.

