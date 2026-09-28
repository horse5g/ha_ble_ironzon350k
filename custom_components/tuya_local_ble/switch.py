"""The Tuya BLE integration."""
from __future__ import annotations

from dataclasses import dataclass, field

import logging
from typing import Any, Callable

from homeassistant.components.switch import (
    SwitchEntityDescription,
    SwitchEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN
from .devices import TuyaBLEData, TuyaBLEEntity, TuyaBLEProductInfo
from .tuya_ble import TuyaBLEDataPointType, TuyaBLEDevice

_LOGGER = logging.getLogger(__name__)


TuyaBLESwitchGetter = (
    Callable[["TuyaBLESwitch", TuyaBLEProductInfo], bool | None] | None
)


TuyaBLESwitchIsAvailable = (
    Callable[["TuyaBLESwitch", TuyaBLEProductInfo], bool] | None
)


TuyaBLESwitchSetter = (
    Callable[["TuyaBLESwitch", TuyaBLEProductInfo, bool], None] | None
)


@dataclass
class TuyaBLESwitchMapping:
    dp_id: int
    description: SwitchEntityDescription
    force_add: bool = True
    dp_type: TuyaBLEDataPointType | None = None
    bitmap_mask: bytes | None = None
    is_available: TuyaBLESwitchIsAvailable = None
    getter: TuyaBLESwitchGetter = None
    setter: TuyaBLESwitchSetter = None


def is_fingerbot_in_program_mode(
    self: TuyaBLESwitch, product: TuyaBLEProductInfo
) -> bool:
    result: bool = True
    if product.fingerbot:
        datapoint = self._device.datapoints[product.fingerbot.mode]
        if datapoint:
            result = datapoint.value == 2
    return result


def is_fingerbot_in_switch_mode(
    self: TuyaBLESwitch, product: TuyaBLEProductInfo
) -> bool:
    result: bool = True
    if product.fingerbot:
        datapoint = self._device.datapoints[product.fingerbot.mode]
        if datapoint:
            result = datapoint.value == 1
    return result


def get_fingerbot_program_repeat_forever(
    self: TuyaBLESwitch, product: TuyaBLEProductInfo
) -> bool | None:
    result: bool | None = None
    if product.fingerbot and product.fingerbot.program:
        datapoint = self._device.datapoints[product.fingerbot.program]
        if datapoint and type(datapoint.value) is bytes:
            repeat_count = int.from_bytes(datapoint.value[0:2], "big")
            result = repeat_count == 0xFFFF
    return result


def set_fingerbot_program_repeat_forever(
    self: TuyaBLESwitch, product: TuyaBLEProductInfo, value: bool
) -> None:
    if product.fingerbot and product.fingerbot.program:
        datapoint = self._device.datapoints[product.fingerbot.program]
        if datapoint and type(datapoint.value) is bytes:
            new_value = (
                int.to_bytes(0xFFFF if value else 1, 2, "big") + 
                datapoint.value[2:]
            )
            self._hass.create_task(datapoint.set_value(new_value))


@dataclass
class TuyaBLEFingerbotSwitchMapping(TuyaBLESwitchMapping):
    description: SwitchEntityDescription = field(
        default_factory=lambda: SwitchEntityDescription(
            key="switch",
        )
    )
    is_available: TuyaBLESwitchIsAvailable = is_fingerbot_in_switch_mode


@dataclass
class TuyaBLEReversePositionsMapping(TuyaBLESwitchMapping):
    description: SwitchEntityDescription = field(
        default_factory=lambda: SwitchEntityDescription(
            key="reverse_positions",
            icon="mdi:arrow-up-down-bold",
            entity_category=EntityCategory.CONFIG,
        )
    )
    is_available: TuyaBLESwitchIsAvailable = is_fingerbot_in_switch_mode


@dataclass
class TuyaBLECategorySwitchMapping:
    products: dict[str, list[TuyaBLESwitchMapping]] | None = None
    mapping: list[TuyaBLESwitchMapping] | None = None


mapping: dict[str, TuyaBLECategorySwitchMapping] = {
    "co2bj": TuyaBLECategorySwitchMapping(
        products={
            "59s19z5m": [  # CO2 Detector
                TuyaBLESwitchMapping(
                    dp_id=11,
                    description=SwitchEntityDescription(
                        key="carbon_dioxide_severely_exceed_alarm",
                        icon="mdi:molecule-co2",
                        entity_category=EntityCategory.CONFIG,
                        entity_registry_enabled_default=False,
                    ),
                    bitmap_mask=b"\x01",
                ),
                TuyaBLESwitchMapping(
                    dp_id=11,
                    description=SwitchEntityDescription(
                        key="low_battery_alarm",
                        icon="mdi:battery-alert",
                        entity_category=EntityCategory.CONFIG,
                        entity_registry_enabled_default=False,
                    ),
                    bitmap_mask=b"\x02",
                ),
                TuyaBLESwitchMapping(
                    dp_id=13,
                    description=SwitchEntityDescription(
                        key="carbon_dioxide_alarm_switch",
                        icon="mdi:molecule-co2",
                        entity_category=EntityCategory.CONFIG,
                    ),
                ),
            ],
        },
    ),
    "jtmspro": TuyaBLECategorySwitchMapping(
        products={
            "ikphogdj": [  # HL Knob-2, TuyaOS FD50 lock
                TuyaBLESwitchMapping(
                    dp_id=33,
                    description=SwitchEntityDescription(
                        key="automatic_lock",
                        icon="mdi:lock-clock",
                        entity_category=EntityCategory.CONFIG,
                    ),
                ),
            ],
            "z1dfsaya": [  # YD_350K, TuyaOS FD50 lock
                TuyaBLESwitchMapping(
                    dp_id=33,
                    description=SwitchEntityDescription(
                        key="passage_mode_control",
                        icon="mdi:door-open",
                        entity_category=EntityCategory.CONFIG,
                    ),
                ),
                TuyaBLESwitchMapping(
                    dp_id=79,
                    description=SwitchEntityDescription(
                        key="secure_lock_control",
                        icon="mdi:shield-lock",
                        entity_category=EntityCategory.CONFIG,
                    ),
                ),
            ],
        },
    ),
    "ms": TuyaBLECategorySwitchMapping(
        products={
            **dict.fromkeys(
                ["ludzroix", "isk2p555"], # Smart Lock
                [
                    TuyaBLESwitchMapping(
                        dp_id=47,
                        description=SwitchEntityDescription(
                            key="lock_motor_state",
                        ),
                    ),
                ]
            ),
        }
    ),
    "szjqr": TuyaBLECategorySwitchMapping(
        products={
            **dict.fromkeys(
                ["3yqdo5yt", "xhf790if"],  # CubeTouch 1s and II
                [
                    TuyaBLEFingerbotSwitchMapping(dp_id=1),
                    TuyaBLEReversePositionsMapping(dp_id=4),
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
                    TuyaBLEFingerbotSwitchMapping(dp_id=2),
                    TuyaBLEReversePositionsMapping(dp_id=11),
                    TuyaBLESwitchMapping(
                        dp_id=17,
                        description=SwitchEntityDescription(
                            key="manual_control",
                            icon="mdi:gesture-tap-box",
                            entity_category=EntityCategory.CONFIG,
                        ),
                    ),
                    TuyaBLESwitchMapping(
                        dp_id=2,
                        description=SwitchEntityDescription(
                            key="program",
                            icon="mdi:repeat",
                        ),
                        is_available=is_fingerbot_in_program_mode,
                    ),
                    TuyaBLESwitchMapping(
                        dp_id=121,
                        description=SwitchEntityDescription(
                            key="program_repeat_forever",
                            icon="mdi:repeat",
                            entity_category=EntityCategory.CONFIG,
                        ),
                        getter=get_fingerbot_program_repeat_forever,
                        is_available=is_fingerbot_in_program_mode,
                        setter=set_fingerbot_program_repeat_forever,
                    ),
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
                    TuyaBLEFingerbotSwitchMapping(dp_id=2),
                    TuyaBLEReversePositionsMapping(dp_id=11),
                ],
            ),
        },
    ),
    "wk": TuyaBLECategorySwitchMapping(
        products={
            **dict.fromkeys(
                [
                    "drlajpqc",
                    "nhj2j7su",
                ],  # Thermostatic Radiator Valve
                [
                    TuyaBLESwitchMapping(
                        dp_id=8,
                        description=SwitchEntityDescription(
                            key="window_check",
                            icon="mdi:window-closed",
                            entity_category=EntityCategory.CONFIG,
                        ),
                    ),
                    TuyaBLESwitchMapping(
                        dp_id=10,
                        description=SwitchEntityDescription(
                            key="antifreeze",
                            icon="mdi:snowflake-off",
                            entity_category=EntityCategory.CONFIG,
                        ),
                    ),
                    TuyaBLESwitchMapping(
                        dp_id=40,
                        description=SwitchEntityDescription(
                            key="child_lock",
                            icon="mdi:account-lock",
                            entity_category=EntityCategory.CONFIG,
                        ),
                    ),
                    TuyaBLESwitchMapping(
                        dp_id=130,
                        description=SwitchEntityDescription(
                            key="water_scale_proof",
                            icon="mdi:water-check",
                            entity_category=EntityCategory.CONFIG,
                        ),
                    ),
                    TuyaBLESwitchMapping(
                        dp_id=107,
                        description=SwitchEntityDescription(
                            key="programming_mode",
                            icon="mdi:calendar-edit",
                            entity_category=EntityCategory.CONFIG,
                        ),
                    ),
                    TuyaBLESwitchMapping(
                        dp_id=108,
                        description=SwitchEntityDescription(
                            key="programming_switch",
                            icon="mdi:calendar-clock",
                            entity_category=EntityCategory.CONFIG,
                        ),
                    ),
                ],
            ),
        },
    ),
    "wsdcg": TuyaBLECategorySwitchMapping(
        products={
            "ojzlzzsw": [  # Soil moisture sensor
                TuyaBLESwitchMapping(
                    dp_id=21,
                    description=SwitchEntityDescription(
                        key="switch",
                        icon="mdi:thermometer",
                        entity_category=EntityCategory.CONFIG,
                        entity_registry_enabled_default=False,
                    ),
                ),
            ],
            "jm6iasmb": [  # Temperature Humidity Sensor
                TuyaBLESwitchMapping(
                    dp_id=21,
                    description=SwitchEntityDescription(
                        key="switch",
                        icon="mdi:thermometer",
                        entity_category=EntityCategory.CONFIG,
                        entity_registry_enabled_default=False,
                    ),
                ),
            ],
        },
    ),
    "ggq": TuyaBLECategorySwitchMapping(
        products={
            "6pahkcau": [  # Irrigation computer
                TuyaBLESwitchMapping(
                    dp_id=1,
                    description=SwitchEntityDescription(
                        key="water_valve",
                        entity_registry_enabled_default=True,
                    ),
                ),
            ],
        },
    ),
}


def get_mapping_by_device(device: TuyaBLEDevice) -> list[TuyaBLECategorySwitchMapping]:
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


class TuyaBLESwitch(TuyaBLEEntity, SwitchEntity):
    """Representation of a Tuya BLE Switch."""

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: DataUpdateCoordinator,
        device: TuyaBLEDevice,
        product: TuyaBLEProductInfo,
        mapping: TuyaBLESwitchMapping,
    ) -> None:
        super().__init__(hass, coordinator, device, product, mapping.description)
        self._mapping = mapping

    @property
    def is_on(self) -> bool | None:
        """Return true if switch is on."""

        if self._mapping.getter:
            return self._mapping.getter(self, self._product)

        datapoint = self._device.datapoints[self._mapping.dp_id]
        if datapoint:
            if (
                datapoint.type
                in [TuyaBLEDataPointType.DT_RAW, TuyaBLEDataPointType.DT_BITMAP]
                and self._mapping.bitmap_mask
            ):
                bitmap_value = bytes(datapoint.value)
                bitmap_mask = self._mapping.bitmap_mask
                for v, m in zip(bitmap_value, bitmap_mask, strict=True):
                    if (v & m) != 0:
                        return True
                return False
            return bool(datapoint.value)
        return None

    def _is_350k_control(self) -> bool:
        return (
            self._device.product_id == "z1dfsaya"
            and self._mapping.dp_id in (33, 79)
        )

    async def _async_set_350k_control(self, value: bool) -> None:
        """Write a 350K control without optimistic local state changes."""
        try:
            sent = await self._device.set_350k_bool_datapoint(
                self._mapping.dp_id, value
            )
            if not sent:
                _LOGGER.warning(
                    "%s: 350K control DP%s=%s was not applied",
                    self._device.address,
                    self._mapping.dp_id,
                    value,
                )
        except Exception:
            # Keep HA task errors contained here.  The device method already
            # logs the detailed failure, but this also protects callers if a
            # future protocol change raises before entering that method.
            _LOGGER.exception(
                "%s: Failed to apply 350K control DP%s=%s",
                self._device.address,
                self._mapping.dp_id,
                value,
            )
        finally:
            # is_on continues to reflect the last value reported by the lock.
            self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        if self._is_350k_control():
            await self._async_set_350k_control(True)
            return
        self.turn_on(**kwargs)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        if self._is_350k_control():
            await self._async_set_350k_control(False)
            return
        self.turn_off(**kwargs)

    def turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on (legacy synchronous entity path)."""
        if self._is_350k_control():
            # Normally Home Assistant uses async_turn_on above.  Keep this
            # fallback safe as well: no optimistic cache mutation, and the
            # device-level fail-fast lock prevents command queue buildup.
            self._hass.create_task(self._async_set_350k_control(True))
            return

        if self._mapping.setter:
            return self._mapping.setter(self, self._product, True)

        new_value: bool | bytes
        if self._mapping.bitmap_mask:
            datapoint = self._device.datapoints.get_or_create(
                self._mapping.dp_id,
                TuyaBLEDataPointType.DT_BITMAP,
                self._mapping.bitmap_mask,
            )
            bitmap_mask = self._mapping.bitmap_mask
            bitmap_value = bytes(datapoint.value)
            new_value = bytes(
                v | m for (v, m) in zip(bitmap_value, bitmap_mask, strict=True)
            )
        else:
            datapoint = self._device.datapoints.get_or_create(
                self._mapping.dp_id,
                TuyaBLEDataPointType.DT_BOOL,
                True,
            )
            new_value = True
        if datapoint:
            self._hass.create_task(datapoint.set_value(new_value))
            if self._device.product_id == "ikphogdj" and self._mapping.dp_id == 33:
                self._hass.create_task(self._device.linger_connected(30))

    def turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off (legacy synchronous entity path)."""
        if self._is_350k_control():
            self._hass.create_task(self._async_set_350k_control(False))
            return

        if self._mapping.setter:
            return self._mapping.setter(self, self._product, False)

        new_value: bool | bytes
        if self._mapping.bitmap_mask:
            datapoint = self._device.datapoints.get_or_create(
                self._mapping.dp_id,
                TuyaBLEDataPointType.DT_BITMAP,
                self._mapping.bitmap_mask,
            )
            bitmap_mask = self._mapping.bitmap_mask
            bitmap_value = bytes(datapoint.value)
            new_value = bytes(
                v & ~m for (v, m) in zip(bitmap_value, bitmap_mask, strict=True)
            )
        else:
            datapoint = self._device.datapoints.get_or_create(
                self._mapping.dp_id,
                TuyaBLEDataPointType.DT_BOOL,
                False,
            )
            new_value = False
        if datapoint:
            self._hass.create_task(datapoint.set_value(new_value))
            if self._device.product_id == "ikphogdj" and self._mapping.dp_id == 33:
                self._hass.create_task(self._device.linger_connected(30))

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        result = super().available
        if result and self._mapping.is_available:
            result = self._mapping.is_available(self, self._product)
        return result



