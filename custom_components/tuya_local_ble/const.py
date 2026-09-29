"""Constants for the Tuya Local BLE integration."""
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

# Ironzon / YD_350K identity and physical Tuya datapoints. Keep these in one
# place so entity mappings, events, diagnostics and protocol code do not drift.
PRODUCT_ID_350K: Final = "z1dfsaya"
DP_350K_BATTERY_PERCENT: Final = 8
DP_350K_FINGERPRINT_CREDENTIAL_ID: Final = 12
DP_350K_PIN_CREDENTIAL_ID: Final = 13
DP_350K_BLE_UNLOCK_EVENT: Final = 19
DP_350K_LOCK_RECORD: Final = 20
DP_350K_FAILED_CREDENTIAL: Final = 21
DP_350K_LANGUAGE: Final = 28
DP_350K_BEEP_VOLUME: Final = 31
DP_350K_SECURE_STATE: Final = 32
DP_350K_PASSAGE_MODE: Final = 33
DP_350K_MANUAL_LOCK: Final = 46
DP_350K_LOCK_STATE: Final = 47
DP_350K_SPECIAL_ENUM: Final = 68
DP_350K_BLE_UNLOCK: Final = 71
DP_350K_SPECIAL_BOOL: Final = 78
DP_350K_SECURE_CONTROL: Final = 79

# Synthetic, local-only button IDs for YD_350K actions that are not real Tuya
# datapoints. Keep these named so dispatch/availability logic cannot silently
# diverge from the entity mappings.
BUTTON_350K_REFRESH_STATUS: Final = -9001
BUTTON_350K_CLEAR_DIAGNOSTICS: Final = -9002

# Synthetic, local-only datapoints for YD_350K diagnostics. Tuya BLE datapoint
# IDs are one byte on this device, so negative IDs cannot collide with a real DP.
DP_350K_LAST_ACCESS_EVENT: Final = -3501
DP_350K_LAST_CREDENTIAL_ID: Final = -3502
DP_350K_LAST_ACCESS_EVENT_TIME: Final = -3503
DP_350K_LAST_LOCK_RECORD: Final = -3504
DP_350K_LAST_ACK_LATENCY_MS: Final = -3505
DP_350K_LAST_GATT_WRITE_COUNT: Final = -3506
DP_350K_LAST_GATT_WRITE_BYTES: Final = -3507
DP_350K_WRITE_CHUNK_SIZE: Final = -3508
DP_350K_RECONNECT_COUNT: Final = -3509
DP_350K_CONNECTED_SINCE: Final = -3510
DP_350K_LAST_DISCONNECT_TIME: Final = -3511
DP_350K_LAST_EVENT_SEQUENCE: Final = -3512
DP_350K_EVENT_SEQUENCE_GAPS: Final = -3513
DP_350K_LAST_COMMAND: Final = -3514
DP_350K_LAST_COMMAND_RESULT: Final = -3515
DP_350K_LAST_COMMAND_DURATION_MS: Final = -3516
DP_350K_LAST_ACTUATION_LATENCY_MS: Final = -3517
DP_350K_UNKNOWN_DP_COUNT: Final = -3518
DP_350K_EVENT_TIMELINE_COUNT: Final = -3519
DP_350K_LAST_DEVICE_REPORT_TIME: Final = -3520
DP_350K_STATE_AGE_SECONDS: Final = -3521
DP_350K_SESSION_STATE: Final = -3522
DP_350K_LAST_RX_AGE_SECONDS: Final = -3523
DP_350K_COMMAND_COUNTERS: Final = -3524
DP_350K_DEVICE_VERSION: Final = -3525
DP_350K_HARDWARE_VERSION: Final = -3526
DP_350K_PROTOCOL_VERSION: Final = -3527

EVENT_350K: Final = DOMAIN + "_350k_event"
