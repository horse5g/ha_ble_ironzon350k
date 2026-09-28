from pathlib import Path
import json
import re

root = Path("custom_components/tuya_local_ble")

# ---- const.py -------------------------------------------------
p = root / "const.py"
s = p.read_text()
needle = "DP_350K_WRITE_CHUNK_SIZE: Final = -3508\n"
add = """DP_350K_WRITE_CHUNK_SIZE: Final = -3508
DP_350K_RECONNECT_COUNT: Final = -3509
DP_350K_CONNECTED_SINCE: Final = -3510
DP_350K_LAST_DISCONNECT_TIME: Final = -3511
DP_350K_LAST_EVENT_SEQUENCE: Final = -3512
DP_350K_EVENT_SEQUENCE_GAPS: Final = -3513
DP_350K_LAST_COMMAND: Final = -3514
DP_350K_LAST_COMMAND_RESULT: Final = -3515
DP_350K_LAST_COMMAND_DURATION_MS: Final = -3516
DP_350K_LAST_ACTUATION_LATENCY_MS: Final = -3517
"""
if "DP_350K_RECONNECT_COUNT" not in s:
    assert needle in s
    s = s.replace(needle, add, 1)
p.write_text(s)

# ---- tuya_ble.py ---------------------------------------------
p = root / "tuya_ble" / "tuya_ble.py"
s = p.read_text()

import_needle = "    DP_350K_WRITE_CHUNK_SIZE,\n"
import_add = """    DP_350K_WRITE_CHUNK_SIZE,
    DP_350K_RECONNECT_COUNT,
    DP_350K_CONNECTED_SINCE,
    DP_350K_LAST_DISCONNECT_TIME,
    DP_350K_LAST_EVENT_SEQUENCE,
    DP_350K_EVENT_SEQUENCE_GAPS,
    DP_350K_LAST_COMMAND,
    DP_350K_LAST_COMMAND_RESULT,
    DP_350K_LAST_COMMAND_DURATION_MS,
    DP_350K_LAST_ACTUATION_LATENCY_MS,
"""
if "    DP_350K_RECONNECT_COUNT," not in s:
    assert import_needle in s
    s = s.replace(import_needle, import_add, 1)

init_needle = "        self._350k_unlock_requested_monotonic: float | None = None\n"
init_add = """        self._350k_unlock_requested_monotonic: float | None = None
        # Session-local diagnostics. These intentionally reset when the HA
        # config entry reloads; they describe the current integration runtime.
        self._350k_seen_connected_once = False
        self._350k_reconnect_count = 0
        self._350k_last_event_seq: int | None = None
        self._350k_event_sequence_gaps = 0
        # Correlate acknowledged lock/unlock commands with authoritative DP47.
        self._350k_actuation_started_monotonic: float | None = None
        self._350k_actuation_expected_state: bool | None = None
        self._350k_actuation_command: str | None = None
"""
if "_350k_seen_connected_once" not in s:
    assert init_needle in s
    s = s.replace(init_needle, init_add, 1)

