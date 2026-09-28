from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import secrets
import time
from collections.abc import Callable
from struct import pack, unpack

from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
from bleak.exc import BleakDBusError
from bleak_retry_connector import BLEAK_BACKOFF_TIME
from bleak_retry_connector import BLEAK_RETRY_EXCEPTIONS
from bleak_retry_connector import (
    BleakClientWithServiceCache,
    BleakError,
    BleakNotFoundError,
    establish_connection,
)
from Crypto.Cipher import AES

from ..const import (
    DP_350K_LAST_ACCESS_EVENT,
    DP_350K_LAST_ACCESS_EVENT_TIME,
    DP_350K_LAST_CREDENTIAL_ID,
    DP_350K_LAST_LOCK_RECORD,
)

from .const import (
    CHARACTERISTIC_NOTIFY,
    CHARACTERISTIC_NOTIFY_FD50,
    CHARACTERISTIC_WRITE,
    CHARACTERISTIC_WRITE_FD50,
    GATT_MTU,
    MANUFACTURER_DATA_ID,
    RESPONSE_WAIT_TIMEOUT,
    SERVICE_UUID,
    TuyaBLECode,
    TuyaBLEDataPointType,
)
from .exceptions import (
    TuyaBLEDataCRCError,
    TuyaBLEDataFormatError,
    TuyaBLEDataLengthError,
    TuyaBLEDeviceError,
    TuyaBLEEnumValueError,
)
from .manager import AbstaractTuyaBLEDeviceManager, TuyaBLEDeviceCredentials

_LOGGER = logging.getLogger(__name__)


BLEAK_EXCEPTIONS = (*BLEAK_RETRY_EXCEPTIONS, OSError)


class TuyaBLEDataPoint:
    def __init__(
        self,
        owner: TuyaBLEDataPoints,
        id: int,
        timestamp: float,
        flags: int,
        type: TuyaBLEDataPointType,
        value: bytes | bool | int | str,
    ) -> None:
        self._owner = owner
        self._id = id
        self._value = value
        self._changed_by_device = False
        self._update_from_device(timestamp, flags, type, value)

    def _update_from_device(
        self,
        timestamp: float,
        flags: int,
        type: TuyaBLEDataPointType,
        value: bytes | bool | int | str,
    ) -> None:
        self._timestamp = timestamp
        self._flags = flags
        self._type = type
        self._changed_by_device = self._value != value
        self._value = value

    def _get_value(self) -> bytes:
        match self._type:
            case TuyaBLEDataPointType.DT_RAW | TuyaBLEDataPointType.DT_BITMAP:
                return self._value
            case TuyaBLEDataPointType.DT_BOOL:
                return pack(">B", 1 if self._value else 0)
            case TuyaBLEDataPointType.DT_VALUE:
                return pack(">i", self._value)
            case TuyaBLEDataPointType.DT_ENUM:
                if self._value > 0xFFFF:
                    return pack(">I", self._value)
                elif self._value > 0xFF:
                    return pack(">H", self._value)
                else:
                    return pack(">B", self._value)
            case TuyaBLEDataPointType.DT_STRING:
                return self._value.encode()

    @property
    def id(self) -> int:
        return self._id

    @property
    def timestamp(self) -> float:
        return self._timestamp

    @property
    def flags(self) -> int:
        return self._flags

    @property
    def type(self) -> TuyaBLEDataPointType:
        return self._type

    @property
    def value(self) -> bytes | bool | int | str:
        return self._value

    @property
    def changed_by_device(self) -> bool:
        return self._changed_by_device

    async def set_value(self, value: bytes | bool | int | str) -> None:
        match self._type:
            case TuyaBLEDataPointType.DT_RAW | TuyaBLEDataPointType.DT_BITMAP:
                self._value = bytes(value)
            case TuyaBLEDataPointType.DT_BOOL:
                self._value = bool(value)
            case TuyaBLEDataPointType.DT_VALUE:
                self._value = int(value)
            case TuyaBLEDataPointType.DT_ENUM:
                value = int(value)
                if value >= 0:
                    self._value = value
                else:
                    raise TuyaBLEEnumValueError()

            case TuyaBLEDataPointType.DT_STRING:
                self._value = str(value)

        self._changed_by_device = False
        await self._owner._update_from_user(self._id)


class TuyaBLEDataPoints:
    def __init__(self, owner: TuyaBLEDevice) -> None:
        self._owner = owner
        self._datapoints: dict[int, TuyaBLEDataPoint] = {}
        self._update_started: int = 0
        self._updated_datapoints: list[int] = []

    def __len__(self) -> int:
        return len(self._datapoints)

    def __getitem__(self, key: int) -> TuyaBLEDataPoint | None:
        return self._datapoints.get(key)

    def has_id(self, id: int, type: TuyaBLEDataPointType | None = None) -> bool:
        return (id in self._datapoints) and (
            (type is None) or (self._datapoints[id].type == type)
        )

    def get_or_create(
        self,
        id: int,
        type: TuyaBLEDataPointType,
        value: bytes | bool | int | str | None = None,
    ) -> TuyaBLEDataPoint:
        datapoint = self._datapoints.get(id)
        if datapoint:
            return datapoint
        datapoint = TuyaBLEDataPoint(self, id, time.time(), 0, type, value)
        self._datapoints[id] = datapoint
        return datapoint

    def begin_update(self) -> None:
        self._update_started += 1

    async def end_update(self) -> None:
        if self._update_started > 0:
            self._update_started -= 1
            if self._update_started == 0 and len(self._updated_datapoints) > 0:
                await self._owner._send_datapoints(self._updated_datapoints)
                self._updated_datapoints = []

    def _update_from_device(
        self,
        dp_id: int,
        timestamp: float,
        flags: int,
        type: TuyaBLEDataPointType,
        value: bytes | bool | int | str,
    ) -> None:
        dp = self._datapoints.get(dp_id)
        if dp:
            dp._update_from_device(timestamp, flags, type, value)
        else:
            self._datapoints[dp_id] = TuyaBLEDataPoint(
                self, dp_id, timestamp, flags, type, value
            )

    async def _update_from_user(self, dp_id: int) -> None:
        if self._update_started > 0:
            if dp_id in self._updated_datapoints:
                self._updated_datapoints.remove(dp_id)
            self._updated_datapoints.append(dp_id)
        else:
            await self._owner._send_datapoints([dp_id])


global_connect_lock = asyncio.Lock()


