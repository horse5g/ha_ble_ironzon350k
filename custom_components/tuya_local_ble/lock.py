"""The Tuya BLE integration."""
from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass, replace
import logging
import time
from typing import Any, Callable

from homeassistant.components.lock import LockEntity, LockEntityDescription, LockState
from homeassistant.const import STATE_UNKNOWN
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    CONF_KEEP_CONNECTED,
    DP_350K_BLE_UNLOCK,
    DP_350K_LOCK_STATE,
    DP_350K_MANUAL_LOCK,
    PRODUCT_ID_350K,
)
from .devices import TuyaBLEConfigEntry, TuyaBLEEntity, TuyaBLEProductInfo
from .tuya_ble import TuyaBLEDataPointType, TuyaBLEDevice

_LOGGER = logging.getLogger(__name__)

TuyaBLELockIsAvailable = Callable[["TuyaBLELock", TuyaBLEProductInfo], bool] | None


@dataclass
class TuyaBLELockMapping:
    dp_id: int
    dp_id_lock: int
    dp_id_unlock: int
    dp_id_nop: int
    keep_connect_timer: int
    description: LockEntityDescription
    force_add: bool = True
    keep_connect: bool = False
    dp_type: TuyaBLEDataPointType | None = None
    is_available: TuyaBLELockIsAvailable = None
    value_means_locked: bool = False


@dataclass
class TuyaBLECategoryLockMapping:
    products: dict[str, list[TuyaBLELockMapping]] | None = None
    mapping: list[TuyaBLELockMapping] | None = None


mapping: dict[str, TuyaBLECategoryLockMapping] = {
    "jtmspro": TuyaBLECategoryLockMapping(
        products={
            PRODUCT_ID_350K: [
                TuyaBLELockMapping(
                    dp_id_unlock=DP_350K_BLE_UNLOCK,
                    dp_id_lock=DP_350K_MANUAL_LOCK,
                    dp_id=DP_350K_LOCK_STATE,
                    dp_id_nop=0,
                    keep_connect=False,
                    keep_connect_timer=120,
                    value_means_locked=False,
                    description=LockEntityDescription(
                        key="experimental_lock",
                        translation_key="experimental_lock",
                        entity_registry_enabled_default=False,
                    ),
                ),
            ],
            "rlyxv7pe": [
                TuyaBLELockMapping(
                    dp_id_unlock=6,
                    dp_id_lock=46,
                    dp_id=47,
                    dp_id_nop=52,
                    keep_connect=True,
                    keep_connect_timer=60,
                    description=LockEntityDescription(key="manual_lock"),
                ),
            ],
            "hc7n0urm": [
                TuyaBLELockMapping(
                    dp_id_unlock=6,
                    dp_id_lock=46,
                    dp_id=118,
                    dp_id_nop=52,
                    keep_connect=False,
                    keep_connect_timer=60,
                    description=LockEntityDescription(key="manual_lock"),
                ),
            ],
            "y2yaegze": [
                TuyaBLELockMapping(
                    dp_id_unlock=6,
                    dp_id_lock=46,
                    dp_id=118,
                    dp_id_nop=52,
                    keep_connect=False,
                    keep_connect_timer=60,
                    description=LockEntityDescription(key="manual_lock"),
                ),
            ],
            "ikphogdj": [
                TuyaBLELockMapping(
                    dp_id_unlock=6,
                    dp_id_lock=46,
                    dp_id=47,
                    value_means_locked=False,
                    dp_id_nop=52,
                    keep_connect=False,
                    keep_connect_timer=60,
                    description=LockEntityDescription(key="manual_lock"),
                ),
            ],
            "c6hfl8bt": [
                TuyaBLELockMapping(
                    dp_id_unlock=6,
                    dp_id_lock=46,
                    dp_id=47,
                    value_means_locked=False,
                    dp_id_nop=52,
                    keep_connect=False,
                    keep_connect_timer=60,
                    description=LockEntityDescription(key="manual_lock"),
                ),
            ],
        }
    ),
}


def get_mapping_by_device(device: TuyaBLEDevice) -> list[TuyaBLELockMapping]:
    category = mapping.get(device.category)
    if category is None or category.products is None:
        return []
    return category.products.get(device.product_id) or category.mapping or []