helper_needle = """    @property
    def keepalive_enabled(self) -> bool:
"""
helper_add = """    def _publish_350k_diagnostics(
        self,
        values: list[tuple[int, TuyaBLEDataPointType, bytes | bool | int | str]],
        *,
        timestamp: float | None = None,
        fire: bool = True,
    ) -> None:
        \"\"\"Update synthetic 350K diagnostics without touching real Tuya DPs.\"\"\"
        if self.product_id != \"z1dfsaya\":
            return
        now = time.time() if timestamp is None else timestamp
        updates: list[TuyaBLEDataPoint] = []
        for dp_id, dp_type, value in values:
            self._datapoints._update_from_device(dp_id, now, 0, dp_type, value)
            updates.append(self._datapoints[dp_id])
        # Do not fire while disconnected: TuyaBLECoordinator treats any DP
        # callback as evidence of an active connection. Silent values become
        # visible on the next real update/reconnect instead.
        if (
            fire
            and updates
            and self._client is not None
            and self._client.is_connected
        ):
            self._fire_callbacks(updates)

    def _finish_350k_command(
        self, command: str, result: str, started_monotonic: float
    ) -> None:
        \"\"\"Publish total command duration, including any on-demand reconnect.\"\"\"
        duration_ms = max(
            0,
            int(round((time.monotonic() - started_monotonic) * 1000.0)),
        )
        self._publish_350k_diagnostics(
            [
                (DP_350K_LAST_COMMAND, TuyaBLEDataPointType.DT_STRING, command),
                (DP_350K_LAST_COMMAND_RESULT, TuyaBLEDataPointType.DT_STRING, result),
                (
                    DP_350K_LAST_COMMAND_DURATION_MS,
                    TuyaBLEDataPointType.DT_VALUE,
                    duration_ms,
                ),
            ]
        )
        self._log_350k_event(
            \"%s: 350K command=%s result=%s total_duration_ms=%s\",
            self.address,
            command,
            result,
            duration_ms,
        )

    def _arm_350k_actuation(self, command: str, expected_unlocked: bool) -> None:
        \"\"\"Start ACK-to-DP47 motor timing for a confirmed command ACK.\"\"\"
        self._350k_actuation_command = command
        self._350k_actuation_expected_state = expected_unlocked
        self._350k_actuation_started_monotonic = time.monotonic()

    def _record_350k_connected(self) -> None:
        \"\"\"Record a newly authenticated 350K BLE session.\"\"\"
        if self.product_id != \"z1dfsaya\":
            return
        if self._350k_seen_connected_once:
            self._350k_reconnect_count += 1
        else:
            self._350k_seen_connected_once = True
        now = time.time()
        self._publish_350k_diagnostics(
            [
                (
                    DP_350K_CONNECTED_SINCE,
                    TuyaBLEDataPointType.DT_VALUE,
                    int(now),
                ),
                (
                    DP_350K_RECONNECT_COUNT,
                    TuyaBLEDataPointType.DT_VALUE,
                    self._350k_reconnect_count,
                ),
            ],
            timestamp=now,
        )

    def _record_350k_event_sequence(
        self, event_seq: int, datapoints: list[TuyaBLEDataPoint]
    ) -> None:
        \"\"\"Track the 40-bit report sequence and small forward gaps.

        A gap can indicate reports generated while HA was disconnected or a
        transport loss. Large jumps are treated as a lock reboot/reset rather
        than adding an absurd number of missing reports.
        \"\"\"
        mask = (1 << 40) - 1
        previous = self._350k_last_event_seq
        if previous is not None:
            expected = (previous + 1) & mask
            forward = (event_seq - expected) & mask
            if 0 < forward <= 1000:
                self._350k_event_sequence_gaps += forward
                self._log_350k_event(
                    \"%s: 350K V4 sequence gap previous=0x%010x current=0x%010x \"
                    \"missing=%s total_missing=%s\",
                    self.address,
                    previous,
                    event_seq,
                    forward,
                    self._350k_event_sequence_gaps,
                )
            elif forward > 1000 and event_seq != expected:
                self._log_350k_event(
                    \"%s: 350K V4 sequence discontinuity previous=0x%010x \"
                    \"current=0x%010x (reset/reorder; not counted)\",
                    self.address,
                    previous,
                    event_seq,
                )
        self._350k_last_event_seq = event_seq
        now = time.time()
        for dp_id, value in (
            (DP_350K_LAST_EVENT_SEQUENCE, event_seq),
            (DP_350K_EVENT_SEQUENCE_GAPS, self._350k_event_sequence_gaps),
        ):
            self._datapoints._update_from_device(
                dp_id,
                now,
                0,
                TuyaBLEDataPointType.DT_VALUE,
                int(value),
            )
            datapoints.append(self._datapoints[dp_id])

    @property
    def keepalive_enabled(self) -> bool:
"""
if "_record_350k_event_sequence" not in s:
    assert helper_needle in s
    s = s.replace(helper_needle, helper_add, 1)

