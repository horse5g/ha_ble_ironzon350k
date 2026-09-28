from __future__ import annotations

from pathlib import Path
import json
import re

ROOT = Path("custom_components/tuya_local_ble")


def replace_once(text: str, old: str, new: str, *, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


# ---------------------------------------------------------------------------
# Pure 350K helpers: deliberately Home-Assistant-free so they can be unit tested
# in a plain Python runner.
# ---------------------------------------------------------------------------
helper = ROOT / "tuya_ble" / "diagnostics_350k.py"
helper.write_text(
'''"""Pure helpers for YD_350K diagnostics and protocol experiments."""
from __future__ import annotations

EVENT_TIMELINE_CAPACITY = 50
TIMELINE_SENSITIVE_SCALAR_DPS = frozenset({12, 13, 19})
INTERPRETED_DPS = frozenset({
    8, 12, 13, 19, 20, 21, 28, 31, 32, 33, 46, 47, 79,
})

TUYA_DT_RAW = 0
TUYA_DT_BOOL = 1
TUYA_DT_VALUE = 2
TUYA_DT_STRING = 3
TUYA_DT_ENUM = 4
TUYA_DT_BITMAP = 5


def build_v4_bool_data(dp_id: int, value: bool) -> bytes:
    """Build the typed 350K V4 boolean body used by confirmed controls."""
    if not 0 <= int(dp_id) <= 0xFF:
        raise ValueError("dp_id out of range")
    return (
        b"\\x00\\x00\\x00\\x00\\x01"
        + bytes([int(dp_id), TUYA_DT_BOOL])
        + b"\\x00\\x01"
        + bytes([1 if value else 0])
    )


def build_v4_enum_data(dp_id: int, value: int) -> bytes:
    """Build the typed 350K V4 one-byte enum body."""
    if not 0 <= int(dp_id) <= 0xFF or not 0 <= int(value) <= 0xFF:
        raise ValueError("dp_id/value out of range")
    return (
        b"\\x00\\x00\\x00\\x00\\x01"
        + bytes([int(dp_id), TUYA_DT_ENUM])
        + b"\\x00\\x01"
        + bytes([int(value)])
    )


def valid_dp71_payload_shape(payload: bytes) -> bool:
    """Validate only the non-secret framing of the inferred DP71 command."""
    return (
        len(payload) == 28
        and payload[:9] == b"\\x00\\x00\\x00\\x00\\x01\\x47\\x00\\x00\\x13"
    )


def normalize_write_chunk_size(max_size: int, fallback: int = 20, cap: int = 244) -> int:
    """Choose a safe write-without-response payload size."""
    try:
        value = int(max_size)
    except (TypeError, ValueError):
        return fallback
    if value <= fallback:
        return fallback
    return min(value, cap)


def compute_sequence_gap(
    previous: int | None,
    current: int,
    *,
    bits: int = 40,
    max_counted_gap: int = 1000,
) -> tuple[int, bool]:
    """Return (missing_count, discontinuity) for a wrapping event counter."""
    if previous is None:
        return 0, False
    mask = (1 << bits) - 1
    expected = (int(previous) + 1) & mask
    forward = (int(current) - expected) & mask
    if forward == 0:
        return 0, False
    if forward <= max_counted_gap:
        return forward, False
    return 0, True


def sanitize_timeline_scalar(
    dp_id: int,
    type_name: str,
    value: object,
) -> tuple[bool | int | None, bool]:
    """Return (safe_scalar, payload_redacted) for timeline storage."""
    if type_name == "DT_BOOL":
        return bool(value), False
    if type_name in ("DT_ENUM", "DT_VALUE"):
        if int(dp_id) in TIMELINE_SENSITIVE_SCALAR_DPS:
            return None, True
        return int(value), False
    return None, True


def append_bounded_event(
    buffer: list[dict[str, object]],
    event: dict[str, object],
    *,
    capacity: int = EVENT_TIMELINE_CAPACITY,
) -> None:
    """Append an event and trim oldest entries to a fixed capacity."""
    buffer.append(event)
    overflow = len(buffer) - int(capacity)
    if overflow > 0:
        del buffer[:overflow]


def sanitize_marker_text(value: object, max_length: int) -> str:
    """Normalize a user-supplied marker label/note for bounded attributes."""
    text = " ".join(str(value).split())
    return text[:max_length]
''',
    encoding="utf-8",
)


# ---------------------------------------------------------------------------
# const.py
# ---------------------------------------------------------------------------
p = ROOT / "const.py"
s = p.read_text(encoding="utf-8")
needle = "DP_350K_EVENT_TIMELINE_COUNT: Final = -3519\n"
addition = needle + '''DP_350K_LAST_DEVICE_REPORT_TIME: Final = -3520
DP_350K_STATE_AGE_SECONDS: Final = -3521
DP_350K_SESSION_STATE: Final = -3522
DP_350K_LAST_RX_AGE_SECONDS: Final = -3523
DP_350K_COMMAND_COUNTERS: Final = -3524
DP_350K_DEVICE_VERSION: Final = -3525
DP_350K_HARDWARE_VERSION: Final = -3526
DP_350K_PROTOCOL_VERSION: Final = -3527

EVENT_350K: Final = DOMAIN + "_350k_event"
'''
if "DP_350K_LAST_DEVICE_REPORT_TIME" not in s:
    s = replace_once(s, needle, addition, label="const synthetic diagnostics")
p.write_text(s, encoding="utf-8")


# ---------------------------------------------------------------------------
# tuya_ble.py
# ---------------------------------------------------------------------------
p = ROOT / "tuya_ble" / "tuya_ble.py"
s = p.read_text(encoding="utf-8")

# Add new local diagnostic constants to the existing ..const import.
needle = '''    DP_350K_EVENT_TIMELINE_COUNT,
    PROTOCOL_LOG_EVENTS,
'''
replacement = '''    DP_350K_EVENT_TIMELINE_COUNT,
    DP_350K_LAST_DEVICE_REPORT_TIME,
    DP_350K_STATE_AGE_SECONDS,
    DP_350K_SESSION_STATE,
    DP_350K_LAST_RX_AGE_SECONDS,
    DP_350K_COMMAND_COUNTERS,
    DP_350K_DEVICE_VERSION,
    DP_350K_HARDWARE_VERSION,
    DP_350K_PROTOCOL_VERSION,
    PROTOCOL_LOG_EVENTS,
'''
if "    DP_350K_LAST_DEVICE_REPORT_TIME," not in s:
    s = replace_once(s, needle, replacement, label="tuya import diagnostic constants")

# Import the pure helpers.
needle = '''from .exceptions import (
'''
helper_import = '''from .diagnostics_350k import (
    EVENT_TIMELINE_CAPACITY,
    INTERPRETED_DPS,
    TIMELINE_SENSITIVE_SCALAR_DPS,
    append_bounded_event,
    build_v4_bool_data,
    build_v4_enum_data,
    compute_sequence_gap,
    normalize_write_chunk_size,
    sanitize_marker_text,
    sanitize_timeline_scalar,
    valid_dp71_payload_shape,
)
from .exceptions import (
'''
if "from .diagnostics_350k import (" not in s:
    s = replace_once(s, needle, helper_import, label="tuya pure helper import")

# Replace duplicated discovery constants with helper aliases.
pattern = re.compile(
    r'''# Datapoints whose 350K receive-side meaning is sufficiently understood that\n'''
    r'''# they already have dedicated parsing/entities\. Everything else is eligible\n'''
    r'''# for the sanitized discovery recorder below\.\n'''
    r'''_350K_EVENT_TIMELINE_CAPACITY = 25\n'''
    r'''# Credential/user identifiers are useful elsewhere in dedicated diagnostics,\n'''
    r'''# but the generic timeline deliberately redacts them so it is safer to share\.\n'''
    r'''_350K_TIMELINE_SENSITIVE_SCALAR_DPS = frozenset\(\{12, 13, 19\}\)\n\n'''
    r'''_350K_INTERPRETED_DPS = frozenset\(\{.*?\}\)\n''',
    re.S,
)
replacement = '''# Shared with the pure unit-testable helpers.
_350K_EVENT_TIMELINE_CAPACITY = EVENT_TIMELINE_CAPACITY
_350K_TIMELINE_SENSITIVE_SCALAR_DPS = TIMELINE_SENSITIVE_SCALAR_DPS
_350K_INTERPRETED_DPS = INTERPRETED_DPS
'''
if "_350K_EVENT_TIMELINE_CAPACITY = 25" in s:
    s, count = pattern.subn(replacement, s, count=1)
    if count != 1:
        raise RuntimeError("replace duplicated 350K helper constants failed")

# Extend runtime state.
needle = '''        self._350k_event_timeline: list[dict[str, object]] = []
        # Session-local diagnostics. These intentionally reset when the HA
'''
replacement = '''        self._350k_event_timeline: list[dict[str, object]] = []
        self._350k_last_rx_seen = False
        self._350k_last_device_report_time: float | None = None
        self._350k_command_counters: dict[str, int] = {
            "total": 0,
            "success": 0,
            "timeout_or_not_acknowledged": 0,
            "ble_error": 0,
            "not_connected": 0,
            "busy": 0,
            "unavailable": 0,
            "error": 0,
            "reconnect_required": 0,
        }
        # Session-local diagnostics. These intentionally reset when the HA
'''
if "self._350k_command_counters" not in s:
    s = replace_once(s, needle, replacement, label="tuya runtime harness state")

# Initialize local-only datapoints that should exist before the first report.
old = '''                self._datapoints._update_from_device(
                    DP_350K_UNKNOWN_DP_COUNT,
                    now,
                    0,
                    TuyaBLEDataPointType.DT_VALUE,
                    0,
                )
                self._datapoints._update_from_device(
                    DP_350K_EVENT_TIMELINE_COUNT,
                    now,
                    0,
                    TuyaBLEDataPointType.DT_VALUE,
                    0,
                )
'''
new = '''                for dp_id, dp_type, value in (
                    (DP_350K_UNKNOWN_DP_COUNT, TuyaBLEDataPointType.DT_VALUE, 0),
                    (DP_350K_EVENT_TIMELINE_COUNT, TuyaBLEDataPointType.DT_VALUE, 0),
                    (DP_350K_STATE_AGE_SECONDS, TuyaBLEDataPointType.DT_VALUE, 0),
                    (DP_350K_SESSION_STATE, TuyaBLEDataPointType.DT_STRING, "disconnected"),
                    (DP_350K_LAST_RX_AGE_SECONDS, TuyaBLEDataPointType.DT_VALUE, 0),
                    (DP_350K_COMMAND_COUNTERS, TuyaBLEDataPointType.DT_VALUE, 0),
                    (DP_350K_DEVICE_VERSION, TuyaBLEDataPointType.DT_STRING, ""),
                    (DP_350K_HARDWARE_VERSION, TuyaBLEDataPointType.DT_STRING, ""),
                    (DP_350K_PROTOCOL_VERSION, TuyaBLEDataPointType.DT_STRING, ""),
                ):
                    self._datapoints._update_from_device(
                        dp_id, now, 0, dp_type, value
                    )
'''
if "(DP_350K_COMMAND_COUNTERS, TuyaBLEDataPointType.DT_VALUE, 0)" not in s:
    s = replace_once(s, old, new, label="tuya initialize diagnostics")

# Insert harness properties/methods before _finish_350k_command.
anchor = '''    def _finish_350k_command(
        self, command: str, result: str, started_monotonic: float
    ) -> None:
'''
if "def sanitized_diagnostics_snapshot(" not in s:
    block = '''    @property
    def session_state(self) -> str:
        """Return disconnected/connected/authenticated for local diagnostics."""
        if self._client is not None and self._client.is_connected:
            return "authenticated" if self._is_paired else "connected"
        return "disconnected"

    @property
    def last_device_report_timestamp(self) -> float | None:
        return self._350k_last_device_report_time

    @property
    def state_age_seconds(self) -> int | None:
        if self._350k_last_device_report_time is None:
            return None
        return max(0, int(time.time() - self._350k_last_device_report_time))

    @property
    def last_rx_age_seconds(self) -> int | None:
        if not self._350k_last_rx_seen:
            return None
        return max(0, int(time.monotonic() - self._350k_last_rx_monotonic))

    @property
    def command_counters(self) -> dict[str, int]:
        return dict(self._350k_command_counters)

    def _publish_350k_command_counters(self) -> None:
        self._publish_350k_diagnostics(
            [(
                DP_350K_COMMAND_COUNTERS,
                TuyaBLEDataPointType.DT_VALUE,
                int(self._350k_command_counters["total"]),
            )]
        )

    def _begin_350k_command(self, command: str) -> float:
        self._350k_command_counters["total"] += 1
        if self.session_state != "authenticated":
            self._350k_command_counters["reconnect_required"] += 1
        self._publish_350k_command_counters()
        return time.monotonic()

    def _record_350k_busy(self, command: str) -> None:
        self._350k_command_counters["total"] += 1
        self._350k_command_counters["busy"] += 1
        self._publish_350k_diagnostics(
            [
                (DP_350K_LAST_COMMAND, TuyaBLEDataPointType.DT_STRING, command),
                (DP_350K_LAST_COMMAND_RESULT, TuyaBLEDataPointType.DT_STRING, "busy"),
                (DP_350K_LAST_COMMAND_DURATION_MS, TuyaBLEDataPointType.DT_VALUE, 0),
                (
                    DP_350K_COMMAND_COUNTERS,
                    TuyaBLEDataPointType.DT_VALUE,
                    int(self._350k_command_counters["total"]),
                ),
            ]
        )

    def _record_350k_device_report(
        self, datapoints: list[TuyaBLEDataPoint]
    ) -> None:
        """Record receive-time freshness for a validated 350K V4 report."""
        now = time.time()
        self._350k_last_device_report_time = now
        for dp_id, value in (
            (DP_350K_LAST_DEVICE_REPORT_TIME, int(now)),
            (DP_350K_STATE_AGE_SECONDS, 0),
        ):
            self._datapoints._update_from_device(
                dp_id, now, 0, TuyaBLEDataPointType.DT_VALUE, value
            )
            datapoints.append(self._datapoints[dp_id])

    def mark_350k_test(self, label: str, note: str | None = None) -> None:
        """Insert a human test marker into the sanitized local timeline."""
        if self.product_id != "z1dfsaya":
            raise TuyaBLEDeviceError(0)
        safe_label = sanitize_marker_text(label, 64)
        if not safe_label:
            raise ValueError("marker label cannot be empty")
        entry: dict[str, object] = {
            "timestamp": int(time.time()),
            "source": "marker",
            "label": safe_label,
            "user_supplied": True,
        }
        if note:
            safe_note = sanitize_marker_text(note, 100)
            if safe_note:
                entry["note"] = safe_note
        append_bounded_event(
            self._350k_event_timeline,
            entry,
            capacity=_350K_EVENT_TIMELINE_CAPACITY,
        )
        self._publish_350k_diagnostics(
            [(
                DP_350K_EVENT_TIMELINE_COUNT,
                TuyaBLEDataPointType.DT_VALUE,
                len(self._350k_event_timeline),
            )]
        )

    def clear_350k_diagnostics(self) -> None:
        """Clear experiment observations without changing physical lock state."""
        if self.product_id != "z1dfsaya":
            raise TuyaBLEDeviceError(0)
        self._350k_unknown_dps.clear()
        self._350k_unknown_dp_overflow = 0
        self._350k_event_timeline.clear()
        self._350k_last_event_seq = None
        self._350k_event_sequence_gaps = 0
        for key in self._350k_command_counters:
            self._350k_command_counters[key] = 0
        self._publish_350k_diagnostics(
            [
                (DP_350K_UNKNOWN_DP_COUNT, TuyaBLEDataPointType.DT_VALUE, 0),
                (DP_350K_EVENT_TIMELINE_COUNT, TuyaBLEDataPointType.DT_VALUE, 0),
                (DP_350K_EVENT_SEQUENCE_GAPS, TuyaBLEDataPointType.DT_VALUE, 0),
                (DP_350K_COMMAND_COUNTERS, TuyaBLEDataPointType.DT_VALUE, 0),
                (DP_350K_LAST_COMMAND, TuyaBLEDataPointType.DT_STRING, ""),
                (DP_350K_LAST_COMMAND_RESULT, TuyaBLEDataPointType.DT_STRING, ""),
                (DP_350K_LAST_COMMAND_DURATION_MS, TuyaBLEDataPointType.DT_VALUE, 0),
                (DP_350K_LAST_ACTUATION_LATENCY_MS, TuyaBLEDataPointType.DT_VALUE, 0),
                (DP_350K_LAST_ACK_LATENCY_MS, TuyaBLEDataPointType.DT_VALUE, 0),
                (DP_350K_LAST_GATT_WRITE_COUNT, TuyaBLEDataPointType.DT_VALUE, 0),
                (DP_350K_LAST_GATT_WRITE_BYTES, TuyaBLEDataPointType.DT_VALUE, 0),
            ]
        )

    def sanitized_diagnostics_snapshot(self) -> dict[str, object]:
        """Return a shareable snapshot without auth/credential/raw payload data."""
        def diag_value(dp_id: int) -> object | None:
            dp = self._datapoints[dp_id]
            if dp is None or isinstance(dp.value, (bytes, bytearray)):
                return None
            return dp.value

        known: dict[str, dict[str, object]] = {}
        for dp_id in (8, 28, 31, 32, 33, 47, 68, 78, 79):
            dp = self._datapoints[dp_id]
            if dp is None or isinstance(dp.value, (bytes, bytearray)):
                continue
            known[str(dp_id)] = {"type": dp.type.name, "value": dp.value}

        return {
            "sanitized": True,
            "generated_at": int(time.time()),
            "device": {
                "product_id": self.product_id,
                "product_model": self.product_model,
                "product_name": self.product_name,
                "firmware_version": self.device_version,
                "hardware_version": self.hardware_version,
                "protocol_version": self.protocol_version,
            },
            "session": {
                "state": self.session_state,
                "keepalive_enabled": self.keepalive_enabled,
                "reconnect_count": self._350k_reconnect_count,
                "connected_since": diag_value(DP_350K_CONNECTED_SINCE),
                "last_disconnect": diag_value(DP_350K_LAST_DISCONNECT_TIME),
                "last_device_report": (
                    int(self._350k_last_device_report_time)
                    if self._350k_last_device_report_time is not None
                    else None
                ),
                "state_age_seconds": self.state_age_seconds,
                "last_rx_age_seconds": self.last_rx_age_seconds,
                "last_event_sequence": self._350k_last_event_seq,
                "sequence_gaps": self._350k_event_sequence_gaps,
            },
            "commands": {
                "counters": self.command_counters,
                "last_command": diag_value(DP_350K_LAST_COMMAND),
                "last_result": diag_value(DP_350K_LAST_COMMAND_RESULT),
                "last_duration_ms": diag_value(DP_350K_LAST_COMMAND_DURATION_MS),
                "last_ack_latency_ms": diag_value(DP_350K_LAST_ACK_LATENCY_MS),
                "last_actuation_latency_ms": diag_value(
                    DP_350K_LAST_ACTUATION_LATENCY_MS
                ),
            },
            "transport": {
                "last_gatt_write_count": diag_value(DP_350K_LAST_GATT_WRITE_COUNT),
                "largest_last_gatt_write": diag_value(DP_350K_LAST_GATT_WRITE_BYTES),
                "write_chunk_size": diag_value(DP_350K_WRITE_CHUNK_SIZE),
            },
            "known_datapoints": known,
            "unknown_datapoints": self.unknown_dp_diagnostics,
            "timeline": self.event_timeline_diagnostics,
        }

    async def refresh_350k_status(self) -> bool:
        """Explicitly connect/authenticate and request DEVICE_STATUS once."""
        if self.product_id != "z1dfsaya":
            raise TuyaBLEDeviceError(0)
        command = "refresh_status"
        if self._350k_control_lock.locked():
            self._record_350k_busy(command)
            return False
        started = self._begin_350k_command(command)
        async with self._350k_control_lock:
            try:
                await self._ensure_connected()
                if (
                    self._expected_disconnect
                    or self._client is None
                    or not self._client.is_connected
                ):
                    self._finish_350k_command(command, "not_connected", started)
                    return False
                result = await self._send_packet_while_connected(
                    TuyaBLECode.FUN_SENDER_DEVICE_STATUS,
                    bytes(),
                    0,
                    True,
                )
                self._finish_350k_command(
                    command,
                    "acknowledged" if result else "not_acknowledged",
                    started,
                )
                return result
            except BLEAK_EXCEPTIONS:
                self._finish_350k_command(command, "ble_error", started)
                return False
            except Exception:
                self._finish_350k_command(command, "error", started)
                _LOGGER.exception("%s: 350K manual status refresh failed", self.address)
                return False

'''
    s = replace_once(s, anchor, block + anchor, label="tuya insert test harness")

# Count command outcomes in _finish_350k_command.
old = '''        self._publish_350k_diagnostics(
            [
                (DP_350K_LAST_COMMAND, TuyaBLEDataPointType.DT_STRING, command),
'''
new = '''        if result == "acknowledged":
            self._350k_command_counters["success"] += 1
        elif result == "not_acknowledged":
            self._350k_command_counters["timeout_or_not_acknowledged"] += 1
        elif result in self._350k_command_counters:
            self._350k_command_counters[result] += 1
        else:
            self._350k_command_counters["error"] += 1
        self._publish_350k_diagnostics(
            [
                (DP_350K_LAST_COMMAND, TuyaBLEDataPointType.DT_STRING, command),
'''
# Only replace the occurrence inside _finish, which follows our inserted block.
finish_pos = s.find("    def _finish_350k_command(")
if finish_pos < 0:
    raise RuntimeError("_finish_350k_command not found")
sub = s[finish_pos:]
if "self._350k_command_counters[\"success\"]" not in sub[:2000]:
    sub = replace_once(sub, old, new, label="tuya finish command counters")
    s = s[:finish_pos] + sub

# Include counter synthetic DP in the finish update so entities refresh once.
needle = '''                (
                    DP_350K_LAST_COMMAND_DURATION_MS,
                    TuyaBLEDataPointType.DT_VALUE,
                    duration_ms,
                ),
            ]
        )
'''
replacement = '''                (
                    DP_350K_LAST_COMMAND_DURATION_MS,
                    TuyaBLEDataPointType.DT_VALUE,
                    duration_ms,
                ),
                (
                    DP_350K_COMMAND_COUNTERS,
                    TuyaBLEDataPointType.DT_VALUE,
                    int(self._350k_command_counters["total"]),
                ),
            ]
        )
'''
finish_pos = s.find("    def _finish_350k_command(")
sub = s[finish_pos:]
if "DP_350K_COMMAND_COUNTERS" not in sub[:1800]:
    sub = replace_once(sub, needle, replacement, label="tuya finish counters datapoint")
    s = s[:finish_pos] + sub

# Publish authenticated session state + versions on completed handshake.
needle = '''                (
                    DP_350K_RECONNECT_COUNT,
                    TuyaBLEDataPointType.DT_VALUE,
                    self._350k_reconnect_count,
                ),
            ],
'''
replacement = '''                (
                    DP_350K_RECONNECT_COUNT,
                    TuyaBLEDataPointType.DT_VALUE,
                    self._350k_reconnect_count,
                ),
                (
                    DP_350K_SESSION_STATE,
                    TuyaBLEDataPointType.DT_STRING,
                    "authenticated",
                ),
                (
                    DP_350K_DEVICE_VERSION,
                    TuyaBLEDataPointType.DT_STRING,
                    self.device_version,
                ),
                (
                    DP_350K_HARDWARE_VERSION,
                    TuyaBLEDataPointType.DT_STRING,
                    self.hardware_version,
                ),
                (
                    DP_350K_PROTOCOL_VERSION,
                    TuyaBLEDataPointType.DT_STRING,
                    self.protocol_version,
                ),
            ],
'''
record_pos = s.find("    def _record_350k_connected(")
sub = s[record_pos:]
if "DP_350K_DEVICE_VERSION" not in sub[:2200]:
    sub = replace_once(sub, needle, replacement, label="tuya connected session diagnostics")
    s = s[:record_pos] + sub

# Sequence gap uses the pure helper.
old = '''        mask = (1 << 40) - 1
        previous = self._350k_last_event_seq
        if previous is not None:
            expected = (previous + 1) & mask
            forward = (event_seq - expected) & mask
            if 0 < forward <= 1000:
                self._350k_event_sequence_gaps += forward
                self._log_350k_event(
                    "%s: 350K V4 sequence gap previous=0x%010x current=0x%010x "
                    "missing=%s total_missing=%s",
                    self.address,
                    previous,
                    event_seq,
                    forward,
                    self._350k_event_sequence_gaps,
                )
            elif forward > 1000 and event_seq != expected:
                self._log_350k_event(
                    "%s: 350K V4 sequence discontinuity previous=0x%010x "
                    "current=0x%010x (reset/reorder; not counted)",
                    self.address,
                    previous,
                    event_seq,
                )
'''
new = '''        previous = self._350k_last_event_seq
        missing, discontinuity = compute_sequence_gap(previous, event_seq)
        if missing:
            self._350k_event_sequence_gaps += missing
            self._log_350k_event(
                "%s: 350K V4 sequence gap previous=0x%010x current=0x%010x "
                "missing=%s total_missing=%s",
                self.address,
                previous,
                event_seq,
                missing,
                self._350k_event_sequence_gaps,
            )
        elif discontinuity and previous is not None:
            self._log_350k_event(
                "%s: 350K V4 sequence discontinuity previous=0x%010x "
                "current=0x%010x (reset/reorder; not counted)",
                self.address,
                previous,
                event_seq,
            )
'''
if "missing, discontinuity = compute_sequence_gap" not in s:
    s = replace_once(s, old, new, label="tuya sequence helper")

# Timeline sanitization + bounded helper.
old = '''        payload_redacted = False
        scalar: bool | int | None = None
        if dp_type == TuyaBLEDataPointType.DT_BOOL:
            scalar = bool(value)
        elif dp_type in (TuyaBLEDataPointType.DT_ENUM, TuyaBLEDataPointType.DT_VALUE):
            if dp_id in _350K_TIMELINE_SENSITIVE_SCALAR_DPS:
                payload_redacted = True
            else:
                scalar = int(value)
        else:
            payload_redacted = True
'''
new = '''        scalar, payload_redacted = sanitize_timeline_scalar(
            dp_id, dp_type.name, value
        )
'''
if "sanitize_timeline_scalar(" not in s[s.find("def _record_350k_event_timeline"):s.find("def _record_350k_unknown_dp")]:
    s = replace_once(s, old, new, label="tuya timeline sanitizer")
old = '''        self._350k_event_timeline.append(entry)
        if len(self._350k_event_timeline) > _350K_EVENT_TIMELINE_CAPACITY:
            del self._350k_event_timeline[
                : len(self._350k_event_timeline) - _350K_EVENT_TIMELINE_CAPACITY
            ]
'''
new = '''        append_bounded_event(
            self._350k_event_timeline,
            entry,
            capacity=_350K_EVENT_TIMELINE_CAPACITY,
        )
'''
if "append_bounded_event(" not in s[s.find("def _record_350k_event_timeline"):s.find("def _record_350k_unknown_dp")]:
    s = replace_once(s, old, new, label="tuya bounded timeline")

# Use pure builders.
old = '''        return (
            b"\\x00\\x00\\x00\\x00\\x01"
            + bytes([dp_id, int(TuyaBLEDataPointType.DT_BOOL.value)])
            + b"\\x00\\x01"
            + bytes([1 if value else 0])
        )
'''
if "return build_v4_bool_data(dp_id, value)" not in s:
    s = replace_once(s, old, "        return build_v4_bool_data(dp_id, value)\n", label="tuya bool builder helper")
old = '''        return (
            b"\\x00\\x00\\x00\\x00\\x01"
            + bytes([dp_id, int(TuyaBLEDataPointType.DT_ENUM.value)])
            + b"\\x00\\x01"
            + bytes([int(value)])
        )
'''
if "return build_v4_enum_data(dp_id, value)" not in s:
    s = replace_once(s, old, "        return build_v4_enum_data(dp_id, value)\n", label="tuya enum builder helper")

# Native-size write helper.
old = '''        if max_size <= GATT_MTU:
            return GATT_MTU
        return min(max_size, 244)
'''
new = '''        return normalize_write_chunk_size(
            max_size, fallback=GATT_MTU, cap=244
        )
'''
if "return normalize_write_chunk_size(" not in s:
    s = replace_once(s, old, new, label="tuya chunk helper")

# Command begin/busy accounting for confirmed boolean writes.
old = '''        if self._350k_control_lock.locked():
            _LOGGER.warning(
                "%s: Ignoring 350K DP%s=%s; another control operation is still pending",
                self.address,
                dp_id,
                value,
            )
            return False

        command = {
            33: "passage_on" if value else "passage_off",
            46: "lock" if value else "manual_lock_false",
            79: "secure_on" if value else "secure_off",
        }[dp_id]
        started = time.monotonic()
'''
new = '''        command = {
            33: "passage_on" if value else "passage_off",
            46: "lock" if value else "manual_lock_false",
            79: "secure_on" if value else "secure_off",
        }[dp_id]
        if self._350k_control_lock.locked():
            self._record_350k_busy(command)
            _LOGGER.warning(
                "%s: Ignoring 350K DP%s=%s; another control operation is still pending",
                self.address,
                dp_id,
                value,
            )
            return False

        started = self._begin_350k_command(command)
'''
if "started = self._begin_350k_command(command)" not in s[s.find("async def set_350k_bool_datapoint"):s.find("def _build_350k_v4_enum_data")]:
    s = replace_once(s, old, new, label="tuya bool command counters")

# Enum writes.
old = '''        if self._350k_control_lock.locked():
            _LOGGER.warning(
                "%s: Ignoring 350K DP%s=%s; another control operation is pending",
                self.address,
                dp_id,
                value,
            )
            return False
        command = "language" if dp_id == 28 else "volume"
        started = time.monotonic()
'''
new = '''        command = "language" if dp_id == 28 else "volume"
        if self._350k_control_lock.locked():
            self._record_350k_busy(command)
            _LOGGER.warning(
                "%s: Ignoring 350K DP%s=%s; another control operation is pending",
                self.address,
                dp_id,
                value,
            )
            return False
        started = self._begin_350k_command(command)
'''
if "self._record_350k_busy(command)" not in s[s.find("async def set_350k_enum_datapoint"):s.find("async def unlock_350k")]:
    s = replace_once(s, old, new, label="tuya enum command counters")

# Unlock command + framing validation.
old = '''        if self._350k_control_lock.locked():
            _LOGGER.warning(
                "%s: Ignoring 350K unlock; another control operation is still pending",
                self.address,
            )
            return False

        command = "unlock"
        started = time.monotonic()
'''
new = '''        command = "unlock"
        if self._350k_control_lock.locked():
            self._record_350k_busy(command)
            _LOGGER.warning(
                "%s: Ignoring 350K unlock; another control operation is still pending",
                self.address,
            )
            return False

        started = self._begin_350k_command(command)
'''
if "started = self._begin_350k_command(command)" not in s[s.find("async def unlock_350k"):s.find("async def linger_connected")]:
    s = replace_once(s, old, new, label="tuya unlock counters")
needle = '''                payload = self._build_raykube_unlock_v4_data()
'''
replacement = '''                payload = self._build_raykube_unlock_v4_data()
                if not valid_dp71_payload_shape(payload):
                    raise TuyaBLEDeviceError("unexpected 350K DP71 payload framing")
'''
unlock_pos = s.find("async def unlock_350k")
sub = s[unlock_pos:s.find("async def linger_connected", unlock_pos)]
if "valid_dp71_payload_shape" not in sub:
    sub = replace_once(sub, needle, replacement, label="tuya unlock shape validation")
    s = s[:unlock_pos] + sub + s[s.find("async def linger_connected", unlock_pos):]

# Receive freshness: track real RX and valid V4 reports.
needle = '''            self._350k_last_rx_monotonic = time.monotonic()
'''
replacement = '''            self._350k_last_rx_monotonic = time.monotonic()
            self._350k_last_rx_seen = True
'''
# There is one notification-handler occurrence; avoid touching __init__ assignment.
notif = s.find("    def _notification_handler(")
if notif < 0:
    raise RuntimeError("notification handler not found")
sub = s[notif:]
if "self._350k_last_rx_seen = True" not in sub[:800]:
    sub = replace_once(sub, needle, replacement, label="tuya last rx seen")
    s = s[:notif] + sub

needle = '''        kind = data[6]
        self._record_350k_event_sequence(event_seq, datapoints)
'''
replacement = '''        kind = data[6]
        self._record_350k_device_report(datapoints)
        self._record_350k_event_sequence(event_seq, datapoints)
'''
if "self._record_350k_device_report(datapoints)" not in s:
    s = replace_once(s, needle, replacement, label="tuya report freshness")

# Mark disconnected state silently alongside last-disconnect timestamp.
needle = '''                    (
                        DP_350K_LAST_DISCONNECT_TIME,
                        TuyaBLEDataPointType.DT_VALUE,
                        int(now),
                    )
                ],
'''
replacement = '''                    (
                        DP_350K_LAST_DISCONNECT_TIME,
                        TuyaBLEDataPointType.DT_VALUE,
                        int(now),
                    ),
                    (
                        DP_350K_SESSION_STATE,
                        TuyaBLEDataPointType.DT_STRING,
                        "disconnected",
                    ),
                ],
'''
disconnect_pos = s.find("    def _disconnected(")
sub = s[disconnect_pos:s.find("    def _disconnect(", disconnect_pos)]
if "DP_350K_SESSION_STATE" not in sub:
    sub = replace_once(sub, needle, replacement, label="tuya disconnected session state")
    s = s[:disconnect_pos] + sub + s[s.find("    def _disconnect(", disconnect_pos):]

p.write_text(s, encoding="utf-8")


# ---------------------------------------------------------------------------
# sensor.py
# ---------------------------------------------------------------------------
p = ROOT / "sensor.py"
s = p.read_text(encoding="utf-8")
needle = '''    DP_350K_EVENT_TIMELINE_COUNT,
)'''
replacement = '''    DP_350K_EVENT_TIMELINE_COUNT,
    DP_350K_LAST_DEVICE_REPORT_TIME,
    DP_350K_STATE_AGE_SECONDS,
    DP_350K_SESSION_STATE,
    DP_350K_LAST_RX_AGE_SECONDS,
    DP_350K_COMMAND_COUNTERS,
    DP_350K_DEVICE_VERSION,
    DP_350K_HARDWARE_VERSION,
    DP_350K_PROTOCOL_VERSION,
)'''
if "    DP_350K_LAST_DEVICE_REPORT_TIME," not in s:
    s = replace_once(s, needle, replacement, label="sensor diagnostics imports")

anchor = '''def unknown_dp_recorder_getter(self: TuyaBLESensor) -> None:
'''
if "def state_age_getter(" not in s:
    getters = '''def state_age_getter(self: TuyaBLESensor) -> None:
    """Expose seconds since the last parsed device V4 report."""
    self._attr_native_value = self._device.state_age_seconds


def session_state_getter(self: TuyaBLESensor) -> None:
    self._attr_native_value = self._device.session_state


def last_rx_age_getter(self: TuyaBLESensor) -> None:
    self._attr_native_value = self._device.last_rx_age_seconds


def command_counters_getter(self: TuyaBLESensor) -> None:
    counters = self._device.command_counters
    self._attr_native_value = int(counters["total"])
    self._attr_extra_state_attributes = counters


'''
    s = replace_once(s, anchor, getters + anchor, label="sensor harness getters")

# Add mappings after event timeline recorder.
needle = '''                TuyaBLESensorMapping(
                    dp_id=DP_350K_EVENT_TIMELINE_COUNT,
                    getter=event_timeline_getter,
                    description=SensorEntityDescription(
                        key="event_timeline_recorder",
                        icon="mdi:timeline-clock-outline",
                        entity_category=EntityCategory.DIAGNOSTIC,
                        entity_registry_enabled_default=False,
                    ),
                ),
'''
addition = needle + '''                TuyaBLESensorMapping(
                    dp_id=DP_350K_LAST_DEVICE_REPORT_TIME,
                    getter=diagnostic_timestamp_getter,
                    description=SensorEntityDescription(
                        key="last_device_report",
                        device_class=SensorDeviceClass.TIMESTAMP,
                        icon="mdi:clock-check-outline",
                        entity_category=EntityCategory.DIAGNOSTIC,
                        entity_registry_enabled_default=False,
                    ),
                ),
                TuyaBLESensorMapping(
                    dp_id=DP_350K_STATE_AGE_SECONDS,
                    getter=state_age_getter,
                    description=SensorEntityDescription(
                        key="state_age",
                        icon="mdi:timer-outline",
                        native_unit_of_measurement="s",
                        entity_category=EntityCategory.DIAGNOSTIC,
                        entity_registry_enabled_default=False,
                    ),
                ),
                TuyaBLESensorMapping(
                    dp_id=DP_350K_SESSION_STATE,
                    getter=session_state_getter,
                    description=SensorEntityDescription(
                        key="session_state",
                        icon="mdi:bluetooth-connect",
                        entity_category=EntityCategory.DIAGNOSTIC,
                        entity_registry_enabled_default=False,
                    ),
                ),
                TuyaBLESensorMapping(
                    dp_id=DP_350K_LAST_RX_AGE_SECONDS,
                    getter=last_rx_age_getter,
                    description=SensorEntityDescription(
                        key="last_rx_age",
                        icon="mdi:bluetooth-audio",
                        native_unit_of_measurement="s",
                        entity_category=EntityCategory.DIAGNOSTIC,
                        entity_registry_enabled_default=False,
                    ),
                ),
                TuyaBLESensorMapping(
                    dp_id=DP_350K_COMMAND_COUNTERS,
                    getter=command_counters_getter,
                    description=SensorEntityDescription(
                        key="command_counters",
                        icon="mdi:counter",
                        entity_category=EntityCategory.DIAGNOSTIC,
                        entity_registry_enabled_default=False,
                    ),
                ),
                TuyaBLESensorMapping(
                    dp_id=DP_350K_DEVICE_VERSION,
                    description=SensorEntityDescription(
                        key="device_firmware_version",
                        icon="mdi:chip",
                        entity_category=EntityCategory.DIAGNOSTIC,
                        entity_registry_enabled_default=False,
                    ),
                ),
                TuyaBLESensorMapping(
                    dp_id=DP_350K_HARDWARE_VERSION,
                    description=SensorEntityDescription(
                        key="device_hardware_version",
                        icon="mdi:expansion-card",
                        entity_category=EntityCategory.DIAGNOSTIC,
                        entity_registry_enabled_default=False,
                    ),
                ),
                TuyaBLESensorMapping(
                    dp_id=DP_350K_PROTOCOL_VERSION,
                    description=SensorEntityDescription(
                        key="device_protocol_version",
                        icon="mdi:protocol",
                        entity_category=EntityCategory.DIAGNOSTIC,
                        entity_registry_enabled_default=False,
                    ),
                ),
'''
if 'key="last_device_report"' not in s:
    s = replace_once(s, needle, addition, label="sensor harness mappings")

# Poll age sensors so they continue increasing while the sleeping lock is idle.
anchor = '''    @callback
    def _handle_coordinator_update(self) -> None:
'''
if "def should_poll(self)" not in s[s.find("class TuyaBLESensor"):]:
    block = '''    @property
    def should_poll(self) -> bool:
        return self._mapping.dp_id in (
            DP_350K_STATE_AGE_SECONDS,
            DP_350K_LAST_RX_AGE_SECONDS,
        )

    async def async_update(self) -> None:
        if self._mapping.getter is not None:
            self._mapping.getter(self)

'''
    sensor_class_pos = s.find("class TuyaBLESensor")
    anchor_pos = s.find(anchor, sensor_class_pos)
    if anchor_pos < 0:
        raise RuntimeError("sensor update anchor not found")
    s = s[:anchor_pos] + block + s[anchor_pos:]

p.write_text(s, encoding="utf-8")


# ---------------------------------------------------------------------------
# button.py: manual status refresh + clear diagnostics
# ---------------------------------------------------------------------------
p = ROOT / "button.py"
s = p.read_text(encoding="utf-8")
if "from homeassistant.helpers.entity import EntityCategory" not in s:
    s = replace_once(
        s,
        "from homeassistant.helpers.entity_platform import AddEntitiesCallback\n",
        "from homeassistant.helpers.entity import EntityCategory\nfrom homeassistant.helpers.entity_platform import AddEntitiesCallback\n",
        label="button EntityCategory import",
    )
needle = '''                TuyaBLEButtonMapping(
                    dp_id=71,
                    description=ButtonEntityDescription(
                        key="unlock_door",
                        translation_key="unlock_door",
                        icon="mdi:lock-open",
                        entity_registry_enabled_default=False,
                    ),
                ),
'''
addition = needle + '''                TuyaBLEButtonMapping(
                    dp_id=-9001,
                    description=ButtonEntityDescription(
                        key="refresh_status",
                        translation_key="refresh_status",
                        icon="mdi:refresh",
                        entity_category=EntityCategory.DIAGNOSTIC,
                        entity_registry_enabled_default=False,
                    ),
                ),
                TuyaBLEButtonMapping(
                    dp_id=-9002,
                    description=ButtonEntityDescription(
                        key="clear_diagnostics",
                        translation_key="clear_diagnostics",
                        icon="mdi:broom",
                        entity_category=EntityCategory.DIAGNOSTIC,
                        entity_registry_enabled_default=False,
                    ),
                ),
'''
if 'key="refresh_status"' not in s:
    s = replace_once(s, needle, addition, label="button harness mappings")
needle = '''        if self._device.product_id == "z1dfsaya" and self._mapping.dp_id == 71:
            # Experimental authenticated BLE unlock. The command ACK is not
            # treated as proof of an unlocked door; DP47 remains authoritative.
            self._hass.create_task(self._device.unlock_350k())
            return

'''
addition = needle + '''        if self._device.product_id == "z1dfsaya" and self._mapping.dp_id == -9001:
            self._hass.create_task(self._device.refresh_350k_status())
            return

        if self._device.product_id == "z1dfsaya" and self._mapping.dp_id == -9002:
            self._device.clear_350k_diagnostics()
            return

'''
if "self._mapping.dp_id == -9001" not in s:
    s = replace_once(s, needle, addition, label="button harness press handlers")
p.write_text(s, encoding="utf-8")


# ---------------------------------------------------------------------------
# devices.py: sanitized HA event bus events for known access/state transitions.
# ---------------------------------------------------------------------------
p = ROOT / "devices.py"
s = p.read_text(encoding="utf-8")
needle = '''    DEVICE_DEF_MANUFACTURER,
    DOMAIN,
    FINGERBOT_BUTTON_EVENT,
'''
replacement = '''    DEVICE_DEF_MANUFACTURER,
    DOMAIN,
    EVENT_350K,
    DP_350K_LAST_ACCESS_EVENT,
    FINGERBOT_BUTTON_EVENT,
'''
if "    EVENT_350K," not in s:
    s = replace_once(s, needle, replacement, label="devices event imports")

anchor = '''    @callback
    def _async_handle_update(self, updates: list[TuyaBLEDataPoint]) -> None:
'''
if "def _async_fire_350k_event" not in s:
    helper_block = '''    @callback
    def _async_fire_350k_event(self, event_type: str, timestamp: float) -> None:
        registry = dr.async_get(self.hass)
        registry_device = registry.async_get_device(
            identifiers={(DOMAIN, self._device.address)}
        )
        payload = {
            "type": event_type,
            "timestamp": int(timestamp),
            "address": self._device.address,
        }
        if registry_device is not None:
            payload[CONF_DEVICE_ID] = registry_device.id
        self.hass.bus.async_fire(EVENT_350K, payload)

'''
    s = replace_once(s, anchor, helper_block + anchor, label="devices 350k event helper")

needle = '''        self._async_handle_connect()
        self.async_set_updated_data(None)
        info = get_device_product_info(self._device)
'''
replacement = '''        self._async_handle_connect()
        self.async_set_updated_data(None)
        if self._device.product_id == "z1dfsaya":
            for update in updates:
                if update.id == DP_350K_LAST_ACCESS_EVENT:
                    self._async_fire_350k_event(str(update.value), update.timestamp)
                elif update.id == 47 and update.changed_by_device:
                    self._async_fire_350k_event(
                        "unlocked" if bool(update.value) else "locked",
                        update.timestamp,
                    )
        info = get_device_product_info(self._device)
'''
if "update.id == DP_350K_LAST_ACCESS_EVENT" not in s:
    s = replace_once(s, needle, replacement, label="devices event emission")
p.write_text(s, encoding="utf-8")


# ---------------------------------------------------------------------------
# services.py + services.yaml
# ---------------------------------------------------------------------------
(ROOT / "services.py").write_text(
'''"""Local test-harness services for the Tuya BLE integration."""
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
''',
    encoding="utf-8",
)

(ROOT / "services.yaml").write_text(
'''mark_350k_test:
  name: Mark 350K test
  description: Add a bounded user label to the sanitized 350K event timeline without sending anything to the lock.
  fields:
    device_id:
      name: Device
      description: Home Assistant device ID. Optional when exactly one 350K is loaded.
      selector:
        device:
          integration: tuya_local_ble
    config_entry_id:
      name: Config entry ID
      description: Optional explicit Tuya BLE config entry ID.
      selector:
        text:
    label:
      name: Label
      required: true
      example: fingerprint_unlock
      selector:
        text:
    note:
      name: Note
      description: Optional short user-supplied note. Do not put secrets here.
      selector:
        text:

export_350k_diagnostics:
  name: Export sanitized 350K diagnostics
  description: Return a shareable in-memory snapshot with protocol/session diagnostics, safe known values, unknown-DP summaries, and the sanitized event timeline. Keys, credential IDs, and raw payload contents are omitted.
  fields:
    device_id:
      name: Device
      description: Home Assistant device ID. Optional when exactly one 350K is loaded.
      selector:
        device:
          integration: tuya_local_ble
    config_entry_id:
      name: Config entry ID
      description: Optional explicit Tuya BLE config entry ID.
      selector:
        text:
''',
    encoding="utf-8",
)

# Register services after entry data exists.
p = ROOT / "__init__.py"
s = p.read_text(encoding="utf-8")
if "from .services import async_register_services" not in s:
    s = replace_once(
        s,
        "from .devices import TuyaBLECoordinator, TuyaBLEData, get_device_product_info\n",
        "from .devices import TuyaBLECoordinator, TuyaBLEData, get_device_product_info\nfrom .services import async_register_services\n",
        label="init service import",
    )
needle = '''    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = TuyaBLEData(
        entry.title,
        device,
        product_info,
        manager,
        coordinator,
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
'''
replacement = '''    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = TuyaBLEData(
        entry.title,
        device,
        product_info,
        manager,
        coordinator,
    )
    async_register_services(hass)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
'''
if "    async_register_services(hass)" not in s:
    s = replace_once(s, needle, replacement, label="init service registration")
p.write_text(s, encoding="utf-8")


# ---------------------------------------------------------------------------
# Device automation triggers for the events already mapped by the parser.
# ---------------------------------------------------------------------------
(ROOT / "device_trigger.py").write_text(
'''"""Experimental device triggers for the YD_350K."""
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
''',
    encoding="utf-8",
)


# ---------------------------------------------------------------------------
# strings/translations
# ---------------------------------------------------------------------------
for rel in ("strings.json", "translations/en.json"):
    p = ROOT / rel
    data = json.loads(p.read_text(encoding="utf-8"))
    entity = data.setdefault("entity", {})
    buttons = entity.setdefault("button", {})
    buttons.setdefault("refresh_status", {"name": "Refresh lock status"})
    buttons.setdefault("clear_diagnostics", {"name": "Clear test diagnostics"})
    sensors = entity.setdefault("sensor", {})
    names = {
        "last_device_report": "Last device report",
        "state_age": "State age",
        "session_state": "BLE session state",
        "last_rx_age": "Last BLE RX age",
        "command_counters": "Command counters",
        "device_firmware_version": "Device firmware version",
        "device_hardware_version": "Device hardware version",
        "device_protocol_version": "Tuya protocol version",
    }
    for key, name in names.items():
        sensors.setdefault(key, {"name": name})
    data.setdefault("device_automation", {}).setdefault("trigger_type", {}).update({
        "fingerprint_unlock": "Unlocked by fingerprint",
        "pin_unlock": "Unlocked by PIN",
        "bluetooth_unlock": "Unlocked over Bluetooth",
        "failed_fingerprint": "Fingerprint unlock failed",
        "failed_pin": "PIN unlock failed",
        "locked": "Lock became locked",
        "unlocked": "Lock became unlocked",
    })
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Pure unit tests.
# ---------------------------------------------------------------------------
tests = Path("tests")
tests.mkdir(exist_ok=True)
(tests / "test_350k_protocol.py").write_text(
'''from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

PATH = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "tuya_local_ble"
    / "tuya_ble"
    / "diagnostics_350k.py"
)
spec = importlib.util.spec_from_file_location("diagnostics_350k", PATH)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)


class Test350KProtocolHelpers(unittest.TestCase):
    def test_confirmed_dp46_bool_payload(self):
        self.assertEqual(
            module.build_v4_bool_data(46, True),
            bytes.fromhex("00000000012e01000101"),
        )

    def test_enum_payload(self):
        self.assertEqual(
            module.build_v4_enum_data(31, 2),
            bytes.fromhex("00000000011f04000102"),
        )

    def test_dp71_shape_only(self):
        payload = bytes.fromhex("000000000147000013") + b"x" * 19
        self.assertTrue(module.valid_dp71_payload_shape(payload))
        self.assertFalse(module.valid_dp71_payload_shape(payload[:-1]))

    def test_sequence_gap_and_wrap(self):
        self.assertEqual(module.compute_sequence_gap(10, 11), (0, False))
        self.assertEqual(module.compute_sequence_gap(10, 14), (3, False))
        self.assertEqual(module.compute_sequence_gap(10, 5000), (0, True))
        self.assertEqual(module.compute_sequence_gap((1 << 40) - 1, 0), (0, False))

    def test_write_size_fallback_and_cap(self):
        self.assertEqual(module.normalize_write_chunk_size(20), 20)
        self.assertEqual(module.normalize_write_chunk_size(19), 20)
        self.assertEqual(module.normalize_write_chunk_size(68), 68)
        self.assertEqual(module.normalize_write_chunk_size(512), 244)

    def test_timeline_redacts_credentials_and_raw(self):
        scalar, redacted = module.sanitize_timeline_scalar(12, "DT_VALUE", 7)
        self.assertIsNone(scalar)
        self.assertTrue(redacted)
        scalar, redacted = module.sanitize_timeline_scalar(47, "DT_BOOL", True)
        self.assertIs(scalar, True)
        self.assertFalse(redacted)
        scalar, redacted = module.sanitize_timeline_scalar(20, "DT_RAW", b"abc")
        self.assertIsNone(scalar)
        self.assertTrue(redacted)

    def test_timeline_bound(self):
        buffer = []
        for i in range(module.EVENT_TIMELINE_CAPACITY + 5):
            module.append_bounded_event(buffer, {"i": i})
        self.assertEqual(len(buffer), module.EVENT_TIMELINE_CAPACITY)
        self.assertEqual(buffer[0]["i"], 5)

    def test_marker_text_is_bounded(self):
        self.assertEqual(module.sanitize_marker_text("  hello   world  ", 64), "hello world")
        self.assertEqual(len(module.sanitize_marker_text("x" * 100, 64)), 64)


if __name__ == "__main__":
    unittest.main()
''',
    encoding="utf-8",
)


# ---------------------------------------------------------------------------
# README documentation / pending-validation checklist.
# ---------------------------------------------------------------------------
p = Path("README.md")
s = p.read_text(encoding="utf-8")
insert_before = "## Suggested test sequence\n"
if "## Test harness services and automation" not in s:
    docs = '''## Test harness services and automation

The experimental branch includes a local-only test harness intended to make one physical test session useful without requiring raw authenticated captures.

### Test markers

Call `tuya_local_ble.mark_350k_test` immediately before a physical/app/HA action. `label` is required; `note` is optional. Both are user supplied, whitespace-normalized, and bounded. The marker does **not** send anything to the lock; it is inserted into the same sanitized event timeline as a `source: marker` record. Do not place secrets in marker labels or notes.

Example:

```yaml
action: tuya_local_ble.mark_350k_test
data:
  label: fingerprint_unlock
```

The sanitized timeline capacity is now 50 entries so a complete fingerprint/PIN/manual/HA test matrix is less likely to wrap.

### Sanitized diagnostic export

`tuya_local_ble.export_350k_diagnostics` is a response-producing service. It returns current firmware/protocol metadata, session freshness, reconnect/sequence diagnostics, command counters/timings, safe scalar state, unknown-DP summaries, and the sanitized timeline. It intentionally omits local keys, secKeys, `ble_unlock_check`, credential IDs, and raw/string/bitmap payload contents.

When exactly one 350K is loaded, the target fields can be omitted. With multiple locks, specify `device_id` or `config_entry_id`.

### Local diagnostic buttons

Two disabled-by-default diagnostic buttons are available:

- **Refresh lock status** — explicitly connects/authenticates and requests `DEVICE_STATUS` once. It is user initiated; unlike Keep BLE connection alive it does not run continuously.
- **Clear test diagnostics** — clears the unknown-DP summary, sanitized timeline, sequence-gap count, command counters, and recent command/transport measurements without changing any physical lock configuration.

### Freshness / session / command diagnostics

Disabled-by-default sensors now include **Last device report**, **State age**, **BLE session state**, **Last BLE RX age**, and **Command counters**. State/RX ages are local freshness measurements; the lock's retained DP47 state is still authoritative for the last reported physical state.

Command counters are session-local and include total attempts, successful ACKs, not-acknowledged/timeouts, BLE errors, not-connected failures, busy/rejected attempts, unavailable commands, generic errors, and commands that required establishing a session first.

### Home Assistant events and device triggers

Known parser events are emitted on the local HA event bus as `tuya_local_ble_350k_event` without credential IDs. Experimental device triggers are available for fingerprint unlock, PIN unlock, Bluetooth unlock, failed fingerprint, failed PIN, locked, and unlocked. These triggers should remain considered experimental until the corresponding physical test checklist is completed.

### Firmware / protocol metadata

Disabled-by-default diagnostic sensors expose device firmware, hardware, and Tuya protocol versions so captures from different 350K firmware revisions can be compared without inspecting raw traffic.

### Protocol regression tests

`tests/test_350k_protocol.py` covers the confirmed DP46 V4 payload, DP28/31 enum framing, non-secret DP71 framing shape, 40-bit sequence wrap/gaps, negotiated GATT write-size selection, timeline redaction/bounds, and marker sanitization. The test module imports only pure helpers and does not require access to the physical lock or private credentials.

'''
    if insert_before not in s:
        raise RuntimeError("README suggested-test anchor missing")
    s = s.replace(insert_before, docs + insert_before, 1)

# Append new implemented-but-unvalidated items to checklist if absent.
check_anchor = "- [ ] **Cold-vs-warm latency comparison**"
if check_anchor in s and "**Test-marker service**" not in s:
    line_end = s.find("\n", s.find(check_anchor))
    if line_end < 0:
        line_end = len(s)
    extra = '''
- [ ] **Test-marker service** — verify marker ordering relative to subsequent lock reports and multi-lock targeting.
- [ ] **Sanitized diagnostic export** — verify service response remains free of credential IDs/raw payloads while retaining enough metadata for offline comparison.
- [ ] **State freshness/session sensors** — verify Last device report, State age, BLE session state, and Last RX age across sleep/reconnect cycles.
- [ ] **Command counters** — verify success, timeout/not-acknowledged, BLE error, busy, and reconnect-required accounting.
- [ ] **Manual Refresh lock status** — verify it wakes/connects on demand, requests status once, and does not alter lock configuration.
- [ ] **Clear test diagnostics** — verify it clears only local experiment state and never changes physical lock settings.
- [ ] **HA event-bus events/device triggers** — verify each known access/lock transition fires once per physical event without leaking credential IDs.
- [ ] **Firmware/protocol diagnostic sensors** — verify values match the device-info handshake and persist through normal sleep cycles.
'''
    s = s[:line_end + 1] + extra + s[line_end + 1:]

p.write_text(s, encoding="utf-8")
