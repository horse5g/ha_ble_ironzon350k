"""The Tuya BLE integration."""
from __future__ import annotations

from dataclasses import dataclass, field
import logging

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    DOMAIN,
    FINGERBOT_MODE_PROGRAM,
    FINGERBOT_MODE_PUSH,
    FINGERBOT_MODE_SWITCH,
)
from .devices import TuyaBLEData, TuyaBLEEntity, TuyaBLEProductInfo
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
            "z1dfsaya": [
                TuyaBLESelectMapping(
                    dp_id=31,
                    description=SelectEntityDescription(
                        key="beep_volume",
                        options=["mute", "low", "normal", "high"],
                        entity_category=EntityCategory.CONFIG,
                    ),
                ),
                TuyaBLESelectMapping(
                    dp_id=28,
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
    product_mapping = category.products.get(device.product_id)
    if product_mapping is not None:
        return product_mapping
    return category.mapping or []


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
        # Some locks ACK enum writes without a durable DP echo. Keep the last
        # valid option so unrelated coordinator updates do not blank HA state.
        self._sticky_option: str | None = None

    def _is_sticky_select(self) -> bool:
        if self._device.product_id == "hc7n0urm":
            return self._mapping.dp_id in (31, 48)
        if self._device.product_id == "ikphogdj":
            return self._mapping.dp_id == 31
        if self._device.product_id == "z1dfsaya":
            return self._mapping.dp_id in (28, 31)
        return False

    def _option_from_datapoint(self) -> str | None:
        datapoint = self._device.datapoints[self._mapping.dp_id]
        if not datapoint:
            return None
        options = self._attr_options or []
        value = datapoint.value
        try:
            int_value = int(value)
        except (TypeError, ValueError):
            return value if isinstance(value, str) and value in options else None
        if 0 <= int_value < len(options):
            return options[int_value]
        return None

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        if self._is_sticky_select():
            return True
        return super().available

    @property
    def current_option(self) -> str | None:
        """Return the selected entity option."""
        option = self._option_from_datapoint()
        if option is not None:
            self._sticky_option = option
            return option
        options = self._attr_options or []
        if self._is_sticky_select() and self._sticky_option in options:
            return self._sticky_option
        return None

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        options = self._attr_options or []
        if option not in options:
            return
        int_value = options.index(option)
        if (
            self._device.product_id == "z1dfsaya"
            and self._mapping.dp_id in (28, 31)
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
        await datapoint.set_value(int_value)
        self._sticky_option = option
        self.async_write_ha_state()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Tuya BLE selects."""
    data: TuyaBLEData = hass.data[DOMAIN][entry.entry_id]
    mappings = get_mapping_by_device(data.device)
    entities = [
        TuyaBLESelect(
            hass,
            data.coordinator,
            data.device,
            data.product,
            mapping,
        )
        for mapping in mappings
        if mapping.force_add
        or data.device.datapoints.has_id(mapping.dp_id, mapping.dp_type)
    ]
    async_add_entities(entities)