disconnect_needle = """    def _disconnected(self, client: BleakClientWithServiceCache) -> None:
        \"\"\"Disconnected callback.\"\"\"
        self._350k_unlock_requested_monotonic = None
"""
disconnect_add = """    def _disconnected(self, client: BleakClientWithServiceCache) -> None:
        \"\"\"Disconnected callback.\"\"\"
        self._350k_unlock_requested_monotonic = None
        if self.product_id == \"z1dfsaya\":
            now = time.time()
            self._publish_350k_diagnostics(
                [
                    (
                        DP_350K_LAST_DISCONNECT_TIME,
                        TuyaBLEDataPointType.DT_VALUE,
                        int(now),
                    )
                ],
                timestamp=now,
                fire=False,
            )
            self._350k_actuation_started_monotonic = None
            self._350k_actuation_expected_state = None
            self._350k_actuation_command = None
"""
if "fire=False,\n            )\n            self._350k_actuation_started_monotonic = None" not in s:
    assert disconnect_needle in s
    s = s.replace(disconnect_needle, disconnect_add, 1)

connected_needle = """                    _LOGGER.debug(\"%s: Successfully connected\", self.address)
                    self._fire_connected_callbacks()
                    self._ensure_350k_keepalive_task()
"""
connected_add = """                    _LOGGER.debug(\"%s: Successfully connected\", self.address)
                    self._record_350k_connected()
                    self._fire_connected_callbacks()
                    self._ensure_350k_keepalive_task()
"""
if "self._record_350k_connected()" not in s:
    assert connected_needle in s
    s = s.replace(connected_needle, connected_add, 1)

sequence_needle = """        event_seq = int.from_bytes(data[0:5], \"big\")
        frame_marker = data[5]
        kind = data[6]
"""
sequence_add = """        event_seq = int.from_bytes(data[0:5], \"big\")
        frame_marker = data[5]
        kind = data[6]
        self._record_350k_event_sequence(event_seq, datapoints)
"""
if "self._record_350k_event_sequence(event_seq, datapoints)" not in s:
    assert sequence_needle in s
    s = s.replace(sequence_needle, sequence_add, 1)

old_dp47 = """        if dp_id == 47 and dp_type == TuyaBLEDataPointType.DT_BOOL:
            unlock_started = self._350k_unlock_requested_monotonic
            if unlock_started is not None:
                elapsed = time.monotonic() - unlock_started
                if elapsed > 15.0:
                    self._350k_unlock_requested_monotonic = None
                elif bool(value):
                    self._log_350k_event(
                        \"%s: 350K experimental unlock confirmed by DP47=True \"
                        \"after %.1f ms\",
                        self.address,
                        elapsed * 1000.0,
                    )
                    self._350k_unlock_requested_monotonic = None
"""
new_dp47 = """        if dp_id == 47 and dp_type == TuyaBLEDataPointType.DT_BOOL:
            started = self._350k_actuation_started_monotonic
            expected_state = self._350k_actuation_expected_state
            if started is not None and expected_state is not None:
                elapsed = time.monotonic() - started
                if elapsed > 15.0:
                    self._350k_actuation_started_monotonic = None
                    self._350k_actuation_expected_state = None
                    self._350k_actuation_command = None
                elif bool(value) == expected_state:
                    latency_ms = max(0, int(round(elapsed * 1000.0)))
                    command = self._350k_actuation_command or \"lock_state_change\"
                    self._log_350k_event(
                        \"%s: 350K %s confirmed by DP47=%s after %s ms from ACK\",
                        self.address,
                        command,
                        value,
                        latency_ms,
                    )
                    self._datapoints._update_from_device(
                        DP_350K_LAST_ACTUATION_LATENCY_MS,
                        time.time(),
                        0,
                        TuyaBLEDataPointType.DT_VALUE,
                        latency_ms,
                    )
                    datapoints.append(
                        self._datapoints[DP_350K_LAST_ACTUATION_LATENCY_MS]
                    )
                    self._350k_actuation_started_monotonic = None
                    self._350k_actuation_expected_state = None
                    self._350k_actuation_command = None
                    self._350k_unlock_requested_monotonic = None
"""
if old_dp47 in s:
    s = s.replace(old_dp47, new_dp47, 1)
