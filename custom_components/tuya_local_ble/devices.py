"""The Tuya BLE integration."""
from __future__ import annotations

from dataclasses import dataclass
import logging

from home_assistant_bluetooth import BluetoothServiceInfoBleak
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, CONF_DEVICE_ID
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity import DeviceInfo, EntityDescription
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import CoordinatorEntity, DataUpdateCoordinator

from .const import (
    DEVICE_DEF_MANUFACTURER,
    DOMAIN,
    DP_350K_LAST_ACCESS_EVENT,
    DP_350K_LOCK_STATE,
    EVENT_350K,
    FINGERBOT_BUTTON_EVENT,
    PRODUCT_ID_350K,
    SET_DISCONNECTED_DELAY,
)
from .keyman import HASSTuyaBLEDeviceManager
from .tuya_ble import (
    AbstaractTuyaBLEDeviceManager,
    TuyaBLEDataPoint,
    TuyaBLEDevice,
    TuyaBLEDeviceCredentials,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class TuyaBLEFingerbotInfo:
    switch: int
    mode: int
    up_position: int
    down_position: int
    hold_time: int
    reverse_positions: int
    manual_control: int = 0
    program: int = 0


@dataclass
class TuyaBLEProductInfo:
    name: str
    manufacturer: str = DEVICE_DEF_MANUFACTURER
    fingerbot: TuyaBLEFingerbotInfo | None = None


class TuyaBLEEntity(CoordinatorEntity):
    """Tuya BLE base entity."""

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: TuyaBLECoordinator,
        device: TuyaBLEDevice,
        product: TuyaBLEProductInfo,
        description: EntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self._hass = hass
        self._coordinator = coordinator
        self._device = device
        self._product = product
        if description.translation_key is None:
            self._attr_translation_key = description.key
        self.entity_description = description
        self._attr_has_entity_name = True
        self._attr_device_info = get_device_info(self._device)
        self._attr_unique_id = f"{self._device.device_id}-{description.key}"

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self._coordinator.connected

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()


class TuyaBLECoordinator(DataUpdateCoordinator[None]):
    """Data coordinator for receiving Tuya BLE updates."""

    def __init__(
        self, hass: HomeAssistant, device: TuyaBLEDevice, config_entry_id: str
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(hass, _LOGGER, name=DOMAIN)
        self._device = device
        self._config_entry_id = config_entry_id
        self._disconnected = True
        self._unsub_disconnect: CALLBACK_TYPE | None = None
        device.register_connected_callback(self._async_handle_connect)
        device.register_callback(self._async_handle_update)
        device.register_disconnected_callback(self._async_handle_disconnect)

    @property
    def connected(self) -> bool:
        """Return whether the coordinator currently considers BLE connected."""
        return not self._disconnected

    @callback
    def _async_handle_connect(self) -> None:
        if self._unsub_disconnect is not None:
            self._unsub_disconnect()
            self._unsub_disconnect = None
        if self._disconnected:
            self._disconnected = False
            self.async_update_listeners()

    @callback
    def _async_fire_350k_event(self, event_type: str, timestamp: float) -> None:
        registry = dr.async_get(self.hass)
        registry_device = registry.async_get_device_by_identifier(
            (DOMAIN, self._device.address), self._config_entry_id
        )
        payload = {
            "type": event_type,
            "timestamp": int(timestamp),
            "address": self._device.address,
        }
        if registry_device is not None:
            payload[CONF_DEVICE_ID] = registry_device.id
        self.hass.bus.async_fire(EVENT_350K, payload)

    @callback
    def _async_handle_update(self, updates: list[TuyaBLEDataPoint]) -> None:
        """Trigger coordinator listeners and local integration events."""
        self._async_handle_connect()
        self.async_set_updated_data(None)
        if self._device.product_id == PRODUCT_ID_350K:
            for update in updates:
                if update.id == DP_350K_LAST_ACCESS_EVENT:
                    self._async_fire_350k_event(str(update.value), update.timestamp)
                elif update.id == DP_350K_LOCK_STATE and update.changed_by_device:
                    self._async_fire_350k_event(
                        "unlocked" if bool(update.value) else "locked",
                        update.timestamp,
                    )

        info = get_device_product_info(self._device)
        if info and info.fingerbot and info.fingerbot.manual_control != 0:
            for update in updates:
                if update.id == info.fingerbot.switch and update.changed_by_device:
                    self.hass.bus.async_fire(
                        FINGERBOT_BUTTON_EVENT,
                        {
                            CONF_ADDRESS: self._device.address,
                            CONF_DEVICE_ID: self._device.device_id,
                        },
                    )

    @callback
    def _set_disconnected(self, _: None) -> None:
        """Mark the coordinator disconnected after the idle timeout."""
        self._disconnected = True
        self._unsub_disconnect = None
        self.async_update_listeners()

    @callback
    def _async_handle_disconnect(self) -> None:
        """Schedule the delayed disconnected state transition."""
        if self._unsub_disconnect is None:
            self._unsub_disconnect = async_call_later(
                self.hass, SET_DISCONNECTED_DELAY, self._set_disconnected
            )

    async def _async_update_data(self) -> None:
        """The device pushes updates; coordinator polling is not used."""


@dataclass
class TuyaBLEData:
    """Runtime data for the Tuya BLE integration."""

    title: str
    device: TuyaBLEDevice
    product: TuyaBLEProductInfo
    manager: HASSTuyaBLEDeviceManager
    coordinator: TuyaBLECoordinator


type TuyaBLEConfigEntry = ConfigEntry[TuyaBLEData]


@dataclass
class TuyaBLECategoryInfo:
    products: dict[str, TuyaBLEProductInfo]
    info: TuyaBLEProductInfo | None = None


devices_database: dict[str, TuyaBLECategoryInfo] = {
    "co2bj": TuyaBLECategoryInfo(
        products={
            "59s19z5m": TuyaBLEProductInfo(name="CO2 Detector"),
        },
    ),
    "ldcg": TuyaBLECategoryInfo(
        products={
            "poaanotz": TuyaBLEProductInfo(name="RV CO And Propane Gas Alarm"),
        },
    ),
    "ms": TuyaBLECategoryInfo(
        products={
            **dict.fromkeys(
                ["ludzroix", "isk2p555"],
                TuyaBLEProductInfo(name="Smart Lock"),
            ),
        },
    ),
    "jtmspro": TuyaBLECategoryInfo(
        products={
            PRODUCT_ID_350K: TuyaBLEProductInfo(name="350K"),
            "rlyxv7pe": TuyaBLEProductInfo(name="A1 PRO MAX"),
            "hc7n0urm": TuyaBLEProductInfo(name="Raykube A1 Ultra"),
            "y2yaegze": TuyaBLEProductInfo(name="CTL20H SmartLock"),
            "ikphogdj": TuyaBLEProductInfo(name="HL Knob-2"),
        },
    ),
    "szjqr": TuyaBLECategoryInfo(
        products={
            "3yqdo5yt": TuyaBLEProductInfo(
                name="CUBETOUCH 1s",
                fingerbot=TuyaBLEFingerbotInfo(
                    switch=1,
                    mode=2,
                    up_position=5,
                    down_position=6,
                    hold_time=3,
                    reverse_positions=4,
                ),
            ),
            "xhf790if": TuyaBLEProductInfo(
                name="CubeTouch II",
                fingerbot=TuyaBLEFingerbotInfo(
                    switch=1,
                    mode=2,
                    up_position=5,
                    down_position=6,
                    hold_time=3,
                    reverse_positions=4,
                ),
            ),
            **dict.fromkeys(
                ["blliqpsj", "ndvkgsrm", "yiihr7zh", "neq16kgd"],
                TuyaBLEProductInfo(
                    name="Fingerbot Plus",
                    fingerbot=TuyaBLEFingerbotInfo(
                        switch=2,
                        mode=8,
                        up_position=15,
                        down_position=9,
                        hold_time=10,
                        reverse_positions=11,
                        manual_control=17,
                        program=121,
                    ),
                ),
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
                ],
                TuyaBLEProductInfo(
                    name="Fingerbot",
                    fingerbot=TuyaBLEFingerbotInfo(
                        switch=2,
                        mode=8,
                        up_position=15,
                        down_position=9,
                        hold_time=10,
                        reverse_positions=11,
                        program=121,
                    ),
                ),
            ),
        },
    ),
    "wk": TuyaBLECategoryInfo(
        products={
            **dict.fromkeys(
                ["drlajpqc", "nhj2j7su"],
                TuyaBLEProductInfo(name="Thermostatic Radiator Valve"),
            ),
        },
    ),
    "wsdcg": TuyaBLECategoryInfo(
        products={
            "ojzlzzsw": TuyaBLEProductInfo(name="Soil moisture sensor"),
            "jm6iasmb": TuyaBLEProductInfo(name="Temperature Humidity Sensor"),
        },
    ),
    "znhsb": TuyaBLECategoryInfo(
        products={
            "cdlandip": TuyaBLEProductInfo(name="Smart water bottle"),
        },
    ),
    "ggq": TuyaBLECategoryInfo(
        products={
            "6pahkcau": TuyaBLEProductInfo(name="Irrigation computer"),
        },
    ),
}


def get_product_info_by_ids(
    category: str, product_id: str
) -> TuyaBLEProductInfo | None:
    category_info = devices_database.get(category)
    if category_info is None:
        return None
    return category_info.products.get(product_id) or category_info.info


def get_device_product_info(device: TuyaBLEDevice) -> TuyaBLEProductInfo | None:
    return get_product_info_by_ids(device.category, device.product_id)


def get_short_address(address: str) -> str:
    results = address.replace("-", ":").upper().split(":")
    return f"{results[-3]}{results[-2]}{results[-1]}"[-6:]


async def get_device_readable_name(
    discovery_info: BluetoothServiceInfoBleak,
    manager: AbstaractTuyaBLEDeviceManager | None,
) -> str:
    credentials: TuyaBLEDeviceCredentials | None = None
    product_info: TuyaBLEProductInfo | None = None
    if manager:
        credentials = await manager.get_device_credentials(discovery_info.address)
        if credentials:
            product_info = get_product_info_by_ids(
                credentials.category,
                credentials.product_id,
            )
    short_address = get_short_address(discovery_info.address)
    if product_info:
        return f"{product_info.name} {short_address}"
    if credentials:
        return f"{credentials.device_name} {short_address}"
    return f"{discovery_info.device.name} {short_address}"


def get_device_info(device: TuyaBLEDevice) -> DeviceInfo:
    product_info = None
    if device.category and device.product_id:
        product_info = get_product_info_by_ids(device.category, device.product_id)
    product_name = product_info.name if product_info else device.name
    return DeviceInfo(
        connections={(dr.CONNECTION_BLUETOOTH, device.address)},
        hw_version=device.hardware_version,
        identifiers={(DOMAIN, device.address)},
        manufacturer=(
            product_info.manufacturer if product_info else DEVICE_DEF_MANUFACTURER
        ),
        model=f"{device.product_model or product_name} ({device.product_id})",
        name=f"{product_name} {get_short_address(device.address)}",
        sw_version=f"{device.device_version} (protocol {device.protocol_version})",
    )
