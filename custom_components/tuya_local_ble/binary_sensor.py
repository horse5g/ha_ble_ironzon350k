"""The Tuya BLE integration."""
from __future__ import annotations

from dataclasses import dataclass

import time
from .tuya_ble import TuyaBLEDataPointType

import logging
from typing import Callable

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    DOMAIN,
)
from .devices import TuyaBLEData, TuyaBLEEntity, TuyaBLEProductInfo
from .tuya_ble import TuyaBLEDataPointType, TuyaBLEDevice

_LOGGER = logging.getLogger(__name__)

SIGNAL_STRENGTH_DP_ID = -1
LOCK_STATE_STALE_SECONDS = 90


TuyaBLEBinarySensorIsAvailable = (
    Callable[["TuyaBLEBinarySensor", TuyaBLEProductInfo], bool] | None
)

@dataclass
class TuyaBLEBinarySensorMapping:
    dp_id: int
    description: BinarySensorEntityDescription
    force_add: bool = True
    dp_type: TuyaBLEDataPointType | None = None
    getter: Callable[[TuyaBLEBinarySensor], None] | None = None
    #coefficient: float = 1.0
    #icons: list[str] | None = None
    is_available: TuyaBLEBinarySensorIsAvailable = None

@dataclass
class TuyaBLECategoryBinarySensorMapping:
    products: dict[str, list[TuyaBLEBinarySensorMapping]] | None = None
    mapping: list[TuyaBLEBinarySensorMapping] | None = None

mapping: dict[str, TuyaBLECategoryBinarySensorMapping] = {
    "jtmspro": TuyaBLECategoryBinarySensorMapping(
        products={
            "z1dfsaya": [
                TuyaBLEBinarySensorMapping(
                    dp_id=47,
                    description=BinarySensorEntityDescription(
                        key="lock_state",
                        device_class=BinarySensorDeviceClass.LOCK,
                    ),
                ),
                TuyaBLEBinarySensorMapping(
                    dp_id=33,
                    description=BinarySensorEntityDescription(
                        key="passage_mode",
                        icon="mdi:door-open",
                    ),
                ),
                TuyaBLEBinarySensorMapping(
                    dp_id=32,
                    description=BinarySensorEntityDescription(
                        key="secure_lock",
                        icon="mdi:shield-lock",
                    ),
                ),
            ],
        },
    ),
    "wk": TuyaBLECategoryBinarySensorMapping(
        products={
            "drlajpqc": [  # Thermostatic Radiator Valve
                TuyaBLEBinarySensorMapping(
                    dp_id=105,
                    description=BinarySensorEntityDescription(
                        key="battery",
                        #icon="mdi:battery-alert",
                        device_class=BinarySensorDeviceClass.BATTERY,
                        entity_category=EntityCategory.DIAGNOSTIC,
                    ),
                ),
            ],
        },
    ),   
}


def get_mapping_by_device(device: TuyaBLEDevice) -> list[TuyaBLEBinarySensorMapping]:
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


class TuyaBLEBinarySensor(TuyaBLEEntity, BinarySensorEntity):
    """Representation of a Tuya BLE binary sensor."""

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: DataUpdateCoordinator,
        device: TuyaBLEDevice,
        product: TuyaBLEProductInfo,
        mapping: TuyaBLEBinarySensorMapping,
    ) -> None:
        super().__init__(hass, coordinator, device, product, mapping.description)
        self._mapping = mapping
        self._stale_timer = None
        self._stale_timer_timestamp: float | None = None

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if self._mapping.getter is not None:
            self._mapping.getter(self)
        else:
            datapoint = self._device.datapoints[self._mapping.dp_id]
            if datapoint:
                self._attr_is_on = bool(datapoint.value)

                if (
                    self._device.product_id == "z1dfsaya"
                    and self._mapping.dp_id == 47
                ):
                    self._schedule_lock_state_stale(datapoint)
        self.async_write_ha_state()

    def _schedule_lock_state_stale(self, datapoint) -> None:
        """Schedule the transition to unavailable for a physical DP47 report."""
        if self._stale_timer_timestamp == datapoint.timestamp:
            return
        if self._stale_timer is not None:
            self._stale_timer()
            self._stale_timer = None
        self._stale_timer_timestamp = datapoint.timestamp
        age = max(0.0, time.time() - datapoint.timestamp)
        delay = max(0.1, LOCK_STATE_STALE_SECONDS - age)
        self._stale_timer = async_call_later(
            self._hass, delay, self._mark_lock_state_stale
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if self._device.product_id == "z1dfsaya" and self._mapping.dp_id == 47:
            datapoint = self._device.datapoints[47]
            if datapoint is not None:
                self._schedule_lock_state_stale(datapoint)

    @callback
    def _mark_lock_state_stale(self, _now) -> None:
        """Refresh HA so DP47 transitions to unavailable after its TTL."""
        self._stale_timer = None
        self.async_write_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        if self._stale_timer is not None:
            self._stale_timer()
            self._stale_timer = None
        await super().async_will_remove_from_hass()

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        if self._device.product_id == "z1dfsaya":
            datapoint = self._device.datapoints[self._mapping.dp_id]
            if datapoint is None:
                return False

            if self._mapping.dp_id == 47:
                # Physical lock state must be recent.  Persistent configuration
                # datapoints such as DP32/DP33 may safely retain last-known state.
                return (time.time() - datapoint.timestamp) <= LOCK_STATE_STALE_SECONDS

            return True

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
    entities: list[TuyaBLEBinarySensor] = []
    for mapping in mappings:
        if mapping.force_add or data.device.datapoints.has_id(
            mapping.dp_id, mapping.dp_type
        ):
            entities.append(
                TuyaBLEBinarySensor(
                    hass,
                    data.coordinator,
                    data.device,
                    data.product,
                    mapping,
                )
            )
    async_add_entities(entities)
