"""The Tuya BLE integration."""
from __future__ import annotations

from dataclasses import dataclass, field
import logging

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    DP_350K_BEEP_VOLUME,
    DP_350K_LANGUAGE,
    FINGERBOT_MODE_PROGRAM,
    FINGERBOT_MODE_PUSH,
    FINGERBOT_MODE_SWITCH,
    PRODUCT_ID_350K,
)
from .devices import TuyaBLEConfigEntry, TuyaBLEEntity, TuyaBLEProductInfo
from .tuya_ble import TuyaBLEDataPointType, TuyaBLEDevice

_LOGGER = logging.getLogger(__name__)


@dataclass
class TuyaBLESelectMapping:
    dp_id: int
    description: SelectEntityDescription
    force_add: bool = True
    dp_type: TuyaBLEDataPointType | None = None


@dataclass
class TemperatureUnitDescription(SelectEntityDescription):
    key: str = "temperature_unit"
    icon: str = "mdi:thermometer"
    entity_category: EntityCategory = EntityCategory.CONFIG


@dataclass
class TuyaBLEFingerbotModeMapping(TuyaBLESelectMapping):
    description: SelectEntityDescription = field(
        default_factory=lambda: SelectEntityDescription(
            key="fingerbot_mode",
            entity_category=EntityCategory.CONFIG,
            options=[
                FINGERBOT_MODE_PUSH,
                FINGERBOT_MODE_SWITCH,
                FINGERBOT_MODE_PROGRAM,
            ],
        )
    )


@dataclass
class TuyaBLECategorySelectMapping:
    products: dict[str, list[TuyaBLESelectMapping]] | None = None
    mapping: list[TuyaBLESelectMapping] | None = None


mapping: dict[str, TuyaBLECategorySelectMapping] = {
    "co2bj": TuyaBLECategorySelectMapping(
        products={
            "59s19z5m": [
                TuyaBLESelectMapping(
                    dp_id=101,
                    description=TemperatureUnitDescription(
                        options=[
                            UnitOfTemperature.CELSIUS,
                            UnitOfTemperature.FAHRENHEIT,
                        ],
                    ),
                ),
            ],
        },
    ),
    "ms": TuyaBLECategorySelectMapping(
        products={
            **dict.fromkeys(
                ["ludzroix", "isk2p555"],
                [
                    TuyaBLESelectMapping(
                        dp_id=31,
                        description=SelectEntityDescription(
                            key="beep_volume",
                            options=["mute", "low", "normal", "high"],
                            entity_category=EntityCategory.CONFIG,
                        ),
                    ),
                ],
            ),
        },
    ),
    "jtmspro": TuyaBLECategorySelectMapping(
        products={
            PRODUCT_ID_350K: [
                TuyaBLESelectMapping(
                    dp_id=DP_350K_BEEP_VOLUME,
                    description=SelectEntityDescription(
                        key="beep_volume",
                        options=["mute", "low", "normal", "high"],
                        entity_category=EntityCategory.CONFIG,
                    ),
                ),
                TuyaBLESelectMapping(
                    dp_id=DP_350K_LANGUAGE,
                    description=SelectEntityDescription(
                        key="language",
                        options=["chinese_simplified", "english"],
                        entity_category=EntityCategory.CONFIG,
                    ),
                ),
            ],
            "rlyxv7pe": [
                TuyaBLESelectMapping(
                    dp_id=31,
                    description=SelectEntityDescription(
                        key="beep_volume",
                        options=["mute", "low", "normal", "high"],
                        entity_category=EntityCategory.CONFIG,
                    ),
                ),
                TuyaBLESelectMapping(
                    dp_id=48,
                    description=SelectEntityDescription(
                        key="lock_direction",
                        options=["clockwise", "anticlockwise"],
                        entity_category=EntityCategory.CONFIG,
                    ),
                ),
            ],
            "hc7n0urm": [
                TuyaBLESelectMapping(
                    dp_id=31,
                    description=SelectEntityDescription(
                        key="beep_volume",
                        options=["mute", "low", "normal", "high"],
                        entity_category=EntityCategory.CONFIG,
                    ),
                ),
                TuyaBLESelectMapping(
                    dp_id=48,
                    description=SelectEntityDescription(
                        key="lock_direction",
                        options=["clockwise", "anticlockwise"],
                        entity_category=EntityCategory.CONFIG,
                    ),
                ),
            ],
            "ikphogdj": [
                TuyaBLESelectMapping(
                    dp_id=31,
                    description=SelectEntityDescription(
                        key="beep_volume",
                        options=["mute", "low", "normal", "high"],
                        entity_category=EntityCategory.CONFIG,
                    ),
                ),
            ],
        },
    ),
    "szjqr": TuyaBLECategorySelectMapping(
        products={
            **dict.fromkeys(
                ["3yqdo5yt", "xhf790if"],
                [TuyaBLEFingerbotModeMapping(dp_id=2)],
            ),
            **dict.fromkeys(
                ["blliqpsj", "ndvkgsrm", "yiihr7zh", "neq16kgd"],
                [TuyaBLEFingerbotModeMapping(dp_id=8)],
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
                [TuyaBLEFingerbotModeMapping(dp_id=8)],
            ),
        },
    ),
    "wsdcg": TuyaBLECategorySelectMapping(
        products={
            "ojzlzzsw": [
                TuyaBLESelectMapping(
                    dp_id=9,
                    description=TemperatureUnitDescription(
                        options=[
                            UnitOfTemperature.CELSIUS,
                            UnitOfTemperature.FAHRENHEIT,
                        ],
                        entity_registry_enabled_default=False,
                    ),
                ),
            ],
            "jm6iasmb": [
                TuyaBLESelectMapping(
                    dp_id=9,
                    description=TemperatureUnitDescription(
                        options=[
                            UnitOfTemperature.CELSIUS,
                            UnitOfTemperature.FAHRENHEIT,
                        ],
                        entity_registry_enabled_default=False,
                    ),
                ),
            ],
        },
    ),
    "znhsb": TuyaBLECategorySelectMapping(
        products={
            "cdlandip": [
                TuyaBLESelectMapping(
                    dp_id=106,
                    description=TemperatureUnitDescription(
                        options=[
                            UnitOfTemperature.CELSIUS,
                            UnitOfTemperature.FAHRENHEIT,
                        ],
                    ),
                ),
                TuyaBLESelectMapping(
                    dp_id=107,
                    description=SelectEntityDescription(
                        key="reminder_mode",
                        options=["interval_reminder", "schedule_reminder"],
                        entity_category=EntityCategory.CONFIG,
                    ),
                ),
            ],
        },
    ),
}


