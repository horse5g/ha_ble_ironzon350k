"""The Tuya BLE integration."""
from __future__ import annotations

from dataclasses import dataclass, field
import logging
from typing import Callable

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    BUTTON_350K_CLEAR_DIAGNOSTICS,
    BUTTON_350K_REFRESH_STATUS,
    DP_350K_BLE_UNLOCK,
    DP_350K_MANUAL_LOCK,
    PRODUCT_ID_350K,
)
from .devices import (
    TuyaBLEConfigEntry,
    TuyaBLEEntity,
    TuyaBLEProductInfo,
)
from .tuya_ble import TuyaBLEDataPointType, TuyaBLEDevice

_LOGGER = logging.getLogger(__name__)


TuyaBLEButtonIsAvailable = Callable[["TuyaBLEButton", TuyaBLEProductInfo], bool] | None


@dataclass
class TuyaBLEButtonMapping:
    dp_id: int
    description: ButtonEntityDescription = field(
        default_factory=lambda: ButtonEntityDescription(
            key="push",
            translation_key="push",
        )
    )
    force_add: bool = True
    dp_type: TuyaBLEDataPointType | None = None
    is_available: TuyaBLEButtonIsAvailable = None


def is_fingerbot_in_push_mode(self: TuyaBLEButton, product: TuyaBLEProductInfo) -> bool:
    result = True
    if product.fingerbot:
        datapoint = self._device.datapoints[product.fingerbot.mode]
        if datapoint:
            result = datapoint.value == 0
    return result


@dataclass
class TuyaBLEFingerbotModeMapping(TuyaBLEButtonMapping):
    is_available: TuyaBLEButtonIsAvailable = is_fingerbot_in_push_mode


@dataclass
class TuyaBLECategoryButtonMapping:
    products: dict[str, list[TuyaBLEButtonMapping]] | None = None
    mapping: list[TuyaBLEButtonMapping] | None = None


mapping: dict[str, TuyaBLECategoryButtonMapping] = {
    "szjqr": TuyaBLECategoryButtonMapping(
        products={
            **dict.fromkeys(
                ["3yqdo5yt", "xhf790if"],  # CubeTouch 1s and II
                [TuyaBLEFingerbotModeMapping(dp_id=1)],
            ),
            **dict.fromkeys(
                ["blliqpsj", "ndvkgsrm", "yiihr7zh", "neq16kgd"],
                [TuyaBLEFingerbotModeMapping(dp_id=2)],
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
                [TuyaBLEFingerbotModeMapping(dp_id=2)],
            ),
        },
    ),
    "jtmspro": TuyaBLECategoryButtonMapping(
        products={
            PRODUCT_ID_350K: [
                TuyaBLEButtonMapping(
                    dp_id=DP_350K_MANUAL_LOCK,
                    description=ButtonEntityDescription(
                        key="lock_door",
                        translation_key="lock_door",
                        icon="mdi:lock",
                    ),
                ),
                TuyaBLEButtonMapping(
                    dp_id=DP_350K_BLE_UNLOCK,
                    description=ButtonEntityDescription(
                        key="unlock_door",
                        translation_key="unlock_door",
                        icon="mdi:lock-open",
                        entity_registry_enabled_default=False,
                    ),
                ),
                TuyaBLEButtonMapping(
                    dp_id=BUTTON_350K_REFRESH_STATUS,
                    description=ButtonEntityDescription(
                        key="refresh_status",
                        translation_key="refresh_status",
                        icon="mdi:refresh",
                        entity_category=EntityCategory.DIAGNOSTIC,
                        entity_registry_enabled_default=False,
                    ),
                ),
                TuyaBLEButtonMapping(
                    dp_id=BUTTON_350K_CLEAR_DIAGNOSTICS,
                    description=ButtonEntityDescription(
                        key="clear_diagnostics",
                        translation_key="clear_diagnostics",
                        icon="mdi:broom",
                        entity_category=EntityCategory.DIAGNOSTIC,
                        entity_registry_enabled_default=False,
                    ),
                ),
            ],
        },
    ),
    "znhsb": TuyaBLECategoryButtonMapping(
        products={
            "cdlandip": [
                TuyaBLEButtonMapping(
                    dp_id=109,
                    description=ButtonEntityDescription(key="bright_lid_screen"),
                ),
            ],
        },
    ),
}


def get_mapping_by_device(device: TuyaBLEDevice) -> list[TuyaBLEButtonMapping]:
    category = mapping.get(device.category)
    if category is None or category.products is None:
        return []
    return category.products.get(device.product_id) or category.mapping or []


class TuyaBLEButton(TuyaBLEEntity, ButtonEntity):
    """Representation of a Tuya BLE Button."""

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: DataUpdateCoordinator,
        device: TuyaBLEDevice,
        product: TuyaBLEProductInfo,
        mapping: TuyaBLEButtonMapping,
    ) -> None:
        super().__init__(hass, coordinator, device, product, mapping.description)
        self._mapping = mapping

    async def async_press(self) -> None:
        """Press the button."""
        if self._device.product_id == PRODUCT_ID_350K:
            if self._mapping.dp_id == DP_350K_MANUAL_LOCK:
                await self._device.set_350k_bool_datapoint(DP_350K_MANUAL_LOCK, True)
                return
            if self._mapping.dp_id == DP_350K_BLE_UNLOCK:
                await self._device.unlock_350k()
                return
            if self._mapping.dp_id == BUTTON_350K_REFRESH_STATUS:
                await self._device.refresh_350k_status()
                return
            if self._mapping.dp_id == BUTTON_350K_CLEAR_DIAGNOSTICS:
                self._device.clear_350k_diagnostics()
                return

        datapoint = self._device.datapoints.get_or_create(
            self._mapping.dp_id,
            TuyaBLEDataPointType.DT_BOOL,
            False,
        )
        if datapoint:
            await datapoint.set_value(not bool(datapoint.value))

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        if (
            self._device.product_id == PRODUCT_ID_350K
            and self._mapping.dp_id
            in (BUTTON_350K_REFRESH_STATUS, BUTTON_350K_CLEAR_DIAGNOSTICS)
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
    """Set up the Tuya BLE buttons."""
    data = entry.runtime_data
    mappings = get_mapping_by_device(data.device)
    entities = [
        TuyaBLEButton(
            hass,
            data.coordinator,
            data.device,
            data.product,
            button_mapping,
        )
        for button_mapping in mappings
        if button_mapping.force_add
        or data.device.datapoints.has_id(button_mapping.dp_id, button_mapping.dp_type)
    ]
    async_add_entities(entities)
