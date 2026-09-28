"""Pure helpers for YD_350K diagnostics and protocol experiments."""
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
        b"\x00\x00\x00\x00\x01"
        + bytes([int(dp_id), TUYA_DT_BOOL])
        + b"\x00\x01"
        + bytes([1 if value else 0])
    )


def build_v4_enum_data(dp_id: int, value: int) -> bytes:
    """Build the typed 350K V4 one-byte enum body."""
    if not 0 <= int(dp_id) <= 0xFF or not 0 <= int(value) <= 0xFF:
        raise ValueError("dp_id/value out of range")
    return (
        b"\x00\x00\x00\x00\x01"
        + bytes([int(dp_id), TUYA_DT_ENUM])
        + b"\x00\x01"
        + bytes([int(value)])
    )


def valid_dp71_payload_shape(payload: bytes) -> bool:
    """Validate only the non-secret framing of the inferred DP71 command."""
    return (
        len(payload) == 28
        and payload[:9] == b"\x00\x00\x00\x00\x01\x47\x00\x00\x13"
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
