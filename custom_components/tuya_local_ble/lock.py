"""The Tuya BLE integration."""
from __future__ import annotations

from dataclasses import dataclass, field, replace

import logging
from typing import Callable
from datetime import datetime, timedelta
from threading import Event, Thread
import time

from homeassistant.components.lock import (
    LockEntityDescription,
    LockEntity,
    LockState,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from homeassistant.const import (
    STATE_UNKNOWN,
)

from .const import CONF_KEEP_CONNECTED, DOMAIN
from .devices import TuyaBLEData, TuyaBLEEntity, TuyaBLEProductInfo
from .tuya_ble import TuyaBLEDataPointType, TuyaBLEDevice

_LOGGER = logging.getLogger(__name__)

TuyaBLELockIsAvailable = Callable[["TuyaBLELock", TuyaBLEProductInfo], bool] | None

from typing import Any

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
class TuyaBLELockMapping(TuyaBLELockMapping):
    description: LockEntityDescription = field(
        default_factory=lambda: LockEntityDescription(
            key="push",
            translation_key="push",
        )
    )
    is_available: TuyaBLELockIsAvailable = 0

@dataclass
class TuyaBLECategoryLockMapping:
    products: dict[str, list[TuyaBLELockMapping]] | None = None
    mapping: list[TuyaBLELockMapping] | None = None


mapping: dict[str, TuyaBLECategoryLockMapping] = {
    "jtmspro": TuyaBLECategoryLockMapping(
        products={
            "z1dfsaya":  # Ironzon / YD_350K experimental lock entity
            [
                TuyaBLELockMapping(
                    dp_id_unlock=71,
                    dp_id_lock=46,
                    dp_id=47,
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
            "rlyxv7pe":  # Gimdow Smart Lock
            [
                TuyaBLELockMapping(
                    dp_id_unlock=6,
                    dp_id_lock=46,
                    dp_id=47,
                    # refer to sdk, dp 52 is for deleting temp password
                    # should be safe as a dummy keep alive message
                    dp_id_nop=52,
                    keep_connect=True,
                    keep_connect_timer=60,
                    description=LockEntityDescription(
                        key="manual_lock"
                    ),
                ),
            ],
            "hc7n0urm":  # Raykube A1 Ultra / A1 Pro Max TuyaOS FD50 lock
            [
                TuyaBLELockMapping(
                    dp_id_unlock=6,
                    dp_id_lock=46,
                    # V4 events are parsed, but the full state model is still unknown.
                    # The entity reflects successful remote unlock after V4 ACK.
                    dp_id=118,
                    dp_id_nop=52,
                    keep_connect=False,
                    keep_connect_timer=60,
                    description=LockEntityDescription(
                        key="manual_lock"
                    ),
                ),
            ],
            "y2yaegze":  # CTL20H SmartLock - TuyaOS FD50
            [
                TuyaBLELockMapping(
                    dp_id_unlock=6,
                    dp_id_lock=46,
                    # Physical DP47 is mirrored to synthetic DP118 by the
                    # Raykube V4 parser. 0=locked, 1=unlocked.
                    dp_id=118,
                    dp_id_nop=52,
                    keep_connect=False,
                    keep_connect_timer=60,
                    description=LockEntityDescription(
                        key="manual_lock"
                    ),
                ),
            ],
            "ikphogdj":  # HL Knob-2, TuyaOS FD50 transport
            [
                TuyaBLELockMapping(
                    dp_id_unlock=6,
                    dp_id_lock=46,
                    # Confirmed via HCI capture: dp 47 (lock_motor_state) is
                    # the reliable state signal, including autonomous
                    # auto-lock events - dp 46 (manual_lock) only fires on
                    # commanded actions. Polarity confirmed twice: dp47=1
                    # after unlock, dp47=0 after lock/auto-lock.
                    dp_id=47,
                    value_means_locked=False,
                    dp_id_nop=52,
                    keep_connect=False,
                    keep_connect_timer=60,
                    description=LockEntityDescription(
                        key="manual_lock"
                    ),
                ),
            ],
            "c6hfl8bt":  # MYPIN HS0358 cabinet lock, TuyaOS FD50 transport
            [
                TuyaBLELockMapping(
                    dp_id_unlock=6,
                    dp_id_lock=46,
                    # Same standardized jtmspro/FD50 DP schema as ikphogdj/
                    # hc7n0urm (dp 47 = lock_motor_state); polarity not yet
                    # confirmed against physical unlock/lock for this device.
                    dp_id=47,
                    value_means_locked=False,
                    dp_id_nop=52,
                    keep_connect=False,
                    keep_connect_timer=60,
                    description=LockEntityDescription(
                        key="manual_lock"
                    ),
                ),
            ],
        }
    ), 
}


def get_mapping_by_device(device: TuyaBLEDevice) -> list[TuyaBLECategoryLockMapping]:
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


class TuyaBLELock(TuyaBLEEntity, LockEntity):
    """Representation of a Tuya BLE Lock."""

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
        self._target_state = None
        self._commanded = False
        self._commanded_timer = None
        self._datapoint_nop = None
        self._isjammed = False
        self._keep_connect_stop = Event()
        self._keep_connect_thread: Thread | None = None
        # DP47 is often already present from the setup-time status read.
        self.update_device_state()
        self._update_attrs()
        if mapping.keep_connect:
            self._datapoint_nop = device.datapoints.get_or_create(
                self._mapping.dp_id_nop,
                TuyaBLEDataPointType.DT_BOOL,
                False,
            )
            self._keep_connect_thread = Thread(
                target=self.send_nop_request,
                name=f"tuya-ble-keep-connect-{device.address}",
                daemon=True,
            )
            self._keep_connect_thread.start()

    def send_nop_request(self):
        """Periodically touch a dummy DP to keep the BLE session alive."""
        while not self._keep_connect_stop.wait(self._mapping.keep_connect_timer):
            if self._datapoint_nop:
                self._hass.create_task(self._datapoint_nop.set_value(True))

    async def async_will_remove_from_hass(self) -> None:
        """Stop keepalive thread when the entity is removed/reloaded."""
        self._keep_connect_stop.set()
        thread = self._keep_connect_thread
        if thread is not None and thread.is_alive():
            await self._hass.async_add_executor_job(thread.join, 1.0)

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
    def should_poll(self) -> bool: return False

    def _update_attrs(self) -> None:
        self._attr_is_locking = self.is_locking
        self._attr_is_unlocking = self.is_unlocking
        self._attr_is_locked = self.is_locked
        self._attr_is_unlocked = None if self.is_locked is None else not self.is_locked
        self._attr_is_jammed = self.is_jammed
        self._attr_changed_by = super().changed_by

    async def async_lock(self, **kwargs: Any) -> None:
        """Lock the device."""
        await self._set_lock_state(LockState.LOCKED)

    async def async_unlock(self, **kwargs: Any) -> None:
        """Unlock the device."""
        await self._set_lock_state(LockState.UNLOCKED)

    async def _set_lock_state(self, state: str) -> None:
        self._target_state = state
        self._update_attrs()
        self.async_write_ha_state()

        if self._device.product_id == "z1dfsaya":
            # 350K commands are one-shot authenticated operations. Never
            # mutate DP47 optimistically; wait for the lock to report it.
            self._commanded = True
            self._commanded_timer = datetime.now()
            self._update_attrs()
            self.async_write_ha_state()
            if self._target_state == LockState.UNLOCKED:
                sent = await self._device.unlock_350k()
            else:
                sent = await self._device.set_350k_bool_datapoint(46, True)
            if not sent:
                self._commanded = False
                self._target_state = None
                self._isjammed = False
                self._update_attrs()
                self.async_write_ha_state()
            return

        if self._target_state == LockState.UNLOCKED:
            dp_id = self._mapping.dp_id_unlock
        else:
            dp_id = self._mapping.dp_id_lock

        datapoint = self._device.datapoints.get_or_create(
            dp_id,
            TuyaBLEDataPointType.DT_BOOL,
            False,
        )

        if self._device.product_id in ("hc7n0urm", "y2yaegze") and self._target_state == LockState.UNLOCKED:
            await datapoint.set_value(True)
            self._current_state = LockState.UNLOCKED
            self._commanded = False
            self._isjammed = False
            self._update_attrs()
            self.async_write_ha_state()
            return

        if self._device.product_id in ("hc7n0urm", "y2yaegze") and self._target_state == LockState.LOCKED:
            await datapoint.set_value(True)
            self._current_state = LockState.LOCKED
            self._commanded = False
            self._isjammed = False
            self._update_attrs()
            self.async_write_ha_state()
            return

        if self._device.product_id == "ikphogdj" and self._target_state == LockState.UNLOCKED:
            await datapoint.set_value(True)
            state_value = False if self._mapping.value_means_locked else True
            self._device.datapoints._update_from_device(
                self._mapping.dp_id, time.time(), 0, TuyaBLEDataPointType.DT_BOOL, state_value
            )
            self._current_state = LockState.UNLOCKED
            self._commanded = False
            self._isjammed = False
            self._update_attrs()
            self.async_write_ha_state()
            self._hass.create_task(self._device.linger_connected(30))
            return

        if self._device.product_id == "ikphogdj" and self._target_state == LockState.LOCKED:
            await datapoint.set_value(True)
            state_value = True if self._mapping.value_means_locked else False
            self._device.datapoints._update_from_device(
                self._mapping.dp_id, time.time(), 0, TuyaBLEDataPointType.DT_BOOL, state_value
            )
            self._current_state = LockState.LOCKED
            self._commanded = False
            self._isjammed = False
            self._update_attrs()
            self.async_write_ha_state()
            self._hass.create_task(self._device.linger_connected(30))
            return

        self._hass.create_task(datapoint.set_value(True))
        self._commanded = True
        self._commanded_timer = datetime.now()

    def update_device_state(self):
        datapoint = self._device.datapoints[self._mapping.dp_id]
        if datapoint:
            is_set = bool(datapoint.value)
            if self._mapping.value_means_locked:
                self._current_state = LockState.LOCKED if is_set else LockState.UNLOCKED
            else:
                self._current_state = LockState.UNLOCKED if is_set else LockState.LOCKED
            if self._commanded:
                if ( self._current_state != self._target_state):
                    if ( datetime.now() > self._commanded_timer + timedelta(seconds = 12) ):
                        self._isjammed = True
                        self._commanded = False
                else:
                    self._commanded = False
                    self._isjammed = False

    @callback
    def _handle_coordinator_update(self) -> None:
        self.update_device_state()
        self._update_attrs()
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        if self._device.product_id in ("hc7n0urm", "y2yaegze"):
            return True
        if self._device.product_id in ("ikphogdj", "z1dfsaya"):
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
    entities: list[TuyaBLELock] = []
    raykube_keep_connected = bool(entry.options.get(CONF_KEEP_CONNECTED, False))
    for mapping in mappings:
        runtime_mapping = mapping
        if data.device.product_id in ("hc7n0urm", "y2yaegze"):
            runtime_mapping = replace(
                mapping,
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