elif "DP_350K_LAST_ACTUATION_LATENCY_MS" not in s[
    s.find("if dp_id == 47"):s.find("trailing = data[next_pos:]")
]:
    raise AssertionError("DP47 correlation block not found")

new_bool = """    async def set_350k_bool_datapoint(self, dp_id: int, value: bool) -> bool:
        \"\"\"Write one YD_350K boolean control datapoint.\"\"\"
        if self.product_id != \"z1dfsaya\" or dp_id not in (33, 46, 79):
            raise TuyaBLEDeviceError(0)
        if self._350k_control_lock.locked():
            _LOGGER.warning(
                \"%s: Ignoring 350K DP%s=%s; another control operation is still pending\",
                self.address,
                dp_id,
                value,
            )
            return False

        command = {
            33: \"passage_on\" if value else \"passage_off\",
            46: \"lock\" if value else \"manual_lock_false\",
            79: \"secure_on\" if value else \"secure_off\",
        }[dp_id]
        started = time.monotonic()
        async with self._350k_control_lock:
            payload = self._build_350k_v4_bool_data(dp_id, value)
            _LOGGER.debug(
                \"%s: Sending 350K control update, id: %s, value: %s\",
                self.address,
                dp_id,
                value,
            )
            self._log_350k_raw(
                \"%s: 350K raw FUN_SENDER_DPS_V4 plaintext: %s\",
                self.address,
                payload.hex(),
            )
            try:
                await self._ensure_connected()
                if (
                    self._expected_disconnect
                    or self._client is None
                    or not self._client.is_connected
                ):
                    self._finish_350k_command(command, \"not_connected\", started)
                    return False
                result = await self._send_packet_while_connected(
                    TuyaBLECode.FUN_SENDER_DPS_V4,
                    payload,
                    0,
                    True,
                )
                if not result:
                    self._finish_350k_command(
                        command, \"not_acknowledged\", started
                    )
                    return False
                self._finish_350k_command(command, \"acknowledged\", started)
                if dp_id == 46 and value:
                    self._arm_350k_actuation(\"lock\", expected_unlocked=False)
                return True
            except BLEAK_EXCEPTIONS:
                self._finish_350k_command(command, \"ble_error\", started)
                _LOGGER.warning(
                    \"%s: 350K DP%s=%s write failed due to BLE communication error\",
                    self.address,
                    dp_id,
                    value,
                    exc_info=True,
                )
                return False
            except Exception:
                self._finish_350k_command(command, \"error\", started)
                _LOGGER.exception(
                    \"%s: Unexpected error writing 350K DP%s=%s\",
                    self.address,
                    dp_id,
                    value,
                )
                return False

"""
s, n = re.subn(
    r"    async def set_350k_bool_datapoint\(.*?\n(?=    def _build_350k_v4_enum_data)",
    new_bool,
    s,
    count=1,
    flags=re.S,
)
assert n == 1

