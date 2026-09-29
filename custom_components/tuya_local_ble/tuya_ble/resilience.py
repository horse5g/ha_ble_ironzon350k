"""Small transport-resilience helpers for Tuya BLE."""
from __future__ import annotations

import asyncio
from collections.abc import MutableMapping


def abort_pending_response_futures(
    pending: MutableMapping[int, asyncio.Future[int] | None],
) -> int:
    """Fail outstanding response waiters immediately after BLE disconnect.

    The core protocol normally waits up to RESPONSE_WAIT_TIMEOUT for an ACK.
    When an ESPHome Bluetooth proxy disappears, those waits would otherwise
    keep the 350K control lock occupied even though the transport is already
    gone. OSError is intentionally used because the protocol's BLE exception
    tuple already treats it as a transport failure.
    """
    futures = [
        future
        for future in pending.values()
        if future is not None and not future.done()
    ]
    pending.clear()

    for future in futures:
        future.set_exception(OSError("BLE transport disconnected"))

    return len(futures)