class TuyaBLELock(TuyaBLEEntity, LockEntity):
    """Representation of a Tuya BLE lock."""

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: DataUpdateCoordinator,
        device: TuyaBLEDevice,
        product: TuyaBLEProductInfo,
        mapping: TuyaBLELockMapping,
    ) -> None:
        super().__init__(hass, coordinator, device, product, mapping.description)
        self._mapping = mapping
        self._current_state = STATE_UNKNOWN
        self._target_state: LockState | None = None
        self._commanded = False
        self._commanded_started: float | None = None
        self._datapoint_nop = None
        self._isjammed = False
        self._keep_connect_task: asyncio.Task[None] | None = None

        self.update_device_state()
        self._update_attrs()

        if mapping.keep_connect:
            self._datapoint_nop = device.datapoints.get_or_create(
                self._mapping.dp_id_nop,
                TuyaBLEDataPointType.DT_BOOL,
                False,
            )
            self._keep_connect_task = hass.async_create_task(
                self._async_send_nop_requests(),
                name=f"tuya-ble-keep-connect-{device.address}",
            )

    async def _async_send_nop_requests(self) -> None:
        """Periodically touch a dummy DP to keep the BLE session alive."""
        while True:
            await asyncio.sleep(self._mapping.keep_connect_timer)
            if self._datapoint_nop:
                await self._datapoint_nop.set_value(True)

    async def async_will_remove_from_hass(self) -> None:
        """Stop the keepalive task when the entity is removed or reloaded."""
        if self._keep_connect_task is not None:
            self._keep_connect_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._keep_connect_task
            self._keep_connect_task = None
        await super().async_will_remove_from_hass()

    @property
    def is_locked(self) -> bool | None:
        """Return true if device is locked."""
        if self._current_state == STATE_UNKNOWN:
            return None
        return self._current_state == LockState.LOCKED

    @property
    def is_locking(self) -> bool:
        """Return true if device is locking."""
        return (
            self._current_state == LockState.UNLOCKED
            and self._target_state == LockState.LOCKED
            and self._commanded
        )

    @property
    def is_unlocking(self) -> bool:
        """Return true if device is unlocking."""
        return (
            self._current_state == LockState.LOCKED
            and self._target_state == LockState.UNLOCKED
            and self._commanded
        )

    @property
    def is_jammed(self) -> bool | None:
        """Return true if device is jammed."""
        return self._isjammed

    @property
    def should_poll(self) -> bool:
        """The lock state is pushed by the coordinator."""
        return False

    def _update_attrs(self) -> None:
        self._attr_is_locking = self.is_locking
        self._attr_is_unlocking = self.is_unlocking
        self._attr_is_locked = self.is_locked
        self._attr_is_unlocked = None if self.is_locked is None else not self.is_locked
        self._attr_is_jammed = self.is_jammed

    async def async_lock(self, **kwargs: Any) -> None:
        """Lock the device."""
        await self._set_lock_state(LockState.LOCKED)

    async def async_unlock(self, **kwargs: Any) -> None:
        """Unlock the device."""
        await self._set_lock_state(LockState.UNLOCKED)

    async def _set_lock_state(self, state: LockState) -> None:
        self._target_state = state
        self._update_attrs()
        self.async_write_ha_state()

        if self._device.product_id == PRODUCT_ID_350K:
            self._commanded = True
            self._commanded_started = time.monotonic()
            self._update_attrs()
            self.async_write_ha_state()
            if self._target_state == LockState.UNLOCKED:
                sent = await self._device.unlock_350k()
            else:
                sent = await self._device.set_350k_bool_datapoint(
                    DP_350K_MANUAL_LOCK, True
                )
            if not sent:
                self._commanded = False
                self._target_state = None
                self._isjammed = False
                self._update_attrs()
                self.async_write_ha_state()
            return

        dp_id = (
            self._mapping.dp_id_unlock
            if self._target_state == LockState.UNLOCKED
            else self._mapping.dp_id_lock
        )
        datapoint = self._device.datapoints.get_or_create(
            dp_id,
            TuyaBLEDataPointType.DT_BOOL,
            False,
        )

        if self._device.product_id in ("hc7n0urm", "y2yaegze"):
            await datapoint.set_value(True)
            self._current_state = self._target_state
            self._commanded = False
            self._isjammed = False
            self._update_attrs()
            self.async_write_ha_state()
            return

        if self._device.product_id == "ikphogdj":
            await datapoint.set_value(True)
            unlocked = self._target_state == LockState.UNLOCKED
            state_value = not unlocked if self._mapping.value_means_locked else unlocked
            self._device.datapoints._update_from_device(
                self._mapping.dp_id,
                time.time(),
                0,
                TuyaBLEDataPointType.DT_BOOL,
                state_value,
            )
            self._current_state = self._target_state
            self._commanded = False
            self._isjammed = False
            self._update_attrs()
            self.async_write_ha_state()
            self._hass.async_create_task(self._device.linger_connected(30))
            return

        await datapoint.set_value(True)
        self._commanded = True
        self._commanded_started = time.monotonic()

    def update_device_state(self) -> None:
        """Update HA lock state from the configured state datapoint."""
        datapoint = self._device.datapoints[self._mapping.dp_id]
        if not datapoint:
            return

        is_set = bool(datapoint.value)
        if self._mapping.value_means_locked:
            self._current_state = LockState.LOCKED if is_set else LockState.UNLOCKED
        else:
            self._current_state = LockState.UNLOCKED if is_set else LockState.LOCKED

        if not self._commanded:
            return

        if self._current_state == self._target_state:
            self._commanded = False
            self._isjammed = False
        elif (
            self._commanded_started is not None
            and time.monotonic() > self._commanded_started + 12
        ):
            self._isjammed = True
            self._commanded = False

    @callback
    def _handle_coordinator_update(self) -> None:
        self.update_device_state()
        self._update_attrs()
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        if self._device.product_id in (
            "hc7n0urm",
            "y2yaegze",
            "ikphogdj",
            PRODUCT_ID_350K,
        ):
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
    """Set up the Tuya BLE locks."""
    data = entry.runtime_data
    mappings = get_mapping_by_device(data.device)
    entities: list[TuyaBLELock] = []
    raykube_keep_connected = bool(entry.options.get(CONF_KEEP_CONNECTED, False))
    for lock_mapping in mappings:
        runtime_mapping = lock_mapping
        if data.device.product_id in ("hc7n0urm", "y2yaegze"):
            runtime_mapping = replace(
                lock_mapping,
                keep_connect=raykube_keep_connected,
            )
        if runtime_mapping.force_add or data.device.datapoints.has_id(
            runtime_mapping.dp_id, runtime_mapping.dp_type
        ):
            entities.append(
                TuyaBLELock(
                    hass,
                    data.coordinator,
                    data.device,
                    data.product,
                    runtime_mapping,
                )
            )
    async_add_entities(entities)