class TuyaBLEVerboseLoggingSwitch(TuyaBLEEntity, SwitchEntity, RestoreEntity):
    """Local-only switch controlling extra 350K protocol diagnostics."""

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: DataUpdateCoordinator,
        device: TuyaBLEDevice,
        product: TuyaBLEProductInfo,
    ) -> None:
        super().__init__(
            hass,
            coordinator,
            device,
            product,
            SwitchEntityDescription(
                key="verbose_logging",
                icon="mdi:bug-outline",
                entity_category=EntityCategory.CONFIG,
            ),
        )

    @property
    def is_on(self) -> bool:
        return self._device.verbose_logging

    @property
    def available(self) -> bool:
        # This is a local integration setting, so it remains usable even when
        # the battery lock is asleep or temporarily unreachable.
        return True

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None:
            self._device.set_verbose_logging(last_state.state == STATE_ON)

    async def async_turn_on(self, **kwargs: Any) -> None:
        self._device.set_verbose_logging(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._device.set_verbose_logging(False)
        self.async_write_ha_state()


class TuyaBLEKeepAliveSwitch(TuyaBLEEntity, SwitchEntity, RestoreEntity):
    """Local-only switch keeping the YD_350K authenticated BLE session warm."""

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: DataUpdateCoordinator,
        device: TuyaBLEDevice,
        product: TuyaBLEProductInfo,
    ) -> None:
        super().__init__(
            hass,
            coordinator,
            device,
            product,
            SwitchEntityDescription(
                key="keep_ble_connection_alive",
                icon="mdi:bluetooth-connect",
                entity_category=EntityCategory.CONFIG,
            ),
        )

    @property
    def is_on(self) -> bool:
        return self._device.keepalive_enabled

    @property
    def available(self) -> bool:
        # Local integration setting; it can be toggled even while the lock is
        # temporarily unreachable. The device task only acts on an existing
        # authenticated connection and never forces a new connection itself.
        return True

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None:
            self._device.set_keepalive_enabled(last_state.state == STATE_ON)

    async def async_turn_on(self, **kwargs: Any) -> None:
        self._device.set_keepalive_enabled(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._device.set_keepalive_enabled(False)
        self.async_write_ha_state()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Tuya BLE sensors."""
    data: TuyaBLEData = hass.data[DOMAIN][entry.entry_id]
    mappings = get_mapping_by_device(data.device)
    entities: list[SwitchEntity] = []
    if data.device.product_id == "z1dfsaya":
        entities.extend(
            [
                TuyaBLEVerboseLoggingSwitch(
                    hass,
                    data.coordinator,
                    data.device,
                    data.product,
                ),
                TuyaBLEKeepAliveSwitch(
                    hass,
                    data.coordinator,
                    data.device,
                    data.product,
                ),
            ]
        )

    for mapping in mappings:
        if mapping.force_add or data.device.datapoints.has_id(
            mapping.dp_id, mapping.dp_type
        ):
            entities.append(
                TuyaBLESwitch(
                    hass,
                    data.coordinator,
                    data.device,
                    data.product,
                    mapping,
                )
            )
    async_add_entities(entities)
