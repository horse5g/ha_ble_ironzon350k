"""BLE transport hardening for flaky Home Assistant Bluetooth proxies."""
from __future__ import annotations

import logging

from .const import PRODUCT_ID_350K
from .tuya_ble.const import TuyaBLECode
from .tuya_ble.resilience import abort_pending_response_futures
from .tuya_ble.tuya_ble import BLEAK_EXCEPTIONS, TuyaBLEDevice

_LOGGER = logging.getLogger(__name__)


class ResilientTuyaBLEDevice(TuyaBLEDevice):
    """Tuya BLE device with defensive proxy-disconnect handling.

    ESPHome proxies can disappear while a Tuya request is waiting for its ACK.
    The upstream protocol wait is intentionally generous, so without an early
    abort the 350K control lock can remain occupied long after the transport is
    already gone. This wrapper keeps the wire protocol unchanged while making
    transport teardown fail fast and best-effort.
    """

    def _abort_transport_waiters(self) -> int:
        """Discard partial RX state and wake requests waiting on a dead link."""
        aborted = abort_pending_response_futures(self._input_expected_responses)
        self._clean_input()

        if self.product_id == PRODUCT_ID_350K:
            # Any latency correlation crossing a broken BLE session would be
            # misleading. Authoritative DP47 state is still retained normally.
            self._350k_unlock_requested_monotonic = None
            self._350k_actuation_started_monotonic = None
            self._350k_actuation_expected_state = None
            self._350k_actuation_command = None

        return aborted

    def _fire_disconnected_callbacks(self) -> None:
        """Release pending protocol waits before publishing disconnect."""
        aborted = self._abort_transport_waiters()
        if aborted:
            _LOGGER.debug(
                "%s: aborted %s pending Tuya response waiter(s) after BLE disconnect",
                self.address,
                aborted,
            )
        super()._fire_disconnected_callbacks()

    async def _send_response(
        self,
        code: TuyaBLECode,
        data: bytes,
        response_to: int,
    ) -> None:
        """Best-effort protocol reply when the proxy vanishes mid-frame."""
        try:
            await super()._send_response(code, data, response_to)
        except BLEAK_EXCEPTIONS as ex:
            _LOGGER.debug(
                "%s: dropped Tuya protocol reply because BLE transport disconnected: %s",
                self.address,
                ex,
            )

    async def _execute_disconnect(self) -> None:
        """Treat proxy EOF during an intentional disconnect as already closed."""
        try:
            await super()._execute_disconnect()
        except BLEAK_EXCEPTIONS as ex:
            aborted = self._abort_transport_waiters()
            # If Bleak's normal disconnected callback already ran while
            # disconnect() was in flight, _is_paired is already False and HA
            # has already been notified. Only synthesize the callback when the
            # proxy vanished before Bleak could deliver it.
            if self._is_paired:
                self._is_paired = False
                super()._fire_disconnected_callbacks()
            async with self._seq_num_lock:
                self._current_seq_num = 1
            _LOGGER.debug(
                "%s: BLE proxy disappeared during disconnect; treating link as closed%s: %s",
                self.address,
                f"; aborted {aborted} pending waiter(s)" if aborted else "",
                ex,
            )