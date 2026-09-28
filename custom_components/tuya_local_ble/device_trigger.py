"""Experimental device triggers for the YD_350K."""
from __future__ import annotations

import probatio

from homeassistant.components.device_automation import DEVICE_TRIGGER_BASE_SCHEMA
from homeassistant.components.homeassistant.triggers import event as event_trigger
from homeassistant.const import CONF_DEVICE_ID, CONF_DOMAIN, CONF_PLATFORM, CONF_TYPE
from homeassistant.core import CALLBACK_TYPE, HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.trigger import TriggerActionType, TriggerInfo
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, EVENT_350K

TRIGGER_TYPES = {
    "fingerprint_unlock",
    "pin_unlock",
    "bluetooth_unlock",
    "failed_fingerprint",
    "failed_pin",
    "locked",
    "unlocked",
}

TRIGGER_SCHEMA = DEVICE_TRIGGER_BASE_SCHEMA.extend(
    {probatio.Required(CONF_TYPE): probatio.In(TRIGGER_TYPES)}
)


def _is_350k_device(hass: HomeAssistant, device_id: str) -> bool:
    registry_device = dr.async_get(hass).async_get(device_id)
    if registry_device is None:
        return False
    addresses = {
        value
        for domain, value in registry_device.identifiers
        if domain == DOMAIN
    }
    return any(
        data.device.product_id == "z1dfsaya" and data.device.address in addresses
        for data in hass.data.get(DOMAIN, {}).values()
    )


async def async_get_triggers(
    hass: HomeAssistant, device_id: str
) -> list[dict[str, str]]:
    if not _is_350k_device(hass, device_id):
        return []
    base = {
        CONF_PLATFORM: "device",
        CONF_DOMAIN: DOMAIN,
        CONF_DEVICE_ID: device_id,
    }
    return [{CONF_TYPE: trigger_type, **base} for trigger_type in sorted(TRIGGER_TYPES)]


async def async_attach_trigger(
    hass: HomeAssistant,
    config: ConfigType,
    action: TriggerActionType,
    trigger_info: TriggerInfo,
) -> CALLBACK_TYPE:
    event_config = event_trigger.TRIGGER_SCHEMA(
        {
            event_trigger.CONF_PLATFORM: "event",
            event_trigger.CONF_EVENT_TYPE: EVENT_350K,
            event_trigger.CONF_EVENT_DATA: {
                CONF_DEVICE_ID: config[CONF_DEVICE_ID],
                CONF_TYPE: config[CONF_TYPE],
            },
        }
    )
    return await event_trigger.async_attach_trigger(
        hass, event_config, action, trigger_info, platform_type="device"
    )
