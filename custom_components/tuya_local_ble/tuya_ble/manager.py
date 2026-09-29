"""Credential manager abstractions for Tuya BLE devices."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class TuyaBLEDeviceCredentials:
    """Locally stored credentials and metadata for a Tuya BLE device."""

    uuid: str
    local_key: str
    device_id: str
    category: str
    product_id: str
    device_name: str | None
    product_model: str | None
    product_name: str | None
    ble_unlock_check: str | None = None
    sec_key: str | None = None

    def __str__(self) -> str:
        """Return a redacted representation safe for ordinary logs."""
        return (
            "uuid: xxxxxxxxxxxxxxxx, "
            "local_key: xxxxxxxxxxxxxxxx, "
            "device_id: xxxxxxxxxxxxxxxx, "
            "category: %s, "
            "product_id: %s, "
            "device_name: %s, "
            "product_model: %s, "
            "product_name: %s, "
            "ble_unlock_check: %s, "
            "sec_key: %s"
        ) % (
            self.category,
            self.product_id,
            self.device_name,
            self.product_model,
            self.product_name,
            "set" if self.ble_unlock_check else "not set",
            "set" if self.sec_key else "not set",
        )


class AbstractTuyaBLEDeviceManager(ABC):
    """Abstract manager for Tuya BLE device credentials."""

    @abstractmethod
    async def get_device_credentials(
        self,
        address: str,
        force_update: bool = False,
        save_data: bool = False,
    ) -> TuyaBLEDeviceCredentials | None:
        """Get credentials for a Tuya BLE device."""
        raise NotImplementedError

    @classmethod
    def check_and_create_device_credentials(
        cls,
        uuid: str | None,
        local_key: str | None,
        device_id: str | None,
        category: str | None,
        product_id: str | None,
        device_name: str | None,
        product_name: str | None,
        product_model: str | None = None,
        ble_unlock_check: str | None = None,
        sec_key: str | None = None,
    ) -> TuyaBLEDeviceCredentials | None:
        """Validate required fields and create a credentials object."""
        if not (uuid and local_key and device_id and category and product_id):
            return None
        return TuyaBLEDeviceCredentials(
            uuid,
            local_key,
            device_id,
            category,
            product_id,
            device_name,
            product_model,
            product_name,
            ble_unlock_check,
            sec_key,
        )


# Compatibility alias for the misspelled name used by the inherited protocol
# implementation and any existing third-party imports. New code should use
# AbstractTuyaBLEDeviceManager.
AbstaractTuyaBLEDeviceManager = AbstractTuyaBLEDeviceManager
