"""Diagnostics support for the Tuya Local BLE integration."""
from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from .const import PRODUCT_ID_350K
from .devices import TuyaBLEConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: TuyaBLEConfigEntry
) -> dict[str, Any]:
    """Return a shareable diagnostics snapshot for a config entry."""
    data = entry.runtime_data
    device = data.device

    diagnostics: dict[str, Any] = {
        "product": {
            "category": device.category,
            "product_id": device.product_id,
            "product_model": device.product_model,
            "device_version": device.device_version,
            "hardware_version": device.hardware_version,
            "protocol_version": device.protocol_version,
        },
        "runtime": {
            "connected": data.coordinator.connected,
        },
    }

    if device.product_id == PRODUCT_ID_350K:
        # This snapshot intentionally excludes auth keys, credential IDs and raw
        # payload contents. Keep native HA diagnostics aligned with the existing
        # sanitized service response rather than exposing internal device state.
        diagnostics["350k"] = device.sanitized_diagnostics_snapshot()

    return diagnostics