new_enum = """    async def set_350k_enum_datapoint(self, dp_id: int, value: int) -> bool:
        \"\"\"Write DP28 language or DP31 volume without optimistic state.\"\"\"
        if self.product_id != \"z1dfsaya\" or dp_id not in (28, 31):
            raise TuyaBLEDeviceError(0)
        if self._350k_control_lock.locked():
            _LOGGER.warning(
                \"%s: Ignoring 350K DP%s=%s; another control operation is pending\",
                self.address,
                dp_id,
                value,
            )
            return False
        command = \"language\" if dp_id == 28 else \"volume\"
        started = time.monotonic()
        async with self._350k_control_lock:
            payload = self._build_350k_v4_enum_data(dp_id, value)
            _LOGGER.debug(
                \"%s: Sending 350K enum update, id: %s, value: %s\",
                self.address,
                dp_id,
                value,
            )
            self._log_350k_raw(
                \"%s: 350K raw FUN_SENDER_DPS_V4 enum plaintext: %s\",
                self.address,
                payload.hex(),
            )
            try:
                await self._ensure_connected()
                if (
                    self._expected_disconnect
                    or self._client is None
                    or not self._client.is_connected
                ):
                    self._finish_350k_command(command, \"not_connected\", started)
                    return False
                result = await self._send_packet_while_connected(
                    TuyaBLECode.FUN_SENDER_DPS_V4,
                    payload,
                    0,
                    True,
                )
                self._finish_350k_command(
                    command,
                    \"acknowledged\" if result else \"not_acknowledged\",
                    started,
                )
                return result
            except BLEAK_EXCEPTIONS:
                self._finish_350k_command(command, \"ble_error\", started)
                _LOGGER.warning(
                    \"%s: 350K DP%s=%s enum write failed due to BLE error\",
                    self.address,
                    dp_id,
                    value,
                    exc_info=True,
                )
                return False
            except Exception:
                self._finish_350k_command(command, \"error\", started)
                _LOGGER.exception(
                    \"%s: Unexpected error writing 350K enum DP%s=%s\",
                    self.address,
                    dp_id,
                    value,
                )
                return False

"""
s, n = re.subn(
    r"    async def set_350k_enum_datapoint\(.*?\n(?=    async def unlock_350k)",
    new_enum,
    s,
    count=1,
    flags=re.S,
)
assert n == 1

new_unlock = """    async def unlock_350k(self) -> bool:
        \"\"\"Send the experimental YD_350K DP71 BLE unlock command.

        No lock state is changed optimistically. DP47 remains authoritative.
        \"\"\"
        if self.product_id != \"z1dfsaya\":
            raise TuyaBLEDeviceError(0)
        if self._350k_control_lock.locked():
            _LOGGER.warning(
                \"%s: Ignoring 350K unlock; another control operation is still pending\",
                self.address,
            )
            return False

        command = \"unlock\"
        started = time.monotonic()
        async with self._350k_control_lock:
            try:
                payload = self._build_raykube_unlock_v4_data()
            except Exception:
                self._finish_350k_command(command, \"unavailable\", started)
                _LOGGER.warning(
                    \"%s: 350K unlock unavailable; ble_unlock_check is missing or invalid\",
                    self.address,
                )
                return False

            _LOGGER.debug(
                \"%s: Sending experimental 350K DP71 unlock command\",
                self.address,
            )
            self._log_350k_raw(
                \"%s: 350K experimental DP71 unlock metadata: \"
                \"plaintext_len=%s authorization_body=<redacted>\",
                self.address,
                len(payload),
            )
            try:
                await self._ensure_connected()
                if (
                    self._expected_disconnect
                    or self._client is None
                    or not self._client.is_connected
                ):
                    self._finish_350k_command(command, \"not_connected\", started)
                    return False
                result = await self._send_packet_while_connected(
                    TuyaBLECode.FUN_SENDER_DPS_V4,
                    payload,
                    0,
                    True,
                )
                if not result:
                    self._finish_350k_command(
                        command, \"not_acknowledged\", started
                    )
                    return False
                self._finish_350k_command(command, \"acknowledged\", started)
                self._350k_unlock_requested_monotonic = time.monotonic()
                self._arm_350k_actuation(\"unlock\", expected_unlocked=True)
                return True
            except BLEAK_EXCEPTIONS:
                self._350k_unlock_requested_monotonic = None
                self._finish_350k_command(command, \"ble_error\", started)
                _LOGGER.warning(
                    \"%s: 350K DP71 unlock failed due to BLE communication error\",
                    self.address,
                    exc_info=True,
                )
                return False
            except Exception:
                self._350k_unlock_requested_monotonic = None
                self._finish_350k_command(command, \"error\", started)
                _LOGGER.exception(
                    \"%s: Unexpected error sending experimental 350K DP71 unlock\",
                    self.address,
                )
                return False

"""
s, n = re.subn(
    r"    async def unlock_350k\(.*?\n(?=    async def linger_connected)",
    new_unlock,
    s,
    count=1,
    flags=re.S,
)
assert n == 1

p.write_text(s)

