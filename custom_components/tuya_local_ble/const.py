"""The Tuya BLE integration."""
from __future__ import annotations

from typing_extensions import Final

DOMAIN: Final = "tuya_local_ble"

DEVICE_METADATA_UUIDS: Final = "uuids"

DEVICE_DEF_MANUFACTURER: Final = "Tuya"
SET_DISCONNECTED_DELAY = 10 * 60

CONF_UUID: Final = "uuid"
CONF_LOCAL_KEY: Final = "local_key"
CONF_CATEGORY: Final = "category"
CONF_PRODUCT_ID: Final = "product_id"
CONF_DEVICE_NAME: Final = "device_name"
CONF_PRODUCT_MODEL: Final = "product_model"
CONF_PRODUCT_NAME: Final = "product_name"
CONF_BLE_UNLOCK_CHECK: Final = "ble_unlock_check"
# Opt-in persistent BLE session for battery locks (e.g. Raykube hc7n0urm).
# Default off: connect on demand + advertisement refresh. On: keepalive like rlyxv7pe.
CONF_KEEP_CONNECTED: Final = "keep_connected"

# Per-config-entry diagnostics for the YD_350K. Kept separate from Home
# Assistant's global logger level so parsed lock traffic can be enabled without
# enabling DEBUG for the entire integration.
CONF_PROTOCOL_LOG_LEVEL: Final = "protocol_log_level"
PROTOCOL_LOG_OFF: Final = "off"
PROTOCOL_LOG_EVENTS: Final = "events"
PROTOCOL_LOG_RAW: Final = "raw"
PROTOCOL_LOG_LEVELS: Final = (
    PROTOCOL_LOG_OFF,
    PROTOCOL_LOG_EVENTS,
    PROTOCOL_LOG_RAW,
)

CONF_CRED_FILE = DOMAIN + "/devices.json"

BATTERY_STATE_LOW: Final = "low"
BATTERY_STATE_NORMAL: Final = "normal"
BATTERY_STATE_HIGH: Final = "high"

BATTERY_NOT_CHARGING: Final = "not_charging"
BATTERY_CHARGING: Final = "charging"
BATTERY_CHARGED: Final = "charged"

CO2_LEVEL_NORMAL: Final = "normal"
CO2_LEVEL_ALARM: Final = "alarm"

FINGERBOT_MODE_PUSH: Final = "push"
FINGERBOT_MODE_SWITCH: Final = "switch"
FINGERBOT_MODE_PROGRAM: Final = "program"
FINGERBOT_BUTTON_EVENT: Final = "fingerbot_button_pressed"

# Synthetic, local-only datapoints for YD_350K diagnostics. Tuya BLE datapoint
# IDs are one byte on this device, so negative IDs cannot collide with a real DP.
DP_350K_LAST_ACCESS_EVENT: Final = -3501
DP_350K_LAST_CREDENTIAL_ID: Final = -3502
DP_350K_LAST_ACCESS_EVENT_TIME: Final = -3503
DP_350K_LAST_LOCK_RECORD: Final = -3504
