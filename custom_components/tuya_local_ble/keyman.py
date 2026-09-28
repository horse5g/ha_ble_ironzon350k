"""Credential manager for the Tuya BLE integration."""
from __future__ import annotations

import json
import logging
from typing import Any

from homeassistant.const import CONF_DEVICE_ID
from homeassistant.core import HomeAssistant

from .const import (
    CONF_BLE_UNLOCK_CHECK,
    CONF_CATEGORY,
    CONF_CRED_FILE,
    CONF_DEVICE_NAME,
    CONF_LOCAL_KEY,
    CONF_PRODUCT_ID,
    CONF_PRODUCT_MODEL,
    CONF_PRODUCT_NAME,
    CONF_UUID,
)
from .tuya_ble import (
    AbstaractTuyaBLEDeviceManager,
    TuyaBLEDeviceCredentials,
)

_LOGGER = logging.getLogger(__name__)

CONF_SEC_KEY = "sec_key"

CONF_TUYA_DEVICE_KEYS = [
    CONF_UUID,
    CONF_LOCAL_KEY,
    CONF_DEVICE_ID,
    CONF_CATEGORY,
    CONF_PRODUCT_ID,
    CONF_DEVICE_NAME,
    CONF_PRODUCT_NAME,
    CONF_PRODUCT_MODEL,
    CONF_BLE_UNLOCK_CHECK,
    CONF_SEC_KEY,
]


class HASSTuyaBLEDeviceManager(AbstaractTuyaBLEDeviceManager):
    """Manager for locally stored Tuya BLE device credentials."""

    def __init__(self, hass: HomeAssistant, data: dict[str, Any]) -> None:
        assert hass is not None
        self._hass = hass
        self._data = data
        self._devicedata: dict[str, dict[str, Any]] | None = None

    @staticmethod
    def _read_device_config(path: str) -> dict[str, dict[str, Any]]:
        """Read the credential file outside the Home Assistant event loop."""
        with open(path, encoding="utf-8") as file:
            loaded = json.load(file)
        if not isinstance(loaded, dict):
            raise ValueError("Tuya BLE credential file must contain a JSON object")
        return loaded

    async def load_device_config(self) -> None:
        """Load locally stored device credentials without blocking HA's loop."""
        devicedata_path = self._hass.config.path(CONF_CRED_FILE)
        self._devicedata = await self._hass.async_add_executor_job(
            self._read_device_config, devicedata_path
        )

    async def get_device_credentials(
        self,
        address: str,
        force_update: bool = False,
        save_data: bool = False,
    ) -> TuyaBLEDeviceCredentials | None:
        """Get credentials of a Tuya BLE device."""
        if self._devicedata is None:
            await self.load_device_config()

        credentials = self._devicedata.get(address)
        if not credentials:
            _LOGGER.debug("No local Tuya BLE credentials found for %s", address)
            return None

        _LOGGER.debug("Found local Tuya BLE credentials for %s", address)
        return TuyaBLEDeviceCredentials(
            credentials.get(CONF_UUID, ""),
            credentials.get(CONF_LOCAL_KEY, ""),
            credentials.get(CONF_DEVICE_ID, ""),
            credentials.get(CONF_CATEGORY, ""),
            credentials.get(CONF_PRODUCT_ID, ""),
            credentials.get(CONF_DEVICE_NAME, ""),
            credentials.get(CONF_PRODUCT_MODEL, ""),
            credentials.get(CONF_PRODUCT_NAME, ""),
            credentials.get(CONF_BLE_UNLOCK_CHECK, ""),
            credentials.get(CONF_SEC_KEY, ""),
        )

    @property
    def data(self) -> dict[str, Any]:
        """Return manager configuration data."""
        return self._data
