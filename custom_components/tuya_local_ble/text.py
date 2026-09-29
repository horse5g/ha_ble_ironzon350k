"""The Tuya BLE integration."""
from __future__ import annotations

from dataclasses import dataclass
import logging
from struct import pack, unpack
from typing import Callable

from homeassistant.components.text import TextEntity, TextEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .devices import TuyaBLEConfigEntry, TuyaBLEEntity, TuyaBLEProductInfo
from .tuya_ble import TuyaBLEDataPointType, TuyaBLEDevice

_LOGGER = logging.getLogger(__name__)

TuyaBLETextGetter = Callable[["TuyaBLEText", TuyaBLEProductInfo], str | None] | None
TuyaBLETextIsAvailable = Callable[["TuyaBLEText", TuyaBLEProductInfo], bool] | None
TuyaBLETextSetter = Callable[["TuyaBLEText", TuyaBLEProductInfo, str], None] | None


def is_fingerbot_in_program_mode(
    self: TuyaBLEText,
    product: TuyaBLEProductInfo,
) -> bool:
    result = True
    if product.fingerbot:
        datapoint = self._device.datapoints[product.fingerbot.mode]
        if datapoint:
            result = datapoint.value == 2
    return result


def get_fingerbot_program(
    self: TuyaBLEText,
    product: TuyaBLEProductInfo,
) -> str | None:
    result: str | None = None
    if product.fingerbot and product.fingerbot.program:
        datapoint = self._device.datapoints[product.fingerbot.program]
        if datapoint and isinstance(datapoint.value, bytes):
            result = ""
            step_count = datapoint.value[3]
            for step in range(step_count):
                step_pos = 4 + step * 3
                step_data = datapoint.value[step_pos : step_pos + 3]
                position, delay = unpack(">BH", step_data)
                delay = min(delay, 9999)
                result += (
                    (";" if step > 0 else "")
                    + str(position)
                    + (("/" + str(delay)) if delay > 0 else "")
                )
    return result


def set_fingerbot_program(
    self: TuyaBLEText,
    product: TuyaBLEProductInfo,
    value: str,
) -> None:
    if product.fingerbot and product.fingerbot.program:
        datapoint = self._device.datapoints[product.fingerbot.program]
        if datapoint and isinstance(datapoint.value, bytes):
            new_value = bytearray(datapoint.value[0:3])
            steps = value.split(";")
            new_value += int.to_bytes(len(steps), 1, "big")
            for step in steps:
                step_values = step.split("/")
                position = int(step_values[0])
                delay = int(step_values[1]) if len(step_values) > 1 else 0
                new_value += pack(">BH", position, delay)
            self._hass.async_create_task(datapoint.set_value(new_value))


@dataclass
class TuyaBLETextMapping:
    dp_id: int
    description: TextEntityDescription
    force_add: bool = True
    dp_type: TuyaBLEDataPointType | None = None
    default_value: str | None = None
    is_available: TuyaBLETextIsAvailable = None
    getter: TuyaBLETextGetter = None
    setter: TuyaBLETextSetter = None


@dataclass
class TuyaBLECategoryTextMapping:
    products: dict[str, list[TuyaBLETextMapping]] | None = None
    mapping: list[TuyaBLETextMapping] | None = None


mapping: dict[str, TuyaBLECategoryTextMapping] = {
    "szjqr": TuyaBLECategoryTextMapping(
        products={
            **dict.fromkeys(
                ["blliqpsj", "ndvkgsrm", "yiihr7zh", "neq16kgd"],
                [
                    TuyaBLETextMapping(
                        dp_id=121,
                        description=TextEntityDescription(
                            key="program",
                            icon="mdi:repeat",
                            pattern=r"^((\d{1,2}|100)(\/\d{1,2})?)(;((\d{1,2}|100)(\/\d{1,2})?))+$",
                            entity_category=EntityCategory.CONFIG,
                        ),
                        is_available=is_fingerbot_in_program_mode,
                        getter=get_fingerbot_program,
                        setter=set_fingerbot_program,
                    ),
                ],
            ),
        },
    ),
}


def get_mapping_by_device(device: TuyaBLEDevice) -> list[TuyaBLETextMapping]:
    category = mapping.get(device.category)
    if category is None or category.products is None:
        return []
    return category.products.get(device.product_id) or category.mapping or []


class TuyaBLEText(TuyaBLEEntity, TextEntity):
    """Representation of a Tuya BLE text entity."""

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: DataUpdateCoordinator,
        device: TuyaBLEDevice,
        product: TuyaBLEProductInfo,
        mapping: TuyaBLETextMapping,
    ) -> None:
        super().__init__(hass, coordinator, device, product, mapping.description)
        self._mapping = mapping

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        result = super().available
        if result and self._mapping.is_available:
            result = self._mapping.is_available(self, self._product)
        return result

    @property
    def native_value(self) -> str | None:
        """Return the value reported by the text entity."""
        if self._mapping.getter:
            return self._mapping.getter(self, self._product)

        datapoint = self._device.datapoints[self._mapping.dp_id]
        if datapoint:
            return str(datapoint.value)
        return self._mapping.description.default_value

    def set_value(self, value: str) -> None:
        """Change the value."""
        if self._mapping.setter:
            self._mapping.setter(self, self._product, value)
            return
        datapoint = self._device.datapoints.get_or_create(
            self._mapping.dp_id,
            TuyaBLEDataPointType.DT_STRING,
            value,
        )
        if datapoint:
            self._hass.async_create_task(datapoint.set_value(value))


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TuyaBLEConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Tuya BLE text entities."""
    data = entry.runtime_data
    mappings = get_mapping_by_device(data.device)
    async_add_entities(
        TuyaBLEText(
            hass,
            data.coordinator,
            data.device,
            data.product,
            text_mapping,
        )
        for text_mapping in mappings
        if text_mapping.force_add
        or data.device.datapoints.has_id(text_mapping.dp_id, text_mapping.dp_type)
    )
