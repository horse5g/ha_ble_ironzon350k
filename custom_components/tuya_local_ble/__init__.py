"""The Tuya BLE integration."""
from __future__ import annotations

import logging
import time

from bleak_retry_connector import BLEAK_RETRY_EXCEPTIONS as BLEAK_EXCEPTIONS, get_device

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth.match import ADDRESS, BluetoothCallbackMatcher
from homeassistant.const import CONF_ADDRESS, EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryError, ConfigEntryNotReady
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_KEEP_CONNECTED,
    CONF_PROTOCOL_LOG_LEVEL,
    PRODUCT_ID_350K,
    PROTOCOL_LOG_OFF,
)
from .devices import TuyaBLEConfigEntry, TuyaBLECoordinator, TuyaBLEData, get_device_product_info
from .keyman import HASSTuyaBLEDeviceManager
from .resilient_device import ResilientTuyaBLEDevice
from .services import async_register_services

PLATFORMS: list[Platform] = [
    Platform.BUTTON,
    Platform.CLIMATE,
    Platform.NUMBER,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.SELECT,
    Platform.SWITCH,
    Platform.TEXT,
    Platform.LOCK,
]

_LOGGER = logging.getLogger(__name__)


@callback
def _enable_350k_sensor_entries(hass: HomeAssistant, entry_id: str) -> int:
    """Enable all 350K sensors that the integration disabled by default.

    User-disabled entities are deliberately left alone. This also migrates
    existing installs whose diagnostic sensors were registered as disabled by
    older experimental builds.
    """
    registry = er.async_get(hass)
    enabled = 0
    for registry_entry in er.async_entries_for_config_entry(registry, entry_id):
        if (
            registry_entry.domain == Platform.SENSOR
            and registry_entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION
        ):
            registry.async_update_entity(registry_entry.entity_id, disabled_by=None)
            enabled += 1
    return enabled


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up integration-level resources."""
    async_register_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: TuyaBLEConfigEntry) -> bool:
    """Set up Tuya BLE from a config entry."""
    address: str = entry.data[CONF_ADDRESS]
    ble_device = bluetooth.async_ble_device_from_address(
        hass, address.upper(), True
    ) or await get_device(address)
    if not ble_device:
        raise ConfigEntryNotReady(
            f"Could not find Tuya BLE device with address {address}"
        )

    manager = HASSTuyaBLEDeviceManager(hass, entry.options.copy())
    device = ResilientTuyaBLEDevice(manager, ble_device)
    await device.initialize()
    if not device.device_id:
        await device.stop()
        raise ConfigEntryError(
            "No valid local Tuya BLE credentials were found for this device; "
            "check tuya_local_ble/devices.json"
        )

    if device.product_id == PRODUCT_ID_350K:
        device.set_protocol_log_level(
            str(entry.options.get(CONF_PROTOCOL_LOG_LEVEL, PROTOCOL_LOG_OFF))
        )
        # Keepalive is an integration option rather than a lock entity.
        # The 350K implementation only keeps an already-authenticated
        # session warm; it never wakes/connects the lock by itself.
        device.set_keepalive_enabled(
            bool(entry.options.get(CONF_KEEP_CONNECTED, False))
        )
    product_info = get_device_product_info(device)

    coordinator = TuyaBLECoordinator(hass, device, entry.entry_id)
    try:
        await device.update()
    except BLEAK_EXCEPTIONS as ex:
        await device.stop()
        raise ConfigEntryNotReady(
            f"Could not communicate with Tuya BLE device with address {address}"
        ) from ex

    last_raykube_advertisement_update = 0.0

    async def _async_update_raykube_from_advertisement() -> None:
        """Best-effort Raykube state refresh after a BLE advertisement."""
        try:
            await device.update()
        except BLEAK_EXCEPTIONS:
            _LOGGER.debug(
                "%s: Raykube advertisement-triggered update failed",
                address,
                exc_info=True,
            )
        except Exception:
            _LOGGER.debug(
                "%s: Raykube advertisement-triggered update failed unexpectedly",
                address,
                exc_info=True,
            )

    @callback
    def _async_update_ble(
        service_info: bluetooth.BluetoothServiceInfoBleak,
        change: bluetooth.BluetoothChange,
    ) -> None:
        """Update from a BLE callback."""
        nonlocal last_raykube_advertisement_update
        device.set_ble_device_and_advertisement_data(
            service_info.device, service_info.advertisement
        )
        if device.product_id in ("hc7n0urm", "y2yaegze"):
            # Raykube locks do not push manual/keypad state changes while the
            # integration is disconnected. A fresh advertisement after a
            # physical action is the safest low-power cue we have to reconnect
            # and request status, without keeping a permanent BLE session open.
            now = time.monotonic()
            if now - last_raykube_advertisement_update >= 300:
                last_raykube_advertisement_update = now
                hass.async_create_task(_async_update_raykube_from_advertisement())

    entry.async_on_unload(
        bluetooth.async_register_callback(
            hass,
            _async_update_ble,
            BluetoothCallbackMatcher({ADDRESS: address}),
            bluetooth.BluetoothScanningMode.ACTIVE,
        )
    )

    entry.runtime_data = TuyaBLEData(
        entry.title,
        device,
        product_info,
        manager,
        coordinator,
    )

    # Older experimental builds registered many useful 350K diagnostics as
    # disabled-by-integration. Enable those existing registry entries before
    # platform setup so HA actually instantiates them on this load.
    if device.product_id == PRODUCT_ID_350K:
        migrated_sensors = _enable_350k_sensor_entries(hass, entry.entry_id)
        if migrated_sensors:
            _LOGGER.info(
                "%s: enabled %s previously disabled 350K sensor entities",
                address,
                migrated_sensors,
            )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    # On a fresh install, disabled-by-default registry rows are created during
    # the platform setup above. Clear those rows now and reload exactly once so
    # the sensors become live entities. A subsequent setup finds no integration-
    # disabled sensors, so this cannot form a reload loop.
    if device.product_id == PRODUCT_ID_350K:
        newly_enabled_sensors = _enable_350k_sensor_entries(hass, entry.entry_id)
        if newly_enabled_sensors:
            _LOGGER.info(
                "%s: enabled %s newly registered 350K sensor entities; reloading once",
                address,
                newly_enabled_sensors,
            )
            hass.async_create_task(
                hass.config_entries.async_reload(entry.entry_id),
                name=f"tuya-local-ble-enable-350k-sensors-{entry.entry_id}",
            )

    async def _async_stop(event: Event) -> None:
        """Close the connection."""
        await device.stop()

    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _async_stop)
    )
    return True


async def _async_update_listener(
    hass: HomeAssistant, entry: TuyaBLEConfigEntry
) -> None:
    """Reload when integration options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: TuyaBLEConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.device.stop()

    return unload_ok