def get_mapping_by_device(device: TuyaBLEDevice) -> list[TuyaBLESelectMapping]:
    category = mapping.get(device.category)
    if category is None or category.products is None:
        return []
    return category.products.get(device.product_id) or category.mapping or []


class TuyaBLESelect(TuyaBLEEntity, SelectEntity):
    """Representation of a Tuya BLE select."""

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: DataUpdateCoordinator,
        device: TuyaBLEDevice,
        product: TuyaBLEProductInfo,
        mapping: TuyaBLESelectMapping,
    ) -> None:
        super().__init__(hass, coordinator, device, product, mapping.description)
        self._mapping = mapping
        self._attr_options = mapping.description.options
        self._sticky_option: str | None = None

    def _is_sticky_select(self) -> bool:
        if self._device.product_id == "hc7n0urm":
            return self._mapping.dp_id in (31, 48)
        if self._device.product_id == "ikphogdj":
            return self._mapping.dp_id in (31, 48)
        if self._device.product_id == PRODUCT_ID_350K:
            return self._mapping.dp_id in (DP_350K_LANGUAGE, DP_350K_BEEP_VOLUME)
        return False

    def _option_from_datapoint(self) -> str | None:
        datapoint = self._device.datapoints[self._mapping.dp_id]
        if not datapoint:
            return None
        value = datapoint.value
        try:
            int_value = int(value)
        except (TypeError, ValueError):
            return value if isinstance(value, str) and value in self._attr_options else None
        if 0 <= int_value < len(self._attr_options):
            return self._attr_options[int_value]
        return None

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        if self._is_sticky_select():
            return True
        return super().available

    @property
    def current_option(self) -> str | None:
        """Return the selected entity option to represent the entity state."""
        option = self._option_from_datapoint()
        if option is not None:
            self._sticky_option = option
            return option
        if self._is_sticky_select() and self._sticky_option in self._attr_options:
            return self._sticky_option
        return None

    async def async_select_option(self, option: str) -> None:
        """Change the selected option and push local state immediately."""
        if option not in self._attr_options:
            return
        int_value = self._attr_options.index(option)
        if (
            self._device.product_id == PRODUCT_ID_350K
            and self._mapping.dp_id in (DP_350K_LANGUAGE, DP_350K_BEEP_VOLUME)
        ):
            sent = await self._device.set_350k_enum_datapoint(
                self._mapping.dp_id, int_value
            )
            if sent:
                self._sticky_option = option
            self.async_write_ha_state()
            return
        datapoint = self._device.datapoints.get_or_create(
            self._mapping.dp_id,
            TuyaBLEDataPointType.DT_ENUM,
            int_value,
        )
        if not datapoint:
            return
        await datapoint.set_value(int_value)
        self._sticky_option = option
        self.async_write_ha_state()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TuyaBLEConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Tuya BLE selects."""
    data = entry.runtime_data
    mappings = get_mapping_by_device(data.device)
    async_add_entities(
        TuyaBLESelect(
            hass,
            data.coordinator,
            data.device,
            data.product,
            select_mapping,
        )
        for select_mapping in mappings
        if select_mapping.force_add
        or data.device.datapoints.has_id(select_mapping.dp_id, select_mapping.dp_type)
    )