# ---- sensor.py -----------------------------------------------
p = root / "sensor.py"
s = p.read_text()
import_needle = "    DP_350K_WRITE_CHUNK_SIZE,\n"
import_add = """    DP_350K_WRITE_CHUNK_SIZE,
    DP_350K_RECONNECT_COUNT,
    DP_350K_CONNECTED_SINCE,
    DP_350K_LAST_DISCONNECT_TIME,
    DP_350K_LAST_EVENT_SEQUENCE,
    DP_350K_EVENT_SEQUENCE_GAPS,
    DP_350K_LAST_COMMAND,
    DP_350K_LAST_COMMAND_RESULT,
    DP_350K_LAST_COMMAND_DURATION_MS,
    DP_350K_LAST_ACTUATION_LATENCY_MS,
"""
if "    DP_350K_RECONNECT_COUNT," not in s:
    assert import_needle in s
    s = s.replace(import_needle, import_add, 1)

getter_needle = """def last_access_event_time_getter(self: TuyaBLESensor) -> None:
    \"\"\"Expose the 350K event epoch as a Home Assistant timestamp.\"\"\"
    datapoint = self._device.datapoints[DP_350K_LAST_ACCESS_EVENT_TIME]
    if datapoint:
        self._attr_native_value = datetime.fromtimestamp(
            int(datapoint.value), tz=timezone.utc
        )


"""
getter_add = getter_needle + """def diagnostic_timestamp_getter(self: TuyaBLESensor) -> None:
    \"\"\"Expose a synthetic epoch datapoint as a Home Assistant timestamp.\"\"\"
    datapoint = self._device.datapoints[self._mapping.dp_id]
    if datapoint:
        self._attr_native_value = datetime.fromtimestamp(
            int(datapoint.value), tz=timezone.utc
        )


"""
if "def diagnostic_timestamp_getter" not in s:
    assert getter_needle in s
    s = s.replace(getter_needle, getter_add, 1)

