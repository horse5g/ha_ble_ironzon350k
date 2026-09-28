"""Local test-harness services for the Tuya BLE integration."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.const import CONF_DEVICE_ID
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN
from .devices import TuyaBLEData

SERVICE_MARK_350K_TEST = "mark_350k_test"
SERVICE_EXPORT_350K_DIAGNOSTICS = "export_350k_diagnostics"

TARGET_SCHEMA = {
    vol.Optional("config_entry_id"): cv.string,
    vol.Optional(CONF_DEVICE_ID): cv.string,
}


def _resolve_350k_data(hass: HomeAssistant, call: ServiceCall) -> TuyaBLEData:
    loaded: dict[str, TuyaBLEData] = hass.data.get(DOMAIN, {})
    entry_id = call.data.get("config_entry_id")
    if entry_id:
        data = loaded.get(entry_id)
        if data is None or data.device.product_id != "z1dfsaya":
            raise HomeAssistantError("Selected config entry is not a loaded 350K lock")
        return data

    device_id = call.data.get(CONF_DEVICE_ID)
    if device_id:
        registry_device = dr.async_get(hass).async_get(device_id)
        if registry_device is None:
            raise HomeAssistantError("Home Assistant device was not found")
        addresses = {
            value
            for domain, value in registry_device.identifiers
            if domain == DOMAIN
        }
        candidates = [
            data
            for data in loaded.values()
            if data.device.product_id == "z1dfsaya"
            and data.device.address in addresses
        ]
    else:
        candidates = [
            data for data in loaded.values() if data.device.product_id == "z1dfsaya"
        ]

    if len(candidates) != 1:
        raise HomeAssistantError(
            "Specify device_id or config_entry_id when more than one 350K lock is loaded"
        )
    return candidates[0]


def async_register_services(hass: HomeAssistant) -> None:
    """Register idempotent domain services."""
    if not hass.services.has_service(DOMAIN, SERVICE_MARK_350K_TEST):
        async def async_mark(call: ServiceCall) -> None:
            data = _resolve_350k_data(hass, call)
            data.device.mark_350k_test(
                call.data["label"],
                call.data.get("note"),
            )

        hass.services.async_register(
            DOMAIN,
            SERVICE_MARK_350K_TEST,
            async_mark,
            schema=vol.Schema(
                {
                    **TARGET_SCHEMA,
                    vol.Required("label"): vol.All(cv.string, vol.Length(min=1, max=64)),
                    vol.Optional("note"): vol.All(cv.string, vol.Length(max=100)),
                }
            ),
        )

    if not hass.services.has_service(DOMAIN, SERVICE_EXPORT_350K_DIAGNOSTICS):
        async def async_export(call: ServiceCall) -> dict[str, Any]:
            data = _resolve_350k_data(hass, call)
            return data.device.sanitized_diagnostics_snapshot()

        hass.services.async_register(
            DOMAIN,
            SERVICE_EXPORT_350K_DIAGNOSTICS,
            async_export,
            schema=vol.Schema(TARGET_SCHEMA),
            supports_response=SupportsResponse.ONLY,
        )
