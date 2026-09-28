"""Config flow for Tuya BLE integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import callback

from .const import (
    CONF_KEEP_CONNECTED,
    CONF_PROTOCOL_LOG_LEVEL,
    DOMAIN,
    PROTOCOL_LOG_EVENTS,
    PROTOCOL_LOG_LEVELS,
    PROTOCOL_LOG_OFF,
    PROTOCOL_LOG_RAW,
)
from .devices import get_device_readable_name
from .keyman import HASSTuyaBLEDeviceManager
from .tuya_ble import SERVICE_UUID

_LOGGER = logging.getLogger(__name__)


class TuyaBLEConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Tuya BLE."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        super().__init__()
        self._discovery_info: BluetoothServiceInfoBleak | None = None
        self._discovered_devices: dict[str, BluetoothServiceInfoBleak] = {}
        self._data: dict[str, Any] = {}
        self._manager: HASSTuyaBLEDeviceManager | None = None
        self._get_device_info_error = False

    def _get_manager(self) -> HASSTuyaBLEDeviceManager:
        """Create the credentials manager on first use."""
        if self._manager is None:
            self._manager = HASSTuyaBLEDeviceManager(self.hass, self._data)
        return self._manager

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> OptionsFlow:
        """Get the options flow for this handler."""
        return TuyaBLEOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle setup started manually from the Integrations UI."""
        return await self.async_step_device(user_input)

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle the Bluetooth discovery step."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        self._discovery_info = discovery_info
        manager = self._get_manager()
        self.context["title_placeholders"] = {
            "name": await get_device_readable_name(discovery_info, manager)
        }
        return await self.async_step_device()

    async def async_step_device(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the user step to pick a discovered device."""
        errors: dict[str, str] = {}
        manager = self._get_manager()

        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            discovery_info = self._discovered_devices[address]
            local_name = await get_device_readable_name(discovery_info, manager)
            await self.async_set_unique_id(
                discovery_info.address, raise_on_progress=False
            )
            self._abort_if_unique_id_configured()
            credentials = await manager.get_device_credentials(
                discovery_info.address, self._get_device_info_error, True
            )
            self._data[CONF_ADDRESS] = discovery_info.address
            if credentials is None:
                self._get_device_info_error = True
                errors["base"] = "device_not_registered"
            else:
                return self.async_create_entry(
                    title=local_name,
                    data={CONF_ADDRESS: discovery_info.address},
                    options=self._data,
                )

        if discovery := self._discovery_info:
            self._discovered_devices[discovery.address] = discovery
        else:
            current_addresses = self._async_current_ids()
            for discovery in async_discovered_service_info(self.hass):
                if (
                    discovery.address in current_addresses
                    or discovery.address in self._discovered_devices
                    or discovery.service_data is None
                    or SERVICE_UUID not in discovery.service_data
                ):
                    continue
                self._discovered_devices[discovery.address] = discovery

        if not self._discovered_devices:
            return self.async_abort(reason="no_unconfigured_devices")

        def_address = (
            user_input.get(CONF_ADDRESS)
            if user_input is not None
            else next(iter(self._discovered_devices))
        )

        return self.async_show_form(
            step_id="device",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_ADDRESS,
                        default=def_address,
                    ): vol.In(
                        {
                            service_info.address: await get_device_readable_name(
                                service_info, manager
                            )
                            for service_info in self._discovered_devices.values()
                        }
                    ),
                },
            ),
            errors=errors,
        )


class TuyaBLEOptionsFlow(OptionsFlow):
    """Handle Tuya BLE options."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage options."""
        if user_input is not None:
            # Preserve existing credential/options keys written at setup time.
            options = dict(self.config_entry.options)
            options[CONF_KEEP_CONNECTED] = bool(
                user_input.get(CONF_KEEP_CONNECTED, False)
            )
            protocol_log_level = str(
                user_input.get(CONF_PROTOCOL_LOG_LEVEL, PROTOCOL_LOG_OFF)
            )
            if protocol_log_level not in PROTOCOL_LOG_LEVELS:
                protocol_log_level = PROTOCOL_LOG_OFF
            options[CONF_PROTOCOL_LOG_LEVEL] = protocol_log_level
            return self.async_create_entry(title="", data=options)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_KEEP_CONNECTED,
                        default=bool(
                            self.config_entry.options.get(CONF_KEEP_CONNECTED, False)
                        ),
                    ): bool,
                    vol.Optional(
                        CONF_PROTOCOL_LOG_LEVEL,
                        default=str(
                            self.config_entry.options.get(
                                CONF_PROTOCOL_LOG_LEVEL, PROTOCOL_LOG_OFF
                            )
                        ),
                    ): vol.In(
                        {
                            PROTOCOL_LOG_OFF: "Off",
                            PROTOCOL_LOG_EVENTS: "Parsed events",
                            PROTOCOL_LOG_RAW: "Raw frames + events",
                        }
                    ),
                }
            ),
        )