sensor_needle = """                TuyaBLESensorMapping(
                    dp_id=DP_350K_WRITE_CHUNK_SIZE,
                    description=SensorEntityDescription(
                        key=\"gatt_write_chunk_size\",
                        icon=\"mdi:bluetooth-transfer\",
                        native_unit_of_measurement=\"B\",
                        entity_category=EntityCategory.DIAGNOSTIC,
                        entity_registry_enabled_default=False,
                    ),
                ),
"""
sensor_add = sensor_needle + """                TuyaBLESensorMapping(
                    dp_id=DP_350K_RECONNECT_COUNT,
                    description=SensorEntityDescription(
                        key=\"ble_reconnect_count\",
                        icon=\"mdi:connection\",
                        entity_category=EntityCategory.DIAGNOSTIC,
                        entity_registry_enabled_default=False,
                    ),
                ),
                TuyaBLESensorMapping(
                    dp_id=DP_350K_CONNECTED_SINCE,
                    getter=diagnostic_timestamp_getter,
                    description=SensorEntityDescription(
                        key=\"ble_connected_since\",
                        device_class=SensorDeviceClass.TIMESTAMP,
                        icon=\"mdi:bluetooth-connect\",
                        entity_category=EntityCategory.DIAGNOSTIC,
                        entity_registry_enabled_default=False,
                    ),
                ),
                TuyaBLESensorMapping(
                    dp_id=DP_350K_LAST_DISCONNECT_TIME,
                    getter=diagnostic_timestamp_getter,
                    description=SensorEntityDescription(
                        key=\"last_ble_disconnect\",
                        device_class=SensorDeviceClass.TIMESTAMP,
                        icon=\"mdi:bluetooth-off\",
                        entity_category=EntityCategory.DIAGNOSTIC,
                        entity_registry_enabled_default=False,
                    ),
                ),
                TuyaBLESensorMapping(
                    dp_id=DP_350K_LAST_EVENT_SEQUENCE,
                    description=SensorEntityDescription(
                        key=\"last_v4_event_sequence\",
                        icon=\"mdi:numeric\",
                        entity_category=EntityCategory.DIAGNOSTIC,
                        entity_registry_enabled_default=False,
                    ),
                ),
                TuyaBLESensorMapping(
                    dp_id=DP_350K_EVENT_SEQUENCE_GAPS,
                    description=SensorEntityDescription(
                        key=\"v4_sequence_gaps\",
                        icon=\"mdi:alert-decagram-outline\",
                        entity_category=EntityCategory.DIAGNOSTIC,
                        entity_registry_enabled_default=False,
                    ),
                ),
                TuyaBLESensorMapping(
                    dp_id=DP_350K_LAST_COMMAND,
                    description=SensorEntityDescription(
                        key=\"last_command\",
                        icon=\"mdi:gesture-tap-button\",
                        entity_category=EntityCategory.DIAGNOSTIC,
                        entity_registry_enabled_default=False,
                    ),
                ),
                TuyaBLESensorMapping(
                    dp_id=DP_350K_LAST_COMMAND_RESULT,
                    description=SensorEntityDescription(
                        key=\"last_command_result\",
                        icon=\"mdi:check-network-outline\",
                        entity_category=EntityCategory.DIAGNOSTIC,
                        entity_registry_enabled_default=False,
                    ),
                ),
                TuyaBLESensorMapping(
                    dp_id=DP_350K_LAST_COMMAND_DURATION_MS,
                    description=SensorEntityDescription(
                        key=\"last_command_duration\",
                        icon=\"mdi:timer-sand\",
                        native_unit_of_measurement=\"ms\",
                        entity_category=EntityCategory.DIAGNOSTIC,
                        entity_registry_enabled_default=False,
                    ),
                ),
                TuyaBLESensorMapping(
                    dp_id=DP_350K_LAST_ACTUATION_LATENCY_MS,
                    description=SensorEntityDescription(
                        key=\"last_actuation_latency\",
                        icon=\"mdi:lock-clock\",
                        native_unit_of_measurement=\"ms\",
                        entity_category=EntityCategory.DIAGNOSTIC,
                        entity_registry_enabled_default=False,
                    ),
                ),
"""
if 'key="ble_reconnect_count"' not in s:
    assert sensor_needle in s
    s = s.replace(sensor_needle, sensor_add, 1)
p.write_text(s)

# ---- translations --------------------------------------------
names = {
    "ble_reconnect_count": "BLE reconnect count",
    "ble_connected_since": "BLE connected since",
    "last_ble_disconnect": "Last BLE disconnect",
    "last_v4_event_sequence": "Last V4 event sequence",
    "v4_sequence_gaps": "V4 sequence gaps",
    "last_command": "Last command",
    "last_command_result": "Last command result",
    "last_command_duration": "Last command duration",
    "last_actuation_latency": "Last lock actuation latency",
}
for rel in ("strings.json", "translations/en.json"):
    p = root / rel
    data = json.loads(p.read_text())
    sensor = data.setdefault("entity", {}).setdefault("sensor", {})
    for key, name in names.items():
        sensor[key] = {"name": name}
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")

# ---- README ---------------------------------------------------
p = Path("README.md")
s = p.read_text()
marker = "## Suggested test sequence\n"
docs = """## Session and command diagnostics

The experimental branch also provides disabled-by-default local diagnostic sensors for:

- BLE reconnect count (session-local; resets when the config entry reloads).
- BLE connected-since and last-disconnect timestamps.
- Last observed 40-bit V4 event sequence and cumulative small sequence gaps.
- Last high-level 350K command, command result, and total duration including on-demand reconnect time.
- ACK latency, GATT write count/size, negotiated write chunk size, and ACK-to-DP47 motor actuation latency.

Sequence gaps are intentionally conservative: small forward jumps are counted as potentially missed reports, while large discontinuities are treated as reboot/reset/reordering and logged without inflating the gap counter. Lock/unlock actuation latency starts after the protocol ACK and stops only when authoritative DP47 reaches the requested physical state.

"""
if "## Session and command diagnostics" not in s:
    assert marker in s
    s = s.replace(marker, docs + marker, 1)
p.write_text(s)
