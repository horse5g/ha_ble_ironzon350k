"""The Tuya BLE integration."""
from __future__ import annotations

from dataclasses import dataclass
import logging
import time
from typing import Callable

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    DP_350K_LOCK_STATE,
    DP_350K_PASSAGE_MODE,
    DP_350K_SECURE_STATE,
    PRODUCT_ID_350K,
)
from .devices import TuyaBLEConfigEntry, TuyaBLEEntity, TuyaBLEProductInfo
from .tuya_ble import TuyaBLEDataPointType, TuyaBLEDevice

_LOGGER = logging.getLogger(__name__)

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
    getter: Callable[["TuyaBLEBinarySensor"], None] | None = None
    is_available: TuyaBLEBinarySensorIsAvailable = None


@dataclass
class TuyaBLECategoryBinarySensorMapping:
    products: dict[str, list[TuyaBLEBinarySensorMapping]] | None = None
    mapping: list[TuyaBLEBinarySensorMapping] | None = None


mapping: dict[str, TuyaBLECategoryBinarySensorMapping] = {
    "jtmspro": TuyaBLECategoryBinarySensorMapping(
        products={
            PRODUCT_ID_350K: [
                TuyaBLEBinarySensorMapping(
                    dp_id=DP_350K_LOCK_STATE,
                    description=BinarySensorEntityDescription(
                        key="lock_state",
                        device_class=BinarySensorDeviceClass.LOCK,
                    ),
                ),
                TuyaBLEBinarySensorMapping(
                    dp_id=DP_350K_PASSAGE_MODE,
                    description=BinarySensorEntityDescription(
                        key="passage_mode",
                        icon="mdi:door-open",
                    ),
                ),
                TuyaBLEBinarySensorMapping(
                    dp_id=DP_350K_SECURE_STATE,
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
            "drlajpqc": [
                TuyaBLEBinarySensorMapping(
                    dp_id=105,
                    description=BinarySensorEntityDescription(
                        key="battery",
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
    if category is None or category.products is None:
        return []
    return category.products.get(device.product_id) or category.mapping or []


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
                    self._device.product_id == PRODUCT_ID_350K
                    and self._mapping.dp_id == DP_350K_LOCK_STATE
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
        """Schedule stale-state tracking for an existing lock-state datapoint."""
        await super().async_added_to_hass()
        if (
            self._device.product_id == PRODUCT_ID_350K
            and self._mapping.dp_id == DP_350K_LOCK_STATE
        ):
            datapoint = self._device.datapoints[DP_350K_LOCK_STATE]
            if datapoint is not None:
                self._schedule_lock_state_stale(datapoint)

    @callback
    def _mark_lock_state_stale(self, _now) -> None:
        """Refresh HA so DP47 transitions to unavailable after its TTL."""
        self._stale_timer = None
        self.async_write_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        """Cancel any pending stale-state timer."""
        if self._stale_timer is not None:
            self._stale_timer()
            self._stale_timer = None
        await super().async_will_remove_from_hass()

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        if self._device.product_id == PRODUCT_ID_350K:
            datapoint = self._device.datapoints[self._mapping.dp_id]
            if datapoint is None:
                return False
            if self._mapping.dp_id == DP_350K_LOCK_STATE:
                return (time.time() - datapoint.timestamp) <= LOCK_STATE_STALE_SECONDS
            return True

        result = super().available
        if result and self._mapping.is_available:
            result = self._mapping.is_available(self, self._product)
        return result


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TuyaBLEConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Tuya BLE binary sensors."""
    data = entry.runtime_data
    mappings = get_mapping_by_device(data.device)
    async_add_entities(
        TuyaBLEBinarySensor(
            hass,
            data.coordinator,
            data.device,
            data.product,
            sensor_mapping,
        )
        for sensor_mapping in mappings
        if sensor_mapping.force_add
        or data.device.datapoints.has_id(sensor_mapping.dp_id, sensor_mapping.dp_type)
    )