class TuyaBLEDevice:
    def __init__(
        self,
        device_manager: AbstaractTuyaBLEDeviceManager,
        ble_device: BLEDevice,
        advertisement_data: AdvertisementData | None = None,
    ) -> None:
        """Init the TuyaBLE."""
        self._device_manager = device_manager
        self._device_info: TuyaBLEDeviceCredentials | None = None
        self._ble_device = ble_device
        self._advertisement_data = advertisement_data
        self._operation_lock = asyncio.Lock()
        self._connect_lock = asyncio.Lock()
        # YD_350K control writes can take many seconds to acknowledge.
        # Keep a separate fail-fast lock so repeated HA UI clicks do not build
        # an unbounded queue of stale control writes behind _operation_lock.
        self._350k_control_lock = asyncio.Lock()
        self._client: BleakClientWithServiceCache | None = None
        self._expected_disconnect = False
        self._connected_callbacks: list[Callable[[], None]] = []
        self._callbacks: list[Callable[[list[TuyaBLEDataPoint]], None]] = []
        self._disconnected_callbacks: list[Callable[[], None]] = []
        self._current_seq_num = 1
        self._seq_num_lock = asyncio.Lock()

        self._characteristic_notify = CHARACTERISTIC_NOTIFY
        self._characteristic_write = CHARACTERISTIC_WRITE
        self._uses_fd50_channel = False

        self._is_bound = False
        self._flags = 0
        self._protocol_version = 2

        self._device_version: str = ""
        self._protocol_version_str: str = ""
        self._hardware_version: str = ""

        self._device_info: TuyaBLEDeviceCredentials | None = None

        self._auth_key: bytes | None = None

        # Legacy Tuya BLE key: first 6 bytes. Keep this for existing devices
        # and pairing behavior that still uses the legacy key form.
        self._local_key: bytes | None = None

        # Newer TuyaOS 0x0e/0x0f security credentials.
        self._local_key_full: bytes | None = None
        self._sec_key: bytes | None = None

        self._login_key: bytes | None = None
        self._session_key: bytes | None = None

        self._is_paired = False

        self._input_buffer: bytearray | None = None
        self._input_expected_packet_num = 0
        self._input_expected_length = 0
        self._input_expected_responses: dict[int,
                                             asyncio.Future[int] | None] = {}
        # self._input_future: asyncio.Future[int] | None = None

        self._datapoints = TuyaBLEDataPoints(self)

        # Local-only UI-controlled protocol diagnostics for the 350K. This does
        # not write anything to the lock and is intentionally off by default.
        self._verbose_logging = False

        # Optional YD_350K connection keeper. The lock is much more responsive
        # when the authenticated BLE session is already alive, so when enabled
        # we send a low-frequency DEVICE_STATUS request only after a long period
        # with no received BLE traffic. It never forces a new connection on its
        # own; normal reconnect handling remains responsible for that.
        self._350k_keepalive_enabled = False
        self._350k_keepalive_task: asyncio.Task | None = None
        self._350k_last_rx_monotonic = time.monotonic()

    def set_ble_device_and_advertisement_data(
        self, ble_device: BLEDevice, advertisement_data: AdvertisementData
    ) -> None:
        """Set the ble device."""
        self._ble_device = ble_device
        self._advertisement_data = advertisement_data

    async def initialize(self) -> None:
        _LOGGER.debug("%s: Initializing", self.address)
        if await self._update_device_info():
            self._decode_advertisement_data()
            
    def _build_pairing_request(self) -> bytes:
        result = bytearray()

        result += self._device_info.uuid.encode()
        result += self._local_key
        result += self._device_info.device_id.encode()
        for _ in range(44 - len(result)):
            result += b"\x00"

        return result

    async def pair(self) -> None:
        """
        _LOGGER.debug("%s: Sending pairing request: %s",
            self.address, data.hex()
        )
        """
        await self._send_packet(
            TuyaBLECode.FUN_SENDER_PAIR, self._build_pairing_request()
        )

    async def update(self) -> None:
        _LOGGER.debug("%s: Updating", self.address)
        await self._send_packet(TuyaBLECode.FUN_SENDER_DEVICE_STATUS, bytes())

    async def _update_device_info(self) -> bool:
        if self._device_info is None:
            if self._device_manager:
                self._device_info = await self._device_manager.get_device_credentials(
                    self._ble_device.address, False
                )
            if self._device_info:
                # Preserve the legacy first-six-byte key for existing devices
                # and the pairing request.
                self._local_key = self._device_info.local_key[:6].encode()

                if self._device_info.product_id == "z1dfsaya":
                    self._local_key_full = self._device_info.local_key.encode()
                    self._sec_key = (self._device_info.sec_key or "").encode()

                    if len(self._local_key_full) != 16:
                        raise TuyaBLEDeviceError(
                            "z1dfsaya requires a 16-byte full local_key"
                        )

                    if len(self._sec_key) != 16:
                        raise TuyaBLEDeviceError(
                            "z1dfsaya requires a 16-byte sec_key"
                        )

                    # Tuya security flag 0x0e.
                    # Verified against the official app's captured request.
                    self._login_key = hashlib.md5(
                        self._local_key_full + self._sec_key
                    ).digest()

                    _LOGGER.debug(
                        "%s: Using TuyaOS 0x0e/0x0f security credentials",
                        self.address,
                    )
                else:
                    self._login_key = hashlib.md5(self._local_key).digest()

        return self._device_info is not None

    def _decode_advertisement_data(self) -> None:
        raw_product_id: bytes | None = None
        # raw_product_key: bytes | None = None
        raw_uuid: bytes | None = None
        if self._advertisement_data:
            if self._advertisement_data.service_data:
                service_data = self._advertisement_data.service_data.get(
                    SERVICE_UUID)
                if service_data and len(service_data) > 1:
                    match service_data[0]:
                        case 0:
                            raw_product_id = service_data[1:]
                        # case 1:
                        #    raw_product_key = service_data[1:]

            if self._advertisement_data.manufacturer_data:
                manufacturer_data = self._advertisement_data.manufacturer_data.get(
                    MANUFACTURER_DATA_ID
                )
                if manufacturer_data and len(manufacturer_data) > 6:
                    self._is_bound = (manufacturer_data[0] & 0x80) != 0
                    self._protocol_version = manufacturer_data[1]
                    raw_uuid = manufacturer_data[6:]
                    if raw_product_id:
                        key = hashlib.md5(raw_product_id).digest()
                        cipher = AES.new(key, AES.MODE_CBC, key)
                        raw_uuid = cipher.decrypt(raw_uuid)
                        self._uuid = raw_uuid.decode("utf-8")

    @property
    def address(self) -> str:
        """Return the address."""
        return self._ble_device.address

    @property
    def name(self) -> str:
        """Get the name of the device."""
        if self._device_info:
            return self._device_info.device_name
        else:
            return self._ble_device.name or self._ble_device.address

    @property
    def rssi(self) -> int | None:
        """Get the rssi of the device."""
        if self._advertisement_data:
            return self._advertisement_data.rssi
        return None

    @property
    def uuid(self) -> str:
        if self._device_info is not None:
            return self._device_info.uuid
        else:
            return ""

    @property
    def local_key(self) -> str:
        if self._device_info is not None:
            return self._device_info.local_key
        else:
            return ""

    @property
    def category(self) -> str:
        if self._device_info is not None:
            return self._device_info.category
        else:
            return ""

    @property
    def device_id(self) -> str:
        if self._device_info is not None:
            return self._device_info.device_id
        else:
            return ""

    @property
    def product_id(self) -> str:
        if self._device_info is not None:
            return self._device_info.product_id
        else:
            return ""

    @property
    def product_model(self) -> str:
        if self._device_info is not None:
            return self._device_info.product_model
        else:
            return ""

    @property
    def product_name(self) -> str:
        if self._device_info is not None:
            return self._device_info.product_name
        else:
            return ""

    @property
    def ble_unlock_check(self) -> str:
        if self._device_info is not None and self._device_info.ble_unlock_check:
            return self._device_info.ble_unlock_check
        else:
            return ""

    @property
    def device_version(self) -> str:
        return self._device_version

    @property
    def hardware_version(self) -> str:
        return self._hardware_version

    @property
    def protocol_version(self) -> str:
        return self._protocol_version_str

    @property
    def datapoints(self) -> TuyaBLEDataPoints:
        """Get datapoints exposed by device."""
        return self._datapoints

    @property
    def verbose_logging(self) -> bool:
        """Return whether local 350K protocol diagnostics are enabled."""
        return self._verbose_logging

    def set_verbose_logging(self, enabled: bool) -> None:
        """Enable or disable local 350K protocol diagnostics."""
        enabled = bool(enabled)
        if self._verbose_logging == enabled:
            return
        self._verbose_logging = enabled
        _LOGGER.info(
            "%s: 350K verbose protocol logging %s",
            self.address,
            "enabled" if enabled else "disabled",
        )

    def _log_350k_verbose(self, message: str, *args: object) -> None:
        """Emit opt-in 350K protocol detail without changing global log level."""
        if self.product_id == "z1dfsaya" and self._verbose_logging:
            _LOGGER.info(message, *args)

    @property
    def keepalive_enabled(self) -> bool:
        """Return whether the local 350K BLE connection keeper is enabled."""
        return self._350k_keepalive_enabled

    def set_keepalive_enabled(self, enabled: bool) -> None:
        """Enable or disable the local 350K BLE connection keeper."""
        enabled = bool(enabled)
        if self._350k_keepalive_enabled == enabled:
            return
        self._350k_keepalive_enabled = enabled
        _LOGGER.info(
            "%s: 350K BLE connection keeper %s",
            self.address,
            "enabled" if enabled else "disabled",
        )
        if enabled:
            self._ensure_350k_keepalive_task()
        else:
            self._cancel_350k_keepalive_task()

    def _ensure_350k_keepalive_task(self) -> None:
        """Start the 350K keeper task if needed."""
        if self.product_id != "z1dfsaya" or not self._350k_keepalive_enabled:
            return
        if self._350k_keepalive_task is not None and not self._350k_keepalive_task.done():
            return
        self._350k_keepalive_task = asyncio.create_task(
            self._350k_keepalive_loop(),
            name=f"tuya_ble_350k_keepalive_{self.address}",
        )

    def _cancel_350k_keepalive_task(self) -> None:
        """Cancel the 350K keeper task."""
        task = self._350k_keepalive_task
        self._350k_keepalive_task = None
        if task is not None and not task.done():
            task.cancel()

    async def _350k_keepalive_loop(self) -> None:
        """Keep an already-open 350K BLE session from going idle.

        This task deliberately does not connect a sleeping or unreachable lock.
        It only sends DEVICE_STATUS when an existing paired connection has
        received no traffic for 120 seconds.

        Real control writes and protocol replies always take priority; if either
        operation lock is busy the keeper simply tries again on the next pass.
        """
        try:
            while self._350k_keepalive_enabled:
                await asyncio.sleep(10)

                if (
                    self.product_id != "z1dfsaya"
                    or self._expected_disconnect
                    or self._client is None
                    or not self._client.is_connected
                    or not self._is_paired
                ):
                    continue

                idle_seconds = time.monotonic() - self._350k_last_rx_monotonic
                if idle_seconds < 120:
                    continue

                if self._operation_lock.locked() or self._350k_control_lock.locked():
                    continue

                _LOGGER.debug(
                    "%s: 350K keepalive after %.1fs idle",
                    self.address,
                    idle_seconds,
                )
                try:
                    ok = await self._send_packet_while_connected(
                        TuyaBLECode.FUN_SENDER_DEVICE_STATUS,
                        bytes(),
                        0,
                        True,
                    )
                    if not ok:
                        _LOGGER.warning(
                            "%s: 350K keepalive was not acknowledged",
                            self.address,
                        )
                except asyncio.CancelledError:
                    raise
                except BLEAK_EXCEPTIONS:
                    _LOGGER.debug(
                        "%s: 350K keepalive BLE error",
                        self.address,
                        exc_info=True,
                    )
                except Exception:
                    _LOGGER.exception(
                        "%s: Unexpected 350K keepalive error",
                        self.address,
                    )
        except asyncio.CancelledError:
            pass
        finally:
            current = asyncio.current_task()
            if self._350k_keepalive_task is current:
                self._350k_keepalive_task = None

    def get_or_create_datapoint(
        self,
        id: int,
        type: TuyaBLEDataPointType,
        value: bytes | bool | int | str | None = None,
    ) -> TuyaBLEDataPoint:
        """Get datapoints exposed by device."""

    def _fire_connected_callbacks(self) -> None:
        """Fire the callbacks."""
        for callback in self._connected_callbacks:
            callback()

    def register_connected_callback(
        self, callback: Callable[[], None]
    ) -> Callable[[], None]:
        """Register a callback to be called when device disconnected."""

        def unregister_callback() -> None:
            self._connected_callbacks.remove(callback)

        self._connected_callbacks.append(callback)
        return unregister_callback

    def _fire_callbacks(self, datapoints: list[TuyaBLEDataPoint]) -> None:
        """Fire the callbacks."""
        for callback in self._callbacks:
            callback(datapoints)

    def register_callback(
        self,
        callback: Callable[[list[TuyaBLEDataPoint]], None],
    ) -> Callable[[], None]:
        """Register a callback to be called when the state changes."""

        def unregister_callback() -> None:
            self._callbacks.remove(callback)

        self._callbacks.append(callback)
        return unregister_callback

    def _fire_disconnected_callbacks(self) -> None:
        """Fire the callbacks."""
        for callback in self._disconnected_callbacks:
            callback()

    def register_disconnected_callback(
        self, callback: Callable[[], None]
    ) -> Callable[[], None]:
        """Register a callback to be called when device disconnected."""

        def unregister_callback() -> None:
            self._disconnected_callbacks.remove(callback)

        self._disconnected_callbacks.append(callback)
        return unregister_callback

    async def start(self):
        """Start the TuyaBLE."""
        _LOGGER.debug("%s: Starting...", self.address)
        # await self._send_packet()

    async def stop(self) -> None:
        """Stop the TuyaBLE."""
        _LOGGER.debug("%s: Stop", self.address)
        self._cancel_350k_keepalive_task()
        await self._execute_disconnect()

    def _disconnected(self, client: BleakClientWithServiceCache) -> None:
        """Disconnected callback."""
        was_paired = self._is_paired
        self._is_paired = False
        self._fire_disconnected_callbacks()
        if self._expected_disconnect:
            _LOGGER.debug(
                "%s: Disconnected from device; RSSI: %s",
                self.address,
                self.rssi,
            )
            return
        self._client = None
        _LOGGER.debug(
            "%s: Device unexpectedly disconnected; RSSI: %s",
            self.address,
            self.rssi,
        )
        if was_paired:
            _LOGGER.debug(
                "%s: Scheduling reconnect; RSSI: %s",
                self.address,
                self.rssi,
            )
            asyncio.create_task(self._reconnect())

    def _disconnect(self) -> None:
        """Disconnect from device."""
        asyncio.create_task(self._execute_timed_disconnect())

    async def _execute_timed_disconnect(self) -> None:
        """Execute timed disconnection."""
        _LOGGER.debug(
            "%s: Disconnecting",
            self.address,
        )
        await self._execute_disconnect()

    async def _execute_disconnect(self) -> None:
        """Execute disconnection."""
        async with self._connect_lock:
            client = self._client
            self._expected_disconnect = True
            self._client = None
            if client and client.is_connected:
                await client.stop_notify(self._characteristic_notify)
                await client.disconnect()
        async with self._seq_num_lock:
            self._current_seq_num = 1

    def _select_characteristics(self, client: BleakClientWithServiceCache) -> None:
        """Select the GATT channel actually exposed by the device."""
        if client.services.get_characteristic(CHARACTERISTIC_NOTIFY):
            self._characteristic_notify = CHARACTERISTIC_NOTIFY
            self._characteristic_write = CHARACTERISTIC_WRITE
        elif client.services.get_characteristic(CHARACTERISTIC_NOTIFY_FD50):
            _LOGGER.debug(
                "%s: legacy characteristics not present,"
                " using FD50 GATT channel",
                self.address,
            )
            self._characteristic_notify = CHARACTERISTIC_NOTIFY_FD50
            self._characteristic_write = CHARACTERISTIC_WRITE_FD50
            self._uses_fd50_channel = True

    async def _ensure_connected(self) -> None:
        """Ensure connection to device is established."""
        global global_connect_lock
        if self._expected_disconnect:
            return
        if self._connect_lock.locked():
            _LOGGER.debug(
                "%s: Connection already in progress,"
                " waiting for it to complete; RSSI: %s",
                self.address,
                self.rssi,
            )
        if self._client and self._client.is_connected and self._is_paired:
            return
        async with self._connect_lock:
            # Check again while holding the lock
            await asyncio.sleep(0.01)
            if self._client and self._client.is_connected and self._is_paired:
                return
            attempts_count = 3
            while attempts_count > 0:
                attempts_count -= 1
                if attempts_count == 0:
                    _LOGGER.error(
                        "%s: Connecting, all attempts failed; RSSI: %s",
                        self.address,
                        self.rssi,
                    )
                    raise BleakNotFoundError()
                try:
                    async with global_connect_lock:
                        _LOGGER.debug(
                            "%s: Connecting; RSSI: %s", self.address, self.rssi
                        )
                        client = await establish_connection(
                            BleakClientWithServiceCache,
                            self._ble_device,
                            self.address,
                            self._disconnected,
                            use_services_cache=True,
                            ble_device_callback=lambda: self._ble_device,
                        )
                except BleakNotFoundError:
                    _LOGGER.error(
                        "%s: device not found, not in range, or poor RSSI: %s",
                        self.address,
                        self.rssi,
                        exc_info=True,
                    )
                    continue
                except BLEAK_EXCEPTIONS:
                    _LOGGER.debug(
                        "%s: communication failed", self.address, exc_info=True
                    )
                    continue
                except:
                    _LOGGER.debug("%s: unexpected error",
                                  self.address, exc_info=True)
                    continue

                if client and client.is_connected:
                    _LOGGER.debug("%s: Connected; RSSI: %s",
                                  self.address, self.rssi)
                    self._client = client
                    self._select_characteristics(client)
                    try:
                        await self._client.start_notify(
                            self._characteristic_notify,
                            self._notification_handler,
                            bluez={"use_start_notify": True},
                        )
                    except:  # [BLEAK_EXCEPTIONS, BleakNotFoundError]:
                        self._client = None
                        _LOGGER.error("%s: starting notifications failed",
                                      self.address, exc_info=True)
                        continue
                else:
                    continue

                if self._client and self._client.is_connected:
                    _LOGGER.debug(
                        "%s: Sending device info request", self.address)
                    try:
                        # Any device negotiating the FD50 GATT channel needs the
                        # same TuyaOS device-info handshake as hc7n0urm/ikphogdj.
                        device_info_payload = (
                            b"\x00\xf3"
                            if (
                                self.product_id in ("hc7n0urm", "ikphogdj")
                                or self._uses_fd50_channel
                            )
                            else bytes(0)
                        )
                        if not await self._send_packet_while_connected(
                            TuyaBLECode.FUN_SENDER_DEVICE_INFO,
                            device_info_payload,
                            0,
                            True,
                        ):
                            self._client = None
                            _LOGGER.error(
                                "%s: Sending device info request failed",
                                self.address,
                            )
                            continue
                    except:  # [BLEAK_EXCEPTIONS, BleakNotFoundError]:
                        self._client = None
                        _LOGGER.error("%s: Sending device info request failed",
                                      self.address, exc_info=True)
                        continue
                else:
                    continue

                if self._client and self._client.is_connected:
                    _LOGGER.debug("%s: Sending pairing request", self.address)
                    try:
                        if not await self._send_packet_while_connected(
                            TuyaBLECode.FUN_SENDER_PAIR,
                            self._build_pairing_request(),
                            0,
                            True,
                        ):
                            self._client = None
                            _LOGGER.error(
                                "%s: Sending pairing request failed",
                                self.address,
                            )
                            continue
                    except:  # [BLEAK_EXCEPTIONS, BleakNotFoundError]:
                        self._client = None
                        _LOGGER.error("%s: Sending pairing request failed",
                                      self.address, exc_info=True)
                        continue
                else:
                    continue

                break

        if self._client:
            if self._client.is_connected:
                if self._is_paired:
                    _LOGGER.debug("%s: Successfully connected", self.address)
                    self._fire_connected_callbacks()
                    self._ensure_350k_keepalive_task()
                else:
                    _LOGGER.error("%s: Connected but not paired", self.address)
            else:
                _LOGGER.error("%s: Not connected", self.address)
        else:
            _LOGGER.error("%s: No client device", self.address)

    async def _reconnect(self) -> None:
        """Attempt a reconnect"""
        _LOGGER.debug("%s: Reconnect, ensuring connection", self.address)
        async with self._seq_num_lock:
            self._current_seq_num = 1
        try:
            if self._expected_disconnect:
                return
            await self._ensure_connected()
            if self._expected_disconnect:
                return
            _LOGGER.debug("%s: Reconnect, connection ensured", self.address)
        except BLEAK_EXCEPTIONS:  # BleakNotFoundError:
            _LOGGER.debug(
                "%s: Reconnect, failed to ensure connection - backing off",
                self.address,
                exc_info=True,
            )
            await asyncio.sleep(BLEAK_BACKOFF_TIME)
            _LOGGER.debug("%s: Reconnecting again", self.address)
            asyncio.create_task(self._reconnect())

    @staticmethod
    def _calc_crc16(data: bytes) -> int:
        crc = 0xFFFF
        for byte in data:
            crc ^= byte & 255
            for _ in range(8):
                tmp = crc & 1
                crc >>= 1
                if tmp != 0:
                    crc ^= 0xA001
        return crc

    @staticmethod
    def _pack_int(value: int) -> bytearray:
        curr_byte: int
        result = bytearray()
        while True:
            curr_byte = value & 0x7F
            value >>= 7
            if value != 0:
                curr_byte |= 0x80
            result += pack(">B", curr_byte)
            if value == 0:
                break
        return result

    @staticmethod
    def _unpack_int(data: bytes, start_pos: int) -> tuple(int, int):
        result: int = 0
        offset: int = 0
        while offset < 5:
            pos: int = start_pos + offset
            if pos >= len(data):
                raise TuyaBLEDataFormatError()
            curr_byte: int = data[pos]
            result |= (curr_byte & 0x7F) << (offset * 7)
            offset += 1
            if (curr_byte & 0x80) == 0:
                break
        if offset > 4:
            raise TuyaBLEDataFormatError()
        else:
            return (result, start_pos + offset)

    def _build_packets(
        self,
        seq_num: int,
        code: TuyaBLECode,
        data: bytes,
        response_to: int = 0,
    ) -> list[bytes]:
        key: bytes
        iv = secrets.token_bytes(16)
        security_flag: bytes
        if code == TuyaBLECode.FUN_SENDER_DEVICE_INFO:
            key = self._login_key
            security_flag = (
                b"\x0e"
                if self.product_id == "z1dfsaya"
                else b"\x04"
            )
        else:
            key = self._session_key
            security_flag = (
                b"\x0f"
                if self.product_id == "z1dfsaya"
                else b"\x05"
            )

        raw = bytearray()
        raw += pack(">IIHH", seq_num, response_to, code.value, len(data))
        raw += data
        crc = self._calc_crc16(raw)
        raw += pack(">H", crc)
        while len(raw) % 16 != 0:
            raw += b"\x00"

        cipher = AES.new(key, AES.MODE_CBC, iv)
        encrypted = security_flag + iv + cipher.encrypt(raw)

        command = []
        packet_num = 0
        pos = 0
        length = len(encrypted)
        while pos < length:
            packet = bytearray()
            packet += self._pack_int(packet_num)

            if packet_num == 0:
                packet += self._pack_int(length)
                packet_protocol_version = self._protocol_version
                
                if self.product_id == "z1dfsaya":
                    packet_protocol_version = 2
                elif code == TuyaBLECode.FUN_SENDER_DEVICE_INFO and (
                    self.product_id in ("hc7n0urm", "ikphogdj") or self._uses_fd50_channel
                ):
                    packet_protocol_version = 2
                packet += pack(">B", packet_protocol_version << 4)

                chunk_mtu = GATT_MTU
                if (
                    code == TuyaBLECode.FUN_SENDER_DEVICE_INFO
                    and self.product_id != "ikphogdj"
                    and (
                        self.product_id in ("hc7n0urm")
                        or self._uses_fd50_channel
                    )
                ):
                    # TuyaOS FD50 locks use MTU exchange and expect DEVICE_INFO
                    # in one write. ikphogdj is the known 20-byte exception.
                    chunk_mtu = 244
            data_part = encrypted[
                pos:pos + chunk_mtu - len(packet)  # fmt: skip
            ]
            packet += data_part
            command.append(packet)

            pos += len(data_part)
            packet_num += 1

        return command

    @property
    def control_busy(self) -> bool:
        """Return whether a YD_350K configuration write is in progress."""
        return self._350k_control_lock.locked()

    def _build_350k_v4_bool_data(self, dp_id: int, value: bool) -> bytes:
        """Build a YD_350K one-byte boolean V4 control write.

        This is deliberately built from the requested value instead of the
        cached datapoint.  The cache therefore continues to represent the last
        value actually reported by the lock and is not changed optimistically.
        """
        if dp_id not in (33, 46, 79):
            raise TuyaBLEDeviceError(0)
        return (
            b"\x00\x00\x00\x00\x01"
            + bytes([dp_id, int(TuyaBLEDataPointType.DT_BOOL.value)])
            + b"\x00\x01"
            + bytes([1 if value else 0])
        )

    async def set_350k_bool_datapoint(self, dp_id: int, value: bool) -> bool:
        """Write one YD_350K boolean control datapoint.

        Only one DP33/DP46/DP79 operation is allowed at a time.  Extra UI clicks
        while an operation is pending are ignored instead of queued.  The
        local datapoint cache is left untouched until the peripheral reports
        its new state through the normal notification parser.
        """
        if self.product_id != "z1dfsaya" or dp_id not in (33, 46, 79):
            raise TuyaBLEDeviceError(0)

        if self._350k_control_lock.locked():
            _LOGGER.warning(
                "%s: Ignoring 350K DP%s=%s; another control operation is still pending",
                self.address,
                dp_id,
                value,
            )
            return False

        async with self._350k_control_lock:
            payload = self._build_350k_v4_bool_data(dp_id, value)
            _LOGGER.debug(
                "%s: Sending 350K control update, id: %s, value: %s",
                self.address,
                dp_id,
                value,
            )
            try:
                await self._ensure_connected()
                if (
                    self._expected_disconnect
                    or self._client is None
                    or not self._client.is_connected
                ):
                    _LOGGER.warning(
                        "%s: 350K DP%s write aborted; device is not connected",
                        self.address,
                        dp_id,
                    )
                    return False

                result = await self._send_packet_while_connected(
                    TuyaBLECode.FUN_SENDER_DPS_V4,
                    payload,
                    0,
                    True,
                )
                if not result:
                    _LOGGER.warning(
                        "%s: 350K DP%s=%s was not acknowledged",
                        self.address,
                        dp_id,
                        value,
                    )
                    return False

                # The device normally pushes the resulting DP state
                # immediately after the command ACK. Do not hold the HA service
                # call open for an arbitrary linger delay; the notification
                # parser will update the entity asynchronously.
                return True
            except BLEAK_EXCEPTIONS:
                _LOGGER.warning(
                    "%s: 350K DP%s=%s write failed due to BLE communication error",
                    self.address,
                    dp_id,
                    value,
                    exc_info=True,
                )
                return False
            except Exception:
                _LOGGER.exception(
                    "%s: Unexpected error writing 350K DP%s=%s",
                    self.address,
                    dp_id,
                    value,
                )
                return False

    async def linger_connected(self, seconds: int, ping_interval: int = 10) -> None:
        """Stay connected for a bounded window, purely passive - no requests
        of our own. Sending our own traffic here risks colliding with the
        device's own asynchronous pushes (e.g. a multi-fragment battery
        report), corrupting the shared packet-reassembly state. This just
        gives such pushes a window to arrive; it does not actively prevent
        the peripheral's own idle-disconnect timer from firing.

        General-purpose utility, not product-specific. Currently only
        called from ikphogdj (HL Knob-2) code paths.
        """
        elapsed = 0
        while elapsed < seconds:
            wait = min(ping_interval, seconds - elapsed)
            await asyncio.sleep(wait)
            elapsed += wait
            if self._expected_disconnect or self._client is None or not self._client.is_connected:
                return

    async def _get_seq_num(self) -> int:
        async with self._seq_num_lock:
            result = self._current_seq_num
            self._current_seq_num += 1
        return result

    async def _send_packet(
        self,
        code: TuyaBLECode,
        data: bytes,
        wait_for_response: bool = True,
        # retry: int | None = None,
    ) -> None:
        """Send packet to device and optional read response."""
        if self._expected_disconnect:
            return
        await self._ensure_connected()
        if self._expected_disconnect:
            return
        await self._send_packet_while_connected(code, data, 0, wait_for_response)

    async def _send_response(
        self,
        code: TuyaBLECode,
        data: bytes,
        response_to: int,
    ) -> None:
        """Send response to received packet."""
        if self._client and self._client.is_connected:
            await self._send_packet_while_connected(code, data, response_to, False)

    async def _send_packet_while_connected(
        self,
        code: TuyaBLECode,
        data: bytes,
        response_to: int,
        wait_for_response: bool,
        # retry: int | None = None
    ) -> bool:
        """Send packet to device and optional read response."""
        # General concurrency fix (not product-specific): the lock used to
        # only cover the write below, released before awaiting the
        # response - so two overlapping commands (e.g. a fast double lock
        # press) could interleave their response tracking and corrupt the
        # shared reassembly state. Now covers the full send-and-wait cycle.
        async with self._operation_lock:
            return await self._send_packet_while_connected_locked(
                code, data, response_to, wait_for_response
            )

    async def _send_packet_while_connected_locked(
        self,
        code: TuyaBLECode,
        data: bytes,
        response_to: int,
        wait_for_response: bool,
    ) -> bool:
        result = True
        future: asyncio.Future | None = None
        seq_num = await self._get_seq_num()
        if wait_for_response:
            future = asyncio.Future()
            self._input_expected_responses[seq_num] = future

        if response_to > 0:
            _LOGGER.debug(
                "%s: Sending packet: #%s %s in response to #%s",
                self.address,
                seq_num,
                code.name,
                response_to,
            )
        else:
            _LOGGER.debug(
                "%s: Sending packet: #%s %s",
                self.address,
                seq_num,
                code.name,
            )
        packets: list[bytes] = self._build_packets(
            seq_num, code, data, response_to)
        await self._int_send_packet_while_connected(packets)
        if future:
            try:
                await asyncio.wait_for(future, RESPONSE_WAIT_TIMEOUT)
            except asyncio.TimeoutError:
                _LOGGER.error(
                    "%s: timeout receiving response, RSSI: %s",
                    self.address,
                    self.rssi,
                )
                result = False
            self._input_expected_responses.pop(seq_num, None)

        return result

    async def _int_send_packet_while_connected(
        self,
        packets: list[bytes],
    ) -> None:
        # The operation_lock acquire/wait-and-log block used to be here but is
        # disabled: product_id ikphogdj doesn't work if this code is enabled
        # (causes a race condition on rare-event concurrent calls).
        try:
            await self._send_packets_locked(packets)
        except BleakNotFoundError:
            _LOGGER.error(
                "%s: device not found, no longer in range, or poor RSSI: %s",
                self.address,
                self.rssi,
                exc_info=True,
            )
            raise
        except BLEAK_EXCEPTIONS:
            _LOGGER.error(
                "%s: communication failed",
                self.address,
                exc_info=True,
            )
            raise

    async def _resend_packets(self, packets: list[bytes]) -> None:
        if self._expected_disconnect:
            return
        await self._ensure_connected()
        if self._expected_disconnect:
            return
        await self._int_send_packet_while_connected(packets)

    async def _send_packets_locked(self, packets: list[bytes]) -> None:
        """Send command to device and read response."""
        try:
            await self._int_send_packets_locked(packets)
        except BleakDBusError as ex:
            # Disconnect so we can reset state and try again
            await asyncio.sleep(BLEAK_BACKOFF_TIME)
            _LOGGER.debug(
                "%s: RSSI: %s; Backing off %ss; Disconnecting due to error: %s",
                self.address,
                self.rssi,
                BLEAK_BACKOFF_TIME,
                ex,
            )
            if self._is_paired:
                asyncio.create_task(self._resend_packets(packets))
            else:
                asyncio.create_task(self._reconnect())
            raise BleakError from ex
        except BleakError as ex:
            # Disconnect so we can reset state and try again
            _LOGGER.debug(
                "%s: RSSI: %s; Disconnecting due to error: %s",
                self.address,
                self.rssi,
                ex,
            )
            if self._is_paired:
                asyncio.create_task(self._resend_packets(packets))
            else:
                asyncio.create_task(self._reconnect())
            raise

    async def _int_send_packets_locked(self, packets: list[bytes]) -> None:
        """Execute command and read response."""
        for packet in packets:
            if self._client:
                try:
                    if self.product_id != "z1dfsaya" or self._verbose_logging:
                        _LOGGER.debug(
                            "%s: Sending packet: %s", self.address, packet.hex()
                        )
                    await self._client.write_gatt_char(
                        self._characteristic_write,
                        packet,
                        False,
                    )
                except:
                    _LOGGER.error(
                        "%s: Error during sending packet",
                        self.address,
                        exc_info=True,
                    )
                    if self._client and self._client.is_connected:
                        self._disconnected(self._client)
                    raise BleakError()
            else:
                _LOGGER.error(
                    "%s: Client disconnected during sending packet",
                    self.address,
                    exc_info=True,
                )
                raise BleakError()

    def _get_key(self, security_flag: int) -> bytes:
        if security_flag == 1:
            return self._auth_key

        if self.product_id == "z1dfsaya":
            if security_flag == 0x0E:
                return self._login_key
            elif security_flag == 0x0F:
                return self._session_key

        if security_flag == 4:
            return self._login_key
        elif security_flag == 5:
            return self._session_key
        else:
            pass

    def _parse_timestamp(self, data: bytes, start_pos: int) -> tuple(float, int):
        timestamp: float
        pos = start_pos
        if pos >= len(data):
            raise TuyaBLEDataLengthError()
        time_type = data[pos]
        pos += 1
        end_pos = pos
        match time_type:
            case 0:
                end_pos += 13
                if end_pos > len(data):
                    raise TuyaBLEDataLengthError()
                timestamp = int(data[pos:end_pos].decode()) / 1000
                pass
            case 1:
                end_pos += 4
                if end_pos > len(data):
                    raise TuyaBLEDataLengthError()
                timestamp = int.from_bytes(data[pos:end_pos], "big") * 1.0
                pass
            case _:
                raise TuyaBLEDataFormatError()

        _LOGGER.debug(
            "%s: Received timestamp: %s",
            self.address,
            time.ctime(timestamp),
        )
        return (timestamp, end_pos)

    def _parse_datapoints_v3(
        self, timestamp: float, flags: int, data: bytes, start_pos: int
    ) -> int:
        datapoints: list[TuyaBLEDataPoint] = []

        pos = start_pos
        while len(data) - pos >= 4:
            id: int = data[pos]
            pos += 1
            _type: int = data[pos]
            if _type > TuyaBLEDataPointType.DT_BITMAP.value:
                raise TuyaBLEDataFormatError()
            type: TuyaBLEDataPointType = TuyaBLEDataPointType(_type)
            pos += 1
            data_len: int = data[pos]
            pos += 1
            next_pos = pos + data_len
            if next_pos > len(data):
                raise TuyaBLEDataLengthError()
            raw_value = data[pos:next_pos]
            match type:
                case (TuyaBLEDataPointType.DT_RAW | TuyaBLEDataPointType.DT_BITMAP):
                    value = raw_value
                case TuyaBLEDataPointType.DT_BOOL:
                    value = int.from_bytes(raw_value, "big") != 0
                case (TuyaBLEDataPointType.DT_VALUE | TuyaBLEDataPointType.DT_ENUM):
                    value = int.from_bytes(raw_value, "big", signed=True)
                case TuyaBLEDataPointType.DT_STRING:
                    value = raw_value.decode()

            _LOGGER.debug(
                "%s: Received datapoint update, id: %s, type: %s: value: %s",
                self.address,
                id,
                type.name,
                value,
            )
            self._datapoints._update_from_device(
                id, timestamp, flags, type, value)
            datapoints.append(self._datapoints[id])
            pos = next_pos

        self._fire_callbacks(datapoints)

    def _parse_datapoints_v4(self, data: bytes) -> None:
        """Parse Tuya BLE V4 datapoint/event payloads.

        Most devices are still parsed with the legacy V3-like layout below.
        Raykube/TuyaOS FD50 locks use the command-style V4 body handled by
        `_parse_raykube_datapoints_v4`: header:4, op:1, dp_id:1, len:3,
        value:len.  Only safe configuration/status datapoints are surfaced for
        that lock; ambiguous lock-state events are intentionally ignored.
        """
        if self.product_id in ("hc7n0urm", "y2yaegze"):
            self._parse_raykube_datapoints_v4(data)
            return

        if self.product_id == "ikphogdj":
            self._parse_ikphogdj_datapoints_v4(data)
            return

        datapoints: list[TuyaBLEDataPoint] = []
        pos = 4 if len(data) >= 4 else 0
        while len(data) - pos >= 7:
            id = data[pos]
            pos += 1
            flags = int.from_bytes(data[pos:pos + 3], "big")
            pos += 3
            type_value = data[pos]
            pos += 1
            try:
                type = TuyaBLEDataPointType(type_value)
            except ValueError:
                _LOGGER.debug("%s: Unknown V4 datapoint type %s", self.address, type_value)
                break
            data_len = int.from_bytes(data[pos:pos + 2], "big")
            pos += 2
            next_pos = pos + data_len
            if next_pos > len(data):
                raise TuyaBLEDataLengthError()
            raw_value = data[pos:next_pos]
            match type:
                case (TuyaBLEDataPointType.DT_RAW | TuyaBLEDataPointType.DT_BITMAP):
                    value = raw_value
                case TuyaBLEDataPointType.DT_BOOL:
                    value = int.from_bytes(raw_value, "big") != 0
                case (TuyaBLEDataPointType.DT_VALUE | TuyaBLEDataPointType.DT_ENUM):
                    value = int.from_bytes(raw_value, "big", signed=True)
                case TuyaBLEDataPointType.DT_STRING:
                    value = raw_value.decode()
            if self.product_id == "z1dfsaya":
                _LOGGER.debug(
                    "%s: 350K V4 candidate id=%s flags=0x%06x type=%s len=%s raw=%s value=%r",
                    self.address,
                    id,
                    flags,
                    type.name,
                    data_len,
                    raw_value.hex(),
                    value,
                )
            if self.product_id not in ("hc7n0urm", "y2yaegze"):
                self._datapoints._update_from_device(id, time.time(), flags, type, value)
                datapoints.append(self._datapoints[id])

            if (
                self.product_id in ("hc7n0urm", "y2yaegze")
                and type == TuyaBLEDataPointType.DT_RAW
                and raw_value == b"\x00\x01\x01"
                and not self._input_expected_responses
            ):
                # Observed after a manual/open event when the lock reconnects.
                # V4 event ids are sequence-like, so mirror this event into the
                # fixed state datapoint used by the lock entity.
                self._datapoints._update_from_device(
                    118,
                    time.time(),
                    flags,
                    TuyaBLEDataPointType.DT_ENUM,
                    1,
                )
                datapoints.append(self._datapoints[118])
            pos = next_pos

        self._fire_callbacks(datapoints)

    def _parse_350k_datapoints_v4(self, data: bytes, timed: bool = False) -> None:
        """Parse YD_350K / z1dfsaya TuyaOS V4 status and timed-event frames.

        Ordinary status frame observed on FUN_RECEIVE_DP_V4:
            <event_seq:5> 80 <kind:1> <dp_id:1> <type:1>
            <len:2> <value:len>

        Timed event frame observed on FUN_RECEIVE_TIME_DP_V4:
            <event_seq:5> 00 <kind:1> 01 <unix_time:4>
            <dp_id:1> <type:1> <len:2> <value:len>

        Ordinary datapoints are exposed to Home Assistant. Timed events are
        intentionally diagnostic-only for now so event/history records cannot
        accidentally be mistaken for persistent device state.
        """
        datapoints: list[TuyaBLEDataPoint] = []

        def decode_value(
            dp_type: TuyaBLEDataPointType,
            raw_value: bytes,
        ) -> bytes | bool | int | str:
            match dp_type:
                case TuyaBLEDataPointType.DT_RAW | TuyaBLEDataPointType.DT_BITMAP:
                    return raw_value
                case TuyaBLEDataPointType.DT_BOOL:
                    return int.from_bytes(raw_value, "big") != 0
                case TuyaBLEDataPointType.DT_VALUE | TuyaBLEDataPointType.DT_ENUM:
                    return int.from_bytes(raw_value, "big", signed=True)
                case TuyaBLEDataPointType.DT_STRING:
                    return raw_value.decode()
            return raw_value

        if len(data) < 11:
            _LOGGER.debug(
                "%s: 350K short %s payload: %s",
                self.address,
                "timed V4" if timed else "V4",
                data.hex(),
            )
            self._fire_callbacks(datapoints)
            return

        # Observed sequence progression:
        #   00000008fe, 00000008ff, 0000000900, 0000000901 ...
        # so bytes 0..4 form one rolling 40-bit event sequence.
        event_seq = int.from_bytes(data[0:5], "big")
        frame_marker = data[5]
        kind = data[6]

        if timed:
            # 00 <kind> 01 <timestamp:4> <dp> <type> <len:2> <value>
            if len(data) < 16 or frame_marker != 0x00 or data[7] != 0x01:
                _LOGGER.debug(
                    "%s: 350K unrecognized timed V4 payload: %s",
                    self.address,
                    data.hex(),
                )
                self._fire_callbacks(datapoints)
                return

            timestamp = int.from_bytes(data[8:12], "big")
            dp_id = data[12]
            type_value = data[13]
            data_len = int.from_bytes(data[14:16], "big")
            value_pos = 16
            next_pos = value_pos + data_len

            if next_pos > len(data):
                _LOGGER.debug(
                    "%s: 350K truncated timed V4 payload: %s",
                    self.address,
                    data.hex(),
                )
                self._fire_callbacks(datapoints)
                return

            raw_value = data[value_pos:next_pos]

            try:
                dp_type = TuyaBLEDataPointType(type_value)
            except ValueError:
                self._log_350k_verbose(
                    "%s: 350K timed event seq=0x%010x kind=0x%02x "
                    "timestamp=%s dp=%s unknown_type=%s len=%s raw=%s",
                    self.address,
                    event_seq,
                    kind,
                    time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp)),
                    dp_id,
                    type_value,
                    data_len,
                    raw_value.hex(),
                )
                self._fire_callbacks(datapoints)
                return

            try:
                value = decode_value(dp_type, raw_value)
            except (UnicodeDecodeError, ValueError):
                value = raw_value

            trailing = data[next_pos:]
            self._log_350k_verbose(
                "%s: 350K timed event seq=0x%010x kind=0x%02x "
                "timestamp=%s dp=%s type=%s len=%s raw=%s value=%r%s",
                self.address,
                event_seq,
                kind,
                time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp)),
                dp_id,
                dp_type.name,
                data_len,
                raw_value.hex(),
                value,
                (" trailing=" + trailing.hex()) if trailing else "",
            )

            # Keep timed Tuya records out of the real DP namespace, but surface
            # the events we have positively identified through synthetic, local-
            # only datapoints. These are read-only and can never be sent to Tuya.
            def update_local(
                synthetic_id: int,
                synthetic_type: TuyaBLEDataPointType,
                synthetic_value: bytes | bool | int | str,
            ) -> None:
                self._datapoints._update_from_device(
                    synthetic_id,
                    float(timestamp),
                    kind,
                    synthetic_type,
                    synthetic_value,
                )
                datapoints.append(self._datapoints[synthetic_id])

            access_event: str | None = None
            credential_id: int | None = None

            if dp_id == 12 and dp_type == TuyaBLEDataPointType.DT_VALUE:
                access_event = "fingerprint_unlock"
                credential_id = int(value)
            elif dp_id == 13 and dp_type == TuyaBLEDataPointType.DT_VALUE:
                access_event = "pin_unlock"
                credential_id = int(value)
            elif dp_id == 21 and dp_type == TuyaBLEDataPointType.DT_ENUM:
                access_event = {
                    0: "failed_fingerprint",
                    1: "failed_pin",
                }.get(int(value), f"alarm_{int(value)}")
            elif dp_id == 20 and dp_type == TuyaBLEDataPointType.DT_RAW:
                # DP20 is a lock history/event record. Its byte-level semantics
                # are not fully mapped yet, so expose the exact plaintext record.
                update_local(
                    DP_350K_LAST_LOCK_RECORD,
                    TuyaBLEDataPointType.DT_STRING,
                    raw_value.hex(),
                )

            if access_event is not None:
                update_local(
                    DP_350K_LAST_ACCESS_EVENT,
                    TuyaBLEDataPointType.DT_STRING,
                    access_event,
                )
                update_local(
                    DP_350K_LAST_ACCESS_EVENT_TIME,
                    TuyaBLEDataPointType.DT_VALUE,
                    int(timestamp),
                )
                if credential_id is not None:
                    update_local(
                        DP_350K_LAST_CREDENTIAL_ID,
                        TuyaBLEDataPointType.DT_VALUE,
                        credential_id,
                    )

            self._fire_callbacks(datapoints)
            return

        # Ordinary status/delta:
        # 80 <kind> <dp> <type> <len:2> <value>
        if frame_marker != 0x80:
            _LOGGER.debug(
                "%s: 350K unrecognized V4 marker 0x%02x payload: %s",
                self.address,
                frame_marker,
                data.hex(),
            )
            self._fire_callbacks(datapoints)
            return

        dp_id = data[7]
        type_value = data[8]
        data_len = int.from_bytes(data[9:11], "big")
        value_pos = 11
        next_pos = value_pos + data_len

        if next_pos > len(data):
            _LOGGER.debug(
                "%s: 350K truncated V4 payload for dp %s: %s",
                self.address,
                dp_id,
                data.hex(),
            )
            self._fire_callbacks(datapoints)
            return

        raw_value = data[value_pos:next_pos]

        try:
            dp_type = TuyaBLEDataPointType(type_value)
        except ValueError:
            self._log_350k_verbose(
                "%s: 350K V4 seq=0x%010x kind=0x%02x dp=%s "
                "unknown_type=%s len=%s raw=%s",
                self.address,
                event_seq,
                kind,
                dp_id,
                type_value,
                data_len,
                raw_value.hex(),
            )
            self._fire_callbacks(datapoints)
            return

        try:
            value = decode_value(dp_type, raw_value)
        except (UnicodeDecodeError, ValueError):
            value = raw_value

        trailing = data[next_pos:]
        self._log_350k_verbose(
            "%s: 350K V4 seq=0x%010x kind=0x%02x dp=%s "
            "type=%s len=%s raw=%s value=%r%s",
            self.address,
            event_seq,
            kind,
            dp_id,
            dp_type.name,
            data_len,
            raw_value.hex(),
            value,
            (" trailing=" + trailing.hex()) if trailing else "",
        )

        self._datapoints._update_from_device(
            dp_id,
            time.time(),
            kind,
            dp_type,
            value,
        )
        datapoints.append(self._datapoints[dp_id])
        self._fire_callbacks(datapoints)

    def _parse_raykube_datapoints_v4(self, data: bytes) -> None:
        """Parse Raykube/TuyaOS FD50 command-style V4 datapoint payloads.

        Captured command/event bodies use:
        00000000 01 <dp_id> <len:3> <value:len>

        The lock may also emit other V4 event bodies on the same message code.
        Those frames should not make the integration disconnect, so this parser
        scans for the safe command-style datapoints we understand and ignores
        malformed/unknown frames instead of raising.
        """
        datapoints: list[TuyaBLEDataPoint] = []
        # CTL20H initial bulk status snapshot.
        # DP8 is battery percentage encoded as a 4-byte Tuya VALUE.
        # DP47 is the physical lock state: 0=locked, 1=unlocked.
        if self.product_id == "y2yaegze" and len(data) > 20:
            battery_marker = b"\x08\x02\x00\x04"
            battery_pos = data.find(battery_marker)

            if (
                battery_pos >= 0
                and battery_pos + len(battery_marker) + 4 <= len(data)
            ):
                battery_raw = data[
                    battery_pos + len(battery_marker):
                    battery_pos + len(battery_marker) + 4
                ]
                battery_value = int.from_bytes(
                    battery_raw,
                    "big",
                    signed=False,
                )

                if 0 <= battery_value <= 100:
                    self._datapoints._update_from_device(
                        8,
                        time.time(),
                        0,
                        TuyaBLEDataPointType.DT_VALUE,
                        battery_value,
                    )
                    datapoints.append(self._datapoints[8])

            state_marker = b"\x2f\x01\x00\x01"
            state_pos = data.find(state_marker)

            if state_pos >= 0 and state_pos + len(state_marker) < len(data):
                state_raw = data[state_pos + len(state_marker)]

                if state_raw in (0, 1):
                    self._datapoints._update_from_device(
                        47,
                        time.time(),
                        0,
                        TuyaBLEDataPointType.DT_BOOL,
                        bool(state_raw),
                    )

                    # Mirror physical DP47 to the synthetic state datapoint
                    # already used by the Raykube passive-state event path.
                    self._datapoints._update_from_device(
                        118,
                        time.time(),
                        0,
                        TuyaBLEDataPointType.DT_ENUM,
                        state_raw,
                    )
                    datapoints.append(self._datapoints[118])
        pos = 0
        parsed_ranges: list[tuple[int, int]] = []

        while len(data) - pos >= 5:
            # Generic V4 typed status/event frame seen from manual actions:
            #   <id> <flags:3> <dp_type> <len:2> <value:len>
            # For Raykube hc7n0urm, flags=0x00002f with DT_BOOL is the only
            # passive physical lock-state event observed so far:
            #   true  -> open/unlocked
            #   false -> closed/locked
            # This event is only useful when it is actually received over an
            # active BLE notify session; sleepy battery locks may not report
            # manual changes while disconnected.
            if len(data) - pos >= 8:
                flags = int.from_bytes(data[pos + 1:pos + 4], "big")
                dp_type = data[pos + 4]
                typed_len = int.from_bytes(data[pos + 5:pos + 7], "big")
                typed_value_pos = pos + 7
                typed_next_pos = typed_value_pos + typed_len
                if (
                    flags == 0x00002F
                    and dp_type == TuyaBLEDataPointType.DT_BOOL.value
                    and typed_len == 1
                    and typed_next_pos <= len(data)
                ):
                    raw_value = data[typed_value_pos:typed_next_pos]
                    value = raw_value != b"\x00"
                    _LOGGER.debug(
                        "%s: Received Raykube passive lock-state event, flags: 0x%06x, value: %s",
                        self.address,
                        flags,
                        value,
                    )
                    self._datapoints._update_from_device(
                        118,
                        time.time(),
                        flags,
                        TuyaBLEDataPointType.DT_ENUM,
                        1 if value else 0,
                    )
                    datapoints.append(self._datapoints[118])
                    parsed_ranges.append((pos, typed_next_pos))
                    pos = typed_next_pos
                    continue

            op = data[pos]
            dp_id = data[pos + 1]
            data_len = int.from_bytes(data[pos + 2:pos + 5], "big")
            value_pos = pos + 5
            next_pos = value_pos + data_len

            # Command-style status used in some captures:
            #   01 <dp_id> <len:3> <value:len>
            if op == 1 and dp_id in (9, 31, 48) and 1 <= data_len <= len(data) - value_pos:
                raw_value = data[value_pos:next_pos]
                value = int.from_bytes(raw_value, "big", signed=False)
                _LOGGER.debug(
                    "%s: Received Raykube V4 datapoint update, id: %s, type: DT_ENUM: value: %s",
                    self.address,
                    dp_id,
                    value,
                )
                self._datapoints._update_from_device(
                    dp_id,
                    time.time(),
                    0,
                    TuyaBLEDataPointType.DT_ENUM,
                    value,
                )
                datapoints.append(self._datapoints[dp_id])
                parsed_ranges.append((pos, next_pos))
                pos = next_pos
                continue

            # Event-style echo/status seen from Raykube after V4 writes:
            #   <event> 00 00 <dp_id> <len:3> <value:len>
            # Example: aa 0000 1f 000001 03 => DP31 value 3.
            if len(data) - pos >= 8 and data[pos + 1:pos + 3] == b"\x00\x00":
                dp_id = data[pos + 3]
                data_len = int.from_bytes(data[pos + 4:pos + 7], "big")
                value_pos = pos + 7
                next_pos = value_pos + data_len
                if dp_id in (9, 31, 48) and 1 <= data_len <= len(data) - value_pos:
                    raw_value = data[value_pos:next_pos]
                    value = int.from_bytes(raw_value, "big", signed=False)
                    _LOGGER.debug(
                        "%s: Received Raykube V4 event datapoint update, id: %s, type: DT_ENUM: value: %s",
                        self.address,
                        dp_id,
                        value,
                    )
                    self._datapoints._update_from_device(
                        dp_id,
                        time.time(),
                        0,
                        TuyaBLEDataPointType.DT_ENUM,
                        value,
                    )
                    datapoints.append(self._datapoints[dp_id])
                    parsed_ranges.append((pos, next_pos))
                    pos = next_pos
                    continue

                # Some Raykube status events include the Tuya DP type byte:
                #   <event> 00 00 <dp_id> <dp_type> <len:2> <value:len>
                # Example: a1 0000 09 04 0001 00 => DP9 enum value 0.
                if len(data) - pos >= 8:
                    dp_type = data[pos + 4]
                    data_len = int.from_bytes(data[pos + 5:pos + 7], "big")
                    value_pos = pos + 7
                    next_pos = value_pos + data_len
                    if dp_id in (9, 31, 48) and dp_type in (0, 4) and 1 <= data_len <= len(data) - value_pos:
                        raw_value = data[value_pos:next_pos]
                        value = int.from_bytes(raw_value, "big", signed=False)
                        _LOGGER.debug(
                            "%s: Received Raykube V4 typed event datapoint update, id: %s, type: %s: value: %s",
                            self.address,
                            dp_id,
                            dp_type,
                            value,
                        )
                        self._datapoints._update_from_device(
                            dp_id,
                            time.time(),
                            0,
                            TuyaBLEDataPointType.DT_ENUM,
                            value,
                        )
                        datapoints.append(self._datapoints[dp_id])
                        parsed_ranges.append((pos, next_pos))
                        pos = next_pos
                        continue

            pos += 1

        if not datapoints:
            _LOGGER.debug(
                "%s: Ignoring unsupported Raykube V4 payload: %s",
                self.address,
                data.hex(),
            )
        else:
            _LOGGER.debug(
                "%s: Parsed Raykube V4 datapoints from ranges %s in payload: %s",
                self.address,
                parsed_ranges,
                data.hex(),
            )

        self._fire_callbacks(datapoints)

    def _parse_ikphogdj_datapoints_v4(self, data: bytes) -> None:
        """Parse ikphogdj (HL Knob-2) async DP-change-report V4 payloads.

        Confirmed via HCI capture across dp 8, 12, 19, 21, 31, 33, 46, 47
        (residual_electricity, unlock_fingerprint, unlock_ble, alarm_lock,
        beep_volume, automatic_lock, manual_lock, lock_motor_state):
            00 00 00 00 <counter:1> 80 <kind:1> <dp_id:1> <type:1> <len:2> <value:len>
        `kind` varies (00 seen for action-triggered deltas, 02 seen for an
        unprompted boot/periodic status report carrying battery %) but the
        dp_id/type/len/value layout is identical either way, so it's not
        discriminated on further here.
        `type` matches TuyaBLEDataPointType's integer values directly
        (1=bool, 2=value, 3=string, 4=enum, 0/5=raw/bitmap).
        Unrecognized/malformed frames are ignored rather than raised, since
        the lock may emit other V4 event bodies we don't understand yet.
        """
        datapoints: list[TuyaBLEDataPoint] = []

        if len(data) < 11 or data[0:4] != b"\x00\x00\x00\x00" or data[5] != 0x80:
            _LOGGER.debug(
                "%s: Ignoring unrecognized ikphogdj V4 payload: %s",
                self.address,
                data.hex(),
            )
            self._fire_callbacks(datapoints)
            return

        dp_id = data[7]
        type_value = data[8]
        data_len = int.from_bytes(data[9:11], "big")
        raw_value = data[11:11 + data_len]

        if len(raw_value) != data_len:
            _LOGGER.debug(
                "%s: Truncated ikphogdj V4 payload for dp %s: %s",
                self.address,
                dp_id,
                data.hex(),
            )
            self._fire_callbacks(datapoints)
            return

        try:
            dp_type = TuyaBLEDataPointType(type_value)
        except ValueError:
            _LOGGER.debug(
                "%s: Unknown ikphogdj V4 datapoint type %s for dp %s",
                self.address,
                type_value,
                dp_id,
            )
            self._fire_callbacks(datapoints)
            return

        match dp_type:
            case TuyaBLEDataPointType.DT_RAW | TuyaBLEDataPointType.DT_BITMAP:
                value = raw_value
            case TuyaBLEDataPointType.DT_BOOL:
                value = int.from_bytes(raw_value, "big") != 0
            case TuyaBLEDataPointType.DT_VALUE | TuyaBLEDataPointType.DT_ENUM:
                value = int.from_bytes(raw_value, "big", signed=True)
            case TuyaBLEDataPointType.DT_STRING:
                value = raw_value.decode(errors="replace")

        _LOGGER.debug(
            "%s: Received ikphogdj V4 datapoint update, id: %s, type: %s, value: %s",
            self.address,
            dp_id,
            dp_type.name,
            value,
        )
        self._datapoints._update_from_device(dp_id, time.time(), 0, dp_type, value)
        datapoints.append(self._datapoints[dp_id])

        self._fire_callbacks(datapoints)

    def _handle_command_or_response(
        self, seq_num: int, response_to: int, code: TuyaBLECode, data: bytes
    ) -> None:
        result: int = 0

        match code:
            case TuyaBLECode.FUN_SENDER_DEVICE_INFO:
                if len(data) < 46:
                    raise TuyaBLEDataLengthError()

                self._device_version = ("%s.%s") % (data[0], data[1])
                self._protocol_version_str = ("%s.%s") % (data[2], data[3])
                self._hardware_version = ("%s.%s") % (data[12], data[13])

                self._protocol_version = data[2]
                self._flags = data[4]
                self._is_bound = data[5] != 0

                srand = data[6:12]

                if self.product_id == "z1dfsaya":
                    if self._local_key_full is None or self._sec_key is None:
                        raise TuyaBLEDeviceError(
                            "Missing TuyaOS security credentials"
                        )

                    # Tuya security flag 0x0f.
                    self._session_key = hashlib.md5(
                        self._local_key_full
                        + self._sec_key
                        + srand
                    ).digest()

                    _LOGGER.debug(
                        "%s: Derived TuyaOS 0x0f session key",
                        self.address,
                    )
                else:
                    self._session_key = hashlib.md5(
                        self._local_key + srand
                    ).digest()

                self._auth_key = data[14:46]

            case TuyaBLECode.FUN_SENDER_PAIR:
                if len(data) != 1:
                    raise TuyaBLEDataLengthError()
                result = data[0]
                if result == 2:
                    _LOGGER.debug(
                        "%s: Device is already paired",
                        self.address,
                    )
                    result = 0
                self._is_paired = result == 0

            case TuyaBLECode.FUN_SENDER_DEVICE_STATUS:
                if len(data) != 1:
                    raise TuyaBLEDataLengthError()
                result = data[0]

            case TuyaBLECode.FUN_RECEIVE_TIME1_REQ:
                if len(data) != 0:
                    raise TuyaBLEDataLengthError()

                timestamp = int(time.time_ns() / 1000000)
                timezone = -int(time.timezone / 36)
                data = str(timestamp).encode() + pack(">h", timezone)
                asyncio.create_task(self._send_response(code, data, seq_num))

            case TuyaBLECode.FUN_RECEIVE_TIME2_REQ:
                if len(data) != 0:
                    raise TuyaBLEDataLengthError()

                time_str: time.struct_time = time.localtime()
                timezone = -int(time.timezone / 36)
                data = pack(
                    ">BBBBBBBh",
                    time_str.tm_year % 100,
                    time_str.tm_mon,
                    time_str.tm_mday,
                    time_str.tm_hour,
                    time_str.tm_min,
                    time_str.tm_sec,
                    time_str.tm_wday,
                    timezone,
                )
                asyncio.create_task(self._send_response(code, data, seq_num))

            case TuyaBLECode.FUN_RECEIVE_DP:
                self._parse_datapoints_v3(time.time(), 0, data, 0)
                asyncio.create_task(
                    self._send_response(code, bytes(0), seq_num))

            case TuyaBLECode.FUN_RECEIVE_SIGN_DP:
                dp_seq_num = int.from_bytes(data[:2], "big")
                flags = data[2]
                self._parse_datapoints_v3(time.time(), flags, data, 2)
                data = pack(">HBB", dp_seq_num, flags, 0)
                asyncio.create_task(self._send_response(code, data, seq_num))

            case TuyaBLECode.FUN_RECEIVE_TIME_DP:
                timestamp: float
                pos: int
                timestamp, pos = self._parse_timestamp(data, 0)
                self._parse_datapoints_v3(timestamp, 0, data, pos)
                asyncio.create_task(
                    self._send_response(code, bytes(0), seq_num))

            case TuyaBLECode.FUN_RECEIVE_SIGN_TIME_DP:
                timestamp: float
                pos: int
                dp_seq_num = int.from_bytes(data[:2], "big")
                flags = data[2]
                timestamp, pos = self._parse_timestamp(data, 3)
                self._parse_datapoints_v3(time.time(), flags, data, pos)
                data = pack(">HBB", dp_seq_num, flags, 0)
                asyncio.create_task(self._send_response(code, data, seq_num))

            case TuyaBLECode.FUN_RECEIVE_DP_V4:
                if self.product_id == "z1dfsaya":
                    self._log_350k_verbose(
                        "%s: 350K raw %s plaintext: %s",
                        self.address,
                        code.name,
                        data.hex(),
                    )
                    self._parse_350k_datapoints_v4(data, timed=False)
                else:
                    self._parse_datapoints_v4(data)

                asyncio.create_task(
                    self._send_response(code, bytes(0), seq_num)
                )

            case TuyaBLECode.FUN_RECEIVE_TIME_DP_V4:
                if self.product_id == "z1dfsaya":
                    self._log_350k_verbose(
                        "%s: 350K raw %s plaintext: %s",
                        self.address,
                        code.name,
                        data.hex(),
                    )
                    self._parse_350k_datapoints_v4(data, timed=True)
                else:
                    self._parse_datapoints_v4(data)

                asyncio.create_task(
                    self._send_response(code, bytes(0), seq_num)
                )
        if response_to != 0:
            future = self._input_expected_responses.pop(response_to, None)
            if future:
                _LOGGER.debug(
                    "%s: Received expected response to #%s, result: %s",
                    self.address,
                    response_to,
                    result,
                )
                if result == 0:
                    future.set_result(result)
                else:
                    future.set_exception(TuyaBLEDeviceError(result))

    def _clean_input(self) -> None:
        self._input_buffer = None
        self._input_expected_packet_num = 0
        self._input_expected_length = 0

    def _parse_input(self) -> None:
        security_flag = self._input_buffer[0]
        key = self._get_key(security_flag)
        iv = self._input_buffer[1:17]
        encrypted = self._input_buffer[17:]

        self._clean_input()

        cipher = AES.new(key, AES.MODE_CBC, iv)
        raw = cipher.decrypt(encrypted)

        seq_num: int
        response_to: int
        _code: int
        length: int
        seq_num, response_to, _code, length = unpack(">IIHH", raw[:12])

        data_end_pos = length + 12
        raw_length = len(raw)
        if raw_length < data_end_pos:
            raise TuyaBLEDataLengthError()
        if raw_length > data_end_pos:
            calc_crc = self._calc_crc16(raw[:data_end_pos])
            (data_crc,) = unpack(
                ">H",
                raw[data_end_pos:data_end_pos + 2]  # fmt: skip
            )
            if calc_crc != data_crc:
                raise TuyaBLEDataCRCError()
        data = raw[12:data_end_pos]

        code: TuyaBLECode
        try:
            code = TuyaBLECode(_code)
        except ValueError:
            _LOGGER.debug(
                "%s: Received unknown message: #%s %x, response to #%s, data %s",
                self.address,
                seq_num,
                _code,
                response_to,
                data.hex(),
            )
            return

        if response_to != 0:
            _LOGGER.debug(
                "%s: Received: #%s %s, response to #%s",
                self.address,
                seq_num,
                code.name,
                response_to,
            )
        else:
            _LOGGER.debug(
                "%s: Received: #%s %s",
                self.address,
                seq_num,
                code.name,
            )

        self._handle_command_or_response(seq_num, response_to, code, data)

    def _notification_handler(self, _sender: int, data: bytearray) -> None:
        """Handle notification responses."""
        if self.product_id == "z1dfsaya":
            # Any received GATT notification means the authenticated BLE link is
            # active, including fragments that are part of a larger Tuya frame.
            self._350k_last_rx_monotonic = time.monotonic()

        if self.product_id != "z1dfsaya" or self._verbose_logging:
            _LOGGER.debug("%s: Packet received: %s", self.address, data.hex())

        pos: int = 0
        packet_num: int

        packet_num, pos = self._unpack_int(data, pos)

        if packet_num < self._input_expected_packet_num:
            _LOGGER.error(
                "%s: Unexpcted packet (number %s) in notifications, " "expected %s",
                self.address,
                packet_num,
                self._input_expected_packet_num,
            )
            self._clean_input()

        if packet_num == self._input_expected_packet_num:
            if packet_num == 0:
                self._input_buffer = bytearray()
                self._input_expected_length, pos = self._unpack_int(data, pos)
                pos += 1
            self._input_buffer += data[pos:]
            self._input_expected_packet_num += 1
        else:
            _LOGGER.error(
                "%s: Missing packet (number %s) in notifications, received %s",
                self.address,
                self._input_expected_packet_num,
                packet_num,
            )
            self._clean_input()
            return

        if len(self._input_buffer) > self._input_expected_length:
            _LOGGER.error(
                "%s: Unexpcted length of data in notifications, "
                "received %s expected %s",
                self.address,
                len(self._input_buffer),
                self._input_expected_length,
            )
            self._clean_input()
            return
        elif len(self._input_buffer) == self._input_expected_length:
            self._parse_input()

    async def _send_datapoints_v3(self, datapoint_ids: list[int]) -> None:
        """Send new values of datapoints to the device."""
        data = bytearray()
        for dp_id in datapoint_ids:
            dp = self._datapoints[dp_id]
            value = dp._get_value()
            _LOGGER.debug(
                "%s: Sending datapoint update, id: %s, type: %s: value: %s",
                self.address,
                dp.id,
                dp.type.name,
                dp.value,
            )
            data += pack(">BBB", dp.id, int(dp.type.value), len(value))
            data += value

        if self.product_id in ("hc7n0urm", "y2yaegze"):
            if 6 in datapoint_ids:
                # Raykube A1 Ultra / TuyaOS FD50 remote unlock command captured
                # from the official app. It is built from the per-device
                # `ble_unlock_check` raw status value reported by Tuya Cloud.
                raykube_unlock_v4_data = self._build_raykube_unlock_v4_data()
                await self._send_packet(
                    TuyaBLECode.FUN_SENDER_DPS_V4, raykube_unlock_v4_data, True
                )
            elif 46 in datapoint_ids:
                # Candidate Raykube physical lock command (`manual_lock` / DP 46).
                raykube_lock_v4_data = bytes.fromhex("00000000012e00000101")
                await self._send_packet(
                    TuyaBLECode.FUN_SENDER_DPS_V4, raykube_lock_v4_data, True
                )
            elif set(datapoint_ids).issubset({31, 48}):
                for dp_id in datapoint_ids:
                    raykube_v4_data = self._build_raykube_v4_enum_data(dp_id)
                    await self._send_packet(
                        TuyaBLECode.FUN_SENDER_DPS_V4, raykube_v4_data, True
                    )
            else:
                _LOGGER.debug(
                    "%s: Skipping unsupported Raykube legacy datapoint write: %s",
                    self.address,
                    datapoint_ids,
                )
            return

        if self.product_id == "z1dfsaya":
            # YD_350K: only simple boolean configuration writes are enabled
            # here. DP33 controls passage/auto-lock. DP79 is the
            # writable secure-lock control; DP32 remains the reported secure
            # state. The scalar V4 framing matches the TuyaOS FD50 form used
            # by related locks.
            if set(datapoint_ids).issubset({33, 79}):
                for dp_id in datapoint_ids:
                    payload = self._build_ikphogdj_v4_bool_data(dp_id)
                    await self._send_packet(
                        TuyaBLECode.FUN_SENDER_DPS_V4, payload, True
                    )
            else:
                _LOGGER.debug(
                    "%s: Skipping unsupported 350K datapoint write: %s",
                    self.address,
                    datapoint_ids,
                )
            return

        if self.product_id in ("ikphogdj", "c6hfl8bt"):
            if 6 in datapoint_ids:
                ikphogdj_unlock_v4_data = self._build_raykube_unlock_v4_data()
                await self._send_packet(
                    TuyaBLECode.FUN_SENDER_DPS_V4, ikphogdj_unlock_v4_data, True
                )
            elif 46 in datapoint_ids:
                ikphogdj_lock_v4_data = bytes.fromhex("00000000012e00000101")
                await self._send_packet(
                    TuyaBLECode.FUN_SENDER_DPS_V4, ikphogdj_lock_v4_data, True
                )
            elif 33 in datapoint_ids:
                # automatic_lock, confirmed real V4 format via HCI capture.
                ikphogdj_autolock_v4_data = self._build_ikphogdj_v4_bool_data(33)
                await self._send_packet(
                    TuyaBLECode.FUN_SENDER_DPS_V4, ikphogdj_autolock_v4_data, True
                )
            elif set(datapoint_ids).issubset({31}):
                for dp_id in datapoint_ids:
                    ikphogdj_v4_data = self._build_ikphogdj_v4_enum_data(dp_id)
                    await self._send_packet(
                        TuyaBLECode.FUN_SENDER_DPS_V4, ikphogdj_v4_data, True
                    )
            else:
                _LOGGER.debug(
                    "%s: Skipping unsupported ikphogdj/c6hfl8bt datapoint write: %s",
                    self.address,
                    datapoint_ids,
                )
            return

        #await self._send_packet(TuyaBLECode.FUN_SENDER_DPS, data)
        await self._send_packet(TuyaBLECode.FUN_SENDER_DPS, data, False)

    def _build_raykube_unlock_v4_data(self) -> bytes:
        """Build the Raykube/TuyaOS FD50 V4 remote-unlock payload.

        `ble_unlock_check` is a base64 encoded raw Tuya status field. For the
        verified lock it decodes to:
        00 01 ff ff <8 ASCII digits> 01 <4 bytes> 00 00

        The V4 command payload sent by the official app is:
        00000000 01 47 000013 ffff 0001 <8 ASCII digits> 01 <4 bytes> 00 01
        """
        if not self.ble_unlock_check:
            raise TuyaBLEDeviceError(
                "This TuyaOS FD50 lock (Raykube/hc7n0urm, ikphogdj, "
                "c6hfl8bt) requires the device-specific ble_unlock_check "
                "value in tuya_local_ble/devices.json"
            )

        try:
            check = base64.b64decode(self.ble_unlock_check)
        except Exception as exc:
            raise TuyaBLEDeviceError(
                "ble_unlock_check must be a valid base64 Tuya status value"
            ) from exc

        if len(check) < 19:
            raise TuyaBLEDataLengthError()

        prefix = check[2:4]
        check_code = check[4:12]
        check_key = check[13:17]
        return b"\x00\x00\x00\x00\x01\x47\x00\x00\x13" + prefix + b"\x00\x01" + check_code + b"\x01" + check_key + b"\x00\x01"

    def _build_raykube_v4_enum_data(self, dp_id: int) -> bytes:
        """Build a Raykube/TuyaOS FD50 one-byte V4 enum write."""
        dp = self._datapoints[dp_id]
        value = dp._get_value()
        if len(value) != 1:
            raise TuyaBLEDataLengthError()
        return b"\x00\x00\x00\x00\x01" + bytes([dp_id]) + len(value).to_bytes(3, "big") + value

    def _build_ikphogdj_v4_scalar_data(self, dp_id: int, dp_type: int) -> bytes:
        """Build an ikphogdj (HL Knob-2) V4 write for a simple scalar
        datapoint. Confirmed against real captured traffic 
        (lock dp 46, automatic_lock dp 33, beep_volume dp 31):
            00 00 00 00 <counter=01> <dp_id> <type> <len:2> <value:len>
        counter stays 01 since each command runs on its own fresh connection
        (keep_connect=False for this product).
        dp_type: 0x01 = bool, 0x04 = enum (standard Tuya DP type codes).
        """
        dp = self._datapoints[dp_id]
        value = dp._get_value()
        if len(value) != 1:
            raise TuyaBLEDataLengthError()
        return (
            b"\x00\x00\x00\x00\x01"
            + bytes([dp_id, dp_type])
            + len(value).to_bytes(2, "big")
            + value
        )

    def _build_ikphogdj_v4_enum_data(self, dp_id: int) -> bytes:
        """Build an ikphogdj V4 enum write (e.g. beep_volume)."""
        return self._build_ikphogdj_v4_scalar_data(dp_id, dp_type=0x04)

    def _build_ikphogdj_v4_bool_data(self, dp_id: int) -> bytes:
        """Build an ikphogdj V4 bool write (e.g. automatic_lock)."""
        return self._build_ikphogdj_v4_scalar_data(dp_id, dp_type=0x01)

    async def _send_datapoints(self, datapoint_ids: list[int]) -> None:
        """Send new values of datapoints to the device."""
        if self.product_id in ("hc7n0urm", "y2yaegze") and 6 in datapoint_ids:
            # This battery lock may be disconnected after Home Assistant startup,
            # so protocol_version can still be unknown here. The Raykube V4 path
            # establishes BLE connection and performs DEVICE_INFO/PAIR on demand.
            await self._send_datapoints_v3(datapoint_ids)
            return
        if self.product_id in ("hc7n0urm", "y2yaegze") and 46 in datapoint_ids:
            # Candidate physical lock command; allow on-demand connect.
            await self._send_datapoints_v3(datapoint_ids)
            return
        if self.product_id in ("hc7n0urm", "y2yaegze") and set(datapoint_ids).issubset({31, 48}):
            # Beep volume and lock direction use the same command-style V4
            # write framing as DP46 and must be allowed before protocol_version
            # is known on sleepy battery locks.
            await self._send_datapoints_v3(datapoint_ids)
            return

        if self.product_id == "z1dfsaya" and set(datapoint_ids).issubset({33, 79}):
            # Allow on-demand connect for the two confirmed 350K boolean
            # configuration controls.
            await self._send_datapoints_v3(datapoint_ids)
            return

        if self.product_id in ("ikphogdj", "c6hfl8bt") and (
            6 in datapoint_ids
            or 46 in datapoint_ids
            or 33 in datapoint_ids
            or set(datapoint_ids).issubset({31})
        ):
            await self._send_datapoints_v3(datapoint_ids)
            return

        if self._protocol_version == 3:
            await self._send_datapoints_v3(datapoint_ids)
        else:
            raise TuyaBLEDeviceError(0)
