DOMAIN = "open_banking"

# Keys for config entry
CONF_SECRET_ID = "secret_id"
CONF_SECRET_KEY = "secret_key"
CONF_REQUISITION_ID = "requisition_id"
CONF_REFRESH_TOKEN = "refresh_token"

# How often to poll the Nordigen API -> 2 times a day = every 12 hours
UPDATE_INTERVAL_HOURS = 6

# Nordigen API Error Constants
ERROR_INVALID_CREDENTIALS = "invalid_credentials"
ERROR_NO_LINKED_ACCOUNTS = "no_linked_accounts"
ERROR_EXPIRED_REQUISITION = "expired_requisition"
ERROR_API_FAILURE = "api_failure"
ERROR_INVALID_REQUISITION = "invalid_requisition"
