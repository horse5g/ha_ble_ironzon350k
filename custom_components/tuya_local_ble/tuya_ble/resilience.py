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


def should_reject_control_during_reconnect(
    connect_in_progress: bool,
    session_authenticated: bool,
) -> bool:
    """Return whether a user control would become stale behind reconnect.

    A 350K control may establish its own connection when no connection attempt
    exists.  But if another task is already reconnecting/authenticating, waiting
    behind that task can delay the control by tens of seconds and cause the old
    command to execute long after the user pressed it.  Reject only that case;
    controls on an already-authenticated session, and normal on-demand connects,
    remain allowed.
    """
    return bool(connect_in_progress and not session_authenticated)
