"""The Tuya BLE integration."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

import logging
from typing import Callable

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    #TEMP_CELSIUS,
    #UnitOfTemperature.CELSIUS,
    #VOLUME_MILLILITERS,
    #UnitOfVolume.MILLILITERS,
    UnitOfVolume,
    UnitOfTemperature,
    UnitOfTime,
    UnitOfElectricPotential,
    UnitOfRatio,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    BATTERY_STATE_HIGH,
    BATTERY_STATE_LOW,
    BATTERY_STATE_NORMAL,
    BATTERY_CHARGED,
    BATTERY_CHARGING,
    BATTERY_NOT_CHARGING,
    CO2_LEVEL_ALARM,
    CO2_LEVEL_NORMAL,
    DOMAIN,
    DP_350K_LAST_ACCESS_EVENT,
    DP_350K_LAST_ACCESS_EVENT_TIME,
    DP_350K_LAST_CREDENTIAL_ID,
    DP_350K_LAST_LOCK_RECORD,
    DP_350K_LAST_ACK_LATENCY_MS,
    DP_350K_LAST_GATT_WRITE_COUNT,
    DP_350K_LAST_GATT_WRITE_BYTES,
    DP_350K_WRITE_CHUNK_SIZE,
    DP_350K_RECONNECT_COUNT,
    DP_350K_CONNECTED_SINCE,
    DP_350K_LAST_DISCONNECT_TIME,
    DP_350K_LAST_EVENT_SEQUENCE,
    DP_350K_EVENT_SEQUENCE_GAPS,
    DP_350K_LAST_COMMAND,
    DP_350K_LAST_COMMAND_RESULT,
    DP_350K_LAST_COMMAND_DURATION_MS,
    DP_350K_LAST_ACTUATION_LATENCY_MS,
    DP_350K_UNKNOWN_DP_COUNT,
    DP_350K_EVENT_TIMELINE_COUNT,
    DP_350K_LAST_DEVICE_REPORT_TIME,
    DP_350K_STATE_AGE_SECONDS,
    DP_350K_SESSION_STATE,
    DP_350K_LAST_RX_AGE_SECONDS,
    DP_350K_COMMAND_COUNTERS,
    DP_350K_DEVICE_VERSION,
    DP_350K_HARDWARE_VERSION,
    DP_350K_PROTOCOL_VERSION,
)
from .devices import TuyaBLEData, TuyaBLEEntity, TuyaBLEProductInfo
from .tuya_ble import TuyaBLEDataPointType, TuyaBLEDevice

_LOGGER = logging.getLogger(__name__)

SIGNAL_STRENGTH_DP_ID = -1


TuyaBLESensorIsAvailable = Callable[["TuyaBLESensor", TuyaBLEProductInfo], bool] | None


@dataclass
class TuyaBLESensorMapping:
    dp_id: int
    description: SensorEntityDescription
    force_add: bool = True
    dp_type: TuyaBLEDataPointType | None = None
    getter: Callable[[TuyaBLESensor], None] | None = None
    coefficient: float = 1.0
    icons: list[str] | None = None
    is_available: TuyaBLESensorIsAvailable = None


@dataclass
class TuyaBLEBatteryMapping(TuyaBLESensorMapping):
    description: SensorEntityDescription = field(
        default_factory=lambda: SensorEntityDescription(
            key="battery",
            device_class=SensorDeviceClass.BATTERY,
            native_unit_of_measurement=PERCENTAGE,
            entity_category=EntityCategory.DIAGNOSTIC,
            state_class=SensorStateClass.MEASUREMENT,
        )
    )


@dataclass
class TuyaBLETemperatureMapping(TuyaBLESensorMapping):
    description: SensorEntityDescription = field(
        default_factory=lambda: SensorEntityDescription(
            key="temperature",
            device_class=SensorDeviceClass.TEMPERATURE,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            state_class=SensorStateClass.MEASUREMENT,
        )
    )


def is_co2_alarm_enabled(self: TuyaBLESensor, product: TuyaBLEProductInfo) -> bool:
    result: bool = True
    datapoint = self._device.datapoints[13]
    if datapoint:
        result = bool(datapoint.value)
    return result


def battery_enum_getter(self: TuyaBLESensor) -> None:
    datapoint = self._device.datapoints[104]
    if datapoint:
        self._attr_native_value = datapoint.value * 20.0


def last_access_event_time_getter(self: TuyaBLESensor) -> None:
    """Expose the 350K event epoch as a Home Assistant timestamp."""
    datapoint = self._device.datapoints[DP_350K_LAST_ACCESS_EVENT_TIME]
    if datapoint:
        self._attr_native_value = datetime.fromtimestamp(
            int(datapoint.value), tz=timezone.utc
        )


def diagnostic_timestamp_getter(self: TuyaBLESensor) -> None:
    """Expose a synthetic epoch datapoint as a Home Assistant timestamp."""
    datapoint = self._device.datapoints[self._mapping.dp_id]
    if datapoint:
        self._attr_native_value = datetime.fromtimestamp(
            int(datapoint.value), tz=timezone.utc
        )


def state_age_getter(self: TuyaBLESensor) -> None:
    """Expose seconds since the last parsed device V4 report."""
    self._attr_native_value = self._device.state_age_seconds


def session_state_getter(self: TuyaBLESensor) -> None:
    self._attr_native_value = self._device.session_state


def last_rx_age_getter(self: TuyaBLESensor) -> None:
    self._attr_native_value = self._device.last_rx_age_seconds


def command_counters_getter(self: TuyaBLESensor) -> None:
    counters = self._device.command_counters
    self._attr_native_value = int(counters["total"])
    self._attr_extra_state_attributes = counters


def unknown_dp_recorder_getter(self: TuyaBLESensor) -> None:
    """Expose sanitized session-local unknown-DP metadata."""
    snapshot = self._device.unknown_dp_diagnostics
    self._attr_native_value = int(snapshot["unique_count"])
    self._attr_extra_state_attributes = {
        "overflow_count": snapshot["overflow_count"],
        "session_only": snapshot["session_only"],
        "raw_string_bitmap_contents_stored": snapshot[
            "raw_string_bitmap_contents_stored"
        ],
        "records": snapshot["records"],
    }


def event_timeline_getter(self: TuyaBLESensor) -> None:
    """Expose the bounded sanitized 350K event timeline."""
    snapshot = self._device.event_timeline_diagnostics
    self._attr_native_value = int(snapshot["count"])
    self._attr_extra_state_attributes = {
        "capacity": snapshot["capacity"],
        "session_only": snapshot["session_only"],
        "raw_string_bitmap_contents_stored": snapshot[
            "raw_string_bitmap_contents_stored"
        ],
        "credential_scalar_dps_redacted": snapshot[
            "credential_scalar_dps_redacted"
        ],
        "events": snapshot["events"],
    }


@dataclass
class TuyaBLECategorySensorMapping:
    products: dict[str, list[TuyaBLESensorMapping]] | None = None
    mapping: list[TuyaBLESensorMapping] | None = None


mapping: dict[str, TuyaBLECategorySensorMapping] = {
    "co2bj": TuyaBLECategorySensorMapping(
        products={
            "59s19z5m": [  # CO2 Detector
                TuyaBLESensorMapping(
                    dp_id=1,
                    description=SensorEntityDescription(
                        key="carbon_dioxide_alarm",
                        icon="mdi:molecule-co2",
                        device_class=SensorDeviceClass.ENUM,
                        options=[
                            CO2_LEVEL_ALARM,
                            CO2_LEVEL_NORMAL,
                        ],
                    ),
                    is_available=is_co2_alarm_enabled,
                ),
                TuyaBLESensorMapping(
                    dp_id=2,
                    description=SensorEntityDescription(
                        key="carbon_dioxide",
                        device_class=SensorDeviceClass.CO2,
                        native_unit_of_measurement=UnitOfRatio.PARTS_PER_MILLION,
                        state_class=SensorStateClass.MEASUREMENT,
                    ),
                ),
                TuyaBLEBatteryMapping(dp_id=15),
                TuyaBLETemperatureMapping(dp_id=18),
                TuyaBLESensorMapping(
                    dp_id=19,
                    description=SensorEntityDescription(
                        key="humidity",
                        device_class=SensorDeviceClass.HUMIDITY,
                        native_unit_of_measurement=PERCENTAGE,
                        state_class=SensorStateClass.MEASUREMENT,
                    ),
                ),
            ]
        }
    ),
    "ldcg": TuyaBLECategorySensorMapping(
        products={
            "poaanotz": [  # Briidea RV CO And Propane Gas Alarm
                TuyaBLESensorMapping(
                    dp_id=2,
                    description=SensorEntityDescription(
                        key="propane",
                        icon="mdi:gas-cylinder",
                        native_unit_of_measurement="%LEL",
                        state_class=SensorStateClass.MEASUREMENT,
                    ),
                ),
                TuyaBLESensorMapping(
                    dp_id=8,
                    description=SensorEntityDescription(
                        key="carbon_monoxide",
                        device_class=SensorDeviceClass.CO,
                        native_unit_of_measurement=UnitOfRatio.PARTS_PER_MILLION,
                        state_class=SensorStateClass.MEASUREMENT,
                    ),
                ),
                TuyaBLESensorMapping(
                    dp_id=4,
                    coefficient=10.0,
                    description=SensorEntityDescription(
                        key="supply_voltage",
                        device_class=SensorDeviceClass.VOLTAGE,
                        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
                        state_class=SensorStateClass.MEASUREMENT,
                        entity_category=EntityCategory.DIAGNOSTIC,
                    ),
                ),
            ]
        }
    ),
    "ms": TuyaBLECategorySensorMapping(
        products={
            **dict.fromkeys(
                ["ludzroix", "isk2p555"], # Smart Lock
                [
                    TuyaBLESensorMapping(
                        dp_id=21,
                        description=SensorEntityDescription(
                            key="alarm_lock",
                            device_class=SensorDeviceClass.ENUM,
                            options=[
                                "wrong_finger",
                                "wrong_password",
                                "low_battery",
                            ],
                        ),
                    ),
                    TuyaBLEBatteryMapping(dp_id=8),
                ],
            ),
        }
    ),
    "jtmspro": TuyaBLECategorySensorMapping(
        products={
            "z1dfsaya": [
                TuyaBLEBatteryMapping(dp_id=8),
                TuyaBLESensorMapping(
                    dp_id=DP_350K_LAST_ACCESS_EVENT,
                    description=SensorEntityDescription(
                        key="last_access_event",
                        icon="mdi:history",
                        entity_category=EntityCategory.DIAGNOSTIC,
                    ),
                ),
                TuyaBLESensorMapping(
                    dp_id=DP_350K_LAST_CREDENTIAL_ID,
                    description=SensorEntityDescription(
                        key="last_successful_credential_id",
                        icon="mdi:key-chain",
                        entity_category=EntityCategory.DIAGNOSTIC,
                    ),
                ),
                TuyaBLESensorMapping(
                    dp_id=DP_350K_LAST_ACCESS_EVENT_TIME,
                    getter=last_access_event_time_getter,
                    description=SensorEntityDescription(
                        key="last_access_event_time",
                        device_class=SensorDeviceClass.TIMESTAMP,
                        icon="mdi:clock-outline",
                        entity_category=EntityCategory.DIAGNOSTIC,
                    ),
                ),
                TuyaBLESensorMapping(
                    dp_id=DP_350K_LAST_LOCK_RECORD,
                    description=SensorEntityDescription(
                        key="last_lock_record",
                        icon="mdi:code-braces",
                        entity_category=EntityCategory.DIAGNOSTIC,
                        entity_registry_enabled_default=False,
                    ),
                ),
                TuyaBLESensorMapping(
                    dp_id=DP_350K_LAST_ACK_LATENCY_MS,
                    description=SensorEntityDescription(
                        key="last_tx_ack_latency",
                        icon="mdi:timer-outline",
                        native_unit_of_measurement="ms",
                        entity_category=EntityCategory.DIAGNOSTIC,
                        entity_registry_enabled_default=False,
                    ),
                ),
                TuyaBLESensorMapping(
                    dp_id=DP_350K_LAST_GATT_WRITE_COUNT,
                    description=SensorEntityDescription(
                        key="last_gatt_write_count",
                        icon="mdi:counter",
                        entity_category=EntityCategory.DIAGNOSTIC,
                        entity_registry_enabled_default=False,
                    ),
                ),
                TuyaBLESensorMapping(
                    dp_id=DP_350K_LAST_GATT_WRITE_BYTES,
                    description=SensorEntityDescription(
                        key="last_gatt_write_bytes",
                        icon="mdi:code-greater-than",
                        native_unit_of_measurement="B",
                        entity_category=EntityCategory.DIAGNOSTIC,
                        entity_registry_enabled_default=False,
                    ),
                ),
                TuyaBLESensorMapping(
                    dp_id=DP_350K_WRITE_CHUNK_SIZE,
                    description=SensorEntityDescription(
                        key="gatt_write_chunk_size",
                        icon="mdi:bluetooth-transfer",
                        native_unit_of_measurement="B",
                        entity_category=EntityCategory.DIAGNOSTIC,
                        entity_registry_enabled_default=False,
                    ),
                ),
                TuyaBLESensorMapping(
                    dp_id=DP_350K_RECONNECT_COUNT,
                    description=SensorEntityDescription(
                        key="ble_reconnect_count",
                        icon="mdi:connection",
                        entity_category=EntityCategory.DIAGNOSTIC,
                        entity_registry_enabled_default=False,
                    ),
                ),
                TuyaBLESensorMapping(
                    dp_id=DP_350K_CONNECTED_SINCE,
                    getter=diagnostic_timestamp_getter,
                    description=SensorEntityDescription(
                        key="ble_connected_since",
                        device_class=SensorDeviceClass.TIMESTAMP,
                        icon="mdi:bluetooth-connect",
                        entity_category=EntityCategory.DIAGNOSTIC,
                        entity_registry_enabled_default=False,
                    ),
                ),
                TuyaBLESensorMapping(
                    dp_id=DP_350K_LAST_DISCONNECT_TIME,
                    getter=diagnostic_timestamp_getter,
                    description=SensorEntityDescription(
                        key="last_ble_disconnect",
                        device_class=SensorDeviceClass.TIMESTAMP,
                        icon="mdi:bluetooth-off",
                        entity_category=EntityCategory.DIAGNOSTIC,
                        entity_registry_enabled_default=False,
                    ),
                ),
                TuyaBLESensorMapping(
                    dp_id=DP_350K_LAST_EVENT_SEQUENCE,
                    description=SensorEntityDescription(
                        key="last_v4_event_sequence",
                        icon="mdi:numeric",
                        entity_category=EntityCategory.DIAGNOSTIC,
                        entity_registry_enabled_default=False,
                    ),
                ),
                TuyaBLESensorMapping(
                    dp_id=DP_350K_EVENT_SEQUENCE_GAPS,
                    description=SensorEntityDescription(
                        key="v4_sequence_gaps",
                        icon="mdi:alert-decagram-outline",
                        entity_category=EntityCategory.DIAGNOSTIC,
                        entity_registry_enabled_default=False,
                    ),
                ),
                TuyaBLESensorMapping(
                    dp_id=DP_350K_LAST_COMMAND,
                    description=SensorEntityDescription(
                        key="last_command",
                        icon="mdi:gesture-tap-button",
                        entity_category=EntityCategory.DIAGNOSTIC,
                        entity_registry_enabled_default=False,
                    ),
                ),
                TuyaBLESensorMapping(
                    dp_id=DP_350K_LAST_COMMAND_RESULT,
                    description=SensorEntityDescription(
                        key="last_command_result",
                        icon="mdi:check-network-outline",
                        entity_category=EntityCategory.DIAGNOSTIC,
                        entity_registry_enabled_default=False,
                    ),
                ),
                TuyaBLESensorMapping(
                    dp_id=DP_350K_LAST_COMMAND_DURATION_MS,
                    description=SensorEntityDescription(
                        key="last_command_duration",
                        icon="mdi:timer-sand",
                        native_unit_of_measurement="ms",
                        entity_category=EntityCategory.DIAGNOSTIC,
                        entity_registry_enabled_default=False,
                    ),
                ),
                TuyaBLESensorMapping(
                    dp_id=DP_350K_LAST_ACTUATION_LATENCY_MS,
                    description=SensorEntityDescription(
                        key="last_actuation_latency",
                        icon="mdi:lock-clock",
                        native_unit_of_measurement="ms",
                        entity_category=EntityCategory.DIAGNOSTIC,
                        entity_registry_enabled_default=False,
                    ),
                ),
                TuyaBLESensorMapping(
                    dp_id=DP_350K_UNKNOWN_DP_COUNT,
                    getter=unknown_dp_recorder_getter,
                    description=SensorEntityDescription(
                        key="unknown_dp_recorder",
                        icon="mdi:radar",
                        entity_category=EntityCategory.DIAGNOSTIC,
                        entity_registry_enabled_default=False,
                    ),
                ),
                TuyaBLESensorMapping(
                    dp_id=DP_350K_EVENT_TIMELINE_COUNT,
                    getter=event_timeline_getter,
                    description=SensorEntityDescription(
                        key="event_timeline_recorder",
                        icon="mdi:timeline-clock-outline",
                        entity_category=EntityCategory.DIAGNOSTIC,
                        entity_registry_enabled_default=False,
                    ),
                ),
                TuyaBLESensorMapping(
                    dp_id=DP_350K_LAST_DEVICE_REPORT_TIME,
                    getter=diagnostic_timestamp_getter,
                    description=SensorEntityDescription(
                        key="last_device_report",
                        device_class=SensorDeviceClass.TIMESTAMP,
                        icon="mdi:clock-check-outline",
                        entity_category=EntityCategory.DIAGNOSTIC,
                        entity_registry_enabled_default=False,
                    ),
                ),
                TuyaBLESensorMapping(
                    dp_id=DP_350K_STATE_AGE_SECONDS,
                    getter=state_age_getter,
                    description=SensorEntityDescription(
                        key="state_age",
                        icon="mdi:timer-outline",
                        native_unit_of_measurement="s",
                        entity_category=EntityCategory.DIAGNOSTIC,
                        entity_registry_enabled_default=False,
                    ),
                ),
                TuyaBLESensorMapping(
                    dp_id=DP_350K_SESSION_STATE,
                    getter=session_state_getter,
                    description=SensorEntityDescription(
                        key="session_state",
                        icon="mdi:bluetooth-connect",
                        entity_category=EntityCategory.DIAGNOSTIC,
                        entity_registry_enabled_default=False,
                    ),
                ),
                TuyaBLESensorMapping(
                    dp_id=DP_350K_LAST_RX_AGE_SECONDS,
                    getter=last_rx_age_getter,
                    description=SensorEntityDescription(
                        key="last_rx_age",
                        icon="mdi:bluetooth-audio",
                        native_unit_of_measurement="s",
                        entity_category=EntityCategory.DIAGNOSTIC,
                        entity_registry_enabled_default=False,
                    ),
                ),
                TuyaBLESensorMapping(
                    dp_id=DP_350K_COMMAND_COUNTERS,
                    getter=command_counters_getter,
                    description=SensorEntityDescription(
                        key="command_counters",
                        icon="mdi:counter",
                        entity_category=EntityCategory.DIAGNOSTIC,
                        entity_registry_enabled_default=False,
                    ),
                ),
                TuyaBLESensorMapping(
                    dp_id=DP_350K_DEVICE_VERSION,
                    description=SensorEntityDescription(
                        key="device_firmware_version",
                        icon="mdi:chip",
                        entity_category=EntityCategory.DIAGNOSTIC,
                        entity_registry_enabled_default=False,
                    ),
                ),
                TuyaBLESensorMapping(
                    dp_id=DP_350K_HARDWARE_VERSION,
                    description=SensorEntityDescription(
                        key="device_hardware_version",
                        icon="mdi:expansion-card",
                        entity_category=EntityCategory.DIAGNOSTIC,
                        entity_registry_enabled_default=False,
                    ),
                ),
                TuyaBLESensorMapping(
                    dp_id=DP_350K_PROTOCOL_VERSION,
                    description=SensorEntityDescription(
                        key="device_protocol_version",
                        icon="mdi:protocol",
                        entity_category=EntityCategory.DIAGNOSTIC,
                        entity_registry_enabled_default=False,
                    ),
                ),
            ],
            "rlyxv7pe":  # Smart Lock
            [
                TuyaBLESensorMapping(
                    dp_id=9,
                    description=SensorEntityDescription(
                        key="battery_state",
                        icon="mdi:battery",
                        device_class=SensorDeviceClass.ENUM,
                        options=[
                            BATTERY_STATE_HIGH,
                            BATTERY_STATE_NORMAL,
                            BATTERY_STATE_LOW,
                            BATTERY_STATE_LOW,
                        ],
                    ),
                    icons=[
                        "mdi:battery-check",
                        "mdi:battery-50",
                        "mdi:battery-alert",
                        "mdi:battery-alert",
                    ],
                ),
            ],
            "y2yaegze":  # CTL20H SmartLock, TuyaOS FD50
            [
                TuyaBLEBatteryMapping(
                    # DP8 is a 4-byte Tuya VALUE containing battery percentage.
                    dp_id=8,
                ),
            ],
            "hc7n0urm":  # Raykube A1 Ultra / A1 Pro Max TuyaOS FD50 lock
            [
                TuyaBLESensorMapping(
                    dp_id=9,
                    description=SensorEntityDescription(
                        key="battery_state",
                        icon="mdi:battery",
                        device_class=SensorDeviceClass.ENUM,
                        options=[
                            BATTERY_STATE_HIGH,
                            BATTERY_STATE_NORMAL,
                            BATTERY_STATE_LOW,
                            BATTERY_STATE_LOW,
                        ],
                    ),
                    icons=[
                        "mdi:battery-check",
                        "mdi:battery-50",
                        "mdi:battery-alert",
                        "mdi:battery-alert",
                    ],
                ),
            ],
            "ikphogdj":  # HL Knob-2, TuyaOS FD50 lock
            [
                TuyaBLEBatteryMapping(
                    # dp 8 (residual_electricity), confirmed via HCI capture:
                    # spontaneous report on connect, value matched the app's
                    # displayed battery % exactly.
                    dp_id=8,
                ),
                TuyaBLESensorMapping(
                    # dp 9 (battery_state enum) - present in cloud schema but
                    # never observed being reported over BLE; kept in case it
                    # shows up. dp 8 above is the confirmed-working one.
                    dp_id=9,
                    description=SensorEntityDescription(
                        key="battery_state",
                        icon="mdi:battery",
                        device_class=SensorDeviceClass.ENUM,
                        options=[
                            BATTERY_STATE_HIGH,
                            BATTERY_STATE_NORMAL,
                            BATTERY_STATE_LOW,
                            BATTERY_STATE_LOW,
                        ],
                    ),
                    icons=[
                        "mdi:battery-check",
                        "mdi:battery-50",
                        "mdi:battery-alert",
                        "mdi:battery-alert",
                    ],
                ),
                TuyaBLESensorMapping(
                    # dp 12 (unlock_fingerprint). Confirmed via two HCI
                    # captures with different fingers. This is the
                    # fingerprint slot index used to unlockNo name mapping is 
                    # availablelocally (that only exists in the app/cloud)
                    dp_id=12,
                    description=SensorEntityDescription(
                        key="last_fingerprint_unlock_slot",
                        icon="mdi:fingerprint",
                        entity_category=EntityCategory.DIAGNOSTIC,
                    ),
                ),
            ],
        }
    ),      
    "szjqr": TuyaBLECategorySensorMapping(
        products={
            **dict.fromkeys(
                ["3yqdo5yt", "xhf790if"],  # CubeTouch 1s and II
                [
                    TuyaBLESensorMapping(
                        dp_id=7,
                        description=SensorEntityDescription(
                            key="battery_charging",
                            device_class=SensorDeviceClass.ENUM,
                            entity_category=EntityCategory.DIAGNOSTIC,
                            options=[
                                BATTERY_NOT_CHARGING,
                                BATTERY_CHARGING,
                                BATTERY_CHARGED,
                            ],
                        ),
                        icons=[
                            "mdi:battery",
                            "mdi:power-plug-battery",
                            "mdi:battery-check",
                        ],
                    ),
                    TuyaBLEBatteryMapping(dp_id=8),
                ],
            ),
            **dict.fromkeys(
                [
                    "blliqpsj",
                    "ndvkgsrm",
                    "yiihr7zh", 
                    "neq16kgd"
                ],  # Fingerbot Plus
                [
                    TuyaBLEBatteryMapping(dp_id=12),
                ],
            ),
            **dict.fromkeys(
                [
                    "ltak7e1p",
                    "y6kttvd6",
                    "yrnk7mnn",
                    "nvr2rocq",
                    "bnt7wajf",
                    "rvdceqjh",
                    "5xhbk964",
                ],  # Fingerbot
                [
                    TuyaBLEBatteryMapping(dp_id=12),
                ],
            ),
        },
    ),
    "wsdcg": TuyaBLECategorySensorMapping(
        products={
            "ojzlzzsw": [  # Soil moisture sensor
                TuyaBLETemperatureMapping(
                    dp_id=1,
                    coefficient=10.0,
                ),
                TuyaBLESensorMapping(
                    dp_id=2,
                    description=SensorEntityDescription(
                        key="moisture",
                        device_class=SensorDeviceClass.MOISTURE,
                        native_unit_of_measurement=PERCENTAGE,
                        state_class=SensorStateClass.MEASUREMENT,
                    ),
                ),
                TuyaBLESensorMapping(
                    dp_id=3,
                    description=SensorEntityDescription(
                        key="battery_state",
                        icon="mdi:battery",
                        device_class=SensorDeviceClass.ENUM,
                        entity_category=EntityCategory.DIAGNOSTIC,
                        options=[
                            BATTERY_STATE_LOW,
                            BATTERY_STATE_NORMAL,
                            BATTERY_STATE_HIGH,
                        ],
                    ),
                    icons=[
                        "mdi:battery-alert",
                        "mdi:battery-50",
                        "mdi:battery-check",
                    ],
                ),
                TuyaBLEBatteryMapping(dp_id=4),
            ],
            "jm6iasmb": [  # Temperature Humidity Sensor
                TuyaBLETemperatureMapping(
                    dp_id=1,
                    coefficient=10.0,
                ),
                TuyaBLESensorMapping(
                    dp_id=2,
                    description=SensorEntityDescription(
                        key="humidity",
                        device_class=SensorDeviceClass.HUMIDITY,
                        native_unit_of_measurement=PERCENTAGE,
                        state_class=SensorStateClass.MEASUREMENT,
                    ),
                ),
                TuyaBLESensorMapping(
                    dp_id=3,
                    description=SensorEntityDescription(
                        key="battery_state",
                        icon="mdi:battery",
                        device_class=SensorDeviceClass.ENUM,
                        entity_category=EntityCategory.DIAGNOSTIC,
                        options=[
                            BATTERY_STATE_LOW,
                            BATTERY_STATE_NORMAL,
                            BATTERY_STATE_HIGH,
                        ],
                    ),
                    icons=[
                        "mdi:battery-alert",
                        "mdi:battery-50",
                        "mdi:battery-check",
                    ],
                ),
                TuyaBLEBatteryMapping(dp_id=4),
            ],
        },
    ),
    "znhsb": TuyaBLECategorySensorMapping(
        products={
            "cdlandip":  # Smart water bottle
            [
                TuyaBLETemperatureMapping(
                    dp_id=101,
                ),
                TuyaBLESensorMapping(
                    dp_id=102,
                    description=SensorEntityDescription(
                        key="water_intake",
                        device_class=SensorDeviceClass.WATER,
                        native_unit_of_measurement=UnitOfVolume.MILLILITERS,
                        state_class=SensorStateClass.MEASUREMENT,
                    ),
                ),
                TuyaBLESensorMapping(
                    dp_id=104,
                    description=SensorEntityDescription(
                        key="battery",
                        device_class=SensorDeviceClass.BATTERY,
                        native_unit_of_measurement=PERCENTAGE,
                        entity_category=EntityCategory.DIAGNOSTIC,
                        state_class=SensorStateClass.MEASUREMENT,
                    ),
                    getter=battery_enum_getter,
                ),
            ],
        },
    ),
    "ggq": TuyaBLECategorySensorMapping(
        products={
            "6pahkcau": [  # Irrigation computer
                TuyaBLEBatteryMapping(dp_id=11),
                TuyaBLESensorMapping(
                    dp_id=6,
                    description=SensorEntityDescription(
                        key="time_left",
                        device_class=SensorDeviceClass.DURATION,
                        native_unit_of_measurement=UnitOfTime.MINUTES,
                        state_class=SensorStateClass.MEASUREMENT,
                    ),
                ),
            ],
        },
    ),
}


def rssi_getter(sensor: TuyaBLESensor) -> None:
    sensor._attr_native_value = sensor._device.rssi


rssi_mapping = TuyaBLESensorMapping(
    dp_id=SIGNAL_STRENGTH_DP_ID,
    description=SensorEntityDescription(
        key="signal_strength",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    getter=rssi_getter,
)


def get_mapping_by_device(device: TuyaBLEDevice) -> list[TuyaBLESensorMapping]:
    category = mapping.get(device.category)
    if category is not None and category.products is not None:
        product_mapping = category.products.get(device.product_id)
        if product_mapping is not None:
            return product_mapping
        if category.mapping is not None:
            return category.mapping
        else:
            return []
    else:
        return []


class TuyaBLESensor(TuyaBLEEntity, SensorEntity):
    """Representation of a Tuya BLE sensor."""

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: DataUpdateCoordinator,
        device: TuyaBLEDevice,
        product: TuyaBLEProductInfo,
        mapping: TuyaBLESensorMapping,
    ) -> None:
        super().__init__(hass, coordinator, device, product, mapping.description)
        self._mapping = mapping

    @property
    def should_poll(self) -> bool:
        return self._mapping.dp_id in (
            DP_350K_STATE_AGE_SECONDS,
            DP_350K_LAST_RX_AGE_SECONDS,
        )

    async def async_update(self) -> None:
        if self._mapping.getter is not None:
            self._mapping.getter(self)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if self._mapping.getter is not None:
            self._mapping.getter(self)
        else:
            datapoint = self._device.datapoints[self._mapping.dp_id]
            if datapoint:
                if datapoint.type == TuyaBLEDataPointType.DT_ENUM:
                    if self.entity_description.options is not None:
                        if datapoint.value >= 0 and datapoint.value < len(
                            self.entity_description.options
                        ):
                            self._attr_native_value = self.entity_description.options[
                                datapoint.value
                            ]
                        else:
                            self._attr_native_value = datapoint.value
                    if self._mapping.icons is not None:
                        if datapoint.value >= 0 and datapoint.value < len(
                            self._mapping.icons
                        ):
                            self._attr_icon = self._mapping.icons[datapoint.value]
                elif datapoint.type == TuyaBLEDataPointType.DT_VALUE:
                    self._attr_native_value = (
                        datapoint.value / self._mapping.coefficient
                    )
                else:
                    self._attr_native_value = datapoint.value
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        if (
            self._device.product_id == "z1dfsaya"
            and self._mapping.dp_id != SIGNAL_STRENGTH_DP_ID
        ):
            # The lock deliberately drops its BLE connection between activity.
            # Retain the most recently reported state instead of making the HA
            # entity unavailable just because the GATT session is asleep.
            return self._device.datapoints[self._mapping.dp_id] is not None

        result = super().available
        if result and self._mapping.is_available:
            result = self._mapping.is_available(self, self._product)
        return result


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Tuya BLE sensors."""
    data: TuyaBLEData = hass.data[DOMAIN][entry.entry_id]
    mappings = get_mapping_by_device(data.device)
    entities: list[TuyaBLESensor] = [
        TuyaBLESensor(
            hass,
            data.coordinator,
            data.device,
            data.product,
            rssi_mapping,
        )
    ]
    for mapping in mappings:
        if mapping.force_add or data.device.datapoints.has_id(
            mapping.dp_id, mapping.dp_type
        ):
            entities.append(
                TuyaBLESensor(
                    hass,
                    data.coordinator,
                    data.device,
                    data.product,
                    mapping,
                )
            )
    async_add_entities(entities)
